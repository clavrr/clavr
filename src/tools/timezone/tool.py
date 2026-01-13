"""
Timezone Tool
"""
from typing import Optional, Any
from langchain.tools import BaseTool
from pydantic import Field
import asyncio
from datetime import datetime
import pytz

from ...utils.logger import setup_logger
from ...utils.config import Config

logger = setup_logger(__name__)

class TimezoneTool(BaseTool):
    """Tool for timezone checks and conversions."""
    name: str = "timezone"
    description: str = "Get current time in a location, check time differences, or convert times. Actions: 'current_time' (requires location), 'difference' (requires location, target_location), 'convert' (requires time, location, target_location)."
    
    config: Optional[Config] = Field(default=None)
    _service: Optional[Any] = None
    
    def __init__(self, config: Optional[Config] = None, **kwargs):
        super().__init__(config=config, **kwargs)
        self._service = None

    def _initialize_service(self):
        if self._service is None and self.config:
            try:
                from ...integrations.google_maps.service import MapsService
                self._service = MapsService(self.config)
            except Exception as e:
                logger.error(f"Failed to initialize MapsService for TimezoneTool: {e}")
                self._service = None

    async def _arun(self, action: str = "current_time", location: str = "", target_location: str = "", time: str = "", **kwargs) -> str:
        """Async execution"""
        self._initialize_service()
        if not self._service: return "Service unavailable."

        try:
            if action == "current_time":
                loc = location or kwargs.get("query", "")
                if not loc: return "Please provide a location."
                
                tz_info = await self._service.get_timezone_async(loc)
                if not tz_info: return f"Could not find timezone for {loc}"
                
                tz_id = tz_info.get('timeZoneId')
                tz = pytz.timezone(tz_id)
                now = datetime.now(tz)
                return f"Current time in {loc} ({tz_id}): {now.strftime('%I:%M %p, %A %b %d')}"

            elif action == "difference":
                loc1 = location
                loc2 = target_location
                if not loc1 or not loc2: return "Need two locations."
                
                tz1_info = await self._service.get_timezone_async(loc1)
                tz2_info = await self._service.get_timezone_async(loc2)
                
                if not tz1_info or not tz2_info: return "Could not find one of the locations."
                
                tz1 = pytz.timezone(tz1_info['timeZoneId'])
                tz2 = pytz.timezone(tz2_info['timeZoneId'])
                
                now_utc = datetime.now(pytz.UTC)
                dt1 = now_utc.astimezone(tz1)
                dt2 = now_utc.astimezone(tz2)
                
                diff = (dt2.utcoffset() - dt1.utcoffset()).total_seconds() / 3600
                return f"Time difference: {loc2} is {diff} hours from {loc1}. ({loc1}: {dt1.strftime('%I:%M %p')}, {loc2}: {dt2.strftime('%I:%M %p')})"
                
            return f"Unknown action: {action}"

        except Exception as e:
            return f"Error: {e}"
            
    def _run(self, *args, **kwargs):
        """Sync wrapper"""
        return asyncio.run(self._arun(*args, **kwargs))
