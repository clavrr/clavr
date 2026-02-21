"""
Google OAuth 2.0 handler for user authentication
"""
import os
import secrets
from typing import Dict, Optional, Tuple
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from ..utils.logger import setup_logger

logger = setup_logger(__name__)

# Scope definitions
LOGIN_SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
]

# Service scopes (for integration)
GMAIL_SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
]

CALENDAR_SCOPES = [
    'https://www.googleapis.com/auth/calendar',
]

TASKS_SCOPES = [
    'https://www.googleapis.com/auth/tasks.readonly',
]

DRIVE_SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
]

CONTACTS_SCOPES = [
    'https://www.googleapis.com/auth/contacts.readonly',
    'https://www.googleapis.com/auth/contacts.other.readonly',
]

# Combined service scopes (for legacy use or "all-in-one" flows)
SERVICE_SCOPES = GMAIL_SCOPES + CALENDAR_SCOPES + TASKS_SCOPES + DRIVE_SCOPES + CONTACTS_SCOPES

# Full scopes for authentication - includes all services
# Note: Users must re-authenticate to get new scopes if they previously logged in with limited scopes
SCOPES = LOGIN_SCOPES + SERVICE_SCOPES


class GoogleOAuthHandler:
    """
    Handle Google OAuth 2.0 authentication
    
    Simple wrapper around Google's OAuth library with no unnecessary abstractions.
    """
    
    def __init__(self):
        from ..utils.urls import URLs
        from api.dependencies import AppState
        
        config = AppState.get_config()
        self.oauth_config = None
        if config.oauth and config.oauth.providers and 'google' in config.oauth.providers:
            self.oauth_config = config.oauth.providers['google']

        self.client_id = os.getenv('GOOGLE_CLIENT_ID')
        self.client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        self.redirect_uri = os.getenv(
            'GOOGLE_REDIRECT_URI',
            URLs.OAUTH_REDIRECT
        )
        
        # Override with config if available
        if self.oauth_config:
            self.client_id = self.oauth_config.client_id or self.client_id
            self.client_secret = self.oauth_config.client_secret or self.client_secret
            self.redirect_uri = self.oauth_config.redirect_uri or self.redirect_uri
        
        if not self.client_id or not self.client_secret:
            logger.warning("Google OAuth credentials not configured")
    
    def _get_client_config(self) -> dict:
        """Get client configuration for OAuth flow"""
        auth_uri = "https://accounts.google.com/o/oauth2/auth"
        token_uri = "https://oauth2.googleapis.com/token"
        
        if self.oauth_config:
            auth_uri = self.oauth_config.auth_url or auth_uri
            token_uri = self.oauth_config.token_url or token_uri

        return {
            "web": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": auth_uri,
                "token_uri": token_uri,
                "redirect_uris": [self.redirect_uri]
            }
        }
    
    def get_authorization_url(self, state: Optional[str] = None, scopes: list = None) -> Tuple[str, str]:
        """
        Generate authorization URL for OAuth flow
        
        Args:
            state: Optional CSRF state token
            scopes: Optional list of scopes to request. Defaults to LOGIN_SCOPES (minimal).
                    Pass SERVICE_SCOPES or SCOPES for full integration access.
        
        Returns:
            (authorization_url, state) tuple
        """
        state = state or secrets.token_urlsafe(32)
        use_scopes = scopes if scopes is not None else LOGIN_SCOPES
        
        flow = Flow.from_client_config(
            self._get_client_config(),
            scopes=use_scopes,
            redirect_uri=self.redirect_uri
        )
        
        logger.info(f"Using Google OAuth Redirect URI: {self.redirect_uri}")
        
        # Don't use include_granted_scopes for login - we only want the minimal scopes
        # Integration flows can pass it explicitly if they want to accumulate scopes
        authorization_url, _ = flow.authorization_url(
            access_type='offline',
            state=state,
            prompt='consent'  # Forces Google to return refresh_token on re-authorization
        )
        
        logger.info(f"Generated authorization URL with state: {state[:10]}... (scopes: {len(use_scopes)})")
        return authorization_url, state
    
    def exchange_code_for_tokens(self, code: str, scopes: list = None) -> Dict[str, str]:
        """
        Exchange authorization code for tokens
        
        Args:
            code: Authorization code from callback
            scopes: Scopes to use for the flow. If None, uses LOGIN_SCOPES.
            
        Returns:
            Token information dict
        """
        use_scopes = scopes if scopes is not None else LOGIN_SCOPES
        
        flow = Flow.from_client_config(
            self._get_client_config(),
            scopes=use_scopes,
            redirect_uri=self.redirect_uri
        )
        
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        logger.info("Successfully exchanged code for tokens")
        
        return {
            'access_token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_expiry': credentials.expiry.isoformat() if credentials.expiry else None,
            'scopes': credentials.scopes
        }
    
    def get_user_info(self, access_token: str) -> Dict[str, str]:
        """
        Get user information from Google
        
        Args:
            access_token: Valid access token
            
        Returns:
            User information dict
        """
        credentials = Credentials(token=access_token)
        oauth_service = build('oauth2', 'v2', credentials=credentials)
        user_info = oauth_service.userinfo().get().execute()
        
        logger.info(f"Retrieved user info for: {user_info.get('email')}")
        
        return {
            'google_id': user_info.get('id'),
            'email': user_info.get('email'),
            'name': user_info.get('name'),
            'picture_url': user_info.get('picture')
        }
    
    def refresh_access_token(self, refresh_token: str) -> Dict[str, str]:
        """
        Refresh access token
        
        Args:
            refresh_token: Valid refresh token
            
        Returns:
            New token information
        """
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret
        )
        
        credentials.refresh(Request())
        
        return {
            'access_token': credentials.token,
            'token_expiry': credentials.expiry.isoformat() if credentials.expiry else None
        }
    
    # ============================================
    # ASYNC METHODS (for non-blocking OAuth)
    # ============================================
    
    async def exchange_code_for_tokens_async(self, code: str) -> Dict[str, str]:
        """
        Exchange authorization code for tokens (ASYNC version)
        
        Uses httpx for non-blocking HTTP calls.
        
        Args:
            code: Authorization code from callback
            
        Returns:
            Token information dict
        """
        import httpx
        
        token_url = "https://oauth2.googleapis.com/token"
        
        data = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)
            response.raise_for_status()
            token_data = response.json()
        
        logger.info("Successfully exchanged code for tokens (async)")
        
        return {
            'access_token': token_data.get('access_token'),
            'refresh_token': token_data.get('refresh_token'),
            'token_expiry': token_data.get('expires_in'),  # seconds until expiry
            'scopes': token_data.get('scope', '').split() if token_data.get('scope') else SCOPES
        }
    
    async def get_user_info_async(self, access_token: str) -> Dict[str, str]:
        """
        Get user information from Google (ASYNC version)
        
        Uses httpx for non-blocking HTTP calls.
        
        Args:
            access_token: Valid access token
            
        Returns:
            User information dict
        """
        import httpx
        
        userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(userinfo_url, headers=headers)
            response.raise_for_status()
            user_info = response.json()
        
        logger.info(f"Retrieved user info for: {user_info.get('email')} (async)")
        
        return {
            'google_id': user_info.get('id'),
            'email': user_info.get('email'),
            'name': user_info.get('name'),
            'picture_url': user_info.get('picture')
        }
    
    async def refresh_access_token_async(self, refresh_token: str) -> Dict[str, str]:
        """
        Refresh access token (ASYNC version)
        
        Uses httpx for non-blocking HTTP calls.
        
        Args:
            refresh_token: Valid refresh token
            
        Returns:
            New token information
        """
        import httpx
        
        token_url = "https://oauth2.googleapis.com/token"
        
        data = {
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)
            response.raise_for_status()
            token_data = response.json()
        
        return {
            'access_token': token_data.get('access_token'),
            'token_expiry': token_data.get('expires_in')  # seconds until expiry
        }


