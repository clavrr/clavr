"""
Tool Pre-flight Validation

Graph-guided validation for tool arguments before execution.
Implements the "Confident or Clarify" pattern - if arguments are ambiguous,
ask for clarification rather than guessing.

Features:
- Contact resolution via graph (with fuzzy matching)
- Calendar conflict detection via CalendarService
- Entity validation against knowledge graph
- @validate_preflight decorator for automatic validation
"""
from typing import Dict, Any, Optional, List, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from datetime import datetime, timedelta
import asyncio
import re

from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class ValidationStatus(Enum):
    """Pre-flight validation result status."""
    VALID = "valid"           # All arguments validated, proceed with tool call
    AMBIGUOUS = "ambiguous"   # Ambiguous arguments, need clarification
    INVALID = "invalid"       # Invalid arguments, cannot proceed
    CONFLICT = "conflict"     # Scheduling/resource conflict detected
    SKIP = "skip"             # Skip validation (no graph available)


@dataclass
class ValidationIssue:
    """An issue found during validation."""
    field: str                # The field with the issue
    value: str                # The provided value
    issue_type: str           # "ambiguous", "not_found", "conflict", "invalid"
    candidates: List[str] = field(default_factory=list)  # Possible correct values
    message: str = ""         # Human-readable explanation
    severity: str = "warning" # "error", "warning", "info"
    suggested_action: Optional[str] = None  # What to do about it


@dataclass
class ResolvedEntity:
    """A resolved entity from validation."""
    original: str             # Original input
    resolved_value: str       # Resolved value (e.g., email)
    display_name: str         # Display name
    entity_type: str          # "person", "project", "document"
    confidence: float = 1.0   # Resolution confidence
    graph_node_id: Optional[str] = None  # Link to graph node


@dataclass
class PreflightResult:
    """Result of pre-flight validation."""
    status: ValidationStatus
    issues: List[ValidationIssue] = field(default_factory=list)
    resolved_args: Dict[str, Any] = field(default_factory=dict)
    resolved_entities: List[ResolvedEntity] = field(default_factory=list)
    clarification_prompt: Optional[str] = None  # Prompt to ask user
    warnings: List[str] = field(default_factory=list)
    can_proceed: bool = True  # Whether to proceed (with warnings) or stop
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'status': self.status.value,
            'issues': [{'field': i.field, 'value': i.value, 'type': i.issue_type, 
                       'message': i.message} for i in self.issues],
            'resolved_args': self.resolved_args,
            'clarification_prompt': self.clarification_prompt,
            'warnings': self.warnings,
            'can_proceed': self.can_proceed
        }


