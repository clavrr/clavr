"""
Weather Crawler (Google Weather API)

Fetches weather data for specific locations and times, creating WeatherContext nodes
in the knowledge graph linked to TimeBlocks.

Uses Google Weather API (via generic Google Client or Maps Platform).
"""
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
import aiohttp

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.base_indexer import BaseIndexer
from src.services.indexing.graph.schema import NodeType, RelationType

logger = setup_logger(__name__)

class WeatherCrawler(BaseIndexer):
    """
    Crawler that fetches and indexes weather data using Google API.
    """
    
    def __init__(
        self, 
        config: Config, 
        graph_manager,
        user_id: int
    ):
        super().__init__(config, user_id=user_id, graph_manager=graph_manager)
        from src.integrations.weather.client import WeatherClient
        self.weather_client = WeatherClient(config)
        self.default_lat = 37.7749
        self.default_lon = -122.4194
        
    @property
    def name(self) -> str:
        return "weather"

    async def fetch_delta(self) -> list:
        """Fetch current weather as a single 'item' delta."""
        if not self.weather_client.is_available():
            return []
            
        weather_data = await self._fetch_google_weather(self.default_lat, self.default_lon)
        if weather_data:
            return [weather_data]
        return []

    async def transform_item(self, item: Dict[str, Any]) -> Any:
        """Transform weather data into a ParsedNode."""
        from src.services.indexing.parsers.base import ParsedNode
        
        now = datetime.utcnow()
        node_id = f"weather:{self.user_id}:{now.strftime('%Y-%m-%d_%H')}"
        
        # Parse Google Weather API response structure
        temp_data = item.get("temperature", {})
        condition_data = item.get("weatherCondition", {})
        wind_data = item.get("wind", {})
        
        properties = {
            "description": condition_data.get("description", {}).get("text"),
            "condition": condition_data.get("description", {}).get("text"),
            "temperature": temp_data.get("degrees"),
            "temp_unit": temp_data.get("unit"),
            "humidity": item.get("relativeHumidity"),
            "wind_speed": wind_data.get("speed", {}).get("value"),
            "timestamp": now.isoformat(),
            "location_id": f"{self.default_lat},{self.default_lon}",
            "source": "GoogleWeather",
            "user_id": self.user_id
        }
        
        return ParsedNode(
            node_id=node_id,
            node_type=NodeType.WEATHER_CONTEXT,
            properties=properties
        )

    async def _fetch_google_weather(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        """Fetch weather data from Google API."""
        return await self.weather_client.get_current_conditions(lat, lon)

