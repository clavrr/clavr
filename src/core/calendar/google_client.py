"""
Google Calendar API Client
Provides methods to interact with Google Calendar API
"""
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ...utils.logger import setup_logger
from ...utils.config import Config, get_timezone
from ...utils import retry_calendar_api
from ...utils import (
    with_calendar_circuit_breaker,
    calendar_list_fallback,
    ServiceUnavailableError
)
from ...integrations.google_calendar.exceptions import AuthenticationException
from ..base import BaseGoogleAPIClient
from .utils import (
    parse_datetime_with_timezone,
    format_datetime_rfc3339,
    get_timezone_from_offset,
    get_user_timezone,
    format_event_for_api,
    extract_event_details,
    calculate_time_range,
    get_utc_now,
    convert_to_user_timezone
)

logger = setup_logger(__name__)


class GoogleCalendarClient(BaseGoogleAPIClient):
    """
    Google Calendar API client
    
    Provides methods to interact with Google Calendar:
    - List events
    - Create events
    - Update events
    - Delete events
    - Search events
    """
    
    def _build_service(self) -> Any:
        """Build Google Calendar API service"""
        return build('calendar', 'v3', credentials=self.credentials, cache_discovery=False)
    
    def _get_required_scopes(self) -> List[str]:
        """Get required Google Calendar scopes"""
        return [
            'https://www.googleapis.com/auth/calendar',
            'https://www.googleapis.com/auth/calendar.readonly'
        ]
    
    def _get_service_name(self) -> str:
        """Get service name"""
        return "Google Calendar"
    
    # ========== Retry-Protected API Methods ==========
    
    @with_calendar_circuit_breaker()
    @retry_calendar_api()
    def _list_events_with_retry(
        self,
        calendar_id: str,
        time_min: str,
        time_max: str,
        max_results: int,
        single_events: bool = True,
        order_by: str = 'startTime'
    ) -> Dict[str, Any]:
        """
        List calendar events with automatic retry on transient errors and circuit breaker protection
        
        Args:
            calendar_id: Calendar ID (usually 'primary')
            time_min: Start time (RFC3339 format)
            time_max: End time (RFC3339 format)
            max_results: Maximum results
            single_events: Expand recurring events
            order_by: Sort order
            
        Returns:
            API response with event list
        """
        return self.service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=single_events,
            orderBy=order_by
        ).execute()
    
    @with_calendar_circuit_breaker()
    @retry_calendar_api()
    def _list_events_with_retry_paginated(
        self,
        calendarId: str,
        timeMin: str,
        timeMax: str,
        maxResults: int,
        singleEvents: bool = True,
        orderBy: str = 'startTime',
        pageToken: Optional[str] = None,
        q: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List calendar events with pagination support and automatic retry
        
        Args:
            calendarId: Calendar ID (usually 'primary')
            timeMin: Start time (RFC3339 format)
            timeMax: End time (RFC3339 format)
            maxResults: Maximum results per page
            singleEvents: Expand recurring events
            orderBy: Sort order
            pageToken: Optional page token for pagination
            
        Returns:
            API response with event list and nextPageToken if more pages exist
        """
        if q:
            request_params = {
                'calendarId': calendarId,
                'timeMin': timeMin,
                'timeMax': timeMax,
                'maxResults': maxResults,
                'singleEvents': singleEvents,
                'orderBy': orderBy,
                'q': q
            }
            request = self.service.events().list(**request_params)
        else:
            request = self.service.events().list(
                calendarId=calendarId,
                timeMin=timeMin,
                timeMax=timeMax,
                maxResults=maxResults,
                singleEvents=singleEvents,
                orderBy=orderBy
            )
        
        if pageToken:
            request.pageToken = pageToken
        
        return request.execute()
    
    @with_calendar_circuit_breaker()
    @retry_calendar_api()
    def _get_event_with_retry(self, calendar_id: str, event_id: str) -> Dict[str, Any]:
        """
        Get a calendar event with automatic retry on transient errors and circuit breaker protection
        
        Args:
            calendar_id: Calendar ID
            event_id: Event ID
            
        Returns:
            Event details
        """
        return self.service.events().get(
            calendarId=calendar_id,
            eventId=event_id
        ).execute()
    
    @with_calendar_circuit_breaker()
    @retry_calendar_api()
    def _insert_event_with_retry(self, calendar_id: str, event_body: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a calendar event with automatic retry on transient errors and circuit breaker protection
        
        Args:
            calendar_id: Calendar ID
            event_body: Event data
            
        Returns:
            Created event details
        """
        return self.service.events().insert(
            calendarId=calendar_id,
            body=event_body
        ).execute()
    
    @with_calendar_circuit_breaker()
    @retry_calendar_api()
    def _update_event_with_retry(
        self,
        calendar_id: str,
        event_id: str,
        event_body: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update a calendar event with automatic retry on transient errors and circuit breaker protection
        
        Args:
            calendar_id: Calendar ID
            event_id: Event ID
            event_body: Updated event data
            
        Returns:
            Updated event details
        """
        return self.service.events().update(
            calendarId=calendar_id,
            eventId=event_id,
            body=event_body
        ).execute()
    
    @with_calendar_circuit_breaker()
    @retry_calendar_api()
    def _delete_event_with_retry(self, calendar_id: str, event_id: str) -> None:
        """
        Delete a calendar event with automatic retry on transient errors and circuit breaker protection
        
        Args:
            calendar_id: Calendar ID
            event_id: Event ID
        """
        self.service.events().delete(
            calendarId=calendar_id,
            eventId=event_id
        ).execute()
    
    # ========== Public API Methods ==========
    
    def list_events(
        self,
        days_ahead: int = 7,
        days_back: int = 0,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        max_results: int = 20,
        calendar_id: str = 'primary',
        show_deleted: bool = False,
        query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List events from Google Calendar
        
        Args:
            days_ahead: Number of days to look ahead (default: 7)
            days_back: Number of days to look back (default: 0, for past queries)
            start_date: Optional specific start date (overrides days_back)
            end_date: Optional specific end date (overrides days_ahead)
            max_results: Maximum number of events to return
            calendar_id: Calendar ID (default: 'primary')
            show_deleted: Whether to include deleted events
            
        Returns:
            List of event dictionaries
        """
        if not self.is_available():
            logger.warning("Google Calendar service not available")
            return []
        
        try:
            # Use utility function to calculate time range
            start_utc, end_utc = calculate_time_range(
                start_date=start_date,
                end_date=end_date,
                days_back=days_back,
                days_ahead=days_ahead,
                config=self.config
            )
            
            # Log the query range
            tz_name = get_user_timezone(self.config)
            start_user = convert_to_user_timezone(start_utc, self.config)
            end_user = convert_to_user_timezone(end_utc, self.config)
            logger.info(f"[CAL] Querying events from {start_user.strftime('%Y-%m-%d %H:%M')} ({tz_name}) = {start_utc.strftime('%Y-%m-%d %H:%M')} UTC to {end_user.strftime('%Y-%m-%d %H:%M')} ({tz_name}) = {end_utc.strftime('%Y-%m-%d %H:%M')} UTC")
            
            # Get events from the specified calendar with pagination support
            all_events = []
            page_token = None
            page_count = 0
            
            while True:
                page_count += 1
                # Build request parameters
                request_params = {
                    'calendarId': calendar_id,
                    'timeMin': start_utc.isoformat().replace('+00:00', 'Z'),
                    'timeMax': end_utc.isoformat().replace('+00:00', 'Z'),
                    'maxResults': min(max_results, 2500),  # Google Calendar API max is 2500 per page
                    'singleEvents': True,
                    'orderBy': 'startTime'
                }
                
                if query:
                    request_params['q'] = query
                
                if page_token:
                    request_params['pageToken'] = page_token
                
                # Execute request with retry
                events_result = self._list_events_with_retry_paginated(**request_params)
                
                page_events = events_result.get('items', [])
                all_events.extend(page_events)
                
                logger.info(f"[CAL] Page {page_count}: Retrieved {len(page_events)} events (total so far: {len(all_events)})")
                
                # Check if there are more pages
                page_token = events_result.get('nextPageToken')
                if not page_token or len(all_events) >= max_results:
                    if page_token:
                        logger.info(f"[CAL] More pages available but reached max_results limit ({max_results})")
                    break
            
            events = all_events[:max_results]  # Limit to max_results
            logger.info(f"[CAL] Retrieved {len(events)} total events from {page_count} page(s)")
            
            # Convert to our format using utility function
            formatted_events = []
            for event in events:
                # Get summary/title - Google Calendar API uses 'summary' field
                raw_summary = event.get('summary')
                summary = (raw_summary or '').strip()
                
                if not summary:
                    summary = 'No Title'
                    logger.warning(f"[CAL] Event {event.get('id', 'unknown')} has no summary/title - using 'No Title'")
                
                # Use utility function for standard fields, then add API-specific fields
                formatted_event = extract_event_details(event)
                formatted_event.update({
                    'summary': summary,  # Keep both for compatibility
                    'status': event.get('status', 'confirmed'),
                    'htmlLink': event.get('htmlLink', ''),
                    'created': event.get('created', ''),
                    'updated': event.get('updated', '')
                })
                formatted_events.append(formatted_event)
            
            logger.info(f"[CAL] Retrieved {len(formatted_events)} events from Google Calendar")
            return formatted_events
            
        except HttpError as e:
            error_details = e.error_details if hasattr(e, 'error_details') else {}
            error_reason = error_details.get('error', '') if isinstance(error_details, dict) else str(error_details)
            
            # Check for invalid_grant error (refresh token expired/invalid)
            if e.resp.status == 401:
                error_message = str(e)
                if 'invalid_grant' in error_message.lower() or 'invalid_grant' in str(error_reason).lower():
                    logger.error(f"Google Calendar API authentication error: {e}")
                    logger.error("Your refresh token has expired or been revoked. Please re-authenticate.")
                    logger.error("This usually happens when:")
                    logger.error("  - You changed your Google account password")
                    logger.error("  - You revoked access to the app")
                    logger.error("  - The refresh token expired (after 6 months of inactivity)")
                    logger.error("Solution: Please log out and log back in to refresh your credentials.")
                    # Raise AuthenticationException so the service layer can handle it
                    raise AuthenticationException(
                        "Google Calendar authentication failed: refresh token expired or revoked. Please log out and log back in.",
                        service_name="calendar",
                        details={'error': 'invalid_grant', 'status': 401}
                    )
                else:
                    logger.error(f"Google Calendar API authentication error (401): {e}")
                    logger.error("Please check your credentials and try again.")
                    raise AuthenticationException(
                        f"Google Calendar authentication failed: {error_message}",
                        service_name="calendar",
                        details={'status': 401}
                    )
            elif e.resp.status == 403:
                logger.error(f"Google Calendar API error: {e}")
                logger.error("This usually means the OAuth credentials don't have the required scopes.")
                logger.error("Please re-authenticate with the Google Calendar scope: https://www.googleapis.com/auth/calendar")
                # Raise exception so agent can inform user to connect Calendar
                raise AuthenticationException(
                    "Calendar isn't connected yet. Please connect it from Settings → Integrations to access your calendar.",
                    service_name="calendar",
                    details={'error': 'insufficientPermissions', 'status': 403}
                )
        except AuthenticationException:
            # Re-raise authentication exceptions
            raise
        except Exception as e:
            error_message = str(e)
            # Check for invalid_grant in exception message (Google auth library wraps it)
            if 'invalid_grant' in error_message.lower():
                logger.error(f"Google Calendar authentication error: {e}")
                logger.error("Your refresh token has expired or been revoked. Please re-authenticate.")
                logger.error("Solution: Please log out and log back in to refresh your credentials.")
                raise AuthenticationException(
                    "Google Calendar authentication failed: refresh token expired or revoked. Please log out and log back in.",
                    service_name="calendar",
                    details={'error': 'invalid_grant'}
                )
            else:
                logger.error(f"Failed to list Google Calendar events: {e}")
                raise
    
    def create_event(
        self,
        title: str,
        start_time: str,
        end_time: Optional[str] = None,
        duration_minutes: int = 60,
        description: str = "",
        location: str = "",
        attendees: Optional[List[str]] = None,
        calendar_id: str = 'primary',
        send_updates: bool = True,
        recurrence: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new event in Google Calendar
        
        Args:
            title: Event title
            start_time: Start time (RFC 3339 format)
            end_time: End time (RFC 3339 format, optional)
            duration_minutes: Duration in minutes (if end_time not provided)
            description: Event description
            location: Event location
            attendees: List of attendee emails
            calendar_id: Calendar ID
            send_updates: Whether to send email updates
            
        Returns:
            Created event dictionary or None if failed
        """
        if not self.is_available():
            logger.warning("Google Calendar service not available")
            logger.warning(f"Service: {self.service}")
            logger.warning(f"Credentials: {self.credentials}")
            return None
        
        try:
            # Parse start time using utility function
            start_dt = parse_datetime_with_timezone(start_time, self.config)
            if not start_dt:
                raise ValueError(f"Failed to parse start_time: {start_time}")
            
            # Calculate end time if not provided
            if not end_time:
                # Use default of 60 minutes if duration_minutes is None
                actual_duration = duration_minutes if duration_minutes is not None else 60
                end_dt = start_dt + timedelta(minutes=actual_duration)
                end_time = format_datetime_rfc3339(end_dt, preserve_timezone=True)
            else:
                end_dt = parse_datetime_with_timezone(end_time, self.config)
                if not end_dt:
                    raise ValueError(f"Failed to parse end_time: {end_time}")
            
            # Format times for API (preserve timezone offsets)
            start_rfc3339 = format_datetime_rfc3339(start_dt, preserve_timezone=True)
            end_rfc3339 = format_datetime_rfc3339(end_dt, preserve_timezone=True)
            
            # Determine timezone for event body
            event_timezone = get_user_timezone(self.config)
            
            # If start_time has timezone offset, try to detect timezone name
            if start_dt.tzinfo:
                offset_hours = start_dt.utcoffset().total_seconds() / 3600
                detected_tz = get_timezone_from_offset(offset_hours)
                if detected_tz:
                    event_timezone = detected_tz
                    logger.debug(f"[CAL] Detected timezone from offset {offset_hours}h: {event_timezone}")
            
            # Build event body using utility function
            event_body = format_event_for_api(
                title=title,
                start_time=start_rfc3339,
                end_time=end_rfc3339,
                timezone=event_timezone,
                description=description,
                location=location,
                attendees=attendees,
                recurrence=recurrence
            )
            
            # Create event
            logger.info(f"About to call Google Calendar API with event_body: {event_body}")
            event = self._insert_event_with_retry(
                calendar_id=calendar_id,
                event_body=event_body
            )
            
            logger.info(f"[OK] Created Google Calendar event: {title}")
            logger.info(f"Event response: {event}")
            return event
            
        except HttpError as e:
            error_msg = f"Google Calendar API error creating event '{title}': {e}"
            logger.error(error_msg)
            logger.error(f"Error details: {e.error_details}")
            logger.error(f"Error status: {e.resp.status}")
            # Raise the exception instead of returning None so we can see what's wrong
            raise Exception(error_msg)
        except Exception as e:
            error_msg = f"Failed to create Google Calendar event '{title}': {e}"
            logger.error(error_msg)
            logger.error(f"Exception type: {type(e).__name__}")
            # Raise the exception instead of returning None so we can see what's wrong
            raise Exception(error_msg)
    
    def update_event(
        self,
        event_id: str,
        title: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        calendar_id: str = 'primary',
        send_updates: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Update an existing event in Google Calendar
        
        Args:
            event_id: Event ID to update
            title: New title (optional)
            start_time: New start time (optional)
            end_time: New end time (optional)
            description: New description (optional)
            location: New location (optional)
            attendees: New attendees list (optional)
            calendar_id: Calendar ID
            send_updates: Whether to send email updates
            
        Returns:
            Updated event dictionary or None if failed
        """
        if not self.is_available():
            logger.warning("Google Calendar service not available")
            return None
        
        try:
            # Get existing event
            event = self._get_event_with_retry(
                calendar_id=calendar_id,
                event_id=event_id
            )
            
            # Update fields
            if title:
                event['summary'] = title
            if description is not None:
                event['description'] = description
            if location is not None:
                event['location'] = location
            if attendees is not None:
                event['attendees'] = [{'email': email} for email in attendees]
            
            if start_time:
                event['start'] = {
                    'dateTime': start_time,
                    'timeZone': 'UTC',
                }
            if end_time:
                event['end'] = {
                    'dateTime': end_time,
                    'timeZone': 'UTC',
                }
            
            # Update event
            updated_event = self._update_event_with_retry(
                calendar_id=calendar_id,
                event_id=event_id,
                event_body=event
            )
            
            logger.info(f"[OK] Updated Google Calendar event: {event_id}")
            return updated_event
            
        except HttpError as e:
            logger.error(f"Error updating Google Calendar event {event_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to update Google Calendar event: {e}")
            return None
    
    def delete_event(
        self,
        event_id: str,
        calendar_id: str = 'primary',
        send_updates: bool = True
    ) -> bool:
        """
        Delete an event from Google Calendar
        
        Args:
            event_id: Event ID to delete
            calendar_id: Calendar ID
            send_updates: Whether to send email updates
            
        Returns:
            True if deleted, False otherwise
        """
        if not self.is_available():
            logger.warning("Google Calendar service not available")
            return False
        
        try:
            self._delete_event_with_retry(
                calendar_id=calendar_id,
                event_id=event_id
            )
            
            logger.info(f"[OK] Deleted Google Calendar event: {event_id}")
            return True
            
        except HttpError as e:
            logger.error(f"Error deleting Google Calendar event {event_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete Google Calendar event: {e}")
            return False
