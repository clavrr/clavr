"""
Maps Crawler

Resolves location context for events and updates the user's current location node.
Uses external Maps APIs (e.g. Google Maps, Mapbox) for geocoding.
"""
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.base_indexer import BaseIndexer
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType

logger = setup_logger(__name__)

class MapsCrawler(BaseIndexer):
    """
    Crawler that manages location context.
    """
    
    def __init__(
        self, 
        config: Config, 
        graph_manager: KnowledgeGraphManager,
        user_id: int
    ):
        super().__init__(config, user_id=user_id, graph_manager=graph_manager)
        
    @property
    def name(self) -> str:
        return "maps"

    async def fetch_delta(self) -> list:
        """Fetch current location as a delta (placeholder)."""
        # In a real app, this would poll location or return recently resolved locations
        return []

    async def transform_item(self, item: Any) -> Any:
        """Transform location data into a ParsedNode."""
        # Standardize location transformation if needed
        return None

    async def resolve_location(self, address_query: str) -> Optional[Dict[str, Any]]:

        """
        Geocode an address string to a Location node.
        
        Uses Google Maps Geocoding API if configured, falls back to mock data.
        
        Args:
            address_query: "123 Main St, San Francisco"
            
        Returns:
            Location node properties or None
        """
        if not address_query:
            return None
            
        logger.info(f"[{self.name}] Resolving location: {address_query}")
        
        # Try Google Maps Geocoding API if available
        api_key = self.config.google_maps_api_key if hasattr(self.config, 'google_maps_api_key') else None
        
        if api_key:
            try:
                import httpx
                
                url = "https://maps.googleapis.com/maps/api/geocode/json"
                params = {
                    "address": address_query,
                    "key": api_key
                }
                
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(url, params=params)
                    data = response.json()
                
                if data.get("status") == "OK" and data.get("results"):
                    result = data["results"][0]
                    geometry = result.get("geometry", {}).get("location", {})
                    
                    # Parse address components
                    components = {}
                    for component in result.get("address_components", []):
                        types = component.get("types", [])
                        if "locality" in types:
                            components["city"] = component.get("long_name")
                        elif "administrative_area_level_1" in types:
                            components["state"] = component.get("short_name")
                        elif "country" in types:
                            components["country"] = component.get("long_name")
                    
                    return {
                        "address": result.get("formatted_address", address_query),
                        "city": components.get("city", "Unknown"),
                        "state": components.get("state"),
                        "country": components.get("country", "Unknown"),
                        "coordinates": {
                            "lat": geometry.get("lat", 0.0),
                            "lng": geometry.get("lng", 0.0)
                        },
                        "name": result.get("formatted_address", address_query),
                        "place_id": result.get("place_id")
                    }
                else:
                    logger.warning(f"[{self.name}] Geocoding API returned: {data.get('status')}")
                    
            except ImportError:
                logger.debug("[{self.name}] httpx not available, using mock geocoding")
            except Exception as e:
                logger.warning(f"[{self.name}] Geocoding API failed: {e}")
        
        # Fallback: Mock result for development/testing
        return {
            "address": address_query,
            "city": "Unknown City",
            "country": "Unknown Country",
            "coordinates": {"lat": 0.0, "lng": 0.0},
            "name": address_query
        }

    async def create_location_node(self, location_data: Dict[str, Any]) -> Optional[str]:
        """Create a Location node in the graph."""
        try:
            # Create unique ID based on coords or address
            coords = location_data.get("coordinates", {})
            if coords and coords.get("lat"):
                loc_id = f"loc:{coords['lat']},{coords['lng']}"
            else:
                import hashlib
                hash_id = hashlib.md5(location_data.get("address", "").encode()).hexdigest()
                loc_id = f"loc:{hash_id}"
            
            properties = {
                "name": location_data.get("name") or location_data.get("address"),
                "address": location_data.get("address"),
                "city": location_data.get("city"),
                "country": location_data.get("country"),
                "coordinates": location_data.get("coordinates"),
                "type": "point_of_interest"
            }
            
            await self.graph_manager.add_node(loc_id, NodeType.LOCATION, properties)
            return loc_id
            
        except Exception as e:
            logger.error(f"[{self.name}] Failed to create location node: {e}")
            return None