class ToolPreflightValidator:
    """
    Pre-flight validation for tool calls using knowledge graph.
    
    Implements the "Confident or Clarify" rule:
    - If identity/entity is ambiguous, pause and ask for clarification
    - If scheduling conflicts exist, warn before proceeding
    - If required data is missing, indicate what's needed
    
    Usage:
        validator = ToolPreflightValidator(graph_manager, contact_resolver)
        
        # Before calendar tool call
        result = await validator.validate_calendar_args(
            attendees=["Carol"],
            start_time="tomorrow at 2pm",
            user_id=123
        )
        
        if result.status == ValidationStatus.AMBIGUOUS:
            return {"clarification_needed": result.clarification_prompt}
    """
    
    def __init__(
        self,
        graph_manager: Optional[Any] = None,
        contact_resolver: Optional[Any] = None,
        calendar_service: Optional[Any] = None,
        confidence_threshold: Optional[float] = None
    ):
        """
        Initialize validator.
        
        Args:
            graph_manager: Knowledge graph manager for entity lookup
            contact_resolver: Contact resolver for identity resolution
            calendar_service: CalendarService for conflict detection
            confidence_threshold: Minimum confidence for accepting resolutions (default from ServiceConstants)
        """
        from src.services.service_constants import ServiceConstants
        
        self.graph = graph_manager
        self.contact_resolver = contact_resolver
        self.calendar_service = calendar_service
        self.CONFIDENCE_THRESHOLD = confidence_threshold or ServiceConstants.PREFLIGHT_CONFIDENCE_THRESHOLD
        
        # Cache for recent resolutions (avoid repeated lookups)
        self._resolution_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = timedelta(minutes=5)
        self._cache_timestamps: Dict[str, datetime] = {}
        
        logger.info("ToolPreflightValidator initialized")
    
    async def validate_calendar_args(
        self,
        user_id: int,
        attendees: Optional[List[str]] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        check_conflicts: bool = True,
        calendar_id: str = "primary"
    ) -> PreflightResult:
        """
        Validate calendar tool arguments before execution.
        
        Checks:
        1. Attendee names can be resolved to unique contacts
        2. Time slot doesn't have conflicts (if check_conflicts=True)
        3. Time is in the future (for new events)
        
        Returns:
            PreflightResult with resolved attendees or clarification needed
        """
        issues = []
        warnings = []
        resolved_args = {}
        resolved_entities = []
        
        # 1. Validate and resolve attendees (in parallel)
        if attendees:
            attendee_results = await self._resolve_contacts_batch(attendees, user_id)
            
            resolved_attendees = []
            for attendee, resolution in zip(attendees, attendee_results):
                if resolution['status'] == 'resolved':
                    resolved_attendees.append(resolution['email'])
                    resolved_entities.append(ResolvedEntity(
                        original=attendee,
                        resolved_value=resolution['email'],
                        display_name=resolution.get('name', attendee),
                        entity_type='person',
                        confidence=resolution.get('confidence', 1.0),
                        graph_node_id=resolution.get('node_id')
                    ))
                elif resolution['status'] == 'ambiguous':
                    issues.append(ValidationIssue(
                        field='attendees',
                        value=attendee,
                        issue_type='ambiguous',
                        candidates=resolution['candidates'],
                        message=f"Multiple contacts match '{attendee}'",
                        severity='error',
                        suggested_action=f"Specify full name or email"
                    ))
                else:
                    # Check if it looks like an email
                    if '@' in attendee:
                        resolved_attendees.append(attendee)
                        warnings.append(f"'{attendee}' not in contacts - using as-is")
                    else:
                        issues.append(ValidationIssue(
                            field='attendees',
                            value=attendee,
                            issue_type='not_found',
                            message=f"Could not find contact '{attendee}'",
                            severity='warning',
                            suggested_action=f"Provide full email for '{attendee}'"
                        ))
            
            resolved_args['attendees'] = resolved_attendees
        
        # 2. Parse and validate time
        parsed_start = None
        parsed_end = None
        
        if start_time:
            parsed_start = self._parse_datetime(start_time)
            if parsed_start:
                # Check if in the past
                now = datetime.now()
                if parsed_start < now - timedelta(minutes=5):
                    issues.append(ValidationIssue(
                        field='start_time',
                        value=start_time,
                        issue_type='invalid',
                        message=f"Cannot schedule event in the past",
                        severity='error'
                    ))
                
                resolved_args['start_time'] = parsed_start.isoformat()
                
                # Calculate end time
                if end_time:
                    parsed_end = self._parse_datetime(end_time)
                    if parsed_end:
                        resolved_args['end_time'] = parsed_end.isoformat()
                elif duration_minutes:
                    parsed_end = parsed_start + timedelta(minutes=duration_minutes)
                    resolved_args['end_time'] = parsed_end.isoformat()
                else:
                    # Default 1 hour
                    parsed_end = parsed_start + timedelta(hours=1)
                    resolved_args['end_time'] = parsed_end.isoformat()
        
        # 3. Check for scheduling conflicts via CalendarService
        if check_conflicts and parsed_start and self.calendar_service:
            conflict = await self._check_calendar_conflict_real(
                user_id=user_id,
                start_time=parsed_start,
                end_time=parsed_end,
                calendar_id=calendar_id
            )
            if conflict:
                issues.append(ValidationIssue(
                    field='time',
                    value=start_time,
                    issue_type='conflict',
                    message=f"Conflict with: {conflict['title']} ({conflict['time']})",
                    severity='warning',
                    suggested_action=f"Available slots: {', '.join(conflict.get('alternatives', []))}"
                ))
                warnings.append(f"Scheduling conflict detected: {conflict['title']}")
        
        # Determine overall status
        ambiguous = [i for i in issues if i.issue_type == 'ambiguous']
        errors = [i for i in issues if i.severity == 'error']
        
        if ambiguous:
            return PreflightResult(
                status=ValidationStatus.AMBIGUOUS,
                issues=issues,
                resolved_args=resolved_args,
                resolved_entities=resolved_entities,
                clarification_prompt=self._build_clarification_prompt(ambiguous),
                warnings=warnings,
                can_proceed=False
            )
        
        if errors:
            return PreflightResult(
                status=ValidationStatus.INVALID,
                issues=issues,
                resolved_args=resolved_args,
                resolved_entities=resolved_entities,
                warnings=warnings,
                can_proceed=False
            )
        
        conflict_issues = [i for i in issues if i.issue_type == 'conflict']
        if conflict_issues:
            return PreflightResult(
                status=ValidationStatus.CONFLICT,
                issues=issues,
                resolved_args=resolved_args,
                resolved_entities=resolved_entities,
                warnings=warnings,
                can_proceed=True  # Can proceed with confirmation
            )
        
        return PreflightResult(
            status=ValidationStatus.VALID,
            issues=issues,
            resolved_args=resolved_args,
            resolved_entities=resolved_entities,
            warnings=warnings,
            can_proceed=True
        )
    
    async def validate_email_args(
        self,
        user_id: int,
        to: Optional[List[str]] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None
    ) -> PreflightResult:
        """
        Validate email tool arguments.
        
        Checks:
        1. Recipients can be resolved to email addresses
        2. At least one recipient in 'to'
        """
        issues = []
        warnings = []
        resolved_args = {}
        resolved_entities = []
        
        # Validate at least one recipient
        if not to:
            issues.append(ValidationIssue(
                field='to',
                value='',
                issue_type='invalid',
                message="At least one recipient is required",
                severity='error'
            ))
        
        # Resolve all recipients in parallel
        all_recipients = []
        all_fields = []
        
        for field_name, recipients in [('to', to), ('cc', cc), ('bcc', bcc)]:
            if recipients:
                for r in recipients:
                    all_recipients.append(r)
                    all_fields.append(field_name)
        
        if all_recipients:
            resolutions = await self._resolve_contacts_batch(all_recipients, user_id)
            
            # Group results by field
            field_results: Dict[str, List[str]] = {'to': [], 'cc': [], 'bcc': []}
            
            for recipient, field_name, resolution in zip(all_recipients, all_fields, resolutions):
                if resolution['status'] == 'resolved':
                    field_results[field_name].append(resolution['email'])
                    resolved_entities.append(ResolvedEntity(
                        original=recipient,
                        resolved_value=resolution['email'],
                        display_name=resolution.get('name', recipient),
                        entity_type='person',
                        confidence=resolution.get('confidence', 1.0)
                    ))
                elif resolution['status'] == 'ambiguous':
                    issues.append(ValidationIssue(
                        field=field_name,
                        value=recipient,
                        issue_type='ambiguous',
                        candidates=resolution['candidates'],
                        message=f"Multiple contacts match '{recipient}'",
                        severity='error'
                    ))
                else:
                    if '@' in recipient:
                        field_results[field_name].append(recipient)
                    else:
                        issues.append(ValidationIssue(
                            field=field_name,
                            value=recipient,
                            issue_type='not_found',
                            message=f"Could not resolve '{recipient}' to an email",
                            severity='warning'
                        ))
            
            for fname in ['to', 'cc', 'bcc']:
                if field_results[fname]:
                    resolved_args[fname] = field_results[fname]
        
        # Determine status
        ambiguous = [i for i in issues if i.issue_type == 'ambiguous']
        if ambiguous:
            return PreflightResult(
                status=ValidationStatus.AMBIGUOUS,
                issues=issues,
                resolved_args=resolved_args,
                resolved_entities=resolved_entities,
                clarification_prompt=self._build_clarification_prompt(ambiguous),
                warnings=warnings,
                can_proceed=False
            )
        
        errors = [i for i in issues if i.severity == 'error']
        if errors:
            return PreflightResult(
                status=ValidationStatus.INVALID,
                issues=issues,
                resolved_args=resolved_args,
                resolved_entities=resolved_entities,
                warnings=warnings,
                can_proceed=False
            )
        
        return PreflightResult(
            status=ValidationStatus.VALID,
            resolved_args=resolved_args,
            resolved_entities=resolved_entities,
            issues=issues,
            warnings=warnings,
            can_proceed=True
        )
    
    async def validate_entity(
        self,
        entity_name: str,
        entity_type: str,  # "project", "document", "person", "task"
        user_id: int
    ) -> PreflightResult:
        """
        Validate a single entity reference against the knowledge graph.
        
        Args:
            entity_name: The name to validate (e.g., "Project Alpha")
            entity_type: Type of entity to look for
            user_id: User ID for scoping
            
        Returns:
            PreflightResult with resolved entity or ambiguity
        """
        if not self.graph:
            return PreflightResult(
                status=ValidationStatus.SKIP,
                can_proceed=True
            )
        
        try:
            from src.services.indexing.graph.schema import NodeType
            
            # Map entity type to graph node type
            type_map = {
                'project': NodeType.PROJECT,
                'document': NodeType.DOCUMENT,
                'person': NodeType.CONTACT,
                'task': NodeType.ACTION_ITEM,
            }
            
            node_type = type_map.get(entity_type)
            if not node_type:
                return PreflightResult(
                    status=ValidationStatus.SKIP,
                    can_proceed=True
                )
            
            # Search graph for matches
            matches = await self.graph.find_nodes_by_property(
                'name', entity_name,
                node_type=node_type,
                fuzzy=True,
                limit=5
            )
            
            if not matches:
                return PreflightResult(
                    status=ValidationStatus.VALID,
                    issues=[ValidationIssue(
                        field=entity_type,
                        value=entity_name,
                        issue_type='not_found',
                        message=f"No {entity_type} found matching '{entity_name}'",
                        severity='warning'
                    )],
                    can_proceed=True
                )
            
            if len(matches) == 1:
                match = matches[0]
                return PreflightResult(
                    status=ValidationStatus.VALID,
                    resolved_entities=[ResolvedEntity(
                        original=entity_name,
                        resolved_value=match.get('_id', match.get('id', '')),
                        display_name=match.get('name', entity_name),
                        entity_type=entity_type,
                        confidence=1.0,
                        graph_node_id=match.get('_id')
                    )],
                    can_proceed=True
                )
            
            # Multiple matches - ambiguous
            candidates = [m.get('name', 'Unknown') for m in matches]
            return PreflightResult(
                status=ValidationStatus.AMBIGUOUS,
                issues=[ValidationIssue(
                    field=entity_type,
                    value=entity_name,
                    issue_type='ambiguous',
                    candidates=candidates,
                    message=f"Multiple {entity_type}s match '{entity_name}'",
                    severity='error'
                )],
                clarification_prompt=f"I found multiple {entity_type}s matching '{entity_name}': {', '.join(candidates)}. Which one did you mean?",
                can_proceed=False
            )
            
        except Exception as e:
            logger.debug(f"Entity validation failed: {e}")
            return PreflightResult(
                status=ValidationStatus.SKIP,
                can_proceed=True
            )
    
    async def _resolve_contacts_batch(
        self,
        names: List[str],
        user_id: int
    ) -> List[Dict[str, Any]]:
        """Resolve multiple contacts in parallel."""
        tasks = [self._resolve_contact(name, user_id) for name in names]
        return await asyncio.gather(*tasks)
    
    async def _resolve_contact(self, name: str, user_id: int) -> Dict[str, Any]:
        """Resolve a contact name to email using ContactResolver."""
        # Check cache first
        cache_key = f"{user_id}:{name.lower()}"
        if cache_key in self._resolution_cache:
            cached_time = self._cache_timestamps.get(cache_key)
            if cached_time and datetime.now() - cached_time < self._cache_ttl:
                return self._resolution_cache[cache_key]
        
        # Check if already an email
        if '@' in name:
            result = {'status': 'resolved', 'email': name, 'name': name}
            self._resolution_cache[cache_key] = result
            self._cache_timestamps[cache_key] = datetime.now()
            return result
        
        if not self.contact_resolver:
            return {'status': 'unknown', 'email': None}
        
        try:
            # Try async resolution if available
            if hasattr(self.contact_resolver, 'resolve_alias'):
                resolved = await self._call_resolver(name, user_id)
            else:
                resolved = None
            
            if resolved:
                result = {
                    'status': 'resolved',
                    'email': resolved.email,
                    'name': resolved.person_name,
                    'confidence': resolved.confidence,
                    'node_id': getattr(resolved, 'person_node_id', None)
                }
                self._resolution_cache[cache_key] = result
                self._cache_timestamps[cache_key] = datetime.now()
                return result
            
            # Try fuzzy search via graph
            if self.graph:
                try:
                    from src.services.indexing.graph.schema import NodeType
                    
                    matches = await self.graph.find_nodes_by_property(
                        'name', name,
                        node_type=NodeType.CONTACT,
                        fuzzy=True,
                        limit=5
                    )
                    
                    if len(matches) > 1:
                        candidates = [m.get('name', m.get('email', '')) for m in matches]
                        return {'status': 'ambiguous', 'candidates': candidates}
                    elif len(matches) == 1:
                        match = matches[0]
                        result = {
                            'status': 'resolved',
                            'email': match.get('email'),
                            'name': match.get('name'),
                            'confidence': 0.8,  # Fuzzy match has lower confidence
                            'node_id': match.get('_id')
                        }
                        self._resolution_cache[cache_key] = result
                        self._cache_timestamps[cache_key] = datetime.now()
                        return result
                except Exception as e:
                    logger.debug(f"Graph search failed: {e}")
            
            return {'status': 'not_found'}
            
        except Exception as e:
            logger.debug(f"Contact resolution failed for '{name}': {e}")
            return {'status': 'error', 'error': str(e)}
    
    async def _call_resolver(self, name: str, user_id: int):
        """Call contact resolver (handles both sync and async)."""
        try:
            result = self.contact_resolver.resolve_alias(name, user_id)
            # Check if it's a coroutine
            if asyncio.iscoroutine(result):
                return await result
            return result
        except Exception:
            return None
    
    async def _check_calendar_conflict_real(
        self,
        user_id: int,
        start_time: datetime,
        end_time: datetime,
        calendar_id: str = "primary"
    ) -> Optional[Dict[str, Any]]:
        """Check for calendar conflicts using actual CalendarService."""
        if not self.calendar_service:
            return None
        
        try:
            # Get events in the time range
            events = self.calendar_service.list_events(
                start_date=start_time.date().isoformat(),
                end_date=end_time.date().isoformat(),
                days_back=0,
                days_ahead=1,
                max_results=20
            )
            
            if not events:
                return None
            
            # Check for overlaps
            for event in events:
                event_start = self._parse_event_time(event.get('start', {}))
                event_end = self._parse_event_time(event.get('end', {}))
                
                if not event_start or not event_end:
                    continue
                
                # Check overlap: events overlap if start1 < end2 AND start2 < end1
                if start_time < event_end and event_start < end_time:
                    # Conflict found!
                    conflict_title = event.get('summary', 'Busy')
                    conflict_time = event_start.strftime('%I:%M %p') if event_start else 'Unknown'
                    
                    # Try to find alternative slots
                    alternatives = []
                    try:
                        duration = int((end_time - start_time).total_seconds() / 60)
                        free_slots = self.calendar_service.find_free_time(
                            duration_minutes=duration,
                            max_suggestions=3,
                            working_hours_only=True
                        )
                        for slot in free_slots:
                            slot_start = slot.get('start', '')
                            if slot_start:
                                try:
                                    dt = datetime.fromisoformat(slot_start.replace('Z', '+00:00'))
                                    alternatives.append(dt.strftime('%I:%M %p'))
                                except (ValueError, TypeError):
                                    # Invalid datetime format, skip this alternative
                                    pass
                    except Exception:
                        pass
                    
                    return {
                        'title': conflict_title,
                        'time': conflict_time,
                        'event_id': event.get('id'),
                        'alternatives': alternatives
                    }
            
            return None
            
        except Exception as e:
            logger.debug(f"Conflict check failed: {e}")
            return None
    
    def _parse_datetime(self, value: str) -> Optional[datetime]:
        """Parse datetime from various formats."""
        if not value:
            return None
        
        # Try ISO format first
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            # ISO format parsing failed, try natural language
            pass
        
        # Try dateparser for natural language
        try:
            import dateparser
            parsed = dateparser.parse(value, settings={
                'PREFER_DATES_FROM': 'future',
                'RETURN_AS_TIMEZONE_AWARE': False
            })
            return parsed
        except (ImportError, ValueError, TypeError):
            # dateparser not available or failed, return None
            pass
        
        return None
    
    def _parse_event_time(self, time_data: Dict) -> Optional[datetime]:
        """Parse event time from Google Calendar format."""
        if not time_data:
            return None
        
        dt_str = time_data.get('dateTime') or time_data.get('date')
        if not dt_str:
            return None
        
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            # Invalid datetime format
            return None
    
    def _build_clarification_prompt(self, issues: List[ValidationIssue]) -> str:
        """Build a clarification prompt for ambiguous issues."""
        if not issues:
            return ""
        
        if len(issues) == 1:
            issue = issues[0]
            candidates = ", ".join(issue.candidates[:5])
            return (
                f"I found multiple contacts matching '{issue.value}'. "
                f"Did you mean: {candidates}? "
                f"Please specify which one."
            )
        
        # Multiple issues
        parts = []
        for issue in issues:
            candidates = ", ".join(issue.candidates[:3])
            parts.append(f"'{issue.value}' (could be: {candidates})")
        
        return (
            f"I need clarification on these contacts: {'; '.join(parts)}. "
            f"Please specify which ones you meant."
        )