# Helper functions for FastAPI routes
def get_authorization_url() -> Tuple[str, str]:
    """
    Generate Google OAuth authorization URL
    
    Returns:
        Tuple of (authorization_url, state)
    """
    handler = GoogleOAuthHandler()
    return handler.get_authorization_url()


def exchange_code_for_tokens(code: str) -> Credentials:
    """
    Exchange authorization code for Google credentials
    
    Delegates to GoogleOAuthHandler.exchange_code_for_tokens() to avoid code duplication,
    but returns full Credentials object and provides additional logging.
    
    Args:
        code: Authorization code from OAuth callback
        
    Returns:
        Google Credentials object
    """
    # Delegate to handler for token exchange
    handler = GoogleOAuthHandler()
    token_info = handler.exchange_code_for_tokens(code)
    
    # Create Credentials object from token info
    credentials = Credentials(
        token=token_info['access_token'],
        refresh_token=token_info.get('refresh_token'),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=handler.client_id,
        client_secret=handler.client_secret,
        scopes=token_info.get('scopes')
    )
    
    # Log token details for debugging
    logger.info(f"Token exchange complete:")
    logger.info(f"  - Has access_token: {bool(credentials.token)}")
    logger.info(f"  - Has refresh_token: {bool(credentials.refresh_token)}")
    logger.info(f"  - Scopes: {len(credentials.scopes) if credentials.scopes else 0} scopes")
    
    if not credentials.refresh_token:
        logger.error("⚠️  WARNING: No refresh token received from Google!")
        logger.error("⚠️  This usually means:")
        logger.error("⚠️   1. User has already authorized this app (revoke access and try again)")
        logger.error("⚠️   2. access_type='offline' was not set in authorization URL")
        logger.error("⚠️   3. prompt='consent' was not set to force refresh token")
    
    return credentials
