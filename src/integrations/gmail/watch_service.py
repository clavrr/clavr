"""
Gmail Watch Service - Real-time Email Notifications

This service sets up Gmail Push Notifications (watch API) to receive
real-time notifications when new emails arrive, enabling instant indexing.
"""
import os
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from src.utils.logger import setup_logger
from src.core.email.google_client import GoogleGmailClient
from src.utils.config import Config

logger = setup_logger(__name__)


class GmailWatchService:
    """
    Service for managing Gmail Push Notifications (watch API)
    
    Gmail Push Notifications allow real-time notifications when new emails arrive,
    eliminating the need for frequent polling and enabling instant indexing.
    
    Architecture:
    1. Set up watch subscription for user's Gmail account
    2. Gmail sends notifications to our webhook endpoint
    3. Webhook triggers immediate indexing of new emails
    
    Note: Gmail watch subscriptions expire after 7 days and need to be renewed.
    """
    
    # Gmail watch subscriptions expire after 7 days
    WATCH_EXPIRATION_DAYS = 7
    
    def __init__(self, google_client: GoogleGmailClient, webhook_url: Optional[str] = None):
        """
        Initialize Gmail Watch Service
        
        Args:
            google_client: Authenticated GoogleGmailClient instance
            webhook_url: Public URL where Gmail will send push notifications
                        If None, will use WEBHOOK_BASE_URL from environment
        """
        self.google_client = google_client
        self.webhook_url = webhook_url or os.getenv('WEBHOOK_BASE_URL')
        
        if not self.webhook_url:
            logger.warning(
                "WEBHOOK_BASE_URL not set. Gmail watch requires a public webhook URL. "
                "Set WEBHOOK_BASE_URL environment variable to enable push notifications."
            )
    
    def setup_watch(
        self,
        user_id: str = 'me',
        topic_name: Optional[str] = None,
        label_ids: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Set up Gmail watch subscription for push notifications
        
        Args:
            user_id: Gmail user ID (default: 'me' for authenticated user)
            topic_name: Google Cloud Pub/Sub topic name (optional, uses default if not provided)
            label_ids: List of label IDs to watch (default: ['INBOX'] for inbox only)
        
        Returns:
            Dict with watch response containing:
            - historyId: Starting history ID for this watch
            - expiration: Expiration timestamp (milliseconds since epoch)
        
        Raises:
            HttpError: If watch setup fails (e.g., insufficient permissions, invalid topic)
        """
        if not self.webhook_url:
            raise ValueError(
                "Webhook URL is required for Gmail watch. "
                "Set WEBHOOK_BASE_URL environment variable."
            )
        
        if not self.google_client or not self.google_client.is_available():
            raise ValueError("Gmail client is not available or not authenticated")
        
        # Default to watching inbox only for efficiency
        if label_ids is None:
            label_ids = ['INBOX']
        
        # Use default topic name if not provided
        if topic_name is None:
            topic_name = os.getenv('GMAIL_PUBSUB_TOPIC', 'gmail-notifications')
        
        try:
            logger.info(f"Setting up Gmail watch for user {user_id} with labels: {label_ids}")
            
            # Build watch request
            watch_request = {
                'topicName': topic_name,
                'labelIds': label_ids
            }
            
            # Call Gmail watch API
            response = self.google_client.service.users().watch(
                userId=user_id,
                body=watch_request
            ).execute()
            
            history_id = response.get('historyId')
            expiration_ms = response.get('expiration')
            # Convert expiration_ms to int if it's a string (Gmail API sometimes returns strings)
            if expiration_ms:
                expiration_ms = int(expiration_ms) if isinstance(expiration_ms, str) else expiration_ms
                expiration_dt = datetime.fromtimestamp(expiration_ms / 1000)
            else:
                expiration_dt = None
            
            logger.info(
                f"✅ Gmail watch setup successful! "
                f"History ID: {history_id}, "
                f"Expires: {expiration_dt}"
            )
            
            return {
                'success': True,
                'historyId': history_id,
                'expiration': expiration_ms,
                'expiration_datetime': expiration_dt.isoformat() if expiration_dt else None,
                'label_ids': label_ids,
                'topic_name': topic_name
            }
            
        except HttpError as e:
            error_details = json.loads(e.content.decode('utf-8')) if e.content else {}
            error_reason = error_details.get('error', {}).get('errors', [{}])[0].get('reason', 'unknown')
            
            if error_reason == 'insufficientPermissions':
                logger.error(
                    "❌ Gmail watch failed: Insufficient permissions. "
                    "Ensure the Gmail API scope 'https://www.googleapis.com/auth/gmail.modify' is granted."
                )
            elif error_reason == 'invalidArgument':
                logger.error(
                    "❌ Gmail watch failed: Invalid argument. "
                    "Check that the Pub/Sub topic exists and is accessible."
                )
            else:
                logger.error(f"❌ Gmail watch failed: {error_reason} - {e}")
            
            raise
    
    def stop_watch(self, user_id: str = 'me') -> Dict[str, Any]:
        """
        Stop Gmail watch subscription
        
        Args:
            user_id: Gmail user ID (default: 'me')
        
        Returns:
            Dict with stop response
        """
        try:
            logger.info(f"Stopping Gmail watch for user {user_id}")
            
            self.google_client.service.users().stop(
                userId=user_id
            ).execute()
            
            logger.info("✅ Gmail watch stopped successfully")
            
            return {
                'success': True,
                'message': 'Watch stopped successfully'
            }
            
        except HttpError as e:
            logger.error(f"❌ Failed to stop Gmail watch: {e}")
            raise
    
    def get_history(
        self,
        start_history_id: str,
        user_id: str = 'me',
        max_results: int = 100
    ) -> Dict[str, Any]:
        """
        Get Gmail history since a specific history ID
        
        This is used to process notifications and find new emails.
        
        Args:
            user_id: Gmail user ID (default: 'me')
            start_history_id: Starting history ID (from watch response or previous history)
            max_results: Maximum number of history records to return
        
        Returns:
            Dict with history records containing message changes
        """
        try:
            logger.debug(f"Fetching Gmail history since {start_history_id}")
            
            response = self.google_client.service.users().history().list(
                userId=user_id,
                startHistoryId=start_history_id,
                maxResults=max_results
            ).execute()
            
            history_records = response.get('history', [])
            next_page_token = response.get('nextPageToken')
            
            logger.info(f"Retrieved {len(history_records)} history records")
            
            # Extract message IDs from history
            message_ids = []
            for record in history_records:
                # Check for messagesAdded (new emails)
                messages_added = record.get('messagesAdded', [])
                for msg_added in messages_added:
                    message_id = msg_added.get('message', {}).get('id')
                    if message_id:
                        message_ids.append(message_id)
            
            return {
                'history_records': history_records,
                'message_ids': message_ids,
                'next_page_token': next_page_token,
                'total_records': len(history_records)
            }
            
        except HttpError as e:
            logger.error(f"Failed to fetch Gmail history: {e}")
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
        
        # Convert expiration_ms to int if it's a string
        expiration_ms = int(expiration_ms) if isinstance(expiration_ms, str) else expiration_ms
        expiration_dt = datetime.fromtimestamp(expiration_ms / 1000)
        return datetime.now() < expiration_dt
    
    def get_watch_status(self, user_id: str = 'me') -> Dict[str, Any]:
        """
        Get current watch status (if any)
        
        Note: Gmail API doesn't provide a direct way to check watch status,
        so this is a placeholder for future implementation.
        
        Args:
            user_id: Gmail user ID
        
        Returns:
            Dict with watch status information
        """
        # Gmail API doesn't have a direct "get watch status" endpoint
        # We would need to track this in our database
        return {
            'message': 'Watch status tracking requires database storage',
            'suggestion': 'Store watch expiration in user table and check periodically'
        }

