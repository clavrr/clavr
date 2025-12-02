"""
Calendar Event Handlers

Handles all calendar event operations:
- Event creation with conflict detection
- Event updates and modifications
- Event deletion
- Event moving/rescheduling
- Time parsing and validation
- Event search and matching

This module centralizes all event-related business logic for the calendar parser.
"""
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import pytz
from langchain.tools import BaseTool

from ....utils.logger import setup_logger
from ....core.calendar.utils import (
    parse_datetime_with_timezone,
    format_datetime_for_calendar,
    get_user_timezone,
    get_day_boundaries,
    parse_event_time,
    find_conflicts,
    format_event_time_display,
    calculate_ordinal_day_date,
    DEFAULT_DURATION_MINUTES,
    DEFAULT_DAYS_AHEAD
)
from ...intent import CALENDAR_QUESTION_PATTERNS

logger = setup_logger(__name__)

# Constants for default time values
DEFAULT_AFTERNOON_HOUR = 14  # 2pm
DEFAULT_MORNING_HOUR = 10  # 10am
DEFAULT_EVENING_HOUR = 18  # 6pm


class CalendarEventHandlers:
    """
    Handles all calendar event operations.
    
    This includes:
    - Creating events with conflict detection (_handle_create_action)
    - Updating events (_handle_update_action)
    - Deleting events (_handle_delete_action)
    - Moving/rescheduling events (_handle_move_action, _handle_move_reschedule_action)
    - Finding events by title (_find_event_by_title)
    - Extracting event details from queries (_extract_event_title_from_move_query, _extract_new_time_from_move_query)
    - Parsing relative times (_parse_relative_time_to_iso)
    - Creating events with conflict checking (_parse_and_create_calendar_event_with_conflict_check)
    - Checking for conflicts (_check_calendar_conflicts)
    """
    
    def __init__(self, calendar_parser):
        """
        Initialize event handlers.
        
        Args:
            calendar_parser: Parent CalendarParser instance for accessing llm_client, config, etc.
        """
        self.calendar_parser = calendar_parser
        self.llm_client = calendar_parser.llm_client
        self.config = calendar_parser.config
    
    def handle_create_action(self, tool: BaseTool, query: str) -> str:
        """Handle calendar event creation action with conflict detection and conversational response"""
        # CRITICAL SAFEGUARD: Never create events for list/view queries
        query_lower = query.lower()
        if any(phrase in query_lower for phrase in CALENDAR_QUESTION_PATTERNS):
            logger.error(f"[CAL] CRITICAL BUG FIX: handle_create_action called for list query '{query}' - routing to list instead")
            return self.calendar_parser.list_search_handlers.handle_list_action(tool, query)
        
        result = self.parse_and_create_calendar_event_with_conflict_check(tool, query)
        
        # Check if result indicates an error BEFORE generating conversational response
        result_lower = result.lower()
        is_error = (
            '[error]' in result_lower or 
            'failed' in result_lower or 
            'not available' in result_lower or 
            'please' in result_lower and ('authenticate' in result_lower or 'enable' in result_lower) or
            'restricted' in result_lower
        )
        
        if is_error:
            logger.warning(f"[CAL] Detected error in result, not generating success response: {result[:200]}")
            # For errors, generate conversational error message using LLM
            if self.llm_client:
                try:
                    conversational_error = self._generate_conversational_calendar_action_response(
                        result, query, "create"
                    )
                    if conversational_error:
                        return conversational_error
                except Exception as e:
                    logger.warning(f"[CAL] Failed to generate conversational error response: {e}")
            # Fallback: return the error message as-is (it should already be user-friendly)
            return result
        
        # CRITICAL: ALWAYS generate conversational response using LLM for successful operations
        # This ensures NO robotic patterns ever reach the user
        if not self.llm_client:
            logger.error("[CAL] CRITICAL: LLM client not available! Cannot generate conversational response.")
            logger.error("[CAL] This should never happen - LLM must be configured for calendar operations.")
        
        logger.info("[CAL] Generating conversational create response with LLM")
        logger.info(f"[CAL] Raw result from tool: {result[:200]}...")
        
        conversational_response = None
        if self.llm_client:
            try:
                conversational_response = self._generate_conversational_calendar_action_response(
                    result, query, "create"
                )
                logger.info(f"[CAL] LLM returned response: {conversational_response[:200] if conversational_response else 'None'}...")
            except Exception as e:
                logger.error(f"[CAL] LLM invocation failed: {e}", exc_info=True)
        
        # Process LLM response
        if conversational_response and conversational_response.strip():
            # Final safety check: ensure no tags made it through
            if not re.search(r'\[.*?\]', conversational_response):
                logger.info("[CAL] Successfully generated conversational create response (no tags detected)")
                return conversational_response
            else:
                logger.warning("[CAL] LLM response contains tags, cleaning aggressively...")
                # Aggressively clean
                cleaned = re.sub(r'\[.*?\]\s*', '', conversational_response)
                cleaned = re.sub(r'\*\*', '', cleaned)
                cleaned = re.sub(r'https?://[^\s]+', '', cleaned)
                cleaned = re.sub(r'\s+', ' ', cleaned).strip()
                if cleaned:
                    logger.info(f"[CAL] Cleaned response: {cleaned[:200]}...")
                    return cleaned
        
        # If LLM failed or returned empty, use natural fallback
        logger.warning("[CAL] LLM unavailable or returned empty, using natural fallback")
        
        # If LLM fails, create a simple natural response (strip ALL tags first)
        # Strip all tags from result before extracting
        clean_result = re.sub(r'\[.*?\]\s*', '', result)
        clean_result = re.sub(r'\*\*', '', clean_result)
        
        # Extract title - look for text after "event:" and before "Date:"
        event_title_match = re.search(r'(?:Created|created).*?event[:\s]+(.+?)(?:\s+Date:|\s*$)', clean_result, re.IGNORECASE)
        if event_title_match:
            event_title = event_title_match.group(1).strip()
            # Remove "Google Calendar" if present
            event_title = re.sub(r'Google Calendar\s+', '', event_title, flags=re.IGNORECASE).strip()
            # Split on common separators
            event_title = re.split(r'\s+Date:|\s+Link:', event_title, flags=re.IGNORECASE)[0].strip()
        else:
            # Fallback: try simpler pattern
            event_title_match = re.search(r'(?:Created|created).*?event[:\s]+([^\n]+)', clean_result, re.IGNORECASE)
            if event_title_match:
                event_title = event_title_match.group(1).strip()
                event_title = re.sub(r'Google Calendar\s+', '', event_title, flags=re.IGNORECASE).strip()
                event_title = re.split(r'\s+Date:|\s+Link:', event_title, flags=re.IGNORECASE)[0].strip()
            else:
                event_title = self.calendar_parser._extract_event_title(query) or "the event"
        
        # Extract time - look for text after "Date:" and before "Link:" or end
        time_match = re.search(r'Date[:\s]+(.+?)(?:\s+Link:|\s*$)', clean_result, re.IGNORECASE | re.DOTALL)
        event_time = time_match.group(1).strip() if time_match else None
        
        # Clean extracted values
        event_title = re.sub(r'\[.*?\]', '', event_title).strip()
        if event_time:
            event_time = re.sub(r'\[.*?\]', '', event_time).strip()
            event_time = re.split(r'\s+Link:', event_time, flags=re.IGNORECASE)[0].strip()
        
        if event_time:
            return f"Done! I've added '{event_title}' to your calendar for {event_time}."
        else:
            return f"Done! I've added '{event_title}' to your calendar."
    
    def handle_update_action(self, tool: BaseTool, query: str) -> str:
        """
        Handle calendar update action with conversational response.
        
        Supports:
        - Move/reschedule queries: "move my standup to the afternoon"
        - Standard updates: "update meeting title to X"
        """
        query_lower = query.lower()
        
        # Check if this is a move/reschedule query
        is_move_query = any(word in query_lower for word in ["move", "reschedule", "move to", "reschedule to"])
        
        if is_move_query:
            return self.handle_move_reschedule_action(tool, query)
        
        # Standard update action
        result = tool._run(action="update", title="Event Update", description=query)
        
        # Check for errors first
        result_lower = result.lower()
        is_error = (
            'error' in result_lower or 
            'failed' in result_lower or 
            'not available' in result_lower
        )
        
        if is_error:
            logger.warning(f"[CAL] Detected error in update result: {result[:200]}")
            if self.llm_client:
                try:
                    conversational_error = self._generate_conversational_calendar_action_response(
                        result, query, "update"
                    )
                    if conversational_error:
                        return conversational_error
                except Exception as e:
                    logger.warning(f"[CAL] Failed to generate conversational error response: {e}")
            return result
        
        # CRITICAL: ALWAYS generate conversational response using LLM
        if not self.llm_client:
            logger.error("[CAL] CRITICAL: LLM client not available! Cannot generate conversational response.")
        
        logger.info("[CAL] Generating conversational update response with LLM")
        conversational_response = None
        if self.llm_client:
            try:
                conversational_response = self._generate_conversational_calendar_action_response(
                    result, query, "update"
                )
                logger.info(f"[CAL] LLM returned response: {conversational_response[:200] if conversational_response else 'None'}...")
            except Exception as e:
                logger.error(f"[CAL] LLM invocation failed: {e}", exc_info=True)
        
        # Process LLM response
        if conversational_response and conversational_response.strip():
            if not re.search(r'\[.*?\]', conversational_response):
                logger.info("[CAL] Successfully generated conversational update response (no tags detected)")
                return conversational_response
            else:
                logger.warning("[CAL] LLM response contains tags, cleaning...")
                cleaned = re.sub(r'\[.*?\]\s*', '', conversational_response)
                cleaned = re.sub(r'\*\*', '', cleaned)
                cleaned = re.sub(r'https?://[^\s]+', '', cleaned)
                cleaned = re.sub(r'\s+', ' ', cleaned).strip()
                if cleaned:
                    return cleaned
        
        # If LLM failed, create a simple natural response (strip ALL tags first)
        # Strip all tags from result before extracting
        clean_result = re.sub(r'\[.*?\]\s*', '', result)
        clean_result = re.sub(r'\*\*', '', clean_result)
        event_title_match = re.search(r'(?:Updated|updated).*?event[:\s]+([^\n]+)', clean_result, re.IGNORECASE)
        event_title = event_title_match.group(1).strip() if event_title_match else self.calendar_parser._extract_event_title(query) or "the event"
        # Clean extracted value
        event_title = re.sub(r'\[.*?\]', '', event_title).strip()
        return f"Done! I've updated '{event_title}' for you."
    
    def handle_delete_action(self, tool: BaseTool, query: str) -> str:
        """Handle calendar delete action with conversational response"""
        result = tool._run(action="delete", title="Event to Delete", description=query)
        
        # Check for errors first
        result_lower = result.lower()
        is_error = (
            'error' in result_lower or 
            'failed' in result_lower or 
            'not available' in result_lower
        )
        
        if is_error:
            logger.warning(f"[CAL] Detected error in delete result: {result[:200]}")
            if self.llm_client:
                try:
                    conversational_error = self._generate_conversational_calendar_action_response(
                        result, query, "delete"
                    )
                    if conversational_error:
                        return conversational_error
                except Exception as e:
                    logger.warning(f"[CAL] Failed to generate conversational error response: {e}")
            return result
        
        # CRITICAL: ALWAYS generate conversational response using LLM
        if not self.llm_client:
            logger.error("[CAL] CRITICAL: LLM client not available! Cannot generate conversational response.")
        
        logger.info("[CAL] Generating conversational delete response with LLM")
        conversational_response = None
        if self.llm_client:
            try:
                conversational_response = self._generate_conversational_calendar_action_response(
                    result, query, "delete"
                )
                logger.info(f"[CAL] LLM returned response: {conversational_response[:200] if conversational_response else 'None'}...")
            except Exception as e:
                logger.error(f"[CAL] LLM invocation failed: {e}", exc_info=True)
        
        # Process LLM response
        if conversational_response and conversational_response.strip():
            if not re.search(r'\[.*?\]', conversational_response):
                logger.info("[CAL] Successfully generated conversational delete response (no tags detected)")
                return conversational_response
            else:
                logger.warning("[CAL] LLM response contains tags, cleaning...")
                cleaned = re.sub(r'\[.*?\]\s*', '', conversational_response)
                cleaned = re.sub(r'\*\*', '', cleaned)
                cleaned = re.sub(r'https?://[^\s]+', '', cleaned)
                cleaned = re.sub(r'\s+', ' ', cleaned).strip()
                if cleaned:
                    return cleaned
        
        # If LLM failed, create a simple natural response (strip ALL tags first)
        # Strip all tags from result before extracting
        clean_result = re.sub(r'\[.*?\]\s*', '', result)
        clean_result = re.sub(r'\*\*', '', clean_result)
        event_title_match = re.search(r'(?:Deleted|deleted).*?event[:\s]+([^\n]+)', clean_result, re.IGNORECASE)
        event_title = event_title_match.group(1).strip() if event_title_match else self.calendar_parser._extract_event_title(query) or "the event"
        # Clean extracted value
        event_title = re.sub(r'\[.*?\]', '', event_title).strip()
        return f"Done! I've removed '{event_title}' from your calendar."
    
    def handle_move_action(self, tool: BaseTool, query: str) -> str:
        """
        Handle move action - routes to move/reschedule handler.
        
        Examples:
        - "Move my standup to the afternoon at 2pm"
        - "Reschedule my meeting to tomorrow"
        """
        return self.handle_move_reschedule_action(tool, query)
    
    def handle_move_reschedule_action(self, tool: BaseTool, query: str) -> str:
        """
        Handle move/reschedule queries like "move my standup to the afternoon"
        
        Steps:
        1. Extract event title, date, time from query using LLM
        2. Search for event using LLM-based semantic matching
        3. Extract new time from query using LLM
        4. Parse relative times (afternoon, morning, evening)
        5. Call move_event with event ID and new time
        """
        logger.info(f"[CAL] Handling move/reschedule query: {query}")
        
        # Extract event search criteria (title, date, time) using LLM
        search_criteria = self._extract_move_search_criteria(query)
        event_title = search_criteria.get('title')
        
        # CRITICAL: If no title extracted (likely due to placeholder), try to use stored event list
        if not event_title:
            return "I couldn't identify which event you'd like to move. Could you specify the event name?"
        
        logger.info(f"[CAL] Extracted search criteria: {search_criteria}")
        
        # Search for the event using LLM-based semantic matching
        event = self.find_event_by_criteria(tool, search_criteria, query)
        if not event:
            title_display = event_title or "the event"
            date_display = f" on {search_criteria.get('date')}" if search_criteria.get('date') else ""
            time_display = f" at {search_criteria.get('time')}" if search_criteria.get('time') else ""
            return f"I couldn't find an event matching '{title_display}{date_display}{time_display}'. Could you check the exact name or date?"
        
        event_id = event.get('id')
        if not event_id:
            return f"Found the event '{event_title}' but couldn't get its ID. Please try again."
        
        logger.info(f"[CAL] Found event: {event_title} (ID: {event_id})")
        
        # Extract new time from query
        new_time_str = self.extract_new_time_from_move_query(query)
        if not new_time_str:
            return f"I found '{event_title}', but I couldn't determine when you'd like to move it to. Could you specify a time?"
        
        logger.info(f"[CAL] Extracted new time: {new_time_str}")
        
        # Parse the new time to ISO format
        new_time_iso = self.parse_relative_time_to_iso(new_time_str, event)
        if not new_time_iso:
            return f"I couldn't parse the time '{new_time_str}'. Could you specify a more specific time?"
        
        logger.info(f"[CAL] Parsed new time to ISO: {new_time_iso}")
        
        # Call move_event
        try:
            result = tool._run(
                action="move_event",
                event_id=event_id,
                new_start_time=new_time_iso
            )
            
            # Check for errors
            result_lower = result.lower()
            is_error = (
                'error' in result_lower or 
                'failed' in result_lower or 
                'not available' in result_lower
            )
            
            if is_error:
                logger.warning(f"[CAL] Move event failed: {result}")
                if self.llm_client:
                    try:
                        conversational_error = self._generate_conversational_calendar_action_response(
                            result, query, "move"
                        )
                        if conversational_error:
                            return conversational_error
                    except Exception as e:
                        logger.warning(f"[CAL] Failed to generate conversational error response: {e}")
                return result
            
            # Generate conversational response
            if self.llm_client:
                try:
                    conversational_response = self._generate_conversational_calendar_action_response(
                        result, query, "move"
                    )
                    if conversational_response and conversational_response.strip():
                        if not re.search(r'\[.*?\]', conversational_response):
                            return conversational_response
                except Exception as e:
                    logger.warning(f"[CAL] Failed to generate conversational response: {e}")
            
            # Fallback response
            return f"Done! I've moved '{event_title}' to {new_time_str}."
            
        except Exception as e:
            logger.error(f"[CAL] Error moving event: {e}", exc_info=True)
            return f"I encountered an error while moving the event: {str(e)}"
    
    def _extract_move_search_criteria(self, query: str) -> Dict[str, Any]:
        """
        Extract search criteria (title, date, time) from move/reschedule queries using LLM.
        
        Examples:
        - "move my 1:1 Clavr meeting to 5 pm that day" -> {"title": "1:1 Clavr meeting", "date": "that day", "time": null}
        - "reschedule the team sync to tomorrow" -> {"title": "team sync", "date": "tomorrow", "time": null}
        - "move morning standup to 2pm" -> {"title": "morning standup", "date": null, "time": null}
        """
        criteria = {
            'title': None,
            'date': None,
            'time': None
        }
        
        # CRITICAL: Detect placeholder text from orchestrator (e.g., "[identified meeting from step_1]")
        # If found, we need to use the original query context or skip title extraction
        import re
        placeholder_pattern = r'\[.*?\]'
        if re.search(placeholder_pattern, query):
            logger.warning(f"[CAL] Detected placeholder in query: '{query}' - this suggests orchestrator decomposition")
            # Try to extract title from the part before the placeholder
            # For "move [identified meeting from step_1] to 5 pm", we can't extract title
            # In this case, we should rely on the previous step's result or use a different approach
            # For now, return empty criteria and let the handler use context from previous step
            return criteria
        
        if not self.config:
            # Fallback to pattern-based extraction
            return self._extract_move_search_criteria_patterns(query)
        
        try:
            from ....ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage
            import json
            
            llm = LLMFactory.get_llm_for_provider(self.config, temperature=0.7)
            if not llm:
                return self._extract_move_search_criteria_patterns(query)
            
            prompt = f"""Extract search criteria from this move/reschedule query. The user wants to find a calendar event to move.

Query: "{query}"

Extract:
1. title: Event/meeting title (e.g., "1:1 Clavr meeting", "team standup", "Clavr meeting")
   - Remove action words like "move", "reschedule", "my", "the"
   - "move my 1:1 Clavr meeting" → "1:1 Clavr meeting"
   - "reschedule the team sync" → "team sync"
   - IGNORE placeholder text like "[identified meeting from step_1]" or "[found meeting]" - these are not real titles
2. date: Specific date mentioned (e.g., "tomorrow", "today", "November 20th", "that day", "that day" refers to the event's current date)
   - "that day" means the same day as the event being moved
3. time: Current time of the event (e.g., "at 8 am", "8am", "2 pm")
   - This is the CURRENT time, not the new time

Examples:
- "move my 1:1 Clavr meeting to 5 pm that day" → {{"title": "1:1 Clavr meeting", "date": "that day", "time": null}}
- "reschedule the team sync to tomorrow" → {{"title": "team sync", "date": null, "time": null}}
- "move my meeting at 8 am to 5 pm" → {{"title": "meeting", "date": null, "time": "8 am"}}
- "move [identified meeting from step_1] to 5 pm" → {{"title": null, "date": null, "time": null}} (placeholder detected)

CRITICAL: 
- Extract the event to FIND, not the new time. The new time comes after "to".
- If the query contains placeholder text like "[identified meeting]" or "[found meeting]", return null for title.

Respond with ONLY valid JSON:
{{
    "title": "title or null",
    "date": "date or null",
    "time": "time or null"
}}"""

            response = llm.invoke([HumanMessage(content=prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            if not isinstance(response_text, str):
                response_text = str(response_text) if response_text else ""
            
            if response_text:
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    result = json.loads(json_match.group(0))
                    criteria['title'] = result.get('title') or None
                    criteria['date'] = result.get('date') or None
                    criteria['time'] = result.get('time') or None
                    
                    logger.info(f"[CAL] Extracted move search criteria: {criteria}")
                    return criteria
        except Exception as e:
            logger.debug(f"[CAL] LLM criteria extraction failed: {e}")
        
        # Fallback to pattern-based extraction
        return self._extract_move_search_criteria_patterns(query)
    
    def _extract_move_search_criteria_patterns(self, query: str) -> Dict[str, Any]:
        """Fallback pattern-based extraction"""
        query_lower = query.lower()
        criteria = {'title': None, 'date': None, 'time': None}
        
        # Extract title using patterns
        patterns = [
            r'move\s+(?:my|the)?\s*(.+?)\s+to',
            r'reschedule\s+(?:my|the)?\s*(.+?)\s+to',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query_lower, re.IGNORECASE)
            if match:
                title_part = match.group(1).strip()
                # Clean up the title
                title_part = re.sub(r'\s+(to|for|at|on|in)\s+.*$', '', title_part, flags=re.IGNORECASE)
                if title_part and len(title_part) > 2:
                    criteria['title'] = ' '.join(word.capitalize() for word in title_part.split())
                    break
        
        # Fallback: try general title extraction
        if not criteria['title']:
            criteria['title'] = self.calendar_parser._extract_event_title(query)
        
        return criteria
    
    def extract_event_title_from_move_query(self, query: str) -> Optional[str]:
        """
        Extract event title from move/reschedule queries (legacy method, kept for compatibility).
        Uses LLM-based extraction via _extract_move_search_criteria.
        """
        criteria = self._extract_move_search_criteria(query)
        return criteria.get('title')
    
    def find_event_by_criteria(
        self,
        tool: BaseTool,
        criteria: Dict[str, Any],
        original_query: str,
        days_ahead: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Find an event using LLM-based semantic matching with multiple criteria (title, date, time).
        
        Args:
            tool: Calendar tool instance
            criteria: Dictionary with 'title', 'date', 'time' keys
            original_query: Original user query for context
            days_ahead: Days to search ahead
            
        Returns:
            Event dictionary or None if not found
        """
        try:
            # Use DEFAULT_DAYS_AHEAD if not specified
            if days_ahead is None:
                days_ahead = DEFAULT_DAYS_AHEAD
            
            # Expand search range if date is specified
            if criteria.get('date'):
                days_ahead = max(days_ahead, 30)  # Search wider range for specific dates
            
            # Fetch events using calendar service
            events = []
            if hasattr(tool, 'calendar_service') and tool.calendar_service:
                # Use calendar service search
                search_query = criteria.get('title') or ''
                if search_query:
                    events = tool.calendar_service.search_events(query=search_query, days_ahead=days_ahead)
                else:
                    # If no title, list events
                    events = tool.calendar_service.list_events(days_ahead=days_ahead)
            elif hasattr(tool, 'google_client') and tool.google_client:
                # Fallback to google client
                search_query = criteria.get('title') or ''
                events = tool.google_client.search_events(query=search_query, days_ahead=days_ahead)
            
            if not events:
                logger.info(f"[CAL] No events found for search criteria: {criteria}")
                return None
            
            # Use LLM-based semantic matching
            best_match = self._semantic_match_event_for_move(events, criteria, original_query)
            if best_match:
                logger.info(f"[CAL] Found matching event using semantic matching: {best_match.get('title', 'Unknown')}")
                return best_match
            
            # Fallback: simple title match
            if criteria.get('title'):
                title_lower = criteria['title'].lower()
                for event in events:
                    event_title = (event.get('title') or event.get('summary') or '').lower()
                    if title_lower in event_title or event_title in title_lower:
                        logger.info(f"[CAL] Found matching event using fallback: {event.get('title', 'Unknown')}")
                        return event
            
            # Last resort: return first result
            if events:
                logger.info(f"[CAL] Using first search result as last resort")
                return events[0]
            
            return None
            
        except Exception as e:
            logger.error(f"[CAL] Error finding event by criteria: {e}", exc_info=True)
            return None
    
    def _find_best_match_in_list(self, events: List[Dict[str, Any]], title: str) -> Optional[Dict[str, Any]]:
        """Find best matching event in a list by title (simple matching)"""
        if not events or not title:
            return events[0] if events else None
        
        title_lower = title.lower()
        best_match = None
        best_score = 0
        
        for event in events:
            event_title = (event.get('title') or event.get('summary') or '').lower()
            # Score based on how much of the title matches
            if title_lower in event_title:
                score = len(title_lower) / len(event_title) if event_title else 0
                if score > best_score:
                    best_score = score
                    best_match = event
            elif event_title in title_lower:
                score = len(event_title) / len(title_lower) if title_lower else 0
                if score > best_score:
                    best_score = score
                    best_match = event
        
        return best_match if best_match else (events[0] if events else None)
    
    def find_event_by_title(self, tool: BaseTool, title: str, days_ahead: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Find an event by title in the calendar (legacy method, kept for compatibility).
        Uses LLM-based semantic matching via find_event_by_criteria.
        """
        criteria = {'title': title, 'date': None, 'time': None}
        return self.find_event_by_criteria(tool, criteria, f"find {title}", days_ahead)
    
    def _semantic_match_event_for_move(
        self,
        events: List[Dict[str, Any]],
        criteria: Dict[str, Any],
        original_query: str
    ) -> Optional[Dict[str, Any]]:
        """Use LLM to semantically match an event against search criteria for move operations"""
        if not self.config:
            return None
        
        try:
            from ....ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage
            import json
            from datetime import datetime, timedelta
            
            llm = LLMFactory.get_llm_for_provider(self.config, temperature=0.7)
            if not llm:
                return None
            
            # Get user timezone
            import pytz
            user_tz_str = get_user_timezone(self.config)
            # Convert timezone string to timezone object
            try:
                user_tz = pytz.timezone(user_tz_str)
            except Exception:
                # Fallback to UTC if timezone conversion fails
                user_tz = pytz.UTC
            
            now_user = datetime.now(user_tz)
            
            # Parse criteria date
            criteria_date_str = None
            if criteria.get('date'):
                date_str = criteria.get('date')
                if date_str.lower() == 'that day':
                    # "that day" means we need to find the event first, then use its date
                    # For now, we'll match any date
                    criteria_date_str = None  # Don't filter by date for "that day"
                else:
                    # Parse relative dates
                    if date_str.lower() == 'tomorrow':
                        criteria_date_parsed = (now_user + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                    elif date_str.lower() == 'today':
                        criteria_date_parsed = now_user.replace(hour=0, minute=0, second=0, microsecond=0)
                    else:
                        # Try parsing absolute dates
                        try:
                            from dateutil import parser as date_parser
                            criteria_date_parsed = date_parser.parse(date_str, default=now_user)
                            criteria_date_parsed = criteria_date_parsed.replace(hour=0, minute=0, second=0, microsecond=0)
                        except:
                            criteria_date_parsed = None
                    
                    if criteria_date_parsed:
                        criteria_date_str = criteria_date_parsed.strftime('%B %d, %Y')
            
            best_match = None
            best_confidence = 0.0
            
            for event in events:
                # Get event details
                event_title = event.get('title', event.get('summary', ''))
                event_start = parse_event_time(event.get('start', {}))
                event_date_str = None
                event_date_short = None
                event_time_str = None
                
                if event_start:
                    if event_start.tzinfo:
                        event_start_user = event_start.astimezone(user_tz)
                    else:
                        event_start_user = user_tz.localize(event_start)
                    
                    event_date_str = event_start_user.strftime('%B %d, %Y')
                    event_date_short = event_start_user.strftime('%B %d')
                    event_time_str = event_start_user.strftime('%I:%M %p')
                
                event_description = event.get('description', '')
                
                prompt = f"""Does this calendar event match the user's search criteria for moving/rescheduling?

User's query: "{original_query}"
Search criteria:
- Title: {criteria.get('title') or 'not specified'}
- Date: {criteria.get('date') or 'not specified'} {f'({criteria_date_str})' if criteria_date_str else ''}
- Time: {criteria.get('time') or 'not specified'}

Event details:
- Title: "{event_title}"
- Date: {event_date_str or 'unknown'} (also: {event_date_short or 'unknown'})
- Time: {event_time_str or 'unknown'}
- Description: "{event_description[:200] if event_description else 'none'}"

CRITICAL PRIORITY RULES:
1. If DATE is specified in criteria → Event MUST match that date (highest priority)
   - "November 20th" matches "November 20, 2025" or "November 20"
   - "tomorrow" matches the day after today
   - "that day" means match the event's current date (any date is acceptable)
   - Date matching is EXACT - if date doesn't match (and not "that day"), confidence should be 0.0
2. If TITLE is specified → Event should match that title (high priority)
   - "1:1 Clavr meeting" matches "1:1 Clavr meeting" or "Clavr meeting"
   - Use semantic understanding, not just exact match
3. If TIME is specified → Event should match that time (medium priority)
   - "8 am" matches "8:00 AM" or "08:00"

Examples:
- Query: "move my 1:1 Clavr meeting to 5 pm that day" → Must match title "1:1 Clavr meeting" (any date for "that day")
- Query: "move meeting tomorrow at 8am to 5pm" → Must match date "tomorrow" AND time "8am" AND title "meeting"

IMPORTANT: If date is specified (and not "that day") and doesn't match, return {{"matches": false, "confidence": 0.0}}

Respond with ONLY valid JSON:
{{
    "matches": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}"""

                response = llm.invoke([HumanMessage(content=prompt)])
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                if not isinstance(response_text, str):
                    response_text = str(response_text) if response_text else ""
                
                if response_text:
                    json_match = re.search(r'\{[\s\S]*\}', response_text)
                    if json_match:
                        result = json.loads(json_match.group(0))
                        if result.get('matches', False):
                            confidence = result.get('confidence', 0)
                            if confidence > best_confidence:
                                best_confidence = confidence
                                best_match = event
                                logger.info(f"[CAL] Semantic match: '{event_title}' → confidence: {confidence:.2f}")
            
            if best_match and best_confidence >= 0.7:
                return best_match
            
        except Exception as e:
            logger.debug(f"[CAL] Semantic matching failed: {e}")
        
        return None
    
    def extract_new_time_from_move_query(self, query: str) -> Optional[str]:
        """
        Extract new time from move/reschedule queries using LLM-based extraction.
        
        Examples:
        - "move to the afternoon" -> "afternoon"
        - "reschedule to 2pm" -> "2pm"
        - "move to tomorrow at 3pm" -> "tomorrow at 3pm"
        - "move to 5 pm that day" -> "5 pm" (preserving "that day" context)
        """
        if not self.config:
            return self._extract_new_time_patterns(query)
        
        try:
            from ....ai.llm_factory import LLMFactory
            from langchain_core.messages import HumanMessage
            import json
            
            llm = LLMFactory.get_llm_for_provider(self.config, temperature=0.7)
            if not llm:
                return self._extract_new_time_patterns(query)
            
            prompt = f"""Extract the NEW time/datetime from this move/reschedule query. The user wants to move an event to a new time.

Query: "{query}"

Extract the NEW time/datetime that comes AFTER "to" or "for":
- "move my meeting to 5 pm" → "5 pm"
- "reschedule to the afternoon" → "afternoon"
- "move to tomorrow at 3pm" → "tomorrow at 3pm"
- "move to 5 pm that day" → "5 pm" (keep "that day" if mentioned, it means same day)
- "move to 5 pm" → "5 pm"

CRITICAL: Extract ONLY the new time/datetime, not the event name or other parts.

Examples:
- "move my 1:1 Clavr meeting to 5 pm that day" → "5 pm that day"
- "reschedule the team sync to tomorrow" → "tomorrow"
- "move morning standup to 2pm" → "2pm"
- "move to the afternoon" → "afternoon"

Respond with ONLY the time/datetime string, or "null" if not found:
"time_string" or null"""

            response = llm.invoke([HumanMessage(content=prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            if not isinstance(response_text, str):
                response_text = str(response_text) if response_text else ""
            
            if response_text:
                # Try to parse JSON response
                json_match = re.search(r'["\'](.+?)["\']|null', response_text)
                if json_match:
                    extracted_time = json_match.group(1) if json_match.group(1) else None
                    if extracted_time and extracted_time.lower() != 'null':
                        logger.info(f"[CAL] Extracted new time using LLM: {extracted_time}")
                        return extracted_time
                
                # If not JSON, try to extract directly
                response_text = response_text.strip().strip('"').strip("'")
                if response_text and response_text.lower() != 'null' and len(response_text) > 1:
                    logger.info(f"[CAL] Extracted new time using LLM (direct): {response_text}")
                    return response_text
        except Exception as e:
            logger.debug(f"[CAL] LLM new time extraction failed: {e}")
        
        # Fallback to pattern-based extraction
        return self._extract_new_time_patterns(query)
    
    def _extract_new_time_patterns(self, query: str) -> Optional[str]:
        """Fallback pattern-based extraction for new time"""
        query_lower = query.lower()
        
        # Patterns to extract new time
        patterns = [
            r'(?:to|for)\s+(?:the\s+)?(afternoon|morning|evening|night)',
            r'(?:to|for)\s+(tomorrow|today)\s+(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)',
            r'(?:to|for)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))',
            r'(?:to|for)\s+(tomorrow|today)',
            r'(?:to|at)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query_lower, re.IGNORECASE)
            if match:
                time_part = ' '.join([g for g in match.groups() if g]).strip()
                if time_part:
                    logger.info(f"[CAL] Extracted new time (pattern): {time_part}")
                    return time_part
        
        # Fallback: try to extract any time expression after "to"
        to_match = re.search(r'\s+to\s+(.+?)(?:\s|$)', query_lower)
        if to_match:
            time_part = to_match.group(1).strip()
            # Remove common words that aren't time
            time_part = re.sub(r'\s+(my|the|a|an|meeting|event|standup|sync)\s+', ' ', time_part, flags=re.IGNORECASE)
            time_part = time_part.strip()
            if time_part and len(time_part) > 2:
                logger.info(f"[CAL] Extracted new time (fallback): {time_part}")
                return time_part
        
        return None
    
    def parse_relative_time_to_iso(self, time_str: str, event: Dict[str, Any]) -> Optional[str]:
        """
        Parse relative time expressions like "afternoon", "morning", "2pm" to ISO format.
        
        Args:
            time_str: Time expression (e.g., "afternoon", "2pm", "tomorrow at 3pm")
            event: Original event (to preserve date if not specified)
            
        Returns:
            ISO format datetime string or None
        """
        if not time_str:
            return None
        
        time_str_lower = time_str.lower().strip()
        
        # Get original event time to preserve date (especially for "that day" references)
        original_start = event.get('start', {}).get('dateTime') or event.get('start', {}).get('date')
        if original_start:
            try:
                if 'T' in original_start:
                    original_dt = datetime.fromisoformat(original_start.replace('Z', '+00:00'))
                else:
                    original_dt = datetime.fromisoformat(original_start)
                    original_dt = original_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            except:
                original_dt = datetime.now()
        else:
            original_dt = datetime.now()
        
        # Handle "that day" - preserve the original event's date
        if 'that day' in time_str_lower:
            # Remove "that day" from time_str and use original date
            time_str_lower = time_str_lower.replace('that day', '').strip()
            # Keep the original date from the event
        
        # Handle time of day keywords - use constants for default times
        if 'afternoon' in time_str_lower:
            # Afternoon: 1pm - 5pm, default to 2pm
            target_dt = original_dt.replace(hour=DEFAULT_AFTERNOON_HOUR, minute=0, second=0, microsecond=0)
        elif 'morning' in time_str_lower:
            # Morning: 8am - 12pm, default to 10am
            target_dt = original_dt.replace(hour=DEFAULT_MORNING_HOUR, minute=0, second=0, microsecond=0)
        elif 'evening' in time_str_lower or 'night' in time_str_lower:
            # Evening/Night: 5pm - 9pm, default to 6pm
            target_dt = original_dt.replace(hour=DEFAULT_EVENING_HOUR, minute=0, second=0, microsecond=0)
        else:
            # Try to parse as specific time using existing parser
            if self.calendar_parser.date_parser:
                try:
                    # Try parsing with flexible date parser
                    parsed = self.calendar_parser.date_parser.parse_date_expression(time_str, prefer_future=True)
                    if parsed and 'start' in parsed:
                        target_dt = parsed['start']
                    else:
                        # Try using _extract_event_time
                        time_iso = self.calendar_parser._extract_event_time(time_str)
                        if time_iso:
                            # Parse the ISO string back to datetime
                            if 'T' in time_iso:
                                target_dt = datetime.fromisoformat(time_iso.replace('Z', '+00:00'))
                            else:
                                target_dt = datetime.fromisoformat(time_iso)
                        else:
                            return None
                except Exception as e:
                    logger.warning(f"[CAL] Failed to parse time '{time_str}': {e}")
                    return None
            else:
                # Fallback: try basic time extraction
                time_iso = self.calendar_parser._extract_event_time(time_str)
                if time_iso:
                    try:
                        if 'T' in time_iso:
                            target_dt = datetime.fromisoformat(time_iso.replace('Z', '+00:00'))
                        else:
                            target_dt = datetime.fromisoformat(time_iso)
                    except:
                        return None
                else:
                    return None
        
        # Format to ISO with timezone
        tz_name = get_user_timezone(self.config)
        user_tz = pytz.timezone(tz_name)
        
        # Ensure datetime has timezone
        if target_dt.tzinfo is None:
            target_dt = user_tz.localize(target_dt)
        else:
            target_dt = target_dt.astimezone(user_tz)
        
        # Format as RFC3339
        return target_dt.isoformat().replace('+00:00', 'Z')
    
    def parse_and_create_calendar_event_with_llm(self, tool: BaseTool, query: str, classification: Dict[str, Any]) -> str:
        """
        Parse calendar event creation using LLM classification with conflict detection.
        
        This method uses the LLM classification to extract entities instead of pattern-based extraction.
        
        Args:
            tool: Calendar tool
            query: User query
            classification: LLM classification result with extracted entities
            
        Returns:
            Calendar event creation result with conflict handling
        """
        logger.info(f"[CAL] Parsing calendar event creation with LLM classification for query: {query}")
        
        # CRITICAL SAFEGUARD: Never create events for list/view queries
        query_lower = query.lower()
        if any(phrase in query_lower for phrase in CALENDAR_QUESTION_PATTERNS):
            logger.error(f"[CAL] CRITICAL BUG FIX: parse_and_create_calendar_event_with_llm called for list query '{query}' - routing to list instead")
            return self.calendar_parser.list_search_handlers.handle_list_action(tool, query)
        
        # Extract event details from LLM classification
        entities = classification.get('entities', {})
        title = entities.get('title') or entities.get('event_title') or self.calendar_parser._extract_event_title(query)
        start_time = entities.get('start_time') or self.calendar_parser._extract_event_time(query)
        duration_str = entities.get('duration')
        duration = None
        if duration_str:
            if isinstance(duration_str, int):
                duration = duration_str
            elif isinstance(duration_str, str):
                duration = self.calendar_parser._extract_event_duration(duration_str)
        if duration is None:
            duration = self.calendar_parser._extract_event_duration(query) or DEFAULT_DURATION_MINUTES
        
        attendees = entities.get('attendees', []) or self.calendar_parser._extract_attendees(query)
        location = entities.get('location') or self.calendar_parser._extract_location(query)
        description = entities.get('description') or self._extract_description(query)
        recurrence = entities.get('recurrence') or self._extract_recurrence(query)
        
        # Handle ordinal patterns if recurrence is present
        if recurrence:
            query_lower = query.lower()
            ordinal_patterns = [
                (r'(first|1st)', 1), (r'(second|2nd)', 2), (r'(third|3rd)', 3),
                (r'(fourth|4th)', 4), (r'(fifth|5th)', 5), (r'(last)', -1)
            ]
            day_patterns = [
                ('monday', 'monday'), ('tuesday', 'tuesday'), ('wednesday', 'wednesday'),
                ('thursday', 'thursday'), ('friday', 'friday'), ('saturday', 'saturday'),
                ('sunday', 'sunday')
            ]
            
            ordinal = None
            day_name = None
            
            for ordinal_pattern, ordinal_val in ordinal_patterns:
                if re.search(ordinal_pattern, query_lower):
                    ordinal = ordinal_val
                    break
            
            for day_pattern, day_val in day_patterns:
                if day_pattern in query_lower:
                    day_name = day_val
                    break
            
            if ordinal is not None and day_name is not None:
                logger.info(f"[CAL] Detected ordinal pattern: {ordinal} {day_name}")
                
                now = datetime.now()
                tz_name = get_user_timezone(self.config)
                user_tz = pytz.timezone(tz_name)
                if now.tzinfo is None:
                    now = user_tz.localize(now)
                else:
                    now = now.astimezone(user_tz)
                
                default_hour = DEFAULT_MORNING_HOUR
                default_minute = 0
                if start_time:
                    try:
                        parsed_start = parse_datetime_with_timezone(start_time, self.config)
                        if parsed_start:
                            default_hour = parsed_start.hour
                            default_minute = parsed_start.minute
                    except:
                        pass
                
                calculated_date = calculate_ordinal_day_date(
                    ordinal=ordinal,
                    day_name=day_name,
                    reference_date=now,
                    config=self.config
                )
                
                if calculated_date:
                    calculated_date = calculated_date.replace(hour=default_hour, minute=default_minute)
                    start_time = calculated_date.isoformat()
                    logger.info(f"[CAL] Calculated smart start date for ordinal pattern: {start_time}")
        
        # Check for conflicts before creating the event
        conflict_result = self.check_calendar_conflicts(tool, start_time, duration)
        
        if conflict_result.get('has_conflict', False):
            # Handle conflict by suggesting alternative times
            return self._handle_calendar_conflict(tool, query, title, start_time, duration, 
                                                attendees, location, description, conflict_result)
        else:
            # No conflict, proceed with normal creation
            conflict_resolution = self._detect_conflict_resolution_strategy(query)
            
            # CRITICAL: Resolve attendee names to email addresses before creating event
            if attendees:
                from ....core.calendar.utils import resolve_attendees_to_emails
                
                # Try to get email_service from tool if available
                email_service = None
                if hasattr(tool, 'calendar_service') and tool.calendar_service:
                    # Check if calendar_service has access to email_service
                    if hasattr(tool, 'email_service') and tool.email_service:
                        email_service = tool.email_service
                    elif hasattr(tool, '_email_service') and tool._email_service:
                        email_service = tool._email_service
                
                resolved_emails, unresolved_names = resolve_attendees_to_emails(
                    attendees,
                    email_service=email_service,
                    config=self.calendar_parser.config
                )
                
                # If we have unresolved names, inform the user
                if unresolved_names:
                    names_str = ', '.join(unresolved_names)
                    if resolved_emails:
                        # Some resolved, some not
                        return f"I found email addresses for some attendees, but I couldn't find email addresses for: {names_str}. Could you provide their email addresses so I can add them to the meeting?"
                    else:
                        # None resolved
                        return f"I couldn't find email addresses for: {names_str}. Could you provide their email addresses so I can book the meeting?"
                
                # Use resolved emails
                attendees = resolved_emails if resolved_emails else None
            
            logger.info(f"[CAL] No conflicts detected, creating event")
            return tool._run(
                action="create",
                title=title,
                start_time=start_time,
                duration_minutes=duration,
                attendees=attendees,
                description=description,
                location=location,
                recurrence=recurrence,
                conflict_resolution=conflict_resolution
            )
    
    def parse_and_create_calendar_event_with_conflict_check(self, tool: BaseTool, query: str) -> str:
        """
        Parse calendar event creation with conflict detection and intelligent suggestions
        
        Args:
            tool: Calendar tool
            query: User query
            
        Returns:
            Calendar event creation result with conflict handling
        """
        logger.info(f"[CAL] Parsing calendar event creation with conflict check for query: {query}")
        
        # CRITICAL SAFEGUARD: Never create events for list/view queries
        query_lower = query.lower()
        if any(phrase in query_lower for phrase in CALENDAR_QUESTION_PATTERNS):
            logger.error(f"[CAL] CRITICAL BUG FIX: parse_and_create_calendar_event_with_conflict_check called for list query '{query}' - routing to list instead")
            return self.calendar_parser.list_search_handlers.handle_list_action(tool, query)
        
        # Extract event details
        title = self.calendar_parser._extract_event_title(query)
        start_time = self.calendar_parser._extract_event_time(query)
        duration = self.calendar_parser._extract_event_duration(query)
        attendees = self.calendar_parser._extract_attendees(query)
        location = self.calendar_parser._extract_location(query)
        description = self._extract_description(query)
        
        # Extract recurrence to check for ordinal patterns
        recurrence = self._extract_recurrence(query)
        
        # CRITICAL: If recurrence contains ordinal pattern (first Friday, last Monday, etc.),
        # calculate the correct start date using smart logic
        if recurrence:
            query_lower = query.lower()
            # Check for ordinal patterns
            ordinal_patterns = [
                (r'(first|1st)', 1), (r'(second|2nd)', 2), (r'(third|3rd)', 3),
                (r'(fourth|4th)', 4), (r'(fifth|5th)', 5), (r'(last)', -1)
            ]
            day_patterns = [
                ('monday', 'monday'), ('tuesday', 'tuesday'), ('wednesday', 'wednesday'),
                ('thursday', 'thursday'), ('friday', 'friday'), ('saturday', 'saturday'),
                ('sunday', 'sunday')
            ]
            
            ordinal = None
            day_name = None
            
            for ordinal_pattern, ordinal_val in ordinal_patterns:
                if re.search(ordinal_pattern, query_lower):
                    ordinal = ordinal_val
                    break
            
            for day_pattern, day_val in day_patterns:
                if day_pattern in query_lower:
                    day_name = day_val
                    break
            
            # If we found an ordinal pattern with a day name, calculate smart start date
            if ordinal is not None and day_name is not None:
                logger.info(f"[CAL] Detected ordinal pattern: {ordinal} {day_name}")
                
                # Calculate the correct start date
                now = datetime.now()
                tz_name = get_user_timezone(self.config)
                user_tz = pytz.timezone(tz_name)
                if now.tzinfo is None:
                    now = user_tz.localize(now)
                else:
                    now = now.astimezone(user_tz)
                
                # Use default time from start_time if available, otherwise use default morning hour
                default_hour = DEFAULT_MORNING_HOUR
                default_minute = 0
                if start_time:
                    try:
                        parsed_start = parse_datetime_with_timezone(start_time, self.config)
                        if parsed_start:
                            default_hour = parsed_start.hour
                            default_minute = parsed_start.minute
                    except:
                        pass
                
                calculated_date = calculate_ordinal_day_date(
                    ordinal=ordinal,
                    day_name=day_name,
                    reference_date=now,
                    config=self.config
                )
                
                if calculated_date:
                    # Preserve the time from start_time if it was specified
                    calculated_date = calculated_date.replace(hour=default_hour, minute=default_minute)
                    start_time = calculated_date.isoformat()
                    logger.info(f"[CAL] Calculated smart start date for ordinal pattern: {start_time}")
        
        logger.info(f"[CAL] CalendarEventHandlers.parse_and_create_calendar_event_with_conflict_check called")
        logger.info(f"[CAL] Query: {query}")
        logger.info(f"[CAL] Tool: {tool}")
        logger.info(f"[CAL] Tool name: {tool.name if hasattr(tool, 'name') else 'No name attribute'}")
        logger.info(f"[CAL] Duration: {duration} (type: {type(duration)})")
        logger.info(f"[CAL] Title: {title}")
        logger.info(f"[CAL] Start time: {start_time}")
        logger.info(f"[CAL] Recurrence: {recurrence}")
        
        # Check for conflicts before creating the event
        conflict_result = self.check_calendar_conflicts(tool, start_time, duration)
        
        if conflict_result.get('has_conflict', False):
            # Handle conflict by suggesting alternative times
            return self._handle_calendar_conflict(tool, query, title, start_time, duration, 
                                                attendees, location, description, conflict_result)
        else:
            # Recurrence already extracted above (needed for ordinal date calculation)
            conflict_resolution = self._detect_conflict_resolution_strategy(query)
            
            # CRITICAL: Resolve attendee names to email addresses before creating event
            # Uses Contact Resolver role: Neo4j graph lookup first, then email search fallback
            if attendees:
                from ....core.calendar.utils import resolve_attendees_to_emails
                
                # Try to get email_service from tool
                email_service = None
                if hasattr(tool, 'email_service'):
                    email_service = tool.email_service
                
                # Try to get graph_manager for Neo4j contact resolution
                graph_manager = None
                if hasattr(tool, 'calendar_service') and tool.calendar_service:
                    # Check if calendar_service has access to hybrid_coordinator/graph
                    if hasattr(tool, 'email_service') and tool.email_service:
                        if hasattr(tool.email_service, 'hybrid_coordinator') and tool.email_service.hybrid_coordinator:
                            if hasattr(tool.email_service.hybrid_coordinator, 'graph_manager'):
                                graph_manager = tool.email_service.hybrid_coordinator.graph_manager
                
                # Get user_id if available
                user_id = None
                if hasattr(tool, '_user_id'):
                    user_id = tool._user_id
                
                resolved_emails, unresolved_names = resolve_attendees_to_emails(
                    attendees,
                    email_service=email_service,
                    config=self.calendar_parser.config,
                    graph_manager=graph_manager,
                    user_id=user_id
                )
                
                # If we have unresolved names, inform the user
                if unresolved_names:
                    names_str = ', '.join(unresolved_names)
                    if resolved_emails:
                        # Some resolved, some not
                        return f"I found email addresses for some attendees, but I couldn't find email addresses for: {names_str}. Could you provide their email addresses so I can add them to the meeting?"
                    else:
                        # None resolved
                        return f"I couldn't find email addresses for: {names_str}. Could you provide their email addresses so I can book the meeting?"
                
                # Use resolved emails
                attendees = resolved_emails if resolved_emails else None
            
            # No conflict, proceed with normal creation
            logger.info(f"[CAL] No conflicts detected, creating event")
            return tool._run(
                action="create",
                title=title,
                start_time=start_time,
                duration_minutes=duration,
                attendees=attendees,
                description=description,
                location=location,
                recurrence=recurrence,
                conflict_resolution=conflict_resolution
            )
    
    def check_calendar_conflicts(self, tool: BaseTool, start_time: str, duration: int) -> Dict[str, Any]:
        """
        Check for calendar conflicts at the proposed time using real calendar data.
        Fetches events for a week to enable intelligent suggestions.
        
        Uses utility functions for consistent timezone handling and conflict detection.
        
        Args:
            tool: Calendar tool instance
            start_time: Proposed start time (ISO format or natural language)
            duration: Event duration in minutes
            
        Returns:
            Dictionary with conflict information:
            - has_conflict: Boolean indicating conflicts exist
            - conflicts: List of conflicting events
            - proposed_start: Parsed start datetime (in configured timezone)
            - proposed_end: Calculated end datetime (in configured timezone)
            - all_events: All events in the week (for suggestions)
        """
        try:
            # Parse start time using utility function (handles timezone automatically)
            start_dt = parse_datetime_with_timezone(start_time, self.config)
            if not start_dt:
                logger.warning(f"Could not parse start_time for conflict check: {start_time}")
                return {'has_conflict': False, 'conflicts': [], 'error': 'Invalid start_time'}
            
            end_dt = start_dt + timedelta(minutes=duration)
            
            # Get day boundaries using utility function
            day_start, day_end = get_day_boundaries(start_dt, self.config)
            
            # Get week boundaries for comprehensive suggestions (7 days ahead)
            week_end = day_start + timedelta(days=7)
            
            # Convert to UTC for Google Calendar API
            from datetime import timezone
            day_start_utc = day_start.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
            week_end_utc = week_end.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
            
            tz_name = get_user_timezone(self.config)
            logger.info(
                f"[CAL] Conflict check: Checking {format_event_time_display(start_dt, include_date=True)} "
                f"({tz_name}) against events from {day_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}"
            )
            
            # Get events from Google Calendar API for the entire week
            all_events = []
            if hasattr(tool, 'google_client') and hasattr(tool.google_client, 'get_events_in_range'):
                all_events = tool.google_client.get_events_in_range(day_start_utc, week_end_utc)
                logger.info(f"[CAL] Retrieved {len(all_events)} events for conflict checking (week range)")
                
                # Use utility function to find conflicts
                conflicts = find_conflicts(start_dt, end_dt, all_events)
            else:
                # Fallback: use tool's internal conflict checking
                if hasattr(tool, '_check_calendar_conflicts'):
                    conflict_result = tool._check_calendar_conflicts(start_time, duration)
                    conflicts = conflict_result.get('conflicts', [])
                    all_events = conflict_result.get('all_events', [])
                else:
                    logger.warning("[CAL] Calendar tool does not have google_client, cannot check conflicts")
                    conflicts = []
            
            return {
                'has_conflict': len(conflicts) > 0,
                'conflicts': conflicts,
                'proposed_start': start_dt,
                'proposed_end': end_dt,
                'all_events': all_events  # Include all events for suggestions
            }
            
        except Exception as e:
            logger.warning(f"Could not check for conflicts: {e}", exc_info=True)
            return {'has_conflict': False, 'conflicts': [], 'error': str(e)}
    
    def _extract_description(self, query: str) -> Optional[str]:
        """
        Extract event description from query.
        
        Args:
            query: User query
            
        Returns:
            Description string or None if not found
        """
        # Pattern 1: "description: X" or "details: X"
        match = re.search(r'(?:description|details|about|notes?):\s*([^\n,]+)', query, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Pattern 2: Quoted description
        match = re.search(r'["\']([^"\']+)["\']', query)
        if match:
            # Check if it's not a title (titles usually come before time/location)
            desc = match.group(1).strip()
            if len(desc) > 20:  # Likely a description if longer
                return desc
        
        return None
    
    def _extract_recurrence(self, query: str) -> Optional[str]:
        """
        Extract recurrence pattern from query using RecurrenceParser.
        
        Args:
            query: User query
            
        Returns:
            RRULE string or None if no recurrence found
        """
        try:
            from ....core.calendar.recurrence_parser import RecurrenceParser
            parser = RecurrenceParser()
            result = parser.parse(query)
            if result and result.get('recurrence'):
                return result['recurrence']
        except Exception as e:
            logger.debug(f"Failed to extract recurrence: {e}")
        
        return None
    
    def _handle_calendar_conflict(self, tool: BaseTool, query: str, title: str, 
                                 start_time: str, duration: int, attendees: List[str],
                                 location: Optional[str], description: Optional[str],
                                 conflict_result: Dict[str, Any]) -> str:
        """
        Handle calendar conflicts by suggesting alternative times.
        
        Args:
            tool: Calendar tool
            query: Original user query
            title: Event title
            start_time: Proposed start time
            duration: Event duration in minutes
            attendees: List of attendees
            location: Event location
            description: Event description
            conflict_result: Conflict detection result
            
        Returns:
            Conflict resolution message or alternative time suggestion
        """
        conflicts = conflict_result.get('conflicts', [])
        if not conflicts:
            # No conflicts, proceed with creation
            return tool._run(
                action="create",
                title=title,
                start_time=start_time,
                duration_minutes=duration,
                attendees=attendees,
                description=description,
                location=location
            )
        
        # Get intelligent suggestions using enhanced suggestion system
        suggestions = []
        all_events = conflict_result.get('all_events', [])
        proposed_start = conflict_result.get('proposed_start')
        
        if proposed_start and all_events:
            try:
                # Use CalendarActions suggestion system if available
                if hasattr(tool, 'actions') and hasattr(tool.actions, '_suggest_alternative_times'):
                    suggestions = tool.actions._suggest_alternative_times(
                        proposed_start, duration, all_events, max_suggestions=5
                    )
                else:
                    # Fallback: use calendar service find_free_time
                    if hasattr(tool, 'calendar_service') and tool.calendar_service:
                        try:
                            from datetime import timezone
                            week_start_utc = proposed_start.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
                            week_end_dt = proposed_start + timedelta(days=7)
                            week_end_utc = week_end_dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
                            
                            free_slots = tool.calendar_service.find_free_time(
                                duration_minutes=duration,
                                start_date=week_start_utc,
                                end_date=week_end_utc,
                                working_hours_only=True,
                                max_suggestions=5
                            )
                            
                            for slot in free_slots[:5]:
                                suggestions.append({
                                    'start': slot.get('start', ''),
                                    'display': slot.get('display', slot.get('start', ''))
                                })
                        except Exception as e:
                            logger.warning(f"Failed to get free time suggestions: {e}")
            except Exception as e:
                logger.warning(f"Failed to generate suggestions: {e}")
        
        # Generate intelligent conflict message using LLM if available
        if self.llm_client:
            try:
                conflict_message = self._generate_intelligent_conflict_message(
                    query, title, conflict_result, conflicts, suggestions
                )
                if conflict_message:
                    return conflict_message
            except Exception as e:
                logger.warning(f"Failed to generate intelligent conflict message: {e}")
        
        # Fallback: format conflict message manually
        conflict_msg = f"I found a scheduling conflict for '{title}' at {format_event_time_display(conflict_result['proposed_start'], include_date=True)}.\n\n"
        conflict_msg += f"You have {len(conflicts)} conflicting event(s):\n"
        for i, conflict in enumerate(conflicts[:3], 1):  # Show max 3 conflicts
            conflict_title = conflict.get('title') or conflict.get('summary', 'Unknown')
            conflict_start = conflict.get('start', {}).get('dateTime') or conflict.get('start', {}).get('date')
            if conflict_start:
                try:
                    if 'T' in conflict_start:
                        conflict_dt = datetime.fromisoformat(conflict_start.replace('Z', '+00:00'))
                    else:
                        conflict_dt = datetime.fromisoformat(conflict_start)
                    conflict_msg += f"{i}. {conflict_title} at {format_event_time_display(conflict_dt)}\n"
                except:
                    conflict_msg += f"{i}. {conflict_title}\n"
            else:
                conflict_msg += f"{i}. {conflict_title}\n"
        
        # Add suggestions
        if suggestions:
            conflict_msg += "\n**Suggested alternative times:**\n"
            for i, suggestion in enumerate(suggestions[:5], 1):
                display = suggestion.get('display', suggestion.get('start', ''))
                conflict_msg += f"{i}. {display}\n"
            conflict_msg += "\nWould you like me to schedule it at one of these times instead?"
        else:
            conflict_msg += "\nI couldn't find alternative times automatically. Would you like to try a different time?"
        
        return conflict_msg
    
    def _generate_intelligent_conflict_message(
        self,
        query: str,
        title: str,
        conflict_result: Dict[str, Any],
        conflicts: List[Dict[str, Any]],
        suggestions: List[Dict[str, str]]
    ) -> Optional[str]:
        """
        Generate intelligent conflict message using LLM.
        
        Args:
            query: Original user query
            title: Event title
            conflict_result: Conflict detection result
            conflicts: List of conflicting events
            suggestions: List of suggested alternative times
            
        Returns:
            Intelligent conflict message or None if generation fails
        """
        if not self.llm_client:
            return None
        
        try:
            from langchain_core.messages import HumanMessage
            
            # Format conflicts for prompt
            conflicts_text = ""
            for i, conflict in enumerate(conflicts[:3], 1):
                conflict_title = conflict.get('title') or conflict.get('summary', 'Unknown')
                conflict_start = conflict.get('start', {}).get('dateTime') or conflict.get('start', {}).get('date')
                if conflict_start:
                    try:
                        if 'T' in conflict_start:
                            conflict_dt = datetime.fromisoformat(conflict_start.replace('Z', '+00:00'))
                        else:
                            conflict_dt = datetime.fromisoformat(conflict_start)
                        conflicts_text += f"{i}. {conflict_title} at {format_event_time_display(conflict_dt)}\n"
                    except:
                        conflicts_text += f"{i}. {conflict_title}\n"
                else:
                    conflicts_text += f"{i}. {conflict_title}\n"
            
            # Format suggestions for prompt
            suggestions_text = ""
            for i, suggestion in enumerate(suggestions[:5], 1):
                display = suggestion.get('display', suggestion.get('start', ''))
                suggestions_text += f"{i}. {display}\n"
            
            proposed_time = format_event_time_display(conflict_result['proposed_start'], include_date=True)
            
            prompt = f"""You are Clavr, a friendly and helpful calendar assistant. The user tried to schedule an event but there's a conflict.

User's request: "{query}"
Event title: "{title}"
Proposed time: {proposed_time}
Number of conflicts: {len(conflicts)}

Conflicting events:
{conflicts_text}

Suggested alternative times:
{suggestions_text}

Generate a natural, helpful response that:
1. Acknowledges the conflict in a friendly way
2. Briefly mentions the conflicting events (1-2 sentences max)
3. Presents the suggested alternative times clearly
4. Asks if they'd like to schedule at one of the suggested times
5. Sounds conversational and helpful, not robotic

Guidelines:
- Use second person ("you", "your")
- Be concise but informative
- Don't overwhelm with too many details
- Sound like you're helping a friend, not a robot
- If suggestions span multiple days, mention that

Do NOT include:
- Technical tags like [CONFLICT], [ERROR]
- Excessive formatting
- Calendar IDs or technical details

Response:"""
            
            response = self.llm_client.invoke([HumanMessage(content=prompt)])
            if hasattr(response, 'content'):
                return response.content.strip()
        except Exception as e:
            logger.warning(f"Failed to generate intelligent conflict message: {e}")
        
        return None
    
    def _detect_conflict_resolution_strategy(self, query: str) -> str:
        """
        Detect conflict resolution strategy from query.
        
        Args:
            query: User query
            
        Returns:
            Conflict resolution strategy: "override", "skip", or "ask"
        """
        query_lower = query.lower()
        
        if any(word in query_lower for word in ["override", "force", "anyway", "still"]):
            return "override"
        elif any(word in query_lower for word in ["skip", "cancel", "don't"]):
            return "skip"
        else:
            return "ask"  # Default: ask user
    
    def _generate_conversational_calendar_action_response(self, result: str, query: str, action: str) -> Optional[str]:
        """
        Generate conversational response for calendar actions using LLM.
        
        Args:
            result: Raw tool result
            query: Original user query
            action: Action type (create, update, delete, move)
            
        Returns:
            Conversational response or None if generation fails
        """
        if not self.llm_client:
            return None
        
        try:
            from langchain_core.messages import HumanMessage
            
            prompt = f"""You are Clavr, a friendly calendar assistant. Convert this technical calendar operation result into a natural, conversational response.

User's request: "{query}"
Action performed: {action}
Raw result: {result[:500]}

Generate a friendly, natural response that:
1. Confirms what was done
2. Uses conversational language (no technical tags or brackets)
3. Is concise but informative
4. Matches the user's tone (casual if they were casual, formal if formal)

Response:"""
            
            response = self.llm_client.invoke([HumanMessage(content=prompt)])
            if hasattr(response, 'content'):
                return response.content.strip()
        except Exception as e:
            logger.warning(f"Failed to generate conversational response: {e}")
        
        return None
