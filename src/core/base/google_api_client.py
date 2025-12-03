"""
Base Google API Client
Provides common functionality for all Google API clients (Gmail, Calendar, Tasks)
"""
import os
from abc import ABC, abstractmethod
from typing import List, Optional, Any
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from ...utils.logger import setup_logger
from ...utils.config import Config

logger = setup_logger(__name__)


class BaseGoogleAPIClient(ABC):
    """
    Abstract base class for all Google API clients
    
    Provides common functionality:
    - Credential loading from token.json
    - Service initialization
    - Scope validation
    - Availability checking
    
    Subclasses must implement:
    - _build_service(): Build the specific Google API service
    - _get_required_scopes(): Return required OAuth scopes
    - _get_service_name(): Return the service name for logging
    """
    
    def __init__(self, config: Config, credentials: Optional[Credentials] = None):
        """
        Initialize Google API client
        
        Args:
            config: Configuration object
            credentials: OAuth2 credentials (if None, will try to load from token.json)
        """
        self.config = config
        self.credentials = credentials or self._load_credentials()
        self.service = None
        self._initialize_service()
    
    def _load_credentials(self) -> Optional[Credentials]:
        """
        Load credentials from token.json
        
        NOTE: This is a fallback method. Prefer passing credentials directly
        via constructor to use database-stored tokens instead of token.json
        
        Returns:
            Credentials object or None if not found
        """
        try:
            # Look for token.json in project root
            token_path = os.path.join(os.path.dirname(__file__), '../../../token.json')
            
            if os.path.exists(token_path):
                logger.warning(f"Loading credentials from {token_path} - Consider using database-stored credentials instead")
                credentials = Credentials.from_authorized_user_file(token_path)
                logger.debug(f"Loaded credentials from {token_path}")
                return credentials
            else:
                logger.debug(f"No token.json found at {token_path}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to load credentials from token.json: {e}")
            return None
    
    def _initialize_service(self) -> None:
        """Initialize the Google API service"""
        try:
            if not self.credentials:
                logger.warning(f"No credentials found. {self._get_service_name()} integration disabled.")
                return
            
            self.service = self._build_service()
            
            if self.service:
                logger.info(f"[OK] {self._get_service_name()} API service initialized")
                logger.debug(f"Service: {self.service}")
                logger.debug(f"Credentials scopes: {self.credentials.scopes if self.credentials else 'None'}")
            else:
                logger.warning(f"Failed to build {self._get_service_name()} service")
                
        except Exception as e:
            logger.error(f"Failed to initialize {self._get_service_name()} service: {e}")
            self.service = None
    
    @abstractmethod
    def _build_service(self) -> Any:
        """
        Build the specific Google API service
        
        Returns:
            Google API service object
            
        Example:
            return build('gmail', 'v1', credentials=self.credentials)
        """
        pass
    
    @abstractmethod
    def _get_required_scopes(self) -> List[str]:
        """
        Get required OAuth scopes for this service
        
        Returns:
            List of required scope URLs
            
        Example:
            return ['https://www.googleapis.com/auth/gmail.readonly']
        """
        pass
    
    @abstractmethod
    def _get_service_name(self) -> str:
        """
        Get the service name for logging
        
        Returns:
            Service name (e.g., "Gmail", "Google Calendar", "Google Tasks")
        """
        pass
    
    def is_available(self) -> bool:
        """
        Check if service is available and has proper scopes
        
        Returns:
            True if service is ready to use, False otherwise
        """
        if self.service is None:
            return False
        
        # Check if credentials have the required scopes
        if self.credentials and self.credentials.scopes:
            required_scopes = self._get_required_scopes()
            has_required_scopes = any(
                scope in self.credentials.scopes 
                for scope in required_scopes
            )
            
            if not has_required_scopes:
                service_name = self._get_service_name()
                logger.error(f"[ALERT] {service_name} credentials missing required scopes!")
                logger.error(f"Current scopes: {self.credentials.scopes}")
                logger.error(f"Required scopes: {required_scopes}")
                logger.error(
                    f"Please add the {service_name} scopes to your OAuth consent screen "
                    "and re-authenticate."
                )
                return False
        
        return True
    
    def refresh_credentials(self) -> bool:
        """
        Refresh OAuth credentials if expired
        
        Returns:
            True if refresh successful, False otherwise
        """
        try:
            # Only refresh if credentials are actually expired
            # Don't attempt refresh on rate limit errors or other 401s
            if not self.credentials:
                logger.warning(f"No credentials to refresh for {self._get_service_name()}")
                return False
                
            if not self.credentials.refresh_token:
                logger.warning(f"No refresh token available for {self._get_service_name()}")
                return False
            
            # Check if credentials are actually expired before attempting refresh
            # This prevents unnecessary refresh attempts that can trigger rate limiting
            if self.credentials.expired:
                from google.auth.transport.requests import Request
                
                logger.info(f"Refreshing expired credentials for {self._get_service_name()}")
                self.credentials.refresh(Request())
                logger.info(f"[OK] {self._get_service_name()} credentials refreshed")
                
                # Rebuild service with new credentials
                self.service = self._build_service()
                return True
            else:
                logger.debug(f"Credentials not expired for {self._get_service_name()}, skipping refresh")
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to refresh {self._get_service_name()} credentials: {e}")
            return False
    
    def get_service_info(self) -> dict:
        """
        Get information about the service
        
        Returns:
            Dictionary with service status and information
        """
        return {
            "service_name": self._get_service_name(),
            "available": self.is_available(),
            "has_credentials": self.credentials is not None,
            "credentials_valid": self.credentials.valid if self.credentials else False,
            "required_scopes": self._get_required_scopes(),
            "current_scopes": self.credentials.scopes if self.credentials else []
        }
