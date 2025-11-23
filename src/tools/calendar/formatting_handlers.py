"""
Calendar Formatting Handlers

Handles all formatting and display logic for calendar tool responses.
This module centralizes formatting logic to keep the main CalendarTool class clean.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
import re

from ...utils.logger import setup_logger
from ...ai.prompts import CALENDAR_CONVERSATIONAL_EMPTY, CALENDAR_CONVERSATIONAL_LIST
from ...ai.llm_factory import LLMFactory
from ...utils.config import Config
from langchain_core.messages import HumanMessage, SystemMessage
from ...ai.prompts import get_agent_system_prompt
from ...core.calendar.utils import get_user_timezone

logger = setup_logger(__name__)


class CalendarFormattingHandlers:
    """
    Handles formatting and display logic for calendar responses.
    
    This class centralizes all formatting methods to improve maintainability
    and keep the main CalendarTool class focused on orchestration.
    """
    
    def __init__(self, calendar_tool):
        """
        Initialize formatting handlers.
        
        Args:
            calendar_tool: Parent CalendarTool instance for accessing config, etc.
        """
        self.calendar_tool = calendar_tool
        self.config = calendar_tool.config if hasattr(calendar_tool, 'config') else None
    
    def format_event_list(
        self, 
        events: List[Dict[str, Any]], 
        title: str, 
        query: str = ""
    ) -> str:
        """
        Format list of events for display with conversational response.
        
        Args:
            events: List of event dictionaries
            title: Title/header for the list
            query: Original query (for conversational context)
            
        Returns:
            Formatted string representation of events
        """
        if not events:
            # Even for no events, make it conversational
            if query:
                try:
                    # Use self.config if available, otherwise fall back to Config.from_env()
                    config = self.config if self.config else Config.from_env()
                    llm = LLMFactory.get_llm_for_provider(config, temperature=0.7)
                    
                    if llm:
                        # Use centralized prompt with AGENT_SYSTEM_PROMPT
                        prompt = CALENDAR_CONVERSATIONAL_EMPTY.format(query=query)
                        
                        messages = [
                            SystemMessage(content=get_agent_system_prompt()),
                            HumanMessage(content=prompt)
                        ]
                        response = llm.invoke(messages)
                        response_text = response.content if hasattr(response, 'content') else str(response)
                        
                        if not isinstance(response_text, str):
                            response_text = str(response_text) if response_text else ""
                        
                        if response_text and len(response_text.strip()) > 0:
                            return response_text.strip()
                except Exception as e:
                    logger.debug(f"[CAL] Failed to generate conversational 'no events' response: {e}")
            
            return f"No events found. Your calendar is clear!"
        
        # ALWAYS try conversational response first (even without query)
        conversational = self._generate_conversational_list_response(
            events, 
            query or "list events", 
            title
        )
        if conversational:
            return conversational
        
        # If conversational generation failed, use a natural fallback (NOT robotic)
        # Build a natural sentence instead of bullet points
        event_descriptions = []
        for event in events[:10]:  # Limit to first 10
            summary = event.get('summary') or event.get('title', 'No Title')
            
            # Extract start time
            start = self._extract_start_time_from_event(event)
            if isinstance(start, datetime):
                time_str = start.strftime('%I:%M %p').lstrip('0')
            elif isinstance(start, dict):
                date_time = start.get('dateTime') or start.get('date')
                if date_time:
                    try:
                        start_dt = datetime.fromisoformat(str(date_time).replace('Z', '+00:00'))
                        time_str = start_dt.strftime('%I:%M %p').lstrip('0')
                    except:
                        time_str = str(date_time)
                else:
                    time_str = 'Unknown'
            else:
                time_str = str(start) if start else 'Unknown'
            
            event_descriptions.append(f"**{summary}** at {time_str}")
        
        # Create natural sentence format
        if len(event_descriptions) == 1:
            return f"You've got {event_descriptions[0]}."
        elif len(event_descriptions) == 2:
            return f"You've got {event_descriptions[0]} and {event_descriptions[1]}."
        else:
            first_few = ", ".join(event_descriptions[:-1])
            last_one = event_descriptions[-1]
            if len(events) > 10:
                return f"You've got {first_few}, and {last_one}. That's {len(events)} events total."
            else:
                return f"You've got {first_few}, and {last_one}."
    
    def format_free_time_slots(self, slots: List[Dict[str, Any]]) -> str:
        """
        Format free time slots for display.
        
        Args:
            slots: List of free time slot dictionaries
            
        Returns:
            Formatted string representation of free time slots
        """
        if not slots:
            return "**Free Time Slots**\n\nNo free time slots found in the specified range."
        
        output = f"**Free Time Slots** ({len(slots)} available)\n\n"
        for i, slot in enumerate(slots, 1):
            start = slot.get('start', 'Unknown')
            end = slot.get('end', 'Unknown')
            duration = slot.get('duration_minutes', 0)
            
            output += f"{i}. {start} - {end} ({duration} minutes)\n"
        
        return output
    
    def format_conflicts(
        self, 
        conflicts: List[Dict[str, Any]], 
        requested_time: str
    ) -> str:
        """
        Format conflict information.
        
        Args:
            conflicts: List of conflicting event dictionaries
            requested_time: The requested time that conflicts
            
        Returns:
            Formatted string representation of conflicts
        """
        output = f"**Conflicts detected at {requested_time}**\n\n"
        output += f"Found {len(conflicts)} conflicting event(s):\n\n"
        
        for conflict in conflicts:
            summary = conflict.get('summary', 'Untitled Event')
            start = conflict.get('start_time', 'Unknown')
            end = conflict.get('end_time', 'Unknown')
            
            output += f"- **{summary}**\n"
            output += f"  Time: {start} - {end}\n"
        
        return output
    
    def _extract_start_time_from_event(self, event: Dict[str, Any]):
        """
        Extract start time from event dictionary.
        
        Args:
            event: Event dictionary
            
        Returns:
            Start time (datetime, dict, or None)
        """
        if hasattr(self.calendar_tool, '_extract_start_time_from_event'):
            return self.calendar_tool._extract_start_time_from_event(event)
        
        # Fallback implementation
        start = event.get('start', {})
        if isinstance(start, datetime):
            return start
        return start
    
    def _generate_conversational_list_response(
        self,
        events: List[Dict[str, Any]],
        query: str,
        context_title: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate a natural, conversational response for event lists using LLM.
        
        Returns None if LLM generation fails (caller should use fallback).
        
        Args:
            events: List of events
            query: Original query
            context_title: Optional context title
            
        Returns:
            Conversational response string or None
        """
        try:
            # Use self.config if available, otherwise fall back to Config.from_env()
            config = self.config if self.config else Config.from_env()
            llm = LLMFactory.get_llm_for_provider(config, temperature=0.7)
            if not llm:
                return None
            
            # Get current time for context (CRITICAL for past/future tense)
            from ...core.calendar.utils import get_user_timezone
            import pytz
            
            user_tz_str = get_user_timezone()
            # Convert timezone string to timezone object
            try:
                user_tz = pytz.timezone(user_tz_str)
            except Exception:
                # Fallback to UTC if timezone conversion fails
                user_tz = pytz.UTC
            
            now = datetime.now(user_tz)
            current_date = now.strftime('%A, %B %d, %Y')
            current_time = now.strftime('%I:%M %p').lstrip('0')  # Include current time for past/future detection
            
            # Prepare event data for LLM with time awareness
            event_summaries = []
            for event in events[:10]:  # Limit to first 10 for context
                summary = event.get('summary') or event.get('title', 'No Title')
                start = self._extract_start_time_from_event(event)
                
                # Parse event start time
                event_start_dt = None
                if isinstance(start, datetime):
                    event_start_dt = start
                    if event_start_dt.tzinfo is None:
                        event_start_dt = user_tz.localize(event_start_dt)
                    else:
                        event_start_dt = event_start_dt.astimezone(user_tz)
                    time_str = event_start_dt.strftime('%I:%M %p').lstrip('0')
                    date_str = event_start_dt.strftime('%A, %B %d')
                elif isinstance(start, dict):
                    date_time = start.get('dateTime') or start.get('date')
                    if date_time:
                        try:
                            event_start_dt = datetime.fromisoformat(str(date_time).replace('Z', '+00:00'))
                            if event_start_dt.tzinfo is None:
                                event_start_dt = user_tz.localize(event_start_dt)
                            else:
                                event_start_dt = event_start_dt.astimezone(user_tz)
                            time_str = event_start_dt.strftime('%I:%M %p').lstrip('0')
                            date_str = event_start_dt.strftime('%A, %B %d')
                        except:
                            time_str = str(date_time)
                            date_str = ''
                            event_start_dt = None
                    else:
                        time_str = 'Unknown'
                        date_str = ''
                        event_start_dt = None
                else:
                    time_str = str(start) if start else 'Unknown'
                    date_str = ''
                    event_start_dt = None
                
                # Determine if event is past or future
                is_past = False
                if event_start_dt:
                    is_past = event_start_dt < now
                
                event_summaries.append({
                    'title': summary,
                    'time': time_str,
                    'date': date_str,
                    'is_past': is_past  # CRITICAL: Include past/future flag for LLM
                })
            
            # Use centralized prompt with get_agent_system_prompt() for consistency
            prompt = CALENDAR_CONVERSATIONAL_LIST.format(
                query=query,
                current_date=current_date,
                current_time=current_time,  # CRITICAL: Include current time for past/future detection
                event_count=len(events),
                events_json=json.dumps(event_summaries, indent=2)
            )

            # Use SystemMessage with get_agent_system_prompt() for better conversational responses
            messages = [
                SystemMessage(content=get_agent_system_prompt()),
                HumanMessage(content=prompt)
            ]
            response = llm.invoke(messages)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            if not isinstance(response_text, str):
                response_text = str(response_text) if response_text else ""
            
            if response_text and len(response_text.strip()) > 0:
                # Check if response is too robotic (contains patterns we want to avoid)
                robotic_patterns = [
                    r'You have \d+ events?:',
                    r'You have \d+ event\(s\):',
                    r'^\*\*.*\*\*\s*\(\d+ events?\)',
                    r'^\d+\.\s',  # Numbered list at start
                    r'^\s*[\*\-]\s',  # Bullet points at start
                    r'^\s*•\s',  # Bullet points with bullet character
                ]
                
                is_robotic = any(re.search(pattern, response_text, re.MULTILINE | re.IGNORECASE) for pattern in robotic_patterns)
                
                # CRITICAL: Remove quotes from event titles even if response is otherwise good
                # Check for quoted event titles
                quoted_title_patterns = [
                    r'["\']([^"\']+)["\']',  # Matches "Title" or 'Title'
                    r'"([^"]+)"',  # Matches "Title"
                    r"'([^']+)'",  # Matches 'Title'
                ]
                
                has_quoted_titles = any(re.search(pattern, response_text) for pattern in quoted_title_patterns)
                
                # Clean up quotes if present
                cleaned_response = response_text
                if has_quoted_titles:
                    logger.warning(f"[CAL] LLM response contained quoted event titles, cleaning up")
                    # Remove quotes from event titles - be aggressive about this
                    for pattern in quoted_title_patterns:
                        matches = re.findall(pattern, cleaned_response)
                        for match in matches:
                            content = match.strip('"\'')
                            # If it looks like an event title (reasonable length, not punctuation)
                            if len(content) > 3 and not content.startswith(('(', '[', '{')):
                                # Check context to see if it's likely an event title
                                context = cleaned_response[max(0, cleaned_response.find(match) - 50):min(len(cleaned_response), cleaned_response.find(match) + len(match) + 50)]
                                context_lower = context.lower()
                                # If near event-related words, it's likely an event title
                                if any(word in context_lower for word in ['event', 'meeting', 'have', 'had', 'you', 'your', 'calendar', 'schedule', 'at', 'am', 'pm']):
                                    # Replace quoted title with bold (remove quotes, add bold if not already)
                                    if f"**{content}**" not in cleaned_response:
                                        cleaned_response = cleaned_response.replace(match, f"**{content}**", 1)
                                    else:
                                        cleaned_response = cleaned_response.replace(match, content, 1)
                                    logger.debug(f"[CAL] Removed quotes from event title: '{match}' → **{content}**")
                    response_text = cleaned_response
                
                if not is_robotic and not has_quoted_titles:
                    logger.info(f"[CAL] Generated conversational list response")
                    return response_text.strip()
                elif has_quoted_titles:
                    # Even if response has quoted titles, use cleaned version
                    logger.info(f"[CAL] Generated conversational list response (cleaned quotes)")
                    return response_text.strip()
                else:
                    logger.warning(f"[CAL] LLM response was too robotic: {response_text[:100]}")
                    # Don't return None - let it fall through to natural fallback
                    return None
            
        except Exception as e:
            logger.warning(f"[CAL] Failed to generate conversational list response: {e}")
            return None
        
        return None

