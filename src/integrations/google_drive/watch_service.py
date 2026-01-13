"""
Drive Watch Service - Real-time File Change Notifications

This service sets up Google Drive Push Notifications (watch API) to receive
real-time notifications when files are created, modified, or deleted,
enabling instant indexing of Drive changes.
"""
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from src.utils.logger import setup_logger
from src.integrations.google_drive.client import GoogleDriveClient

logger = setup_logger(__name__)


class DriveWatchService:
    """
    Service for managing Google Drive Push Notifications (watch API)
    
    Google Drive can send push notifications to a webhook URL when files change.
    This uses the changes.watch() API to monitor the user's Drive for any changes.
    
    Architecture:
    1. Set up watch subscription on Drive changes
    2. Drive sends notifications to our webhook endpoint when files change
    3. Webhook triggers immediate indexing of changed files
    
    Note: Drive watch subscriptions expire after 1 week by default and need renewal.
    """
    
    # Drive watch subscriptions expire after ~7 days (configurable up to 1 day originally, now longer)
    # We request max expiration and renew proactively
    WATCH_EXPIRATION_MS = 7 * 24 * 60 * 60 * 1000  # 7 days in milliseconds
    
    def __init__(self, drive_client: GoogleDriveClient, webhook_url: Optional[str] = None):
        """
        Initialize Drive Watch Service
        
        Args:
            drive_client: Authenticated GoogleDriveClient instance
            webhook_url: Public URL where Drive will send push notifications
                        If None, will use WEBHOOK_BASE_URL from environment
        """
        self.drive_client = drive_client
        self.webhook_url = webhook_url or os.getenv('WEBHOOK_BASE_URL')
        
        if not self.webhook_url:
            logger.warning(
                "WEBHOOK_BASE_URL not set. Drive watch requires a public webhook URL. "
                "Set WEBHOOK_BASE_URL environment variable to enable push notifications."
            )
    
    def setup_watch(
        self,
        user_id: int,
        channel_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Set up Drive watch subscription for push notifications on changes.
        
        This uses the changes.watch() API to monitor all file changes in the user's
        Drive. When a file is created, modified, or deleted, Drive will send a
        notification to our webhook.
        
        Args:
            user_id: User ID for channel token identification
            channel_token: Optional token to include in notifications (default: auto-generated)
        
        Returns:
            Dict with watch response containing:
            - channel_id: Unique channel identifier
            - resource_id: Resource being watched
            - expiration: Expiration timestamp
            - start_page_token: Token to use for fetching changes
        
        Raises:
            ValueError: If webhook URL not configured
            HttpError: If watch setup fails
        """
        if not self.webhook_url:
            raise ValueError(
                "Webhook URL is required for Drive watch. "
                "Set WEBHOOK_BASE_URL environment variable."
            )
        
        if not self.drive_client or not self.drive_client.service:
            raise ValueError("Drive client is not available or not authenticated")
        
        try:
            # Generate unique channel ID
            channel_id = f"drive_watch_{user_id}_{uuid.uuid4().hex[:8]}"
            
            # Generate channel token if not provided (includes user_id for identification)
            if channel_token is None:
                channel_token = f"user_{user_id}_{int(datetime.now().timestamp())}"
            
            # Build webhook URL for Drive notifications
            webhook_endpoint = self.webhook_url.rstrip('/') + '/api/drive/push/notification'
            
            logger.info(
                f"Setting up Drive watch for user {user_id}, "
                f"webhook: {webhook_endpoint}"
            )
            
            # First, get the start page token for changes
            start_page_token_response = self.drive_client.service.changes().getStartPageToken().execute()
            start_page_token = start_page_token_response.get('startPageToken')
            
            # Calculate expiration (request max: 1 week from now)
            expiration_ms = int((datetime.now() + timedelta(days=7)).timestamp() * 1000)
            
            # Set up watch on changes
            watch_request = {
                'id': channel_id,
                'type': 'web_hook',
                'address': webhook_endpoint,
                'token': channel_token,
                'expiration': str(expiration_ms)
            }
            
            response = self.drive_client.service.changes().watch(
                pageToken=start_page_token,
                body=watch_request
            ).execute()
            
            resource_id = response.get('resourceId')
            actual_expiration = response.get('expiration')
            
            # Parse expiration for logging
            if actual_expiration:
                expiration_int = int(actual_expiration) if isinstance(actual_expiration, str) else actual_expiration
                expiration_dt = datetime.fromtimestamp(expiration_int / 1000)
            else:
                expiration_dt = None
            
            logger.info(
                f"✅ Drive watch setup successful! "
                f"Channel: {channel_id}, Resource: {resource_id}, "
                f"Expires: {expiration_dt}"
            )
            
            return {
                'success': True,
                'channel_id': channel_id,
                'resource_id': resource_id,
                'expiration': actual_expiration,
                'expiration_datetime': expiration_dt.isoformat() if expiration_dt else None,
                'start_page_token': start_page_token,
                'user_id': user_id,
                'channel_token': channel_token
            }
            
        except Exception as e:
            logger.error(f"❌ Drive watch setup failed: {e}")
            raise
    
    def stop_watch(self, channel_id: str, resource_id: str) -> Dict[str, Any]:
        """
        Stop a Drive watch subscription
        
        Args:
            channel_id: Channel ID from setup_watch response
            resource_id: Resource ID from setup_watch response
        
        Returns:
            Dict with stop response
        """
        try:
            logger.info(f"Stopping Drive watch channel: {channel_id}")
            
            stop_request = {
                'id': channel_id,
                'resourceId': resource_id
            }
            
            self.drive_client.service.channels().stop(body=stop_request).execute()
            
            logger.info("✅ Drive watch stopped successfully")
            
            return {
                'success': True,
                'message': 'Watch stopped successfully',
                'channel_id': channel_id
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to stop Drive watch: {e}")
            raise
    
    def is_watch_active(self, expiration_ms: Optional[int]) -> bool:
        """
        Check if a watch subscription is still active
        
        Args:
            expiration_ms: Expiration timestamp in milliseconds (from watch response)
        
        Returns:
            True if watch is still active, False if expired
        """
        if not expiration_ms:
            return False
        
        expiration_ms = int(expiration_ms) if isinstance(expiration_ms, str) else expiration_ms
        expiration_dt = datetime.fromtimestamp(expiration_ms / 1000)
        return datetime.now() < expiration_dt
    
    def needs_renewal(self, expiration_ms: Optional[int], buffer_hours: int = 24) -> bool:
        """
        Check if watch needs renewal soon
        
        Args:
            expiration_ms: Expiration timestamp in milliseconds
            buffer_hours: Hours before expiration to trigger renewal
        
        Returns:
            True if watch should be renewed
        """
        if not expiration_ms:
            return True
        
        expiration_ms = int(expiration_ms) if isinstance(expiration_ms, str) else expiration_ms
        expiration_dt = datetime.fromtimestamp(expiration_ms / 1000)
        buffer_dt = datetime.now() + timedelta(hours=buffer_hours)
        
        return buffer_dt >= expiration_dt
