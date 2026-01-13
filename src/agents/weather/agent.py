"""
Weather Agent
"""
import re
from typing import Dict, Any, Optional
from src.utils.logger import setup_logger
from ..base import BaseAgent
from .schemas import WEATHER_SCHEMA
from .constants import (
    WEATHER_LOCATION_PATTERNS,
    WEATHER_CLEANUP_SUFFIX,
    WEATHER_CLEANUP_PUNCTUATION
)

logger = setup_logger(__name__)

class WeatherAgent(BaseAgent):
    """
    Agent for weather queries.
    """
    
    async def run(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Execute weather queries.
        """
        logger.info(f"[{self.name}] Processing query: {query}")
        
        # Simple extraction for now
        # We can ask LLM specifically for location
        
        params = await self._extract_params(query, WEATHER_SCHEMA)
        location = params.get("location")
        logger.info(f"[{self.name}] Extracted location: {location}")
        
        if not location:
            # Try to extract location from query using regex patterns
            location = self._extract_location_from_query(query)
            logger.info(f"[{self.name}] Fallback extracted location: {location}")
        
        if not location:
            return "I need to know which location to check the weather for."
             
        tool_input = {
            "query": query,
            "location": location
        }
        
        logger.info(f"[{self.name}] Calling weather tool with location: {location}")
        
        # Tool name 'weather'
        result = await self._safe_tool_execute(
            ["weather"], tool_input, "checking weather"
        )
        
        logger.info(f"[{self.name}] Weather result: {result[:100] if result else 'None'}...")
        return result
    
    def _extract_location_from_query(self, query: str) -> Optional[str]:
        """Extract location from query using regex patterns."""
        for pattern in WEATHER_LOCATION_PATTERNS:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                location = match.group(1).strip()
                # Clean up common trailing words
                location = re.sub(WEATHER_CLEANUP_SUFFIX, '', location, flags=re.IGNORECASE)
                location = re.sub(WEATHER_CLEANUP_PUNCTUATION, '', location).strip()
                if location:
                    return location
        
        return None
