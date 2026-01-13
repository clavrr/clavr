"""
Drive Watch Helper - Utilities for setting up Google Drive Push Notifications

This module provides helper functions to set up Drive watch subscriptions
when users authenticate, enabling real-time file indexing.
"""
import os
from typing import Optional, Dict, Any
from datetime import datetime

from ..utils.logger import setup_logger
from ..integrations.google_drive.client import GoogleDriveClient
from ..integrations.google_drive.watch_service import DriveWatchService
from ..utils.config import Config

logger = setup_logger(__name__)


async def setup_drive_watch_for_user(
    user_id: int,
    drive_client: GoogleDriveClient,
    config: Optional[Config] = None
) -> Dict[str, Any]:
    """
    Set up Drive watch subscription for a user to enable real-time file indexing
    
    This should be called after a user authenticates with Google Drive to enable
    push notifications for file changes.
    
    Args:
        user_id: User ID
        drive_client: Authenticated GoogleDriveClient instance
        config: Application config (optional)
    
    Returns:
        Dict with watch setup results:
        - success: bool
        - channel_id: str (if successful)
        - resource_id: str (if successful)
        - expiration: int (expiration timestamp in ms)
        - expiration_datetime: str (ISO format)
        - error: str (if failed)
    """
    import asyncio
    
    try:
        # Get webhook URL from config or environment
        webhook_url = None
        if config:
            if isinstance(config, dict):
                webhook_url = config.get('WEBHOOK_BASE_URL') or config.get('webhook_base_url')
            elif hasattr(config, 'webhook_base_url'):
                webhook_url = getattr(config, 'webhook_base_url', None) or getattr(config, 'WEBHOOK_BASE_URL', None)
        
        # Fallback to environment variable
        if not webhook_url:
            webhook_url = os.getenv('WEBHOOK_BASE_URL')
        
        if not webhook_url:
            logger.warning(
                f"WEBHOOK_BASE_URL not set. Cannot set up Drive watch for user {user_id}. "
                "Real-time indexing will use polling fallback."
            )
            return {
                'success': False,
                'error': 'WEBHOOK_BASE_URL not configured',
                'fallback': 'polling'
            }
        
        # Create watch service
        watch_service = DriveWatchService(
            drive_client=drive_client,
            webhook_url=webhook_url
        )
        
        logger.info(f"Setting up Drive watch for user {user_id}")
        
        # Set up watch subscription - RUN IN THREAD TO AVOID BLOCKING
        result = await asyncio.to_thread(
            watch_service.setup_watch,
            user_id=user_id
        )
        
        logger.info(
            f"✅ Drive watch set up successfully for user {user_id}. "
            f"Expires: {result.get('expiration_datetime')}"
        )
        
        return result
        
    except ValueError as e:
        error_msg = str(e)
        logger.warning(
            f"⚠️ Drive watch setup failed for user {user_id}: {error_msg}"
        )
        logger.info("   Will use polling fallback for real-time indexing")
        return {
            'success': False,
            'error': error_msg,
            'user_id': user_id,
            'fallback': 'polling'
        }
    except Exception as e:
        logger.error(
            f"❌ Failed to set up Drive watch for user {user_id}: {e}",
            exc_info=True
        )
        return {
            'success': False,
            'error': str(e),
            'user_id': user_id,
            'fallback': 'polling'
        }


async def renew_drive_watch_if_needed(
    user_id: int,
    drive_client: GoogleDriveClient,
    current_expiration_ms: Optional[int] = None,
    current_channel_id: Optional[str] = None,
    current_resource_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Renew Drive watch subscription if it's about to expire
    
    Drive watch subscriptions expire after ~7 days. This function checks
    if renewal is needed and sets up a new watch if necessary.
    
    Args:
        user_id: User ID
        drive_client: Authenticated GoogleDriveClient instance
        current_expiration_ms: Current expiration timestamp in milliseconds
        current_channel_id: Current channel ID (to stop old watch)
        current_resource_id: Current resource ID (to stop old watch)
    
    Returns:
        Dict with renewal results
    """
    try:
        watch_service = DriveWatchService(drive_client=drive_client)
        
        # Check if watch needs renewal (expires within 24 hours)
        if current_expiration_ms and not watch_service.needs_renewal(current_expiration_ms):
            logger.debug(f"Drive watch for user {user_id} doesn't need renewal yet")
            return {
                'success': True,
                'renewed': False,
                'message': 'Watch still active'
            }
        
        # Stop old watch if we have the IDs
        if current_channel_id and current_resource_id:
            try:
                watch_service.stop_watch(current_channel_id, current_resource_id)
            except Exception as e:
                logger.debug(f"Could not stop old watch (may have already expired): {e}")
        
        # Set up new watch
        logger.info(f"Renewing Drive watch for user {user_id}")
        return await setup_drive_watch_for_user(
            user_id=user_id,
            drive_client=drive_client
        )
        
    except Exception as e:
        logger.error(f"Failed to renew Drive watch for user {user_id}: {e}")
        return {
            'success': False,
            'error': str(e)
        }
