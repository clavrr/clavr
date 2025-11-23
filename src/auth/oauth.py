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

# OAuth scopes
SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/tasks',
]


class GoogleOAuthHandler:
    """
    Handle Google OAuth 2.0 authentication
    
    Simple wrapper around Google's OAuth library with no unnecessary abstractions.
    """
    
    def __init__(self):
        self.client_id = os.getenv('GOOGLE_CLIENT_ID')
        self.client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        self.redirect_uri = os.getenv(
            'GOOGLE_REDIRECT_URI',
            'http://localhost:8000/auth/google/callback'
        )
        
        if not self.client_id or not self.client_secret:
            logger.warning("Google OAuth credentials not configured")
    
    def _get_client_config(self) -> dict:
        """Get client configuration for OAuth flow"""
        return {
            "web": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self.redirect_uri]
            }
        }
    
    def get_authorization_url(self, state: Optional[str] = None) -> Tuple[str, str]:
        """
        Generate authorization URL for OAuth flow
        
        Returns:
            (authorization_url, state) tuple
        """
        state = state or secrets.token_urlsafe(32)
        
        flow = Flow.from_client_config(
            self._get_client_config(),
            scopes=SCOPES,
            redirect_uri=self.redirect_uri
        )
        
        authorization_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            state=state,
            prompt='consent'  # Get refresh token
        )
        
        logger.info(f"Generated authorization URL with state: {state[:10]}...")
        return authorization_url, state
    
    def exchange_code_for_tokens(self, code: str) -> Dict[str, str]:
        """
        Exchange authorization code for tokens
        
        Args:
            code: Authorization code from callback
            
        Returns:
            Token information dict
        """
        flow = Flow.from_client_config(
            self._get_client_config(),
            scopes=SCOPES,
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
    
    Args:
        code: Authorization code from OAuth callback
        
    Returns:
        Google Credentials object
    """
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    redirect_uri = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:8000/api/auth/google/callback')
    
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri]
            }
        },
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    
    flow.fetch_token(code=code)
    credentials = flow.credentials
    
    # Log token details for debugging
    logger.info(f"Token exchange complete:")
    logger.info(f"  - Has access_token: {bool(credentials.token)}")
    logger.info(f"  - Has refresh_token: {bool(credentials.refresh_token)}")
    logger.info(f"  - Token expiry: {credentials.expiry}")
    logger.info(f"  - Scopes: {len(credentials.scopes) if credentials.scopes else 0} scopes")
    
    if not credentials.refresh_token:
        logger.error("⚠️  WARNING: No refresh token received from Google!")
        logger.error("⚠️  This usually means:")
        logger.error("⚠️   1. User has already authorized this app (revoke access and try again)")
        logger.error("⚠️   2. access_type='offline' was not set in authorization URL")
        logger.error("⚠️   3. prompt='consent' was not set to force refresh token")
    
    return credentials

