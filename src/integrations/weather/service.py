"""
Weather Service
Business logic for weather data.
"""
from typing import Optional, Dict, Any
from ...utils.logger import setup_logger
from ...utils.config import Config
from .client import WeatherClient

# Optional dependency
try:
    from ..google_maps.service import MapsService
except ImportError:
    MapsService = None

logger = setup_logger(__name__)

class WeatherService:
    """
    Service provides weather intelligence.
    Uses Maps integration for geocoding.
    """
    def __init__(self, config: Config):
        self.config = config
        self.client = WeatherClient(config)
        self.maps_service = MapsService(config) if MapsService else None
    
    async def get_current_weather(self, location: str) -> str:
        """
        Get a human-readable summary of current weather for a location.
        """
        logger.info(f"[WeatherService] Getting weather for: {location}")
        
        if not self.client.is_available():
            logger.warning("[WeatherService] Weather client not available (missing API key)")
            return "Weather service is not configured (missing API key)."
            
        if not self.maps_service:
            logger.warning("[WeatherService] Maps service unavailable")
            return "Maps service unavailable for geocoding location."

        # 1. Geocode using async method (New Places API compatible)
        logger.info(f"[WeatherService] Geocoding location: {location}")
        coords = await self.maps_service.get_location_coordinates_async(location)
        if not coords:
            logger.warning(f"[WeatherService] Geocoding failed for: {location}")
            return f"Could not find location '{location}'."
            
        lat = coords.get('lat')
        lng = coords.get('lng')
        
        if lat is None or lng is None:
            return f"Invalid coordinates for '{location}'."
        
        logger.info(f"[WeatherService] Got coords: {lat}, {lng}")

        # 2. Fetch Weather
        logger.info(f"[WeatherService] Fetching weather for coords")
        data = await self.client.get_current_conditions(lat, lng)
        
        if not data:
            logger.warning(f"[WeatherService] Weather API returned no data")
            return f"Could not retrieve weather for {location}."
        
        # Check for coverage error
        if data.get("error") == "location_not_covered":
            return f"Sorry, Clavr doesn't have coverage for {location}. This is a limitation of the Google Weather API which only covers select regions."
            
        # 3. Format Response
        # Google Weather API response structure:
        # { "temperature": { "degrees": 9, "unit": "CELSIUS" }, 
        #   "weatherCondition": { "description": { "text": "Sunny" } },
        #   "relativeHumidity": 79, "wind": { "speed": { "value": 6 } } }
        temp = data.get('temperature', {}).get('degrees')
        unit = data.get('temperature', {}).get('unit', 'CELSIUS')
        condition_obj = data.get('weatherCondition', {})
        condition = condition_obj.get('description', {}).get('text', 'Unknown')
        humidity = data.get('relativeHumidity')
        wind = data.get('wind', {}).get('speed', {}).get('value')
        
        if temp is None:
             logger.warning(f"[WeatherService] Parsing failed: {str(data)[:200]}")
             return f"Weather data retrieved but parsing failed."
             
        unit_str = "°C" if "CELSIUS" in str(unit).upper() else "°F"
        
        # Build a nice summary
        summary = f"🌤️ **Weather in {location}:**\n\n"
        summary += f"**{condition}**, {temp}{unit_str}\n"
        
        if humidity:
            summary += f"- Humidity: {humidity}%\n"
        if wind:
            summary += f"- Wind: {wind} km/h\n"
             
        return summary

