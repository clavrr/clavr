"""
Timezone Agent

Handles timezone-related queries such as:
- Current time in a location
- Time zone differences
- Time conversions between zones
"""
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import pytz

from ..base import BaseAgent
from ...integrations.google_maps.service import MapsService
from ...utils.logger import setup_logger
from .constants import (
    LOCATION_PATTERNS, TIME_DIFF_BETWEEN_AND,
    TIME_CONVERT_PATTERNS, TIME_12H, TIME_24H,
    TIME_SIMPLE_INT, CLEAN_PUNCTUATION, CLEAN_LEADING_THE
)

logger = setup_logger(__name__)


class TimezoneAgent(BaseAgent):
    """Agent for handling timezone and time-related queries."""
    
    def __init__(self, config: Dict[str, Any], tools: list, domain_context: Optional[Any] = None, event_emitter: Any = None):
        super().__init__(config, tools, domain_context, event_emitter)
        self._maps_service = None
    
    def _get_maps_service(self) -> MapsService:
        """Lazy initialization of MapsService."""
        if not self._maps_service:
            self._maps_service = MapsService(self.config)
        return self._maps_service
    
    async def run(self, query: str) -> str:
        """
        Execute timezone queries.
        """
        logger.info(f"[{self.name}] Processing query: {query}")
        
        query_lower = query.lower()
        
        # Determine intent
        if any(w in query_lower for w in ["what time", "current time", "time in", "time is it"]):
            return await self._handle_current_time(query)
        elif any(w in query_lower for w in ["time difference", "hours ahead", "hours behind", "difference between"]):
            return await self._handle_time_difference(query)
        elif any(w in query_lower for w in ["convert", "when it's", "when its"]):
            return await self._handle_time_conversion(query)
        else:
            # Default to current time lookup
            return await self._handle_current_time(query)
    
    async def _handle_current_time(self, query: str) -> str:
        """Get current time in a location."""
        try:
            maps_service = self._get_maps_service()
            
            # Extract location from query use constant patterns
            location = None
            for pattern in LOCATION_PATTERNS:
                match = re.search(pattern, query, re.IGNORECASE)
                if match:
                    location = match.group(1).strip()
                    break
            
            if not location:
                # Try to find any city/country name
                return "I need a location to check the time. Try: 'What time is it in Tokyo?'"
            
            # Clean up location
            location = re.sub(CLEAN_PUNCTUATION, '', location).strip()
            location = re.sub(CLEAN_LEADING_THE, '', location, flags=re.IGNORECASE).strip()
            
            # Get timezone directly for the location (service handles geocoding internally)
            tz_info = await maps_service.get_timezone_async(location)
            
            if not tz_info:
                return f"I couldn't determine the timezone for {location}."
            
            timezone_id = tz_info.get('timeZoneId', 'UTC')
            timezone_name = tz_info.get('timeZoneName', timezone_id)
            
            # Get current time in that timezone
            try:
                tz = pytz.timezone(timezone_id)
                local_time = datetime.now(tz)
                
                # Format nicely
                time_str = local_time.strftime("%I:%M %p")
                date_str = local_time.strftime("%A, %B %d, %Y")
                
                # Get offset from UTC
                offset = local_time.strftime("%z")
                offset_formatted = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
                
                return f"🕐 **Current time in {location.title()}:**\n\n" \
                       f"**{time_str}**\n" \
                       f"{date_str}\n\n" \
                       f"- Timezone: {timezone_name}\n" \
                       f"- UTC offset: {offset_formatted}"
                       
            except Exception as e:
                logger.warning(f"Pytz lookup failed for {timezone_id}: {e}")
                return f"The timezone for {location} is {timezone_name}, but I couldn't calculate the exact current time."
                
        except Exception as e:
            logger.error(f"[{self.name}] Current time lookup failed: {e}")
            return f"I encountered an error checking the time: {str(e)}"
    
    async def _handle_time_difference(self, query: str) -> str:
        """Calculate time difference between two locations."""
        try:
            maps_service = self._get_maps_service()
            
            # Extract two locations
            between_match = re.search(TIME_DIFF_BETWEEN_AND, query, re.IGNORECASE)
            
            if not between_match:
                return "I need two locations to calculate time difference. Try: 'What's the time difference between New York and London?'"
            
            location1 = between_match.group(1).strip()
            location2 = between_match.group(2).strip()
            location2 = re.sub(CLEAN_PUNCTUATION, '', location2).strip()
            
            # Get timezones for both locations (service handles geocoding internally)
            tz_info1 = await maps_service.get_timezone_async(location1)
            tz_info2 = await maps_service.get_timezone_async(location2)
            
            if not tz_info1:
                return f"I couldn't find the location '{location1}'."
            if not tz_info2:
                return f"I couldn't find the location '{location2}'."
            
            # Calculate difference
            tz1 = pytz.timezone(tz_info1['timeZoneId'])
            tz2 = pytz.timezone(tz_info2['timeZoneId'])
            
            now = datetime.now(pytz.UTC)
            time1 = now.astimezone(tz1)
            time2 = now.astimezone(tz2)
            
            # Get UTC offsets in hours
            offset1 = time1.utcoffset().total_seconds() / 3600
            offset2 = time2.utcoffset().total_seconds() / 3600
            
            diff_hours = offset2 - offset1
            
            if diff_hours > 0:
                diff_text = f"{location2} is **{abs(diff_hours):.1f} hours ahead** of {location1}"
            elif diff_hours < 0:
                diff_text = f"{location2} is **{abs(diff_hours):.1f} hours behind** {location1}"
            else:
                diff_text = f"{location1} and {location2} are in the **same timezone**"
            
            return f"🌍 **Time Difference:**\n\n" \
                   f"{diff_text}\n\n" \
                   f"- {location1}: {time1.strftime('%I:%M %p')} ({tz_info1['timeZoneName']})\n" \
                   f"- {location2}: {time2.strftime('%I:%M %p')} ({tz_info2['timeZoneName']})"
                   
        except Exception as e:
            logger.error(f"[{self.name}] Time difference calculation failed: {e}")
            return f"I encountered an error calculating the time difference: {str(e)}"
    
    async def _handle_time_conversion(self, query: str) -> str:
        """Convert a specific time between timezones."""
        try:
            maps_service = self._get_maps_service()
            
            # Use constant patterns
            time_str = None
            source_location = None
            target_location = None
            
            for pattern in TIME_CONVERT_PATTERNS:
                match = re.search(pattern, query, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    if len(groups) == 3:
                        # Check which pattern matched by structure (simple heuristic based on previous logic)
                        if 'what time' in pattern and 'when' in pattern:
                            # First pattern: target, time, source
                            target_location = groups[0].strip()
                            time_str = groups[1].strip()
                            source_location = groups[2].strip()
                        elif pattern.startswith(r"when"):
                            # Second pattern: time, source, target
                            # Note: regex string in code doesn't start with ^, but constant definition is the same string.
                            # Actually, I should check the constant name or index, which is brittle.
                            # Better: Re-implement the logic using the list index or specific checks.
                            # Since I extracted list into `TIME_CONVERT_PATTERNS`, I can just iterate.
                            # But wait, logic depends on WHICH pattern matched.
                            # I will infer based on groups or just rely on the order in the constant list if I import it in same order.
                            # To be safe, I'll check index.
                            idx = TIME_CONVERT_PATTERNS.index(pattern)
                            if idx == 0: # target, time, source
                                target_location = groups[0].strip()
                                time_str = groups[1].strip()
                                source_location = groups[2].strip()
                            elif idx == 1: # time, source, target
                                time_str = groups[0].strip()
                                source_location = groups[1].strip()
                                target_location = groups[2].strip()
                            else: # time, source, target for others
                                time_str = groups[0].strip()
                                source_location = groups[1].strip()
                                target_location = groups[2].strip()
                    break
            
            if not all([time_str, source_location, target_location]):
                return "I need a time and two locations. Try: 'What time is it in Tokyo when it's 3pm in New York?'"
            
            # Clean up locations
            source_location = re.sub(CLEAN_PUNCTUATION, '', source_location).strip()
            target_location = re.sub(CLEAN_PUNCTUATION, '', target_location).strip()
            
            # Parse the time string
            parsed_time = self._parse_time_string(time_str)
            if not parsed_time:
                return f"I couldn't understand the time '{time_str}'. Please use formats like '3pm', '15:00', or '3:30 PM'."
            
            hour, minute = parsed_time
            
            # Get timezones for both locations
            tz_info_source = await maps_service.get_timezone_async(source_location)
            tz_info_target = await maps_service.get_timezone_async(target_location)
            
            if not tz_info_source:
                return f"I couldn't find the location '{source_location}'."
            if not tz_info_target:
                return f"I couldn't find the location '{target_location}'."
            
            source_tz = pytz.timezone(tz_info_source['timeZoneId'])
            target_tz = pytz.timezone(tz_info_target['timeZoneId'])
            
            # Create datetime in source timezone (use today's date)
            today = datetime.now(source_tz).date()
            source_dt = source_tz.localize(datetime(today.year, today.month, today.day, hour, minute))
            
            # Convert to target timezone
            target_dt = source_dt.astimezone(target_tz)
            
            # Format output
            source_time_str = source_dt.strftime("%I:%M %p")
            target_time_str = target_dt.strftime("%I:%M %p")
            
            # Check if it's a different day
            day_diff = ""
            if target_dt.date() > source_dt.date():
                day_diff = " (next day)"
            elif target_dt.date() < source_dt.date():
                day_diff = " (previous day)"
            
            return f"🕐 **Time Conversion:**\n\n" \
                   f"When it's **{source_time_str}** in {source_location.title()},\n" \
                   f"it's **{target_time_str}**{day_diff} in {target_location.title()}.\n\n" \
                   f"- {source_location.title()}: {tz_info_source['timeZoneName']}\n" \
                   f"- {target_location.title()}: {tz_info_target['timeZoneName']}"
                   
        except Exception as e:
            logger.error(f"[{self.name}] Time conversion failed: {e}")
            return f"I encountered an error with time conversion: {str(e)}"
    
    def _parse_time_string(self, time_str: str) -> Optional[tuple]:
        """
        Parse a time string and return (hour, minute) in 24-hour format.
        Supports: "3pm", "3:30pm", "15:00", "3:30 PM", etc.
        """
        time_str = time_str.strip().lower()
        
        # Pattern for 12-hour format with AM/PM
        match_12h = re.match(TIME_12H, time_str)
        if match_12h:
            hour = int(match_12h.group(1))
            minute = int(match_12h.group(2)) if match_12h.group(2) else 0
            period = match_12h.group(3)
            
            if period == 'pm' and hour != 12:
                hour += 12
            elif period == 'am' and hour == 12:
                hour = 0
            
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return (hour, minute)
        
        # Pattern for 24-hour format
        match_24h = re.match(TIME_24H, time_str)
        if match_24h:
            hour = int(match_24h.group(1))
            minute = int(match_24h.group(2))
            
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return (hour, minute)
        
        # Just a number (assume PM if between 1-11)
        match_simple = re.match(TIME_SIMPLE_INT, time_str)
        if match_simple:
            hour = int(match_simple.group(1))
            if 1 <= hour <= 11:
                hour += 12  # Assume PM
            if 0 <= hour <= 23:
                return (hour, 0)
        
        return None
