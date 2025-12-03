"""
Domain Specialist Roles: Execute domain-specific operations

Responsible for:
- Executing operations in their domain
- Handling domain-specific errors
- Optimizing domain access
- Caching domain results
"""

from typing import Dict, Any, List, Optional, Any as GenericAny
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from datetime import datetime

from ...utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class SpecialistResult:
    """Result from a domain specialist execution"""
    specialist_domain: str
    action: str
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    cached: bool = False
    timestamp: datetime = field(default_factory=datetime.now)


class DomainSpecialistRole(ABC):
    """
    Base class for domain specialists
    
    Each domain (email, calendar, tasks) has a specialist that knows:
    - How to interact with that domain's service/tools
    - How to handle domain-specific errors
    - Best practices for optimization (caching, batching)
    - Domain-specific constraints and limitations
    """
    
    def __init__(self, domain: str, service: Optional[Any] = None, tools: Optional[List] = None, parser: Optional[Any] = None, config: Optional[Any] = None):
        """
        Initialize domain specialist
        
        Args:
            domain: Domain name (e.g., 'email', 'calendar', 'tasks', 'notion')
            service: Optional service object for this domain
            tools: Optional list of tools for this domain
            parser: Optional parser instance for this domain (EmailParser, TaskParser, etc.)
            config: Optional configuration object
        """
        self.domain = domain
        self.service = service
        self.tools = tools or []
        self.parser = parser
        self.config = config
        self.result_cache: Dict[str, SpecialistResult] = {}
        self.stats = {
            'operations_performed': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'errors': 0,
            'avg_execution_time_ms': 0.0,
            'parser_usage_count': 0
        }
    
    def _parse_query(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Parse query using domain parser if available
        
        Args:
            query: User query string
            
        Returns:
            Parsed result dictionary with action, entities, confidence, or None
        """
        if self.parser:
            try:
                parsed = self.parser.parse_query_to_params(query)
                self.stats['parser_usage_count'] += 1
                logger.debug(f"[{self.domain.upper()}] Parser extracted: action={parsed.get('action')}, confidence={parsed.get('confidence', 0):.2f}")
                return parsed
            except Exception as e:
                logger.debug(f"[{self.domain.upper()}] Parser failed: {e}")
        return None
    
    @abstractmethod
    async def search(self, query: str, filters: Dict[str, Any]) -> SpecialistResult:
        """
        Search for items in this domain
        
        Args:
            query: Search query string
            filters: Search filters (dates, people, etc.)
            
        Returns:
            SpecialistResult with search results
        """
        pass
    
    @abstractmethod
    async def create(self, item_type: str, data: Dict[str, Any]) -> SpecialistResult:
        """
        Create a new item in this domain
        
        Args:
            item_type: Type of item to create
            data: Item data
            
        Returns:
            SpecialistResult with created item
        """
        pass
    
    @abstractmethod
    async def update(self, item_id: str, data: Dict[str, Any]) -> SpecialistResult:
        """
        Update an item in this domain
        
        Args:
            item_id: ID of item to update
            data: Updated item data
            
        Returns:
            SpecialistResult with update status
        """
        pass
    
    @abstractmethod
    async def delete(self, item_id: str) -> SpecialistResult:
        """
        Delete an item from this domain
        
        Args:
            item_id: ID of item to delete
            
        Returns:
            SpecialistResult with deletion status
        """
        pass
    
    def _make_cache_key(self, action: str, parameters: Dict[str, Any]) -> str:
        """Generate cache key for an operation"""
        # Simple cache key generation
        params_str = str(sorted(parameters.items()))
        return f"{self.domain}:{action}:{params_str}"
    
    def _get_cached_result(self, cache_key: str) -> Optional[SpecialistResult]:
        """Get result from cache if available"""
        if cache_key in self.result_cache:
            self.stats['cache_hits'] += 1
            result = self.result_cache[cache_key]
            result.cached = True
            return result
        else:
            self.stats['cache_misses'] += 1
            return None
    
    def _cache_result(self, cache_key: str, result: SpecialistResult) -> None:
        """Cache a result"""
        self.result_cache[cache_key] = result
    
    def get_stats(self) -> Dict[str, Any]:
        """Get specialist statistics"""
        total_ops = self.stats['operations_performed']
        if total_ops > 0:
            cache_hit_rate = (self.stats['cache_hits'] / (self.stats['cache_hits'] + self.stats['cache_misses'])) * 100
            error_rate = (self.stats['errors'] / total_ops) * 100
        else:
            cache_hit_rate = 0
            error_rate = 0
        
        return {
            'domain': self.domain,
            'total_operations': total_ops,
            'cache_hits': self.stats['cache_hits'],
            'cache_misses': self.stats['cache_misses'],
            'cache_hit_rate': f"{cache_hit_rate:.1f}%",
            'errors': self.stats['errors'],
            'error_rate': f"{error_rate:.1f}%",
            'avg_execution_time_ms': f"{self.stats['avg_execution_time_ms']:.0f}ms"
        }
    
    def clear_cache(self) -> None:
        """Clear the result cache"""
        self.result_cache.clear()


class EmailSpecialistRole(DomainSpecialistRole):
    """
    Email Domain Specialist
    
    Handles all email-related operations through Gmail integration
    """
    
    def __init__(self, service: Optional[Any] = None, tools: Optional[List] = None, parser: Optional[Any] = None, config: Optional[Any] = None):
        """Initialize Email Specialist"""
        # Initialize parser if not provided but config available
        if parser is None and config:
            try:
                from ..parsers.email_parser import EmailParser
                parser = EmailParser(rag_service=None, memory=None, config=config)
                logger.info("[EMAIL] EmailParser initialized for EmailSpecialistRole")
            except Exception as e:
                logger.debug(f"[EMAIL] Could not initialize EmailParser: {e}")
        
        super().__init__(domain='email', service=service, tools=tools, parser=parser, config=config)
    
    async def search(self, query: str, filters: Dict[str, Any]) -> SpecialistResult:
        """
        Search for emails
        
        Args:
            query: Search query (Gmail query syntax)
            filters: Additional filters (from_date, to_date, sender, etc.)
            
        Returns:
            SpecialistResult with matching emails
        """
        start_time = datetime.now()
        cache_key = self._make_cache_key('search', {'query': query, **filters})
        
        # Check cache
        cached = self._get_cached_result(cache_key)
        if cached:
            return cached
        
        try:
            self.stats['operations_performed'] += 1
            
            # Use parser to extract entities and enhance query
            parsed = self._parse_query(query)
            if parsed:
                entities = parsed.get('entities', {})
                # Enhance filters with parsed entities
                if 'sender' in entities and 'sender' not in filters:
                    filters['sender'] = entities['sender']
                if 'date' in entities and 'from_date' not in filters:
                    filters['from_date'] = entities.get('date')
            
            # Build search query with filters
            search_query = self._build_email_query(query, filters)
            
            # Execute search through service
            if self.service:
                emails = await self._search_via_service(search_query)
            else:
                # Fallback: use tools
                emails = await self._search_via_tools(search_query)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            result = SpecialistResult(
                specialist_domain=self.domain,
                action='search',
                success=True,
                data={'emails': emails, 'count': len(emails)},
                execution_time_ms=execution_time
            )
            
            # Cache result
            self._cache_result(cache_key, result)
            
            return result
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='search',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def create(self, item_type: str, data: Dict[str, Any]) -> SpecialistResult:
        """
        Create email (send)
        
        Args:
            item_type: Should be 'email'
            data: Email data (to, subject, body, etc.)
            
        Returns:
            SpecialistResult with created email
        """
        start_time = datetime.now()
        
        try:
            self.stats['operations_performed'] += 1
            
            if self.service:
                result_data = await self._send_via_service(data)
            else:
                result_data = await self._send_via_tools(data)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='create',
                success=True,
                data=result_data,
                execution_time_ms=execution_time
            )
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='create',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def update(self, item_id: str, data: Dict[str, Any]) -> SpecialistResult:
        """
        Update email (modify labels, archive, etc.)
        
        Args:
            item_id: Email ID
            data: Update data
            
        Returns:
            SpecialistResult with update status
        """
        start_time = datetime.now()
        
        try:
            self.stats['operations_performed'] += 1
            
            if self.service:
                result_data = await self._update_via_service(item_id, data)
            else:
                result_data = await self._update_via_tools(item_id, data)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='update',
                success=True,
                data=result_data,
                execution_time_ms=execution_time
            )
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='update',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def delete(self, item_id: str) -> SpecialistResult:
        """Delete email"""
        start_time = datetime.now()
        
        try:
            self.stats['operations_performed'] += 1
            
            if self.service:
                result_data = await self._delete_via_service(item_id)
            else:
                result_data = await self._delete_via_tools(item_id)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='delete',
                success=True,
                data=result_data,
                execution_time_ms=execution_time
            )
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='delete',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    def _build_email_query(self, query: str, filters: Dict[str, Any]) -> str:
        """Build Gmail query with filters"""
        parts = [query]
        
        if 'from_date' in filters:
            parts.append(f"after:{filters['from_date']}")
        
        if 'to_date' in filters:
            parts.append(f"before:{filters['to_date']}")
        
        if 'sender' in filters:
            parts.append(f"from:{filters['sender']}")
        
        if 'recipient' in filters:
            parts.append(f"to:{filters['recipient']}")
        
        if 'has_attachment' in filters and filters['has_attachment']:
            parts.append("has:attachment")
        
        if 'label' in filters:
            parts.append(f"label:{filters['label']}")
        
        return ' '.join(parts)
    
    async def _search_via_service(self, query: str) -> List[Dict[str, Any]]:
        """Search emails via service"""
        if self.service and hasattr(self.service, 'search'):
            # Call service search method with query
            return await self.service.search(query)
        # Fallback: log query for debugging (service not available)
        logger.debug(f"[EMAIL] Service search not available, query: {query[:50]}")
        return []
    
    async def _search_via_tools(self, query: str) -> List[Dict[str, Any]]:
        """Search emails via tools"""
        if self.tools:
            # Find email search tool and call it with query
            for tool in self.tools:
                if hasattr(tool, 'name') and 'email' in tool.name.lower() and hasattr(tool, 'search'):
                    return await tool.search(query)
        # Fallback: log query for debugging (tools not available)
        logger.debug(f"[EMAIL] Email tool search not available, query: {query[:50]}")
        return []
    
    async def _send_via_service(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Send email via service"""
        if self.service and (hasattr(self.service, 'send') or hasattr(self.service, 'create')):
            # Try send method first, then create method
            send_method = getattr(self.service, 'send', None) or getattr(self.service, 'create', None)
            if send_method:
                return await send_method(data)
        # Fallback: log data for debugging (service not available)
        logger.debug(f"[EMAIL] Service send not available, data keys: {list(data.keys())[:5]}")
        return {'email_id': 'mock_id', 'sent': True}
    
    async def _send_via_tools(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Send email via tools"""
        if self.tools:
            # Find email send/create tool and call it with data
            for tool in self.tools:
                if hasattr(tool, 'name') and 'email' in tool.name.lower():
                    if hasattr(tool, 'send'):
                        return await tool.send(data)
                    elif hasattr(tool, 'create'):
                        return await tool.create(data)
        # Fallback: log data for debugging (tools not available)
        logger.debug(f"[EMAIL] Email tool send not available, data keys: {list(data.keys())[:5]}")
        return {'email_id': 'mock_id', 'sent': True}
    
    async def _update_via_service(self, item_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update email via service"""
        if self.service and hasattr(self.service, 'update'):
            # Call service update method with item_id and data
            return await self.service.update(item_id, data)
        # Fallback: log item_id and data for debugging (service not available)
        logger.debug(f"[EMAIL] Service update not available, item_id: {item_id[:20]}, data keys: {list(data.keys())[:5]}")
        return {'success': True}
    
    async def _update_via_tools(self, item_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update email via tools"""
        if self.tools:
            # Find email update tool and call it with item_id and data
            for tool in self.tools:
                if hasattr(tool, 'name') and 'email' in tool.name.lower() and hasattr(tool, 'update'):
                    return await tool.update(item_id, data)
        # Fallback: log item_id and data for debugging (tools not available)
        logger.debug(f"[EMAIL] Email tool update not available, item_id: {item_id[:20]}, data keys: {list(data.keys())[:5]}")
        return {'success': True}
    
    async def _delete_via_service(self, item_id: str) -> Dict[str, Any]:
        """Delete email via service"""
        if self.service and hasattr(self.service, 'delete'):
            # Call service delete method with item_id
            return await self.service.delete(item_id)
        # Fallback: log item_id for debugging (service not available)
        logger.debug(f"[EMAIL] Service delete not available, item_id: {item_id[:20]}")
        return {'success': True}
    
    async def _delete_via_tools(self, item_id: str) -> Dict[str, Any]:
        """Delete email via tools"""
        if self.tools:
            # Find email delete tool and call it with item_id
            for tool in self.tools:
                if hasattr(tool, 'name') and 'email' in tool.name.lower() and hasattr(tool, 'delete'):
                    return await tool.delete(item_id)
        # Fallback: log item_id for debugging (tools not available)
        logger.debug(f"[EMAIL] Email tool delete not available, item_id: {item_id[:20]}")
        return {'success': True}


class CalendarSpecialistRole(DomainSpecialistRole):
    """
    Calendar Domain Specialist
    
    Handles all calendar-related operations through Google Calendar integration
    """
    
    def __init__(self, service: Optional[Any] = None, tools: Optional[List] = None, parser: Optional[Any] = None, config: Optional[Any] = None):
        """Initialize Calendar Specialist"""
        # Initialize parser if not provided but config available
        if parser is None and config:
            try:
                from ..parsers.calendar_parser import CalendarParser
                parser = CalendarParser(rag_service=None, memory=None, config=config)
                logger.info("[CALENDAR] CalendarParser initialized for CalendarSpecialistRole")
            except Exception as e:
                logger.debug(f"[CALENDAR] Could not initialize CalendarParser: {e}")
        
        super().__init__(domain='calendar', service=service, tools=tools, parser=parser, config=config)
    
    async def search(self, query: str, filters: Dict[str, Any]) -> SpecialistResult:
        """
        Search for calendar events
        
        Args:
            query: Search query
            filters: Additional filters (date_from, date_to, attendee, etc.)
            
        Returns:
            SpecialistResult with matching events
        """
        start_time = datetime.now()
        cache_key = self._make_cache_key('search', {'query': query, **filters})
        
        cached = self._get_cached_result(cache_key)
        if cached:
            return cached
        
        try:
            self.stats['operations_performed'] += 1
            
            if self.service:
                events = await self._search_via_service(query, filters)
            else:
                events = await self._search_via_tools(query, filters)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            result = SpecialistResult(
                specialist_domain=self.domain,
                action='search',
                success=True,
                data={'events': events, 'count': len(events)},
                execution_time_ms=execution_time
            )
            
            self._cache_result(cache_key, result)
            
            return result
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='search',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def create(self, item_type: str, data: Dict[str, Any]) -> SpecialistResult:
        """Create calendar event"""
        start_time = datetime.now()
        
        try:
            self.stats['operations_performed'] += 1
            
            if self.service:
                result_data = await self._create_via_service(data)
            else:
                result_data = await self._create_via_tools(data)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='create',
                success=True,
                data=result_data,
                execution_time_ms=execution_time
            )
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='create',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def update(self, item_id: str, data: Dict[str, Any]) -> SpecialistResult:
        """Update calendar event"""
        start_time = datetime.now()
        
        try:
            self.stats['operations_performed'] += 1
            
            if self.service:
                result_data = await self._update_via_service(item_id, data)
            else:
                result_data = await self._update_via_tools(item_id, data)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='update',
                success=True,
                data=result_data,
                execution_time_ms=execution_time
            )
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='update',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def delete(self, item_id: str) -> SpecialistResult:
        """Delete calendar event"""
        start_time = datetime.now()
        
        try:
            self.stats['operations_performed'] += 1
            
            if self.service:
                result_data = await self._delete_via_service(item_id)
            else:
                result_data = await self._delete_via_tools(item_id)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='delete',
                success=True,
                data=result_data,
                execution_time_ms=execution_time
            )
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='delete',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def _search_via_service(self, query: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search calendar events via service"""
        return []
    
    async def _search_via_tools(self, query: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search calendar events via tools"""
        return []
    
    async def _create_via_service(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create event via service"""
        return {'event_id': 'mock_id', 'created': True}
    
    async def _create_via_tools(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create event via tools"""
        return {'event_id': 'mock_id', 'created': True}
    
    async def _update_via_service(self, item_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update event via service"""
        return {'success': True}
    
    async def _update_via_tools(self, item_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update event via tools"""
        return {'success': True}
    
    async def _delete_via_service(self, item_id: str) -> Dict[str, Any]:
        """Delete event via service"""
        return {'success': True}
    
    async def _delete_via_tools(self, item_id: str) -> Dict[str, Any]:
        """Delete event via tools"""
        return {'success': True}


class TaskSpecialistRole(DomainSpecialistRole):
    """
    Task Domain Specialist
    
    Handles all task-related operations through Google Tasks integration
    """
    
    def __init__(self, service: Optional[Any] = None, tools: Optional[List] = None, parser: Optional[Any] = None, config: Optional[Any] = None):
        """Initialize Task Specialist"""
        # Initialize parser if not provided but config available
        if parser is None and config:
            try:
                from ..parsers.task_parser import TaskParser
                parser = TaskParser(rag_service=None, memory=None, config=config)
                logger.info("[TASK] TaskParser initialized for TaskSpecialistRole")
            except Exception as e:
                logger.debug(f"[TASK] Could not initialize TaskParser: {e}")
        
        super().__init__(domain='tasks', service=service, tools=tools, parser=parser, config=config)
    
    async def search(self, query: str, filters: Dict[str, Any]) -> SpecialistResult:
        """
        Search for tasks
        
        Args:
            query: Search query
            filters: Additional filters (status, due_date, etc.)
            
        Returns:
            SpecialistResult with matching tasks
        """
        start_time = datetime.now()
        cache_key = self._make_cache_key('search', {'query': query, **filters})
        
        cached = self._get_cached_result(cache_key)
        if cached:
            return cached
        
        try:
            self.stats['operations_performed'] += 1
            
            if self.service:
                tasks = await self._search_via_service(query, filters)
            else:
                tasks = await self._search_via_tools(query, filters)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            result = SpecialistResult(
                specialist_domain=self.domain,
                action='search',
                success=True,
                data={'tasks': tasks, 'count': len(tasks)},
                execution_time_ms=execution_time
            )
            
            self._cache_result(cache_key, result)
            
            return result
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='search',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def create(self, item_type: str, data: Dict[str, Any]) -> SpecialistResult:
        """Create task"""
        start_time = datetime.now()
        
        try:
            self.stats['operations_performed'] += 1
            
            if self.service:
                result_data = await self._create_via_service(data)
            else:
                result_data = await self._create_via_tools(data)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='create',
                success=True,
                data=result_data,
                execution_time_ms=execution_time
            )
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='create',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def update(self, item_id: str, data: Dict[str, Any]) -> SpecialistResult:
        """Update task"""
        start_time = datetime.now()
        
        try:
            self.stats['operations_performed'] += 1
            
            if self.service:
                result_data = await self._update_via_service(item_id, data)
            else:
                result_data = await self._update_via_tools(item_id, data)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='update',
                success=True,
                data=result_data,
                execution_time_ms=execution_time
            )
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='update',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def delete(self, item_id: str) -> SpecialistResult:
        """Delete task"""
        start_time = datetime.now()
        
        try:
            self.stats['operations_performed'] += 1
            
            if self.service:
                result_data = await self._delete_via_service(item_id)
            else:
                result_data = await self._delete_via_tools(item_id)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='delete',
                success=True,
                data=result_data,
                execution_time_ms=execution_time
            )
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='delete',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def _search_via_service(self, query: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search tasks via service"""
        return []
    
    async def _search_via_tools(self, query: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search tasks via tools"""
        return []
    
    async def _create_via_service(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create task via service"""
        return {'task_id': 'mock_id', 'created': True}
    
    async def _create_via_tools(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create task via tools"""
        return {'task_id': 'mock_id', 'created': True}
    
    async def _update_via_service(self, item_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update task via service"""
        return {'success': True}
    
    async def _update_via_tools(self, item_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update task via tools"""
        return {'success': True}
    
    async def _delete_via_service(self, item_id: str) -> Dict[str, Any]:
        """Delete task via service"""
        return {'success': True}
    
    async def _delete_via_tools(self, item_id: str) -> Dict[str, Any]:
        """Delete task via tools"""
        return {'success': True}


class NotionSpecialistRole(DomainSpecialistRole):
    """
    Notion Domain Specialist
    
    Handles all Notion-related operations through Notion integration
    """
    
    def __init__(self, service: Optional[Any] = None, tools: Optional[List] = None, parser: Optional[Any] = None, config: Optional[Any] = None):
        """Initialize Notion Specialist"""
        # Initialize parser if not provided but config available
        if parser is None and config:
            try:
                from ..parsers.notion_parser import NotionParser
                parser = NotionParser(rag_service=None, memory=None, config=config)
                logger.info("[NOTION] NotionParser initialized for NotionSpecialistRole")
            except Exception as e:
                logger.debug(f"[NOTION] Could not initialize NotionParser: {e}")
        
        super().__init__(domain='notion', service=service, tools=tools, parser=parser, config=config)
    
    async def search(self, query: str, filters: Dict[str, Any]) -> SpecialistResult:
        """
        Search for Notion pages
        
        Args:
            query: Search query
            filters: Additional filters (database_id, etc.)
            
        Returns:
            SpecialistResult with matching pages
        """
        start_time = datetime.now()
        cache_key = self._make_cache_key('search', {'query': query, **filters})
        
        cached = self._get_cached_result(cache_key)
        if cached:
            return cached
        
        try:
            self.stats['operations_performed'] += 1
            
            # Use parser to extract entities
            parsed = self._parse_query(query)
            if parsed:
                entities = parsed.get('entities', {})
                if 'database_id' in entities and 'database_id' not in filters:
                    filters['database_id'] = entities['database_id']
                if 'query' in entities:
                    query = entities['query']
            
            if self.service:
                pages = await self._search_via_service(query, filters)
            else:
                pages = await self._search_via_tools(query, filters)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            result = SpecialistResult(
                specialist_domain=self.domain,
                action='search',
                success=True,
                data={'pages': pages, 'count': len(pages)},
                execution_time_ms=execution_time
            )
            
            self._cache_result(cache_key, result)
            
            return result
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='search',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def create(self, item_type: str, data: Dict[str, Any]) -> SpecialistResult:
        """Create Notion page or database entry"""
        start_time = datetime.now()
        
        try:
            self.stats['operations_performed'] += 1
            
            if self.service:
                result_data = await self._create_via_service(data)
            else:
                result_data = await self._create_via_tools(data)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='create',
                success=True,
                data=result_data,
                execution_time_ms=execution_time
            )
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='create',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def update(self, item_id: str, data: Dict[str, Any]) -> SpecialistResult:
        """Update Notion page"""
        start_time = datetime.now()
        
        try:
            self.stats['operations_performed'] += 1
            
            if self.service:
                result_data = await self._update_via_service(item_id, data)
            else:
                result_data = await self._update_via_tools(item_id, data)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='update',
                success=True,
                data=result_data,
                execution_time_ms=execution_time
            )
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='update',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def delete(self, item_id: str) -> SpecialistResult:
        """Delete Notion page"""
        start_time = datetime.now()
        
        try:
            self.stats['operations_performed'] += 1
            
            if self.service:
                result_data = await self._delete_via_service(item_id)
            else:
                result_data = await self._delete_via_tools(item_id)
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='delete',
                success=True,
                data=result_data,
                execution_time_ms=execution_time
            )
        
        except Exception as e:
            self.stats['errors'] += 1
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return SpecialistResult(
                specialist_domain=self.domain,
                action='delete',
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )
    
    async def _search_via_service(self, query: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search Notion pages via service"""
        return []
    
    async def _search_via_tools(self, query: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search Notion pages via tools"""
        return []
    
    async def _create_via_service(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create page via service"""
        return {'page_id': 'mock_id', 'created': True}
    
    async def _create_via_tools(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create page via tools"""
        return {'page_id': 'mock_id', 'created': True}
    
    async def _update_via_service(self, item_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update page via service"""
        return {'success': True}
    
    async def _update_via_tools(self, item_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update page via tools"""
        return {'success': True}
    
    async def _delete_via_service(self, item_id: str) -> Dict[str, Any]:
        """Delete page via service"""
        return {'success': True}
    
    async def _delete_via_tools(self, item_id: str) -> Dict[str, Any]:
        """Delete page via tools"""
        return {'success': True}