def validate_preflight(validator_getter: Callable, validation_type: str = "calendar"):
    """
    Decorator for automatic pre-flight validation on tool methods.
    
    Usage:
        class MyTool:
            @validate_preflight(lambda self: self.validator, "calendar")
            async def schedule_meeting(self, attendees, start_time, **kwargs):
                # Attendees are already resolved at this point
                pass
    
    Args:
        validator_getter: Function to get validator from instance
        validation_type: "calendar", "email", or "entity"
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            validator = validator_getter(self)
            
            if not validator:
                return await func(self, *args, **kwargs)
            
            user_id = kwargs.get('user_id') or getattr(self, 'user_id', None)
            
            if validation_type == "calendar":
                result = await validator.validate_calendar_args(
                    user_id=user_id,
                    attendees=kwargs.get('attendees'),
                    start_time=kwargs.get('start_time'),
                    end_time=kwargs.get('end_time'),
                    duration_minutes=kwargs.get('duration_minutes'),
                    check_conflicts=kwargs.get('check_conflicts', True)
                )
            elif validation_type == "email":
                result = await validator.validate_email_args(
                    user_id=user_id,
                    to=kwargs.get('to'),
                    cc=kwargs.get('cc'),
                    bcc=kwargs.get('bcc')
                )
            else:
                result = PreflightResult(status=ValidationStatus.SKIP, can_proceed=True)
            
            # Handle validation result
            if result.status == ValidationStatus.AMBIGUOUS:
                return {
                    'clarification_needed': True,
                    'prompt': result.clarification_prompt,
                    'issues': [i.message for i in result.issues]
                }
            
            if not result.can_proceed:
                return {
                    'error': True,
                    'message': '; '.join(i.message for i in result.issues),
                    'issues': result.issues
                }
            
            # Update kwargs with resolved values
            if result.resolved_args:
                kwargs.update(result.resolved_args)
            
            # Add warnings if any
            if result.warnings:
                kwargs['_preflight_warnings'] = result.warnings
            
            return await func(self, *args, **kwargs)
        
        return wrapper
    return decorator

