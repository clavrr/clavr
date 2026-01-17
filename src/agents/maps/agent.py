"""
Maps Agent

Handles location-related queries such as:
- Distance between locations
- Directions and travel time
- Place lookups and geocoding
"""
import re
from datetime import datetime
from typing import Optional, Dict, Any

from ..base import BaseAgent
from ...integrations.google_maps.service import MapsService
from ...utils.logger import setup_logger
from .constants import (
    DISTANCE_FROM_TO, DISTANCE_BETWEEN_AND, DIRECTIONS_TO, 
    GEOCODE_LOCATION, CLEAN_PUNCTUATION
)

logger = setup_logger(__name__)


class MapsAgent(BaseAgent):
    """Agent for handling maps, directions, and location queries."""
    
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
        Execute location/maps queries.
        """
        logger.info(f"[{self.name}] Processing query: {query}")
        
        query_lower = query.lower()
        
        # Determine intent
        if any(w in query_lower for w in ["how far", "distance", "miles", "km", "kilometers"]):
            return await self._handle_distance(query)
        elif any(w in query_lower for w in ["directions", "how to get", "route", "navigate"]):
            return await self._handle_directions(query)
        elif any(w in query_lower for w in ["near", "nearby", "closest", "around", "places", "shops", "restaurants", "search"]):
            # Specific check for simple "where is X" that might be a geocode vs search
            if "where is" in query_lower and "near" not in query_lower:
                return await self._handle_geocode(query)
            return await self._handle_search(query)
        elif any(w in query_lower for w in ["where is", "location of", "find", "coordinates"]):
            return await self._handle_geocode(query)
        else:
            # Default to geocoding for general location queries
            return await self._handle_geocode(query)

    async def _handle_search(self, query: str) -> str:
        """Handle place search queries (e.g. 'coffee near office')."""
        try:
            # Resolve location aliases (e.g., 'office' -> actual address) via Semantic Memory
            resolved_query = await self._resolve_location_aliases(query)
            
            maps_service = self._get_maps_service()
            places = await maps_service.search_nearby_places_async(resolved_query)
            
            if not places:
                return f"I couldn't find any places matching '{query}'."
            
            summary = f"📍 **Found {len(places)} places for '{query}':**\n\n"
            for i, p in enumerate(places, 1):
                rating_str = f" ({p['rating']}★)" if p.get('rating') else ""
                summary += f"{i}. **{p['name']}**{rating_str}\n   {p['address']}\n"
                
            return summary

        except Exception as e:
            logger.error(f"[{self.name}] Search failed: {e}")
            return f"I encountered an error searching for places: {str(e)}"
    
    async def _resolve_location_aliases(self, query: str) -> str:
        """
        Resolve location aliases like 'office', 'home', 'gym' to actual addresses
        using Semantic Memory facts.
        
        Args:
            query: Original query containing potential aliases
            
        Returns:
            Query with aliases replaced by actual addresses
        """
        # Common location aliases to check 
        LOCATION_ALIASES = ['office', 'home', 'work', 'gym', 'school', 'apartment']
        
        query_lower = query.lower()
        
        # Check if query contains any aliases
        found_aliases = [alias for alias in LOCATION_ALIASES if alias in query_lower]
        if not found_aliases:
            return query
        
        # Try to resolve via Semantic Memory
        try:
            from ...ai.memory.semantic_memory import SemanticMemory
            from ...utils.config import load_config
            
            config = load_config()
            semantic_memory = SemanticMemory(config)
            
            # Get user_id from domain_context if available
            user_id = getattr(self.domain_context, 'user_id', None) if self.domain_context else None
            if not user_id:
                return query
            
            # Search for location facts
            for alias in found_aliases:
                facts = await semantic_memory.search_facts(
                    query=f"{alias} address location",
                    user_id=user_id,
                    limit=3
                )
                
                if facts:
                    for fact in facts:
                        content = fact.get('content', '').lower()
                        # Look for patterns like "office is at 123 Main St" or "home address: 123 Main St"
                        if alias in content and any(word in content for word in ['at', 'is', 'address', 'located']):
                            # Extract the address portion (simple heuristic)
                            # More sophisticated extraction could use LLM or regex
                            for separator in ['is at', 'address is', 'located at', 'is:', ':', 'is ']:
                                if separator in content:
                                    parts = content.split(separator, 1)
                                    if len(parts) > 1:
                                        address = parts[1].strip().rstrip('.').strip()
                                        if len(address) > 5:  # Sanity check
                                            logger.info(f"[MapsAgent] Resolved '{alias}' to '{address}'")
                                            query = query.replace(alias, address)
                                            break
                            break
                            
        except Exception as e:
            logger.debug(f"[MapsAgent] Semantic memory lookup failed: {e}")
        
        return query
    
    async def _handle_distance(self, query: str) -> str:
        """Handle distance queries between two locations."""
        try:
            maps_service = self._get_maps_service()
            
            # Extract locations using simple patterns
            # Pattern: "from X to Y" or "between X and Y"
            from_match = re.search(DISTANCE_FROM_TO, query, re.IGNORECASE)
            between_match = re.search(DISTANCE_BETWEEN_AND, query, re.IGNORECASE)
            
            if from_match:
                origin = from_match.group(1).strip()
                destination = from_match.group(2).strip()
            elif between_match:
                origin = between_match.group(1).strip()
                destination = between_match.group(2).strip()
            else:
                # Try to find location names
                return "I need two locations to calculate distance. Try: 'How far is it from New York to Boston?'"
            
            # Clean up destination (remove trailing punctuation)
            destination = re.sub(CLEAN_PUNCTUATION, '', destination).strip()
            
            # Get distance using directions API
            result = maps_service.get_directions(origin, destination)
            
            if result and 'legs' in result and len(result['legs']) > 0:
                leg = result['legs'][0]
                distance = leg.get('distance', {}).get('text', 'Unknown')
                duration = leg.get('duration', {}).get('text', 'Unknown')
                
                return f"📍 **Distance from {origin} to {destination}:**\n\n" \
                       f"- **Distance:** {distance}\n" \
                       f"- **Driving time:** {duration}"
            else:
                return f"I couldn't calculate the distance between {origin} and {destination}. Please check the location names."
                
        except Exception as e:
            logger.error(f"[{self.name}] Distance calculation failed: {e}")
            return f"I encountered an error calculating the distance: {str(e)}"
    
    async def _handle_directions(self, query: str) -> str:
        """Handle directions queries."""
        try:
            maps_service = self._get_maps_service()
            
            # Extract origin and destination
            from_match = re.search(DISTANCE_FROM_TO, query, re.IGNORECASE)
            to_match = re.search(DIRECTIONS_TO, query, re.IGNORECASE)
            
            if from_match:
                origin = from_match.group(1).strip()
                destination = from_match.group(2).strip()
            elif to_match:
                origin = "current location"  # Would need GPS in production
                destination = to_match.group(1).strip()
            else:
                return "I need a destination to get directions. Try: 'How do I get from San Francisco to Los Angeles?'"
            
            destination = re.sub(CLEAN_PUNCTUATION, '', destination).strip()
            
            result = maps_service.get_directions(origin, destination)
            
            if result and 'legs' in result and len(result['legs']) > 0:
                leg = result['legs'][0]
                distance = leg.get('distance', {}).get('text', 'Unknown')
                duration = leg.get('duration', {}).get('text', 'Unknown')
                steps = leg.get('steps', [])
                
                response = f"🗺️ **Directions from {origin} to {destination}:**\n\n"
                response += f"- **Total distance:** {distance}\n"
                response += f"- **Estimated time:** {duration}\n\n"
                
                if steps:
                    response += "**Route:**\n"
                    for i, step in enumerate(steps[:5], 1):  # Show first 5 steps
                        instruction = re.sub(r'<[^>]+>', '', step.get('html_instructions', ''))
                        step_distance = step.get('distance', {}).get('text', '')
                        response += f"{i}. {instruction} ({step_distance})\n"
                    
                    if len(steps) > 5:
                        response += f"... and {len(steps) - 5} more steps"
                
                return response
            else:
                return f"I couldn't find directions from {origin} to {destination}."
                
        except Exception as e:
            logger.error(f"[{self.name}] Directions lookup failed: {e}")
            return f"I encountered an error getting directions: {str(e)}"
    
    async def _handle_geocode(self, query: str) -> str:
        """Handle geocoding/location lookup queries."""
        try:
            maps_service = self._get_maps_service()
            
            # Extract location name
            location_match = re.search(GEOCODE_LOCATION, query, re.IGNORECASE)
            
            if location_match:
                location = location_match.group(1).strip()
            else:
                # Use the whole query as location
                location = query.strip()
            
            location = re.sub(CLEAN_PUNCTUATION, '', location).strip()
            
            # Get coordinates (returns dict with 'lat' and 'lng')
            coords = await maps_service.get_location_coordinates_async(location)
            
            if coords:
                lat = coords.get('lat')
                lng = coords.get('lng')
                return f"📍 **{location}**\n\n" \
                       f"- **Latitude:** {lat:.6f}\n" \
                       f"- **Longitude:** {lng:.6f}\n\n" \
                       f"[View on Google Maps](https://www.google.com/maps?q={lat},{lng})"
            else:
                return f"I couldn't find the location '{location}'. Please try a more specific address or place name."
                
        except Exception as e:
            logger.error(f"[{self.name}] Geocoding failed: {e}")
            return f"I encountered an error looking up the location: {str(e)}"
