"""
Calendar Service - Business logic layer for calendar operations

Provides a clean interface for calendar operations, abstracting away the complexity
of Google Calendar API, credential management, and smart scheduling features.

This service is used by:
- CalendarTool (LangChain tool)
- Calendar background workers (Celery tasks)
- API endpoints

Architecture:
    CalendarService → GoogleCalendarClient → Google Calendar API
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from ...core.calendar.google_client import GoogleCalendarClient
from ...utils.logger import setup_logger
from ...utils.config import Config, ConfigDefaults
from .exceptions import (
    CalendarServiceException,
    EventNotFoundException,
    SchedulingConflictException,
    InvalidTimeRangeException,
    ServiceUnavailableException,
    AuthenticationException
)

logger = setup_logger(__name__)


class CalendarService:
    """
    Calendar service providing business logic for calendar operations
    
    Features:
    - Create, update, delete events
    - Search and filter events
    - Smart scheduling (find free time, detect conflicts)
    - Recurring event management
    - Meeting suggestions and optimization
    - Calendar analytics
    """
    
    def __init__(
        self,
        config: Config,
        credentials: Optional[Any] = None
    ):
        """
        Initialize calendar service
        
        Args:
            config: Application configuration
            credentials: OAuth credentials (if available)
        """
        self.config = config
        self.credentials = credentials
        
        # Initialize Google Calendar client
        try:
            self.calendar_client = GoogleCalendarClient(config, credentials=credentials)
            if not self.calendar_client.is_available():
                logger.warning("[CALENDAR_SERVICE] Calendar client not available")
        except Exception as e:
            logger.error(f"[CALENDAR_SERVICE] Failed to initialize Calendar client: {e}")
            self.calendar_client = None

        # Initialize Maps Service
        try:
            from ..google_maps.service import MapsService
            self.maps_service = MapsService(config)
        except Exception as e:
            logger.warning(f"[CALENDAR_SERVICE] Failed to initialize Maps Service: {e}")
            self.maps_service = None
    
    def _ensure_available(self):
        """Ensure Calendar client is available"""
        if not self.calendar_client or not self.calendar_client.is_available():
            raise ServiceUnavailableException(
                "[INTEGRATION_REQUIRED] Calendar permission not granted. Please enable Google integration in Settings.",
                service_name="calendar"
            )
    
    # ===================================================================
    # EVENT OPERATIONS
    # ===================================================================
    
    def create_event(
        self,
        title: str,
        start_time: str,
        end_time: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        recurrence: Optional[str] = None,
        reminders: Optional[List[Dict[str, Any]]] = None,
        check_conflicts: bool = False
    ) -> Dict[str, Any]:
        """
        Create a new calendar event
        
        Args:
            title: Event title/summary
            start_time: Event start time (ISO format)
            end_time: Event end time (optional if duration provided)
            duration_minutes: Event duration (optional if end_time provided)
            description: Event description
            location: Event location
            attendees: List of attendee email addresses
            recurrence: Recurrence rule (e.g., "RRULE:FREQ=DAILY;COUNT=5")
            reminders: List of reminder configurations
            check_conflicts: Whether to check for scheduling conflicts
            
        Returns:
            Created event details
            
        Raises:
            SchedulingConflictException: If conflicts detected and check_conflicts=True
            CalendarServiceException: If creation fails
        """
        self._ensure_available()
        
        try:
            # Check for conflicts if requested
            if check_conflicts:
                # CRITICAL: start_time must be provided for conflict checking
                if not start_time:
                    logger.warning("[CALENDAR_SERVICE] start_time is missing, skipping conflict check but creation will likely fail.")
                else:
                    # CRITICAL: Pass None as end_time if not strictly provided, so find_conflicts
                    # can calculate the true end time using duration_minutes.
                    # Previous bug: passing start_time as end_time created a 0-duration check window.
                    check_end = end_time if end_time else None
                    # FORCE a default duration if none provided, ensuring find_conflicts
                    # has data to calculate a check window.
                    check_duration = duration_minutes if duration_minutes is not None else ConfigDefaults.CALENDAR_DEFAULT_DURATION
                    conflicts = self.find_conflicts(start_time, check_end, check_duration, location=location)
                    if conflicts:
                        # Find alternative time slots
                        try:
                            suggestions = self.find_free_time(
                                duration_minutes=duration_minutes or ConfigDefaults.CALENDAR_DEFAULT_DURATION,
                                start_date=start_time,
                                end_date=(datetime.fromisoformat(start_time.replace('Z', '+00:00')) + timedelta(days=ConfigDefaults.CALENDAR_SUGGESTIONS_DAYS_AHEAD)).isoformat(),
                                max_suggestions=ConfigDefaults.CALENDAR_SUGGESTIONS_MAX,
                                working_hours_only=False # Be flexible for suggestions
                            )
                        except Exception as suggest_err:
                            logger.warning(f"Failed to find suggestions during conflict: {suggest_err}")
                            suggestions = []

                        suggestion_str = ""
                        if suggestions:
                            times = [f"{s['start']}" for s in suggestions] # format nicely in tool/agent layer
                            suggestion_str = f". Alternative times: {', '.join(times)}"

                        raise SchedulingConflictException(
                            f"Found {len(conflicts)} conflicting event(s){suggestion_str}",
                            service_name="calendar",
                            details={'conflicting_events': conflicts, 'suggestions': suggestions}
                        )
            
            logger.info(f"[CALENDAR_SERVICE] Creating event: {title}")
            
            # CRITICAL: Validate attendees are email addresses (safety check)
            # If names are passed, they should have been resolved upstream, but validate here
            if attendees:
                from ...core.calendar.utils import validate_attendees
                validated_attendees = validate_attendees(attendees)
                
                # If validation filtered out invalid emails, log warning
                if validated_attendees and len(validated_attendees) < len(attendees):
                    invalid_count = len(attendees) - len(validated_attendees)
                    invalid_attendees = [a for a in attendees if a not in validated_attendees]
                    logger.warning(f"[CALENDAR_SERVICE] {invalid_count} invalid attendee(s) filtered out: {invalid_attendees}. Expected email addresses.")
                
                # If all attendees were invalid, raise error
                if not validated_attendees and len(attendees) > 0:
                    invalid_attendees_str = ', '.join(attendees)
                    raise CalendarServiceException(
                        f"Invalid attendee email addresses: {invalid_attendees_str}. Please provide valid email addresses.",
                        service_name="calendar",
                        details={'invalid_attendees': attendees}
                    )
                
                attendees = validated_attendees
            
            event = self.calendar_client.create_event(
                title=title,
                start_time=start_time,
                end_time=end_time,
                duration_minutes=duration_minutes or 60,
                description=description or "",
                location=location or "",
                attendees=attendees,
                recurrence=recurrence  # Note: Client expects List[str], not str
            )
            
            logger.info(f"[CALENDAR_SERVICE] Event created: {event.get('id')}")
            return event
            
        except SchedulingConflictException:
            raise
        except Exception as e:
            logger.error(f"[CALENDAR_SERVICE] Failed to create event: {e}")
            raise CalendarServiceException(
                f"Failed to create event: {str(e)}",
                service_name="calendar",
                details={'title': title}
            )
    
    def update_event(
        self,
        event_id: str,
        title: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        check_conflicts: bool = False
    ) -> Dict[str, Any]:
        """
        Update an existing event
        
        Args:
            event_id: Event ID
            title: New title (optional)
            start_time: New start time (optional)
            end_time: New end time (optional)
            description: New description (optional)
            location: New location (optional)
            attendees: New attendees list (optional)
            check_conflicts: Whether to check for conflicts
            
        Returns:
            Updated event details
            
        Raises:
            EventNotFoundException: If event not found
            SchedulingConflictException: If conflicts detected
        """
        self._ensure_available()
        
        try:
            # Check for conflicts if time is changing
            if check_conflicts and (start_time or end_time):
                current_event = self.get_event(event_id)
                new_start = start_time or current_event.get('start', {}).get('dateTime')
                new_end = end_time or current_event.get('end', {}).get('dateTime')
                
                conflicts = self.find_conflicts(new_start, new_end, exclude_event_id=event_id)
                if conflicts:
                    raise SchedulingConflictException(
                        f"Found {len(conflicts)} conflicting event(s)",
                        service_name="calendar",
                        details={'conflicting_events': conflicts}
                    )
            
            logger.info(f"[CALENDAR_SERVICE] Updating event: {event_id}")
            
            update_data = {}
            if title:
                update_data['summary'] = title
            if start_time:
                update_data['start'] = {'dateTime': start_time}
            if end_time:
                update_data['end'] = {'dateTime': end_time}
            if description is not None:
                update_data['description'] = description
            if location is not None:
                update_data['location'] = location
            if attendees is not None:
                update_data['attendees'] = [{'email': email} for email in attendees]
            
            event = self.calendar_client.update_event(event_id, update_data)
            
            logger.info(f"[CALENDAR_SERVICE] Event updated: {event_id}")
            return event
            
        except (EventNotFoundException, SchedulingConflictException):
            raise
        except Exception as e:
            logger.error(f"[CALENDAR_SERVICE] Failed to update event: {e}")
            raise CalendarServiceException(
                f"Failed to update event: {str(e)}",
                service_name="calendar",
                details={'event_id': event_id}
            )
    
    def delete_event(self, event_id: str) -> Dict[str, Any]:
        """
        Delete an event
        
        Args:
            event_id: Event ID to delete
            
        Returns:
            Success confirmation
            
        Raises:
            EventNotFoundException: If event not found
        """
        self._ensure_available()
        
        try:
            logger.info(f"[CALENDAR_SERVICE] Deleting event: {event_id}")
            
            self.calendar_client.delete_event(event_id)
            
            logger.info(f"[CALENDAR_SERVICE] Event deleted: {event_id}")
            return {'event_id': event_id, 'status': 'deleted'}
            
        except Exception as e:
            logger.error(f"[CALENDAR_SERVICE] Failed to delete event: {e}")
            raise CalendarServiceException(
                f"Failed to delete event: {str(e)}",
                service_name="calendar",
                details={'event_id': event_id}
            )
    
    def get_event(self, event_id: str) -> Dict[str, Any]:
        """
        Get a single event by ID
        
        Args:
            event_id: Event ID
            
        Returns:
            Event details
            
        Raises:
            EventNotFoundException: If event not found
        """
        self._ensure_available()
        
        try:
            event = self.calendar_client.get_event(event_id)
            
            if not event:
                raise EventNotFoundException(
                    f"Event {event_id} not found",
                    service_name="calendar"
                )
            
            return event
            
        except EventNotFoundException:
            raise
        except Exception as e:
            logger.error(f"[CALENDAR_SERVICE] Failed to get event: {e}")
            raise CalendarServiceException(
                f"Failed to get event: {str(e)}",
                service_name="calendar",
                details={'event_id': event_id}
            )
    
    # ===================================================================
    # SEARCH AND LISTING
    # ===================================================================
    
    def list_events(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days_back: int = 0,
        days_ahead: int = 7,
        max_results: int = 100,
        query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List calendar events within a time range
        
        Args:
            start_date: Start date filter (ISO format)
            end_date: End date filter (ISO format)
            days_back: Days to look back (if start_date not provided)
            days_ahead: Days to look ahead (if end_date not provided)
            max_results: Maximum number of results
            query: Text search query
            
        Returns:
            List of events
        """
        self._ensure_available()
        
        try:
            logger.info(f"[CALENDAR_SERVICE] Listing events")
            
            # Convert string dates to datetime objects if provided
            start_dt = None
            end_dt = None
            
            if start_date:
                if isinstance(start_date, str):
                    start_dt = datetime.fromisoformat(start_date)
                else:
                    start_dt = start_date
                    
            if end_date:
                if isinstance(end_date, str):
                    end_dt = datetime.fromisoformat(end_date)
                else:
                    end_dt = end_date
            
            events = self.calendar_client.list_events(
                start_date=start_dt,
                end_date=end_dt,
                days_back=days_back,
                days_ahead=days_ahead,
                max_results=max_results,
                query=query
            )
            
            logger.info(f"[CALENDAR_SERVICE] Found {len(events)} events")
            return events
            
        except AuthenticationException as e:
            # Re-raise authentication exceptions so they can be handled by the tool
            raise CalendarServiceException(
                str(e),
                service_name="calendar",
                details=getattr(e, 'details', {})
            )
        except Exception as e:
            logger.error(f"[CALENDAR_SERVICE] Failed to list events: {e}")
            raise CalendarServiceException(
                f"Failed to list events: {str(e)}",
                service_name="calendar"
            )
    
    def search_events(
        self,
        query: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_results: int = 50
    ) -> List[Dict[str, Any]]:
        """Search events by text query"""
        return self.list_events(
            query=query,
            start_date=start_date,
            end_date=end_date,
            max_results=max_results
        )
    
    def get_upcoming_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get upcoming events"""
        return self.list_events(days_back=0, days_ahead=30, max_results=limit)
    
    def get_todays_events(self) -> List[Dict[str, Any]]:
        """Get today's events"""
        today = datetime.now().date().isoformat()
        tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()
        return self.list_events(start_date=today, end_date=tomorrow)
    
    # ===================================================================
    # SMART SCHEDULING
    # ===================================================================
    
    def find_free_time(
        self,
        duration_minutes: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        working_hours_only: bool = True,
        max_suggestions: int = 5
    ) -> List[Dict[str, str]]:
        """
        Find available time slots
        
        Args:
            duration_minutes: Required duration
            start_date: Search start date
            end_date: Search end date
            working_hours_only: Only suggest during working hours (9am-5pm)
            max_suggestions: Maximum number of suggestions
            
        Returns:
            List of available time slots
        """
        self._ensure_available()
        
        try:
            logger.info(f"[CALENDAR_SERVICE] Finding {duration_minutes}min free slots")
            
            # Get all events in the time range
            events = self.list_events(
                start_date=start_date,
                end_date=end_date,
                days_back=0,
                days_ahead=14
            )
            
            # Find gaps between events
            free_slots = self._find_gaps_between_events(
                events,
                duration_minutes,
                working_hours_only,
                max_suggestions
            )
            
            logger.info(f"[CALENDAR_SERVICE] Found {len(free_slots)} free slots")
            return free_slots
            
        except Exception as e:
            logger.error(f"[CALENDAR_SERVICE] Failed to find free time: {e}")
            raise CalendarServiceException(
                f"Failed to find free time: {str(e)}",
                service_name="calendar"
            )
    
    def find_conflicts(
        self,
        start_time: str,
        end_time: str,
        duration_minutes: Optional[int] = None,
        exclude_event_id: Optional[str] = None,
        location: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Find conflicting events for a given time range
        
        Args:
            start_time: Proposed start time
            end_time: Proposed end time
            duration_minutes: Duration (if end_time not provided)
            exclude_event_id: Event ID to exclude (for updates)
            
        Returns:
            List of conflicting events
        """
        # Robustness: start_time is required
        if not start_time:
            logger.error("[CALENDAR_SERVICE] find_conflicts called without start_time")
            return []

        self._ensure_available()
        
        try:
            # Calculate end time if duration provided
            if duration_minutes and not end_time:
                # Guard against None or invalid start_time
                try:
                    start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    end_dt = start_dt + timedelta(minutes=duration_minutes)
                    end_time = end_dt.isoformat()
                except (AttributeError, ValueError) as e:
                    logger.warning(f"[CALENDAR_SERVICE] Invalid start_time format in find_conflicts: {start_time}")
                    return []
            
            # Get events in the time range (list_events might return loose matches, so we must filter)
            # Expand search window BACKWARDS to check for travel time from previous event
            check_start_raw = start_time
            if self.maps_service and location:
                # Look back 2 hours to find the preceding event
                # We need to parse first to subtract time
                s_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                check_start_raw = (s_dt - timedelta(hours=2)).isoformat()

            events = self.list_events(start_date=check_start_raw, end_date=end_time)
            
            # Strict Filter: Verify overlap and exclude self
            from ...core.calendar.utils import events_overlap, parse_event_time, parse_datetime_with_timezone
            
            # Calculate precise window for strict overlap check using config for timezone context
            start_dt = parse_datetime_with_timezone(start_time, self.config)
            
            # ... (rest of existing setup) ...

            if not start_dt:
                # Fallback to naive parsing if util fails, but force simple UTC awareness to avoid crash
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                if start_dt.tzinfo is None:
                     import pytz
                     start_dt = start_dt.replace(tzinfo=pytz.UTC)

            if end_time:
                end_dt = parse_datetime_with_timezone(end_time, self.config)
            else:
                end_dt = start_dt + timedelta(minutes=duration_minutes or 60)
            
            # Ensure end_dt is also aware if it was calculated or parsed naively
            if end_dt and end_dt.tzinfo is None and start_dt.tzinfo:
                 end_dt = end_dt.replace(tzinfo=start_dt.tzinfo)

            # Normalize to remove microseconds to prevent false positives from slight drift
            if start_dt:
                start_dt = start_dt.replace(microsecond=0)
            if end_dt:
                end_dt = end_dt.replace(microsecond=0)

            conflicts = []
            
            # 1. Sort events to find the one immediately BEFORE our proposed start
            # This is needed for travel time calculation
            sorted_events = sorted(events, key=lambda e: parse_event_time(e.get('start', {})).timestamp() if parse_event_time(e.get('start', {})) else 0)
            
            previous_event = None
            
            for event in sorted_events:
                if event.get('id') == exclude_event_id:
                    continue

                # Fix 1: Transparency Handling
                # If event is marked as "transparent" (Free), it does not block time
                if event.get('transparency') == 'transparent':
                    continue
                    
                e_start = parse_event_time(event.get('start', {}))
                e_end = parse_event_time(event.get('end', {}))
                
                if e_start and e_end:
                    # Fix 2: Microsecond Drift
                    # Normalize existing event times too
                    e_start = e_start.replace(microsecond=0)
                    e_end = e_end.replace(microsecond=0)

                    # Strict overlap check for direct conflicts
                    is_overlap = events_overlap(start_dt, end_dt, e_start, e_end)
                    logger.info(f"[DEBUG_CONFLICT] Checking: Proposed {start_dt} - {end_dt} vs Existing {e_start} - {e_end} | Overlap: {is_overlap}")
                    if is_overlap:
                        conflicts.append(event)
                    
                    # Track potential previous event for travel time
                    # Logic: If event ENDS before we START, it is a candidate for "previous event"
                    # We want the *latest* one that ends before we start.
                    if e_end <= start_dt:
                        previous_event = event

            # 2. Check Travel Time from Previous Event
            if self.maps_service and location and previous_event and not conflicts:
                prev_loc = previous_event.get('location')
                if prev_loc:
                    # Calculate travel time
                    # We aim to arrive exactly at start_dt
                    travel_minutes = self.maps_service.get_travel_duration(prev_loc, location, start_dt)
                    
                    if travel_minutes:
                        # Required departure time
                        departure_dt = start_dt - timedelta(minutes=travel_minutes)
                        
                        e_end = parse_event_time(previous_event.get('end', {}))
                        
                        # If we need to leave BEFORE the previous event ends = CONFLICT
                        # We add a small buffer (e.g. 5 mins) for sanity? No, strict for now.
                        if departure_dt < e_end:
                            # Create a synthetic conflict description or attach to the event
                            # We treat the previous event as a conflict because of travel time
                            previous_event['_conflict_reason'] = f"Travel time of {travel_minutes} min required from '{prev_loc}'."
                            conflicts.append(previous_event)

            return conflicts
            
        except Exception as e:
            logger.error(f"[CALENDAR_SERVICE] Failed to find conflicts: {e}")
            raise CalendarServiceException(
                f"Failed to find conflicts: {str(e)}",
                service_name="calendar"
            )
    
    def schedule_meeting(
        self,
        title: str,
        duration_minutes: int,
        attendees: List[str],
        preferred_times: Optional[List[str]] = None,
        description: Optional[str] = None,
        location: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Intelligently schedule a meeting
        
        Args:
            title: Meeting title
            duration_minutes: Meeting duration
            attendees: List of attendee emails
            preferred_times: Preferred start times (will pick first available)
            description: Meeting description
            location: Meeting location
            
        Returns:
            Created meeting event
        """
        self._ensure_available()
        
        try:
            # If no preferred times, find free slots
            if not preferred_times:
                free_slots = self.find_free_time(duration_minutes, max_suggestions=1)
                if not free_slots:
                    raise CalendarServiceException(
                        "No available time slots found",
                        service_name="calendar"
                    )
                start_time = free_slots[0]['start']
                end_time = free_slots[0]['end']
            else:
                # Try preferred times in order
                start_time = None
                end_time = None
                for pref_time in preferred_times:
                    conflicts = self.find_conflicts(pref_time, None, duration_minutes)
                    if not conflicts:
                        start_time = pref_time
                        start_dt = datetime.fromisoformat(pref_time.replace('Z', '+00:00'))
                        end_dt = start_dt + timedelta(minutes=duration_minutes)
                        end_time = end_dt.isoformat()
                        break
                
                if not start_time:
                    raise SchedulingConflictException(
                        "All preferred times have conflicts",
                        service_name="calendar",
                        details={'conflicting_events': []}
                    )
            
            # Create the meeting
            return self.create_event(
                title=title,
                start_time=start_time,
                end_time=end_time,
                description=description,
                location=location,
                attendees=attendees
            )
            
        except Exception as e:
            logger.error(f"[CALENDAR_SERVICE] Failed to schedule meeting: {e}")
            raise CalendarServiceException(
                f"Failed to schedule meeting: {str(e)}",
                service_name="calendar"
            )
    
    # ===================================================================
    # ANALYTICS
    # ===================================================================
    
    def get_calendar_stats(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days_back: int = 7
    ) -> Dict[str, Any]:
        """
        Get calendar statistics and insights
        
        Args:
            start_date: Start date for analysis
            end_date: End date for analysis
            days_back: Days to look back (if dates not provided)
            
        Returns:
            Calendar statistics
        """
        self._ensure_available()
        
        try:
            events = self.list_events(
                start_date=start_date,
                end_date=end_date,
                days_back=days_back,
                days_ahead=0
            )
            
            total_events = len(events)
            total_duration = 0
            event_types = {}
            
            for event in events:
                # Calculate duration
                # Calculate duration
                if 'start' in event and 'end' in event:
                    # Handle both dictionary (raw API) and datetime (client object) formats
                    start_data = event['start']
                    end_data = event['end']
                    
                    try:
                        start_dt = None
                        end_dt = None
                        
                        if isinstance(start_data, datetime):
                            start_dt = start_data
                        elif isinstance(start_data, dict):
                            val = start_data.get('dateTime') or start_data.get('date')
                            if val:
                                start_dt = datetime.fromisoformat(val.replace('Z', '+00:00'))
                                
                        if isinstance(end_data, datetime):
                            end_dt = end_data
                        elif isinstance(end_data, dict):
                            val = end_data.get('dateTime') or end_data.get('date')
                            if val:
                                end_dt = datetime.fromisoformat(val.replace('Z', '+00:00'))

                        if start_dt and end_dt:
                            duration = (end_dt - start_dt).total_seconds() / 60
                            total_duration += duration
                    except Exception as e:
                        logger.warning(f"[CALENDAR_SERVICE] Error parsing duration: {e}")
                        pass
                
                # Count event types (based on title keywords)
                title = event.get('summary', '').lower()
                if 'meeting' in title:
                    event_types['meetings'] = event_types.get('meetings', 0) + 1
                elif 'call' in title:
                    event_types['calls'] = event_types.get('calls', 0) + 1
                else:
                    event_types['other'] = event_types.get('other', 0) + 1
            
            return {
                'total_events': total_events,
                'total_hours': round(total_duration / 60, 2),
                'average_event_duration': round(total_duration / total_events, 2) if total_events > 0 else 0,
                'event_types': event_types
            }
            
        except Exception as e:
            logger.error(f"[CALENDAR_SERVICE] Failed to get calendar stats: {e}")
            raise CalendarServiceException(
                f"Failed to get calendar stats: {str(e)}",
                service_name="calendar"
            )
    
    # ===================================================================
    # HELPER METHODS
    # ===================================================================
    
    def _find_gaps_between_events(
        self,
        events: List[Dict[str, Any]],
        duration_minutes: int,
        working_hours_only: bool,
        max_suggestions: int
    ) -> List[Dict[str, str]]:
        """Find available time gaps between events"""
        # Use parse_event_time to handle both dicts and objects safely
        from ...core.calendar.utils import parse_event_time, format_datetime_rfc3339
        
        # Sort events by start time safely
        def get_start(e):
            dt = parse_event_time(e.get('start', {}))
            return dt.timestamp() if dt else 0
            
        sorted_events = sorted(events, key=get_start)
        
        free_slots = []
        
        # Simple implementation - can be enhanced with working hours logic
        for i in range(len(sorted_events) - 1):
            current_end_dt = parse_event_time(sorted_events[i].get('end', {}))
            next_start_dt = parse_event_time(sorted_events[i + 1].get('start', {}))
            
            if current_end_dt and next_start_dt:
                try:
                    # Both are datetime objects now (aware or naive consistently from utils)
                    gap_minutes = (next_start_dt - current_end_dt).total_seconds() / 60
                    
                    if gap_minutes >= duration_minutes:
                        free_slots.append({
                            'start': format_datetime_rfc3339(current_end_dt),
                            'end': format_datetime_rfc3339(current_end_dt + timedelta(minutes=duration_minutes))
                        })
                        
                        if len(free_slots) >= max_suggestions:
                            break
                except Exception as e:
                    logger.warning(f"Error calculating gap: {e}")
                    continue
        
        return free_slots
    
    # ===================================================================
    # INTEGRATIONS
    # ===================================================================
    
    def create_task_from_event(
        self,
        event_id: str,
        event_title: str,
        event_time: str,
        task_type: str = "preparation",
        task_service: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Create a task from a calendar event
        
        Args:
            event_id: Event ID for linking
            event_title: Event title
            event_time: Event start time
            task_type: Type of task (preparation/followup)
            task_service: Optional task service instance
            
        Returns:
            Created task details
        """
        try:
            logger.info(f"[CALENDAR_SERVICE] Creating {task_type} task for event: {event_id}")
            
            if not task_service:
                from .task_service import TaskService
                task_service = TaskService(
                    config=self.config,
                    credentials=self.credentials
                )
            
            return task_service.create_task_from_event(
                event_id=event_id,
                event_title=event_title,
                event_time=event_time,
                task_type=task_type
            )
            
        except Exception as e:
            logger.error(f"[CALENDAR_SERVICE] Failed to create task from event: {e}")
            from .exceptions import CalendarIntegrationException
            raise CalendarIntegrationException(
                f"Failed to create task from event: {str(e)}",
                service_name="calendar",
                details={'event_id': event_id}
            )
    
    def send_event_summary_email(
        self,
        event_id: str,
        recipient_emails: List[str],
        email_service: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Send event summary email to participants
        
        Args:
            event_id: Event ID
            recipient_emails: List of recipient email addresses
            email_service: Optional email service instance
            
        Returns:
            Email send result
        """
        try:
            self._ensure_available()
            
            # Get event details
            event = self.calendar_client.get_event(event_id)
            if not event:
                raise EventNotFoundException(
                    f"Event {event_id} not found",
                    service_name="calendar"
                )
            
            if not email_service:
                from .email_service import EmailService
                email_service = EmailService(
                    config=self.config,
                    credentials=self.credentials
                )
            
            # Create email content
            start_time = event.get('start', {}).get('dateTime', 'TBD')
            location = event.get('location', 'No location specified')
            description = event.get('description', '')
            
            subject = f"Event Summary: {event.get('summary', 'Untitled Event')}"
            body = f"""
Event Details:
- Title: {event.get('summary', 'Untitled Event')}
- Date & Time: {start_time}
- Location: {location}
- Description: {description}

This is an automated summary from your calendar.
            """.strip()
            
            # Send to first recipient (would need bulk send for multiple)
            return email_service.send_email(
                to=recipient_emails[0],
                subject=subject,
                body=body,
                cc=recipient_emails[1:] if len(recipient_emails) > 1 else None
            )
            
        except Exception as e:
            logger.error(f"[CALENDAR_SERVICE] Failed to send event summary: {e}")
            from .exceptions import CalendarIntegrationException
            raise CalendarIntegrationException(
                f"Failed to send event summary: {str(e)}",
                service_name="calendar",
                details={'event_id': event_id}
            )