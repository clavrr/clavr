"""
Google Maps Client
Wrapper around the Google Maps API for distance matrix and places search.
"""
from typing import Dict, Any, List, Optional
try:
    import googlemaps
except ImportError:
    googlemaps = None
from datetime import datetime

from ...utils.config import Config
from ...utils.logger import setup_logger

logger = setup_logger(__name__)

class GoogleMapsClient:
    """Client for interacting with Google Maps API"""
    
    def __init__(self, config: Config):
        self.config = config
        self.api_key = config.google_maps_api_key if hasattr(config, 'google_maps_api_key') else None
        
        # Fallback to env var lookup if config object doesn't have the property yet
        if not self.api_key:
             import os
             self.api_key = os.getenv("GOOGLE_MAPS_API_KEY")

        if not self.api_key:
            logger.warning("[GoogleMapsClient] No API key found. Maps features will be disabled.")
            self.client = None
        else:
            try:
                self.client = googlemaps.Client(key=self.api_key)
                logger.info("[GoogleMapsClient] Initialized successfully")
            except Exception as e:
                logger.error(f"[GoogleMapsClient] Failed to initialize: {e}")
                self.client = None

    def is_available(self) -> bool:
        return self.client is not None

    def get_travel_time(self, origin: str, destination: str, arrival_time: Optional[datetime] = None) -> Optional[int]:
        """
        Get travel time in minutes between two locations.
        Defaults to driving mode.
        """
        if not self.client:
            return None
            
        try:
            # Distance Matrix API
            matrix = self.client.distance_matrix(
                origins=[origin],
                destinations=[destination],
                mode="driving",
                arrival_time=arrival_time
            )
            
            # Parse result
            if matrix['status'] == 'OK':
                rows = matrix.get('rows', [])
                if rows:
                    elements = rows[0].get('elements', [])
                    if elements:
                        element = elements[0]
                        if element.get('status') == 'OK':
                            duration_seconds = element['duration']['value']
                            return int(duration_seconds / 60)
            
            logger.warning(f"[GoogleMapsClient] Could not calculate route: {origin} -> {destination}")
            return None
            
        except Exception as e:
            logger.error(f"[GoogleMapsClient] Distance Matrix Error: {e}")
            return None

    def search_place(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Search for a place to get formatted address and location details.
        """
        if not self.client:
             return None
             
        try:
            places = self.client.places(query)
            if places['status'] == 'OK' and places['results']:
                return places['results'][0]
            return None
        except Exception as e:
            logger.error(f"[GoogleMapsClient] Places Error: {e}")
            return None
