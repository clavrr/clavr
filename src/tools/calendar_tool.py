"""
Calendar Tool - Service Layer Integration

This tool provides a clean, maintainable interface for Google Calendar operations
using the CalendarService business logic layer.

Architecture:
    CalendarTool → CalendarService → GoogleCalendarClient → Calendar API

The service layer provides:
- Clean business logic interfaces
- Centralized error handling
- Shared code between tools and workers
- Better testability

For advanced features (analytics, smart queries), specialized modules are used:
- calendar/analytics.py: Calendar analytics and insights
- calendar/utils.py: Smart query parsing
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field

from .base_tool import ClavrBaseTool
from ..integrations.google_calendar.service import CalendarService
from ..integrations.google_calendar.exceptions import (
    CalendarServiceException,
    ServiceUnavailableException
)
from ..core.calendar.template_storage import TemplateStorage
from ..core.calendar.utils import DEFAULT_DURATION_MINUTES, DEFAULT_DAYS_AHEAD
from .constants import ToolConfig, ParserIntegrationConfig, ToolLimits
from ..utils.logger import setup_logger
from ..utils.config import Config, get_api_base_url
from ..ai.prompts import (
    CALENDAR_CONVERSATIONAL_LIST,
    CALENDAR_CONVERSATIONAL_EMPTY
)

# Import modular components for advanced features
from .calendar import (
    CalendarAnalytics,
    SmartCalendarParser,
    CalendarOrchestrator
)
from .calendar.task_coordinator import CalendarTaskCoordinator

logger = setup_logger(__name__)


class CalendarActionInput(BaseModel):
    """Input schema for calendar operations"""
    action: str = Field(
        description="Action: 'list', 'create', 'update', 'delete', 'search', 'find_free_time', 'check_availability', 'check_conflicts', 'analyze_conflicts', 'analytics', 'find_duplicates', 'find_missing_details', 'prepare_meeting', 'move_event', 'smart_query', 'create_with_tasks', 'add_prep_tasks', 'add_followup_tasks', 'schedule_prep_time'"
    )
    title: Optional[str] = Field(default=None, description="Event title/summary")
    start_time: Optional[str] = Field(default=None, description="Event start time (ISO format)")
    end_time: Optional[str] = Field(default=None, description="Event end time (ISO format)")
    duration_minutes: Optional[int] = Field(default=60, description="Event duration in minutes")
    attendees: Optional[List[str]] = Field(default=None, description="List of attendee emails")
    description: Optional[str] = Field(default=None, description="Event description")
    location: Optional[str] = Field(default=None, description="Event location")
    event_id: Optional[str] = Field(default=None, description="Event ID (for update/delete)")
    days_ahead: Optional[int] = Field(default=7, description="Days to look ahead")
    days_back: Optional[int] = Field(default=0, description="Days to look back")
    start_date: Optional[str] = Field(default=None, description="Start date (ISO format)")
    end_date: Optional[str] = Field(default=None, description="End date (ISO format)")
    query: Optional[str] = Field(default=None, description="Search query or smart natural language query")
    recurrence: Optional[str] = Field(default=None, description="Recurrence pattern (RRULE format)")
    new_start_time: Optional[str] = Field(default=None, description="New start time for move_event")
    skip_conflict_check: Optional[bool] = Field(default=False, description="Skip automatic conflict detection (default: False)")
    create_prep_tasks: Optional[bool] = Field(default=True, description="Create preparation tasks for event")
    create_followup_tasks: Optional[bool] = Field(default=True, description="Create follow-up tasks for event")


class CalendarTool(ClavrBaseTool):
    """
    Calendar operations tool with service layer integration
    
    **Architecture:**
    CalendarTool → CalendarService → GoogleCalendarClient → Calendar API
    
    **Capabilities:**
    - List upcoming events
    - Create/update/delete events
    - Search events
    - Find free time slots
    - Check conflicts and availability
    - Schedule meetings intelligently
    - Calendar analytics
    
    **Examples:**
        "Show my meetings for today"
        "Schedule a meeting tomorrow at 2pm"
        "Find free time this week"
        "Check for calendar conflicts"
        "Analyze my calendar"
    """
    
    name: str = "calendar"
    description: str = (
        "Manage Google Calendar events with advanced capabilities. "
        "Can list, create, update, delete events, find free time, check conflicts, and provide analytics."
    )
    args_schema: type[BaseModel] = CalendarActionInput
    config: Optional[Config] = Field(default=None, exclude=True)
    
    # Private attributes
    _user_id: Optional[int] = None
    _credentials: Optional[Any] = None
    _calendar_service: Optional[CalendarService] = None
    _template_storage: Optional[TemplateStorage] = None
    _parser: Optional[Any] = None  # CalendarParser instance
    
    # Module instances for advanced features (lazy-loaded)
    _analytics: Optional[CalendarAnalytics] = None
    _orchestrator: Optional[CalendarOrchestrator] = None
    _smart_parser: Optional[SmartCalendarParser] = None
    _task_coordinator: Optional[CalendarTaskCoordinator] = None
    
    # Task service for cross-tool integration
    _task_service: Optional[Any] = None
    
    # Email service for resolving attendee names to emails
    _email_service: Optional[Any] = None
    
    # Context tracking for follow-up queries (stores last shown event list)
    _last_event_list: Optional[List[Dict[str, Any]]] = None
    _last_event_list_query: Optional[str] = None
    
    def __init__(
        self,
        config: Optional[Config] = None,
        user_id: Optional[int] = None,
        credentials: Optional[Any] = None,
        rag_engine: Optional[Any] = None,
        **kwargs
    ):
        """
        Initialize calendar tool with service layer integration
        
        Args:
            config: Configuration object
            user_id: Optional user ID for session-based credential retrieval
            credentials: Optional Google OAuth credentials
            rag_engine: Optional RAG engine for email indexing and contact resolution
        """
        super().__init__(config=config, **kwargs)
        self._user_id = user_id
        self._credentials = credentials
        self._rag_engine = rag_engine  # Store rag_engine for email service initialization
        self._calendar_service = None
        self._template_storage = TemplateStorage()
        self._analytics = None
        self._orchestrator = None
        self._smart_parser = None
        self._task_coordinator = None
        self._task_service = None
        self._email_service = None
        self._last_event_list = None
        self._last_event_list_query = None
        
        # Initialize handlers
        from .calendar.formatting_handlers import CalendarFormattingHandlers
        from .calendar.action_handlers import CalendarActionHandlers
        from .calendar.query_handlers import CalendarQueryHandlers
        
        self._set_attr('formatting_handlers', CalendarFormattingHandlers(self))
        self._set_attr('action_handlers', CalendarActionHandlers(self))
        self._set_attr('query_handlers', CalendarQueryHandlers(self))
        
        # Initialize date parser if available
        if config and self.date_parser is None:
            try:
                from ..utils import FlexibleDateParser
                self._set_attr('date_parser', FlexibleDateParser(config))
            except Exception as e:
                logger.debug(f"FlexibleDateParser not available: {e}")
    
    @property
    def calendar_service(self) -> CalendarService:
        """Get or create the Calendar service with user credentials"""
        # Always recreate service to ensure fresh credentials (don't cache)
        # This ensures that after re-authentication, we use the new credentials
        if not self.config:
            raise ValueError("Config is required for CalendarService")
        
        logger.info(f"[CAL] Creating CalendarService - user_id={self._user_id}")
        
        # Use ServiceFactory to create CalendarService (handles credential loading and refresh)
        if self._user_id:
            try:
                from ..services.factory import ServiceFactory
                from ..database import get_db_context
                
                # Use ServiceFactory to create CalendarService (handles credential loading)
                with get_db_context() as db:
                    service_factory = ServiceFactory(config=self.config)
                    calendar_service = service_factory.create_calendar_service(
                        user_id=self._user_id,
                        db_session=db
                    )
                    
                    if calendar_service and calendar_service.calendar_client:
                        logger.info(f"[OK] CalendarService created via ServiceFactory (user_id={self._user_id})")
                        return calendar_service
                    else:
                        logger.warning(f"[CAL] CalendarService created but client not available")
            except Exception as e:
                logger.error(f"[CAL] Failed to create CalendarService via ServiceFactory: {e}", exc_info=True)
                # Fallback to manual credential loading
                credentials = self._get_credentials_from_session(self._user_id, service_name="CAL")
                if credentials:
                    return CalendarService(config=self.config, credentials=credentials)
        
        # If credentials provided directly, use them
        if self._credentials:
            return CalendarService(config=self.config, credentials=self._credentials)
        
        # No credentials available
        logger.warning(f"[CAL] No credentials available for CalendarService")
        return CalendarService(config=self.config, credentials=None)
    
    @property
    def parser(self):
        """Get CalendarParser instance (lazy-loaded)"""
        if self._parser is None and self.config:
            try:
                from ..agent.parsers.calendar_parser import CalendarParser
                self._parser = CalendarParser(
                    config=self.config,
                    rag_service=getattr(self, 'rag_service', None),
                    memory=getattr(self, 'memory', None)
                )
                logger.info("[OK] CalendarParser initialized for natural language understanding")
            except Exception as e:
                logger.warning(f"Failed to initialize CalendarParser: {e}")
                self._parser = None
        return self._parser
    
    @property
    def email_service(self) -> Optional[Any]:
        """Get or create EmailService for resolving attendee names to emails (lazy-loaded)"""
        if self._email_service is None and self.config:
            try:
                from ..integrations.gmail.service import EmailService
                
                logger.info(f"[CAL] Initializing EmailService for CalendarTool - user_id={self._user_id}, has_credentials={self._credentials is not None}")
                
                # Get credentials if not already provided
                credentials = self._credentials
                if not credentials and self._user_id:
                    logger.info(f"[CAL] Attempting to load credentials from session for user_id={self._user_id}")
                    credentials = self._get_credentials_from_session(self._user_id, service_name="EMAIL")
                
                # Create IntelligentEmailIndexer instance to get the hybrid_coordinator
                hybrid_coordinator = None
                if hasattr(self, '_rag_engine') and self._rag_engine:
                    try:
                        from ..services.indexing import IntelligentEmailIndexer
                        
                        # Try to create indexer to get hybrid coordinator
                        temp_indexer = IntelligentEmailIndexer(
                            config=self.config,
                            google_client=None,  # Will be set later
                            llm_client=getattr(self, '_llm_client', None),
                            rag_engine=self._rag_engine,
                            use_knowledge_graph=True
                        )
                        # Get coordinator from indexer (it's stored as hybrid_index)
                        hybrid_coordinator = getattr(temp_indexer, 'hybrid_index', None)
                        if hybrid_coordinator:
                            logger.info(f"[CAL] Hybrid coordinator available (has_graph={bool(getattr(hybrid_coordinator, 'graph', None))}), will be set for EmailService")
                        else:
                            logger.warning("[CAL] Hybrid coordinator NOT available from IntelligentEmailIndexer for CalendarTool")
                    except Exception as e:
                        logger.debug(f"[CAL] Could not get hybrid coordinator for CalendarTool: {e}")
                
                if credentials or self._credentials:
                    # Create email service with credentials and hybrid_coordinator
                    self._email_service = EmailService(
                        config=self.config,
                        credentials=credentials or self._credentials,
                        rag_engine=getattr(self, '_rag_engine', None),
                        hybrid_coordinator=hybrid_coordinator # Pass hybrid_coordinator here
                    )
                    logger.info(f"[OK] EmailService initialized for CalendarTool (user_id={self._user_id})")
                else:
                    logger.debug(f"[CAL] No credentials available for EmailService - attendee name resolution will be limited")
            except Exception as e:
                logger.warning(f"[CAL] Failed to initialize EmailService for attendee lookup: {e}", exc_info=True)
                self._email_service = None
        
        return self._email_service
    
    @property
    def analytics(self) -> CalendarAnalytics:
        """Get calendar analytics module (lazy-loaded)"""
        if self._analytics is None:
            self._analytics = CalendarAnalytics(
                self.calendar_service.calendar_client if self.calendar_service else None,
                self.config
            )
        return self._analytics
    
    @property
    def smart_parser(self) -> SmartCalendarParser:
        """Get smart calendar parser (lazy-loaded)"""
        if self._smart_parser is None:
            self._smart_parser = SmartCalendarParser()
        return self._smart_parser
    
    @property
    def task_coordinator(self) -> CalendarTaskCoordinator:
        """Get calendar-task coordinator (lazy-loaded)"""
        if self._task_coordinator is None:
            self._task_coordinator = CalendarTaskCoordinator(
                calendar_service=self.calendar_service,
                task_service=self._task_service
            )
        return self._task_coordinator
    
    def set_task_service(self, task_service: Any):
        """Set task service for cross-tool integration"""
        self._task_service = task_service
        # Refresh coordinator if already created
        if self._task_coordinator is not None:
            self._task_coordinator.task_service = task_service
    
    def _extract_start_time_from_event(self, event: Dict[str, Any]):
        """
        Safely extract start time from an event, handling both formats:
        - Google Calendar API format: {'start': {'dateTime': '...', 'date': '...'}}
        - Parsed format: {'start': datetime.datetime(...)}
        
        Returns:
            datetime object, ISO string, or None
        """
        start = event.get('start')
        if not start:
            return None
        
        # If start is already a datetime object, return it as-is
        if isinstance(start, datetime):
            return start
        
        # If start is a dictionary, extract dateTime or date
        if isinstance(start, dict):
            return start.get('dateTime') or start.get('date')
        
        return None
    
    def _run(
        self,
        action: str,
        title: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        duration_minutes: int = 60,
        attendees: Optional[List[str]] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        event_id: Optional[str] = None,
        days_ahead: int = 7,
        days_back: int = 0,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        query: Optional[str] = None,
        recurrence: Optional[str] = None,
        new_start_time: Optional[str] = None,
        skip_conflict_check: bool = False,
        **kwargs
    ) -> str:
        """
        Execute calendar operation using service layer
        
        Routes actions to CalendarService for core operations and
        specialized modules for advanced features (analytics, insights).
        """
        logger.info(f"[CAL] CalendarTool._run called with action='{action}'")
        
        # Store parsed time_period for later use
        parsed_time_period = None
        
        # === PARSER INTEGRATION ===
        # Use CalendarParser for natural language understanding before execution
        # CRITICAL: Only use parser for parsing, NOT for execution when action is already provided
        # This prevents duplicate event creation when action="create" is explicitly provided
        if query and self.parser:
            try:
                if action:
                    # Action already provided - only use parser for entity extraction, not action routing
                    # This prevents duplicate execution when action is explicitly set
                    logger.info(f"[CAL-PARSER] Action '{action}' already provided, using parser only for entity extraction")
                    parsed = self.parser.parse_query_to_params(query)
                    parsed_entities = parsed.get('entities', {})
                    parsed_confidence = parsed.get('confidence', 0.0)
                    logger.info(f"[CAL-PARSER] Extracted entities for action '{action}': {list(parsed_entities.keys())}")
                else:
                    # No action provided - use parser for both action detection and entity extraction
                    logger.info(f"[CAL-PARSER] Parsing query: '{query}'")
                    parsed = self.parser.parse_query_to_params(query)
                    
                    parsed_action = parsed.get('action')
                    parsed_entities = parsed.get('entities', {})
                    parsed_confidence = parsed.get('confidence', 0.0)
                    parsed_metadata = parsed.get('metadata', {})
                    
                    logger.info(f"[CAL-PARSER] Result: action={parsed_action}, confidence={parsed_confidence:.2f}")
                    
                    # Reject if parser detected this is not a calendar query
                    if parsed_action == 'reject':
                        logger.warning(f"[CAL-PARSER] Query rejected: {parsed_metadata.get('error')}")
                        return parsed_metadata.get('suggestion', 'This query cannot be handled by the calendar tool')
                    
                    # Use parsed action if confidence is high enough
                    if parsed_confidence >= ParserIntegrationConfig.USE_PARSED_ACTION_THRESHOLD:
                        action = parsed_action
                        logger.info(f"[CAL-PARSER] Using parsed action: {action} (confidence: {parsed_confidence:.2f})")
                    elif parsed_confidence < ParserIntegrationConfig.LOW_CONFIDENCE_WARNING_THRESHOLD:
                        logger.warning(f"[CAL-PARSER] Low confidence ({parsed_confidence:.2f}) for query: '{query}'")
                
                # Enhance parameters from parsed entities (only if not already provided)
                # This applies to both cases (action provided or not)
                if not title and parsed_entities.get('title'):
                    title = parsed_entities['title']
                    logger.info(f"[CAL-PARSER] Enhanced title: {title}")
                
                if not start_time and parsed_entities.get('start_time'):
                    start_time = parsed_entities['start_time']
                    logger.info(f"[CAL-PARSER] Enhanced start_time: {start_time}")
                
                if not end_time and parsed_entities.get('llm_end_time'):
                    end_time = parsed_entities['llm_end_time']
                    logger.info(f"[CAL-PARSER] Enhanced end_time: {end_time}")
                
                if parsed_entities.get('duration'):
                    duration_minutes = parsed_entities['duration']
                    logger.info(f"[CAL-PARSER] Enhanced duration: {duration_minutes} minutes")
                
                if not attendees and parsed_entities.get('attendees'):
                    attendees = parsed_entities['attendees']
                    logger.info(f"[CAL-PARSER] Enhanced attendees: {attendees}")
                
                if not location and parsed_entities.get('location'):
                    location = parsed_entities['location']
                    logger.info(f"[CAL-PARSER] Enhanced location: {location}")
                
                if not event_id and parsed_entities.get('event_id'):
                    event_id = parsed_entities['event_id']
                    logger.info(f"[CAL-PARSER] Enhanced event_id: {event_id}")
                
                # For list/search actions, use parsed time period
                if action in ['list', 'search', 'count'] and parsed_entities.get('time_period'):
                    time_period = parsed_entities['time_period']
                    parsed_time_period = time_period  # Store for later use
                    logger.info(f"[CAL-PARSER] Using time_period: {time_period}")
                    # Convert time_period to start_date/end_date
                    from ..core.calendar.utils import get_day_boundaries
                    from datetime import datetime as dt, timedelta
                    
                    if time_period == 'today':
                        # Get today's boundaries
                        today_start, today_end = get_day_boundaries(dt.now(), self.config)
                        start_date = today_start.isoformat()
                        end_date = today_end.isoformat()
                        days_ahead = 0
                        days_back = 0
                        logger.info(f"[CAL-PARSER] Converted 'today' to: start={start_date}, end={end_date}")
                    elif time_period == 'tomorrow':
                        # Get tomorrow's boundaries
                        tomorrow = dt.now() + timedelta(days=1)
                        tomorrow_start, tomorrow_end = get_day_boundaries(tomorrow, self.config)
                        start_date = tomorrow_start.isoformat()
                        end_date = tomorrow_end.isoformat()
                        days_ahead = 1
                        days_back = 0
                        logger.info(f"[CAL-PARSER] Converted 'tomorrow' to: start={start_date}, end={end_date}")
                    elif time_period in ['this week', 'week']:
                        # This week: from today to end of week
                        today = dt.now()
                        days_until_sunday = (6 - today.weekday()) % 7  # Days until next Sunday
                        if days_until_sunday == 0:
                            days_until_sunday = 7  # If today is Sunday, go to next Sunday
                        days_ahead = days_until_sunday
                        days_back = 0
                        start_date = None
                        end_date = None
                        logger.info(f"[CAL-PARSER] Converted 'this week' to: days_ahead={days_ahead}")
                    elif time_period == 'next week':
                        # Next week: 7 days from now
                        days_ahead = 14
                        days_back = 0
                        start_date = None
                        end_date = None
                        logger.info(f"[CAL-PARSER] Converted 'next week' to: days_ahead={days_ahead}")
                    elif time_period == 'yesterday':
                        # Yesterday: get yesterday's boundaries
                        yesterday = dt.now() - timedelta(days=1)
                        yesterday_start, yesterday_end = get_day_boundaries(yesterday, self.config)
                        start_date = yesterday_start.isoformat()
                        end_date = yesterday_end.isoformat()
                        days_ahead = 0
                        days_back = 1
                        logger.info(f"[CAL-PARSER] Converted 'yesterday' to: start={start_date}, end={end_date}")
                    elif time_period == 'last_week' or time_period == 'previous_week':
                        # Last week: 7 days back
                        today = dt.now()
                        last_week_start = today - timedelta(days=7)
                        last_week_end = today - timedelta(days=1)
                        last_week_start_boundary, _ = get_day_boundaries(last_week_start, self.config)
                        _, last_week_end_boundary = get_day_boundaries(last_week_end, self.config)
                        start_date = last_week_start_boundary.isoformat()
                        end_date = last_week_end_boundary.isoformat()
                        days_ahead = 0
                        days_back = 7
                        logger.info(f"[CAL-PARSER] Converted 'last_week' to: start={start_date}, end={end_date}")
                    elif time_period == 'last_month' or time_period == 'previous_month':
                        # Last month: approximately 30 days back
                        today = dt.now()
                        last_month_start = today - timedelta(days=30)
                        last_month_end = today - timedelta(days=1)
                        last_month_start_boundary, _ = get_day_boundaries(last_month_start, self.config)
                        _, last_month_end_boundary = get_day_boundaries(last_month_end, self.config)
                        start_date = last_month_start_boundary.isoformat()
                        end_date = last_month_end_boundary.isoformat()
                        days_ahead = 0
                        days_back = 30
                        logger.info(f"[CAL-PARSER] Converted 'last_month' to: start={start_date}, end={end_date}")
                    # For other time periods, keep default behavior
                
            except Exception as e:
                logger.error(f"[CAL-PARSER] Parser failed: {e}", exc_info=True)
                # Continue with original parameters on parser failure
        
        try:
            # Check service availability
            try:
                self.calendar_service._ensure_available()
            except ServiceUnavailableException:
                return self._get_google_calendar_setup_message()
            
            # === CORE EVENT OPERATIONS (via CalendarService) ===
            if action == "create":
                return self.action_handlers.handle_create(
                    title=title,
                    start_time=start_time,
                    end_time=end_time,
                    duration_minutes=duration_minutes,
                    attendees=attendees,
                    description=description,
                    location=location,
                    recurrence=recurrence,
                    **kwargs
                )
            
            elif action == "update":
                return self.action_handlers.handle_update(
                    event_id=event_id,
                    title=title,
                    start_time=start_time,
                    end_time=end_time,
                    description=description,
                    location=location,
                    attendees=attendees,
                    query=query,
                    **kwargs
                )
            
            elif action == "delete":
                return self.action_handlers.handle_delete(
                    event_id=event_id,
                    title=title,
                    query=query,
                    **kwargs
                )
            
            # === SEARCH AND LIST OPERATIONS ===
            elif action == "list":
                return self.query_handlers.handle_list(
                    start_date=start_date,
                    end_date=end_date,
                    days_back=days_back,
                    days_ahead=days_ahead,
                    query=query,
                    parsed_time_period=parsed_time_period,
                    **kwargs
                )
            
            elif action == "search":
                return self.query_handlers.handle_search(
                    query=query,
                    start_date=start_date,
                    end_date=end_date,
                    **kwargs
                )
            
            # === SMART SCHEDULING ===
            elif action == "find_free_time":
                return self.query_handlers.handle_find_free_time(
                    duration_minutes=duration_minutes,
                    start_date=start_date,
                    end_date=end_date,
                    **kwargs
                )
            
            elif action == "check_conflicts":
                return self.query_handlers.handle_check_conflicts(
                    start_time=start_time,
                    end_time=end_time,
                    duration_minutes=duration_minutes,
                    **kwargs
                )
            
            elif action == "check_availability":
                return self.query_handlers.handle_check_availability(
                    start_time=start_time,
                    end_time=end_time,
                    **kwargs
                )
            
            # === ADVANCED OPERATIONS (using specialized modules) ===
            elif action == "schedule_meeting":
                if not title or not attendees:
                    return "[ERROR] Please provide 'title' and 'attendees' for schedule_meeting action"
                
                result = self.calendar_service.schedule_meeting(
                    title=title,
                    attendees=attendees,
                    duration_minutes=duration_minutes,
                    preferred_times=[start_time] if start_time else None,
                    description=description,
                    location=location
                )
                
                return f"Meeting '{title}' scheduled successfully (ID: {result.get('id', 'N/A')})"
            
            # === ANALYTICS (via CalendarAnalytics module) ===
            elif action == "analytics":
                return self.analytics.get_analytics(start_date, end_date)
            
            elif action == "find_missing_details":
                return self.analytics.find_missing_details(days_ahead)
            
            elif action == "find_duplicates":
                # Use analytics module for duplicate detection
                return "[INFO] Duplicate detection feature in development"
            
            elif action == "prepare_meeting":
                if not event_id:
                    return "[ERROR] Please provide 'event_id' for prepare_meeting action"
                return self.analytics.prepare_meeting(event_id)
            
            # === SMART NATURAL LANGUAGE QUERY ===
            elif action == "smart_query":
                if not query:
                    return "[ERROR] Please provide a query for smart_query action"
                return "[INFO] Smart query feature in development"
            
            elif action == "move_event":
                if not event_id or not new_start_time:
                    return "[ERROR] Please provide 'event_id' and 'new_start_time' for move_event action"
                # Move is essentially an update with new start time
                result = self.calendar_service.update_event(
                    event_id=event_id,
                    start_time=new_start_time
                )
                return f"Event moved to {new_start_time}"
            
            elif action == "check_availability":
                return "[INFO] Availability checking feature in development"
            
            elif action == "analyze_conflicts":
                return "[INFO] Conflict analysis feature in development"
            
            # === CALENDAR-TASK INTEGRATION ===
            elif action == "create_with_tasks":
                if not title or not start_time:
                    return "[ERROR] Please provide 'title' and 'start_time' for create_with_tasks action"
                
                # Create calendar event
                event = self.calendar_service.create_event(
                    title=title,
                    start_time=start_time,
                    end_time=end_time,
                    duration_minutes=duration_minutes,
                    description=description,
                    location=location,
                    attendees=attendees
                )
                
                event_id = event.get('id')
                
                # Create prep and follow-up tasks
                prep_tasks = []
                followup_tasks = []
                
                if self._task_service:
                    prep_tasks = self.task_coordinator.create_prep_tasks(
                        event_id=event_id,
                        event_data=event,
                        prep_hours_before=24,
                        auto_suggestions=True
                    )
                    
                    followup_tasks = self.task_coordinator.create_followup_tasks(
                        event_id=event_id,
                        event_data=event,
                        followup_days_after=1
                    )
                
                return f"Created event '{title}' with {len(prep_tasks)} prep tasks and {len(followup_tasks)} follow-up tasks"
            
            elif action == "add_prep_tasks":
                if not event_id:
                    return "[ERROR] Please provide 'event_id' for add_prep_tasks action"
                
                # Get event
                event = self.calendar_service.get_event(event_id)
                
                # Create prep tasks
                if self._task_service:
                    prep_tasks = self.task_coordinator.create_prep_tasks(
                        event_id=event_id,
                        event_data=event,
                        prep_hours_before=24,
                        auto_suggestions=True
                    )
                    return f"Created {len(prep_tasks)} prep tasks for '{event.get('summary', 'event')}'"
                else:
                    return "[ERROR] Task service not available. Use set_task_service() first."
            
            elif action == "add_followup_tasks":
                if not event_id:
                    return "[ERROR] Please provide 'event_id' for add_followup_tasks action"
                
                # Get event
                event = self.calendar_service.get_event(event_id)
                
                # Create follow-up tasks
                if self._task_service:
                    followup_tasks = self.task_coordinator.create_followup_tasks(
                        event_id=event_id,
                        event_data=event,
                        followup_days_after=1
                    )
                    return f"Created {len(followup_tasks)} follow-up tasks for '{event.get('summary', 'event')}'"
                else:
                    return "[ERROR] Task service not available. Use set_task_service() first."
            
            elif action == "schedule_prep_time":
                if not event_id:
                    return "[ERROR] Please provide 'event_id' for schedule_prep_time action"
                
                # Get event
                event = self.calendar_service.get_event(event_id)
                
                # Schedule prep time
                prep_event = self.task_coordinator.schedule_prep_time(
                    event_id=event_id,
                    event_data=event,
                    prep_duration_minutes=duration_minutes or 60,
                    hours_before=24
                )
                
                if prep_event:
                    return f"Scheduled {duration_minutes}min prep time for '{event.get('summary', 'event')}'"
                else:
                    return f"Could not find free time for prep work before meeting"
            
            else:
                return f"[ERROR] Unknown action: {action}"
                
        except CalendarServiceException as e:
            error_msg = str(e)
            # Check for invalid_grant authentication errors
            if 'invalid_grant' in error_msg.lower() or 'refresh token' in error_msg.lower() or 'expired' in error_msg.lower():
                # Clear cached service to force recreation with fresh credentials
                self._calendar_service = None
                # Also clear ServiceFactory cache for this user
                try:
                    from ..services.factory import ServiceFactory
                    if self.config and self._user_id:
                        service_factory = ServiceFactory(config=self.config)
                        # Clear cache - use getattr to avoid type checker issues
                        clear_method = getattr(service_factory, 'clear_cache', None)
                        if clear_method:
                            clear_method('calendar', self._user_id)  # type: ignore
                except Exception as cache_error:
                    logger.debug(f"Failed to clear ServiceFactory cache: {cache_error}")
                
                return (
                    "[ERROR] Your Google Calendar authentication has expired. "
                    "Please log out and log back in to refresh your credentials.\n\n"
                    "This usually happens when:\n"
                    "  - You changed your Google account password\n"
                    "  - You revoked access to the app\n"
                    "  - The refresh token expired (after 6 months of inactivity)"
                )
            return f"[ERROR] Calendar service error: {error_msg}"
        except Exception as e:
            error_msg = str(e)
            # Check for invalid_grant authentication errors
            if 'invalid_grant' in error_msg.lower() or 'refresh token' in error_msg.lower() or 'expired' in error_msg.lower():
                # Clear cached service to force recreation with fresh credentials
                self._calendar_service = None
                # Also clear ServiceFactory cache for this user
                try:
                    from ..services.factory import ServiceFactory
                    if self.config and self._user_id:
                        service_factory = ServiceFactory(config=self.config)
                        # Clear cache - use getattr to avoid type checker issues
                        clear_method = getattr(service_factory, 'clear_cache', None)
                        if clear_method:
                            clear_method('calendar', self._user_id)  # type: ignore
                except Exception as cache_error:
                    logger.debug(f"Failed to clear ServiceFactory cache: {cache_error}")
                
                return (
                    "[ERROR] Your Google Calendar authentication has expired. "
                    "Please log out and log back in to refresh your credentials.\n\n"
                    "This usually happens when:\n"
                    "  - You changed your Google account password\n"
                    "  - You revoked access to the app\n"
                    "  - The refresh token expired (after 6 months of inactivity)"
                )
            return self._handle_error(e, f"calendar action '{action}'")
    
    async def _arun(self, **kwargs) -> str:
        """Async execution (calls sync version)"""
        return self._run(**kwargs)
    
    # === HELPER METHODS ===
    
    def _handle_follow_up_selection(self, query: str, title: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Handle follow-up selections like "the first one", "the second one", "the one at [time]"
        
        Uses stored context from previous event list, or uses parser/memory to understand context.
        """
        if not self._last_event_list:
            # If no stored list, try to get recent events that might match
            query_lower = (query or "").lower().strip()
            has_ordinal = any(word in query_lower for word in ['first', 'second', 'third', 'one', 'two', 'three', '1', '2', '3'])
            if has_ordinal:
                try:
                    events = self.calendar_service.list_events(days_ahead=7)
                    events = events[:10]
                    logger.info(f"[CAL] No stored list, using upcoming events as context ({len(events)} events)")
                    self._last_event_list = events
                except:
                    return None
            else:
                return None
        
        query_lower = (query or "").lower().strip()
        events = self._last_event_list
        
        # Handle ordinal references: "first", "second", "third", "1st", "2nd", etc.
        ordinal_patterns = {
            'first': 0, '1st': 0, 'one': 0, '1': 0,
            'second': 1, '2nd': 1, 'two': 1, '2': 1,
            'third': 2, '3rd': 2, 'three': 2, '3': 2,
            'fourth': 3, '4th': 3, 'four': 3, '4': 3,
            'fifth': 4, '5th': 4, 'five': 4, '5': 4,
        }
        
        for pattern, index in ordinal_patterns.items():
            if pattern in query_lower and index < len(events):
                logger.info(f"[CAL] Resolved ordinal reference '{pattern}' to index {index}")
                return events[index]
        
        # Handle time-based references: "the one at [time]", "at [time]"
        if "at" in query_lower:
            # Extract time from query
            at_idx = query_lower.find("at")
            if at_idx != -1:
                time_text = query[at_idx + 2:].strip()
                # Try to match by time (simplified - could be enhanced)
                for event in events:
                    start_time = event.get('start', {}).get('dateTime', event.get('start', {}).get('date', ''))
                    if start_time and time_text.lower() in start_time.lower():
                        logger.info(f"[CAL] Resolved time reference '{time_text}'")
                        return event
        
        # Handle title-based references: "the one about [title]", "about [title]"
        if title:
            matching = [e for e in events if title.lower() in e.get('title', e.get('summary', '')).lower()]
            if len(matching) == 1:
                logger.info(f"[CAL] Resolved title reference '{title}'")
                return matching[0]
        
        return None
    
    
    def _get_google_calendar_setup_message(self) -> str:
        """Get a clear message about Calendar setup requirements"""
        from ..utils.api import get_api_url_with_fallback
        api_url = get_api_url_with_fallback(self)
        return (
            "[ERROR] Google Calendar is not available. "
            "Please authenticate with Google to enable calendar operations: "
            f"{api_url}/auth/google/login"
        )
    
    def _handle_error(self, error: Exception, context: str) -> str:
        """Handle and format errors"""
        error_msg = f"[ERROR] Failed to execute {context}: {str(error)}"
        logger.error(error_msg, exc_info=True)
        return error_msg
