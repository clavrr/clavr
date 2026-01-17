"""
Maps Tool
"""
from typing import Optional, Any
from langchain.tools import BaseTool
from pydantic import Field
import asyncio

from ...utils.logger import setup_logger
from ...utils.config import Config

logger = setup_logger(__name__)

class MapsTool(BaseTool):
    """Tool for maps, directions, and location lookups."""
    name: str = "maps"
    description: str = "Get directions, travel times, distances, or location coordinates. Actions: 'directions' (requires origin, destination), 'distance' (requires origin, destination), 'geocode' (requires location)."
    
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
                logger.error(f"Failed to initialize MapsService: {e}")
                self._service = None
                
    def _run(self, action: str = "geocode", location: str = "", origin: str = "", destination: str = "", **kwargs) -> str:
        """Execute maps action."""
        self._initialize_service()
        if not self._service:
            return "Maps service unavailable."
            
        try:
            # Sync wrapper for async calls if needed, though MapsService uses sync client mostly?
            # Checking MapsService usage in MapsAgent... it seems get_directions is sync, get_location_coordinates_async is async.
            # We'll use async mostly but _run is sync.
            
            if action == "geocode" or action == "find":
                target = location or kwargs.get("query", "")
                if not target: return "Please provide a location."
                
                # Run async method in sync
                coords = asyncio.run(self._service.get_location_coordinates_async(target))
                if coords:
                    return f"Location: {target}\nLat: {coords['lat']}, Lng: {coords['lng']}"
                return f"Could not find location: {target}"
                
            elif action == "directions" or action == "distance":
                start = origin or kwargs.get("from", "")
                end = destination or kwargs.get("to", "")
                if not start: start = "current location" # Fallback if allowed
                if not end: return "Please provide a destination."
                
                result = self._service.get_directions(start, end)
                if result and 'legs' in result and len(result['legs']) > 0:
                    leg = result['legs'][0]
                    dist = leg.get('distance', {}).get('text')
                    dur = leg.get('duration', {}).get('text')
                    summary = f"Route from {start} to {end}: {dist}, {dur}."
                    
                    if action == "directions" and 'steps' in leg:
                        steps = leg['steps'][:3] # Summarize
                        summary += " Start: " + ", ".join([s.get('html_instructions', '') for s in steps])
                    return summary
                return f"Could not get directions from {start} to {end}."
            
            elif action == "search" or action == "search_nearby":
                query = kwargs.get("query", "") or location
                if not query: return "Please provide a search query."
                
                places = asyncio.run(self._service.search_nearby_places_async(query))
                if not places:
                    return f"I couldn't find any places matching '{query}'."
                
                summary = f"Found {len(places)} places for '{query}':\n"
                for i, p in enumerate(places, 1):
                    rating_str = f" ({p['rating']}★)" if p.get('rating') else ""
                    summary += f"{i}. **{p['name']}**{rating_str}\n   {p['address']}\n"
                return summary
                return f"Unknown action: {action}"
                
        except Exception as e:
            logger.error(f"MapsTool error: {e}")
            return f"Error: {e}"

    async def _arun(self, action: str = "geocode", location: str = "", origin: str = "", destination: str = "", **kwargs) -> str:
        """Async execution"""
        self._initialize_service()
        if not self._service:
            return "Maps service unavailable."
            
        try:
            if action == "geocode" or action == "find":
                target = location or kwargs.get("query", "")
                if not target: return "Please provide a location."
                coords = await self._service.get_location_coordinates_async(target)
                if coords:
                    return f"Location: {target}\nLat: {coords['lat']}, Lng: {coords['lng']}"
                return f"Could not find location: {target}"
                
            elif action == "directions" or action == "distance":
                start = origin or kwargs.get("from", "")
                end = destination or kwargs.get("to", "")
                # Use sync method in thread
                return await asyncio.to_thread(self._run, action=action, origin=start, destination=end)
                
            return f"Unknown action: {action}"
            
        except Exception as e:
            return f"Error: {e}"
