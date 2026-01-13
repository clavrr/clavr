"""
Gmail Watch Helper - Utilities for setting up Gmail Push Notifications

This module provides helper functions to set up Gmail watch subscriptions
when users authenticate, enabling real-time email indexing.
"""
import os
from typing import Optional, Dict, Any
from datetime import datetime

from ..utils.logger import setup_logger
from ..core.email.google_client import GoogleGmailClient
from ..integrations.gmail.watch_service import GmailWatchService
from ..utils.config import Config

logger = setup_logger(__name__)


async def setup_gmail_watch_for_user(
    user_id: int,
    google_client: GoogleGmailClient,
    config: Optional[Config] = None,
    label_ids: Optional[list] = None
) -> Dict[str, Any]:
    """
    Set up Gmail watch subscription for a user to enable real-time email indexing
    
    This should be called after a user authenticates with Gmail to enable
    push notifications for new emails.
    
    Args:
        user_id: User ID
        google_client: Authenticated GoogleGmailClient instance
        config: Application config (optional)
        label_ids: List of Gmail label IDs to watch (default: ['INBOX'])
    
    Returns:
        Dict with watch setup results:
        - success: bool
        - historyId: str (if successful)
        - expiration: int (expiration timestamp in ms)
        - expiration_datetime: str (ISO format)
        - error: str (if failed)
    """
    import asyncio
    
    try:
        # Get webhook URL from config or environment
        webhook_url = None
        if config:
            # Try to get from config object (handle dict or object access)
            if isinstance(config, dict):
                webhook_url = config.get('WEBHOOK_BASE_URL') or config.get('webhook_base_url')
            elif hasattr(config, 'webhook_base_url'):
                webhook_url = getattr(config, 'webhook_base_url', None) or getattr(config, 'WEBHOOK_BASE_URL', None)
        
        # Fallback to environment variable
        if not webhook_url:
            webhook_url = os.getenv('WEBHOOK_BASE_URL')
        
        if not webhook_url:
            logger.warning(
                f"WEBHOOK_BASE_URL not set. Cannot set up Gmail watch for user {user_id}. "
                "Real-time indexing will use polling fallback."
            )
            return {
                'success': False,
                'error': 'WEBHOOK_BASE_URL not configured',
                'fallback': 'polling'
            }
        
        # Ensure webhook URL includes the Gmail push endpoint
        # Use simple string concatenation to be safe
        if not webhook_url.endswith('/api/gmail/push/notification'):
            base = webhook_url.rstrip('/')
            webhook_url = f"{base}/api/gmail/push/notification"
        
        # Create watch service
        watch_service = GmailWatchService(
            google_client=google_client,
            webhook_url=webhook_url
        )
        
        # Set up watch with user-specific channel token
        # Include user_id in token for identification in webhook handler
        channel_token = f"user_{user_id}_{datetime.now().timestamp()}"
        
        # Default to watching inbox only for efficiency
        if label_ids is None:
            label_ids = ['INBOX']
        
        logger.info(
            f"Setting up Gmail watch for user {user_id} "
            f"with labels: {label_ids}"
        )
        
        # Set up watch subscription - RUN IN THREAD TO AVOID BLOCKING
        # Gmail API calls are synchronous and can take seconds
        result = await asyncio.to_thread(
            watch_service.setup_watch,
            user_id='me',
            label_ids=label_ids
        )
        
        logger.info(
            f"✅ Gmail watch set up successfully for user {user_id}. "
            f"Expires: {result.get('expiration_datetime')}"
        )
        
        return {
            'success': True,
            **result,
            'user_id': user_id,
            'channel_token': channel_token
        }
        
    except ValueError as e:
        # Expected error when GOOGLE_CLOUD_PROJECT_ID is not set
        # This is a configuration issue, not a runtime error
        error_msg = str(e)
        if 'Pub/Sub topic name' in error_msg or 'GOOGLE_CLOUD_PROJECT_ID' in error_msg:
            logger.warning(
                f"⚠️ Gmail watch setup failed for user {user_id}: {error_msg}"
            )
            logger.info("   Will use polling fallback for real-time indexing")
        else:
            logger.warning(
                f"⚠️ Gmail watch setup failed for user {user_id}: {error_msg}"
            )
            logger.info("   Will use polling fallback for real-time indexing")
        return {
            'success': False,
            'error': error_msg,
            'user_id': user_id,
            'fallback': 'polling'  # Will fall back to polling
        }
    except Exception as e:
        # Unexpected errors - log with traceback for debugging
        logger.error(
            f"❌ Failed to set up Gmail watch for user {user_id}: {e}",
            exc_info=True
        )
        return {
            'success': False,
            'error': str(e),
            'user_id': user_id,
            'fallback': 'polling'  # Will fall back to polling
        }


async def renew_gmail_watch_if_needed(
    user_id: int,
    google_client: GoogleGmailClient,
    current_expiration_ms: Optional[int] = None
) -> Dict[str, Any]:
    """
    Renew Gmail watch subscription if it's about to expire
    
    Gmail watch subscriptions expire after 7 days. This function checks
    if renewal is needed and sets up a new watch if necessary.
    
    Args:
        user_id: User ID
        google_client: Authenticated GoogleGmailClient instance
        current_expiration_ms: Current expiration timestamp in milliseconds
    
    Returns:
        Dict with renewal results
    """
    try:
        watch_service = GmailWatchService(google_client=google_client)
        
        # Check if watch is still active
        if current_expiration_ms:
            is_active = watch_service.is_watch_active(current_expiration_ms)
            if is_active:
                logger.debug(f"Gmail watch for user {user_id} is still active")
                return {
                    'success': True,
                    'renewed': False,
                    'message': 'Watch still active'
                }
        
        # Watch expired or not active - renew it
        logger.info(f"Renewing Gmail watch for user {user_id}")
        return await setup_gmail_watch_for_user(
            user_id=user_id,
            google_client=google_client
        )
        
    except Exception as e:
        logger.error(f"Failed to renew Gmail watch for user {user_id}: {e}")
        return {
            'success': False,
            'error': str(e)
        }

