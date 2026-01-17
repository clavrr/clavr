import aiohttp
import time
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from ...utils.config import Config
from ...utils.logger import setup_logger
from .client import GoogleMapsClient

logger = setup_logger(__name__)

class MapsService:
    """
    Service for providing location intelligence.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.client = GoogleMapsClient(config)
        
    def get_travel_duration(self, origin: str, destination: str, arrival_dt: datetime) -> Optional[int]:
        """
        Calculate travel time in minutes.
        Returns None if calculation fails or service unavailable.
        """
        if not self.client.is_available():
            return None
            
        # Don't calculate if locations are "virtual" or identical
        if origin.lower() == destination.lower():
            return 0
            
        virtual_keywords = ['zoom', 'google meet', 'online', 'virtual', 'phone', 'call']
        if any(w in origin.lower() for w in virtual_keywords) or \
           any(w in destination.lower() for w in virtual_keywords):
            return 0
            
        return self.client.get_travel_time(origin, destination, arrival_time=arrival_dt)

    def validate_location(self, location: str) -> Optional[str]:
        """
        Verify if a location string corresponds to a real place.
        Returns the formatted address if found, else None.
        """
        if not self.client.is_available():
            return None
            
        place = self.client.search_place(location)
        if place:
            return place.get('formatted_address')
        return None

    def get_location_coordinates(self, location: str) -> Optional[Dict[str, float]]:
        """
        Get lat/lng for a location string using Legacy Places API.
        Returns dict with 'lat', 'lng'.
        """
        if not self.client.is_available():
            return None
            
        place = self.client.search_place(location)
        if place:
            geometry = place.get('geometry', {})
            return geometry.get('location')
        return None

    async def get_location_coordinates_async(self, location: str) -> Optional[Dict[str, float]]:
        """
        Get lat/lng using New Places API (REST).
        This is compatible with "Places API (New)" restrictions.
        """
        
        api_key = self.config.google_maps_api_key
        if not api_key:
            return None
            
        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.location"
        }
        data = {"textQuery": location}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        places = result.get("places", [])
                        if places:
                            loc = places[0].get("location", {})
                            return {"lat": loc.get("latitude"), "lng": loc.get("longitude")}
                    else:
                        error = await response.json()
                        logger.error(f"[MapsService] New Places API Error: {error}")
        except Exception as e:
            logger.error(f"[MapsService] Geocoding failed: {e}")
            
        return None

    async def get_timezone_async(self, location: str) -> Optional[Dict[str, Any]]:
        """
        Get timezone info for a location.
        Returns dict with 'timeZoneId' (e.g., 'America/Los_Angeles'), 'timeZoneName', 'rawOffset', 'dstOffset'.
        """
        # First get coordinates
        coords = await self.get_location_coordinates_async(location)
        if not coords:
            return None
            
        lat = coords.get('lat')
        lng = coords.get('lng')
        
        api_key = self.config.google_maps_api_key
        if not api_key:
            return None
        
        # Time Zone API requires a timestamp
        timestamp = int(time.time())
        url = f"https://maps.googleapis.com/maps/api/timezone/json"
        params = {
            "location": f"{lat},{lng}",
            "timestamp": timestamp,
            "key": api_key
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("status") == "OK":
                            return {
                                "timeZoneId": data.get("timeZoneId"),
                                "timeZoneName": data.get("timeZoneName"),
                                "rawOffset": data.get("rawOffsetSeconds", 0) // 3600,  # Hours from UTC
                                "dstOffset": data.get("dstOffsetSeconds", 0) // 3600
                            }
                        else:
                            logger.error(f"[MapsService] Time Zone API Error: {data}")
                    else:
                        error = await response.text()
                        logger.error(f"[MapsService] Time Zone API HTTP Error: {error}")
        except Exception as e:
            logger.error(f"[MapsService] Timezone lookup failed: {e}")
            
        return None

    async def search_nearby_places_async(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Search for places using New Places API (Text Search).
        Handles queries like "coffee near 123 Main St" or "restaurants in San Francisco".
        """
        
        api_key = self.config.google_maps_api_key
        if not api_key:
            return []
            
        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location,places.rating,places.userRatingCount"
        }
        
        # We can pass the raw query directly (e.g. "coffee near 123 Main St")
        data = {
            "textQuery": query,
            "maxResultCount": limit
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        places_data = result.get("places", [])
                        
                        clean_results = []
                        for p in places_data:
                            name = p.get('displayName', {}).get('text', 'Unknown')
                            addr = p.get('formattedAddress', '')
                            loc = p.get('location', {})
                            rating = p.get('rating')
                            
                            clean_results.append({
                                "name": name,
                                "address": addr,
                                "lat": loc.get('latitude'),
                                "lng": loc.get('longitude'),
                                "rating": rating
                            })
                        return clean_results
                    else:
                        error = await response.json()
                        logger.error(f"[MapsService] Places Search Error: {error}")
        except Exception as e:
            logger.error(f"[MapsService] Places Search failed: {e}")
            
        return []


