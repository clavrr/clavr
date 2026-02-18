"""
Integration Token Provider

Centralized utility for fetching OAuth tokens from UserIntegration table.
Used by integration tools (Slack, Asana, Notion, Linear) to get user-specific tokens.
"""
from typing import Optional, Dict, Any
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


def get_integration_token(user_id: int, provider: str) -> Optional[str]:
    """
    Get OAuth access token for a user's integration.
    
    Args:
        user_id: User ID
        provider: Integration provider name (e.g., 'slack', 'notion', 'asana', 'linear')
        
    Returns:
        Access token string or None if not found/inactive
    """
    try:
        from ..database import get_db_context
        from ..database.models import UserIntegration
        
        with get_db_context() as db:
            integration = db.query(UserIntegration).filter(
                UserIntegration.user_id == user_id,
                UserIntegration.provider == provider,
                UserIntegration.is_active == True
            ).first()
            
            if integration and integration.access_token:
                logger.debug(f"Found {provider} token for user {user_id}")
                return integration.access_token
            
            logger.debug(f"No active {provider} integration for user {user_id}")
            return None
            
    except Exception as e:
        logger.error(f"Failed to get {provider} token for user {user_id}: {e}")
        return None


def get_integration_metadata(user_id: int, provider: str) -> Optional[Dict[str, Any]]:
    """
    Get OAuth metadata for a user's integration.
    
    Args:
        user_id: User ID
        provider: Integration provider name
        
    Returns:
        Metadata dict or None if not found
    """
    try:
        from ..database import get_db_context
        from ..database.models import UserIntegration
        
        with get_db_context() as db:
            integration = db.query(UserIntegration).filter(
                UserIntegration.user_id == user_id,
                UserIntegration.provider == provider,
                UserIntegration.is_active == True
            ).first()
            
            if integration:
                return integration.integration_metadata or {}
            return None
            
    except Exception as e:
        logger.error(f"Failed to get {provider} metadata for user {user_id}: {e}")
        return None


def is_integration_connected(user_id: int, provider: str) -> bool:
    """
    Check if a user has an active integration.
    
    Args:
        user_id: User ID
        provider: Integration provider name
        
    Returns:
        True if integration is active and has a token
    """
    return get_integration_token(user_id, provider) is not None
