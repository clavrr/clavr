"""
Google Weather API Client
Interact with Google Weather REST API.
"""
import aiohttp
import os
from typing import Optional, Dict, Any
from ...utils.logger import setup_logger
from ...utils.config import Config

logger = setup_logger(__name__)

class WeatherClient:
    """Client for Google Weather API (REST)"""
    BASE_URL = "https://weather.googleapis.com/v1"

    def __init__(self, config: Config):
        self.api_key = config.google_maps_api_key
        if not self.api_key:
             self.api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        
        logger.info(f"[WeatherClient] Initialized (API key: {'set' if self.api_key else 'missing'})")

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def get_current_conditions(self, lat: float, lng: float, units: str = "IMPERIAL") -> Optional[Dict[str, Any]]:
        """
        Get current weather conditions.
        units: 'IMPERIAL' (F) or 'METRIC' (C)
        """
        if not self.api_key:
            return None
        
        url = f"{self.BASE_URL}/currentConditions:lookup"
        params = {
            "key": self.api_key,
            "location.latitude": lat,
            "location.longitude": lng,
            "unitsSystem": units
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 404:
                        # Google Weather has limited coverage
                        logger.warning(f"[WeatherClient] Location not covered by Google Weather API: {lat}, {lng}")
                        return {"error": "location_not_covered"}
                    else:
                        text = await resp.text()
                        logger.error(f"[WeatherClient] API Error {resp.status}: {text}")
                        return None
        except Exception as e:
            logger.error(f"[WeatherClient] Request failed: {e}")
            return None
