"""
Calendar Query Handlers

Handles calendar query operations: list, search, find_free_time, check_conflicts, etc.
This module centralizes query handling logic to keep the main CalendarTool class clean.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime

from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class CalendarQueryHandlers:
    """
    Handles calendar query operations.
    
    This class centralizes list, search, and other query operations
    to improve maintainability and keep the main CalendarTool class focused.
    """
    
    def __init__(self, calendar_tool):
        """
        Initialize query handlers.
        
        Args:
            calendar_tool: Parent CalendarTool instance for accessing services, config, etc.
        """
        self.calendar_tool = calendar_tool
        self.config = calendar_tool.config if hasattr(calendar_tool, 'config') else None
    
    def handle_list(
        self,
        start_date: Optional[str],
        end_date: Optional[str],
        days_back: int,
        days_ahead: int,
        query: Optional[str],
        parsed_time_period: Optional[str],
        **kwargs
    ) -> str:
        """
        Handle calendar event listing.
        
        Args:
            start_date: Start date for listing
            end_date: End date for listing
            days_back: Days to look back
            days_ahead: Days to look ahead
            query: Original query for context
            parsed_time_period: Parsed time period from query
            **kwargs: Additional arguments
            
        Returns:
            Formatted event list string
        """
        # Get workflow_emitter from kwargs if available
        workflow_emitter = kwargs.get('workflow_emitter')
        
        # Emit workflow event for listing events
        if workflow_emitter:
            self.calendar_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr checking your calendar...",
                data={'action': 'list'}
            )
        
        # Calculate date range to determine appropriate max_results
        # For wide date ranges (2+ years), increase max_results to ensure accuracy
        max_results = 50  # Default
        if start_date and end_date:
            try:
                from datetime import datetime as dt
                start_dt = dt.fromisoformat(start_date.replace('Z', '+00:00')) if isinstance(start_date, str) else start_date
                end_dt = dt.fromisoformat(end_date.replace('Z', '+00:00')) if isinstance(end_date, str) else end_date
                date_range_days = (end_dt - start_dt).days
                # For ranges > 1 year, increase max_results significantly
                if date_range_days > 365:
                    max_results = min(2500, max(500, date_range_days // 2))  # Scale with range, cap at 2500
                elif date_range_days > 180:  # 6+ months
                    max_results = 500
                elif date_range_days > 90:  # 3+ months
                    max_results = 200
            except Exception as e:
                logger.debug(f"Could not calculate date range for max_results: {e}")
        elif days_back > 365 or days_ahead > 365:
            max_results = 1000  # Large range, increase results
        elif days_back > 180 or days_ahead > 180:
            max_results = 500
        
        # Use days_ahead/days_back if dates not provided
        events = self.calendar_tool.calendar_service.list_events(
            start_date=start_date,
            end_date=end_date,
            days_back=days_back,
            days_ahead=days_ahead,
            max_results=max_results
        )
        
        # Update title based on time period (if parsed)
        title = "Upcoming events"
        if parsed_time_period == 'today':
            title = "Today's events"
        elif parsed_time_period == 'tomorrow':
            title = "Tomorrow's events"
        elif parsed_time_period == 'yesterday':
            title = "Yesterday's events"
        elif parsed_time_period in ['last_week', 'previous_week']:
            title = "Last week's events"
        elif parsed_time_period in ['last_month', 'previous_month']:
            title = "Last month's events"
        
        return self.calendar_tool.formatting_handlers.format_event_list(events, title, query or "")
    
    def handle_search(
        self,
        query: str,
        start_date: Optional[str],
        end_date: Optional[str],
        **kwargs
    ) -> str:
        """
        Handle calendar event search.
        
        Args:
            query: Search query string
            start_date: Optional start date filter
            end_date: Optional end date filter
            **kwargs: Additional arguments
            
        Returns:
            Formatted search results string
        """
        if not query:
            return "[ERROR] Please provide 'query' for search action"
        
        # Get workflow_emitter from kwargs if available
        workflow_emitter = kwargs.get('workflow_emitter')
        
        # Emit workflow event for searching events
        if workflow_emitter:
            self.calendar_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr searching calendar...",
                data={'action': 'search', 'query': query}
            )
        
        events = self.calendar_tool.calendar_service.search_events(
            query=query,
            start_date=start_date,
            end_date=end_date
        )
        
        # Store events for potential follow-up operations (e.g., move/update)
        self.calendar_tool._last_event_list = events
        self.calendar_tool._last_event_list_query = query
        
        return self.calendar_tool.formatting_handlers.format_event_list(events, f"Search results for '{query}'", query)
    
    def handle_find_free_time(
        self,
        duration_minutes: int,
        start_date: Optional[str],
        end_date: Optional[str],
        **kwargs
    ) -> str:
        """
        Handle finding free time slots.
        
        Args:
            duration_minutes: Duration in minutes for free time slots
            start_date: Optional start date
            end_date: Optional end date
            **kwargs: Additional arguments
            
        Returns:
            Formatted free time slots string
        """
        slots = self.calendar_tool.calendar_service.find_free_time(
            duration_minutes=duration_minutes,
            start_date=start_date,
            end_date=end_date,
            max_suggestions=10
        )
        return self.calendar_tool._format_free_time_slots(slots)
    
    def handle_check_conflicts(
        self,
        start_time: Optional[str],
        end_time: Optional[str],
        duration_minutes: int,
        **kwargs
    ) -> str:
        """
        Handle conflict checking.
        
        Args:
            start_time: Start time to check
            end_time: End time to check
            duration_minutes: Duration in minutes
            **kwargs: Additional arguments
            
        Returns:
            Conflict information string
        """
        if not start_time:
            return "[ERROR] Please provide 'start_time' for check_conflicts action"
        
        # Get workflow_emitter from kwargs if available
        workflow_emitter = kwargs.get('workflow_emitter')
        
        # Emit workflow event for checking conflicts
        if workflow_emitter:
            self.calendar_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr checking for conflicts...",
                data={'action': 'check_conflicts', 'start_time': start_time}
            )
        
        conflicts = self.calendar_tool.calendar_service.check_conflicts(
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration_minutes
        )
        
        if conflicts:
            return self.calendar_tool._format_conflicts(conflicts, start_time)
        else:
            return f"No conflicts found at {start_time}."
    
    def handle_check_availability(
        self,
        start_time: Optional[str],
        end_time: Optional[str],
        **kwargs
    ) -> str:
        """
        Handle availability checking.
        
        Args:
            start_time: Start time to check
            end_time: End time to check
            **kwargs: Additional arguments
            
        Returns:
            Availability information string
        """
        if not start_time:
            return "[ERROR] Please provide 'start_time' for check_availability action"
        
        available = self.calendar_tool.calendar_service.check_availability(
            start_time=start_time,
            end_time=end_time
        )
        
        if available:
            return f"You're available at {start_time}."
        else:
            return f"You're not available at {start_time}."


