"""
Weather Tool
"""
from typing import Optional, Any
from langchain.tools import BaseTool
from pydantic import Field

from ...utils.logger import setup_logger
from ...utils.config import Config

logger = setup_logger(__name__)

class WeatherTool(BaseTool):
    """Tool for checking weather conditions."""
    name: str = "weather"
    description: str = "Get current weather for a location. Input should be a location string (e.g. 'San Francisco, CA')."
    
    config: Optional[Config] = Field(default=None)
    _service: Optional[Any] = None
    
    def __init__(self, config: Optional[Config] = None, **kwargs):
        super().__init__(config=config, **kwargs)
        self._service = None

    def _initialize_service(self):
        if self._service is None and self.config:
            try:
                from ...integrations.weather.service import WeatherService
                self._service = WeatherService(self.config)
            except Exception as e:
                logger.error(f"Failed to initialize WeatherService: {e}")
                self._service = None
                
    def _run(self, query: str = "", location: str = "", **kwargs) -> str:
        """
        Execute weather check.
        Accepts 'query' (from direct tool call) or 'location' (from struct extraction).
        """
        target_location = location or query
        if not target_location:
            return "Please provide a location to check the weather for."
            
        self._initialize_service()
        
        if not self._service:
            return "Weather service is unavailable."
            
        try:
            # We need to run async service method in sync context
            import asyncio
            return asyncio.run(self._service.get_current_weather(target_location))
        except Exception as e:
            logger.error(f"Weather tool error: {e}")
            return f"Error checking weather: {e}"
            
    async def _arun(self, query: str = "", location: str = "", **kwargs) -> str:
        """Async execution"""
        target_location = location or query
        if not target_location:
            return "Please provide a location."
            
        self._initialize_service()
        
        if not self._service:
            return "Weather service unavailable."
            
        return await self._service.get_current_weather(target_location)
