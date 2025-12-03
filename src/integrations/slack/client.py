"""
Slack Client Wrapper

Wraps Slack SDK client for Socket Mode communication.
Handles WebSocket connections and message posting.
"""
from typing import Optional, Dict, Any
import asyncio

try:
    from slack_sdk import WebClient
    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse
    SLACK_SDK_AVAILABLE = True
except ImportError:
    SLACK_SDK_AVAILABLE = False
    WebClient = None
    SocketModeClient = None
    SocketModeRequest = None
    SocketModeResponse = None

from .config import SlackConfig
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class SlackClient:
    """
    Slack client wrapper for Socket Mode communication.
    
    Handles:
    - WebSocket connection via Socket Mode
    - Message posting via WebClient
    - Event listening and dispatching
    """
    
    def __init__(self, app_token: Optional[str] = None, bot_token: Optional[str] = None):
        """
        Initialize Slack client.
        
        Args:
            app_token: Slack App-Level Token (xapp-*) - defaults to SLACK_APP_TOKEN env var
            bot_token: Slack Bot User OAuth Token (xoxb-*) - defaults to SLACK_BOT_TOKEN env var
        """
        if not SLACK_SDK_AVAILABLE:
            raise ImportError(
                "slack_sdk is not installed. Install it with: pip install slack-sdk"
            )
        
        self.app_token = app_token or SlackConfig.SLACK_APP_TOKEN
        self.bot_token = bot_token or SlackConfig.SLACK_BOT_TOKEN
        
        if not self.app_token:
            raise ValueError("SLACK_APP_TOKEN is required (set environment variable or pass as parameter)")
        
        if not self.bot_token:
            raise ValueError("SLACK_BOT_TOKEN is required (set environment variable or pass as parameter)")
        
        # Initialize WebClient for API calls (posting messages, reading user info, etc.)
        # Type: ignore since we've already checked SLACK_SDK_AVAILABLE
        self.web_client = WebClient(token=self.bot_token)  # type: ignore
        
        # Initialize SocketModeClient for receiving events
        self.socket_client = SocketModeClient(  # type: ignore
            app_token=self.app_token,
            web_client=self.web_client
        )
        
        logger.info("Slack client initialized (Socket Mode)")
    
    def start(self):
        """Start Socket Mode client (blocking)"""
        logger.info("Starting Slack Socket Mode client...")
        self.socket_client.connect()
        logger.info("Slack Socket Mode client connected")
    
    async def start_async(self):
        """Start Socket Mode client (async)"""
        logger.info("Starting Slack Socket Mode client (async)...")
        # Socket Mode client runs in a separate thread, so we just connect
        self.socket_client.connect()
        logger.info("Slack Socket Mode client connected")
    
    def stop(self):
        """Stop Socket Mode client"""
        logger.info("Stopping Slack Socket Mode client...")
        if self.socket_client:
            self.socket_client.disconnect()
        logger.info("Slack Socket Mode client disconnected")
    
    def post_message(
        self,
        channel: str,
        text: str,
        thread_ts: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Post a message to a Slack channel or DM.
        
        Args:
            channel: Channel ID or DM ID
            text: Message text to post
            thread_ts: Optional thread timestamp to reply in thread
            
        Returns:
            API response dictionary
        """
        try:
            response = self.web_client.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=thread_ts
            )
            
            if response.get('ok'):
                logger.info(f"Posted message to channel {channel}")
                return response
            else:
                error = response.get('error', 'Unknown error')
                logger.error(f"Failed to post message: {error}")
                return response
                
        except Exception as e:
            logger.error(f"Error posting message to Slack: {e}", exc_info=True)
            raise
    
    def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user information from Slack API.
        
        Uses users:read.email scope to get user email for contact resolution.
        
        Args:
            user_id: Slack user ID
            
        Returns:
            User info dictionary with email, name, etc., or None if not found
        """
        try:
            response = self.web_client.users_info(user=user_id)
            
            if response.get('ok'):
                user = response.get('user', {})
                logger.debug(f"Retrieved user info for {user_id}: {user.get('name', 'unknown')}")
                return user
            else:
                error = response.get('error', 'Unknown error')
                logger.warning(f"Failed to get user info for {user_id}: {error}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting user info from Slack: {e}", exc_info=True)
            return None
    
    def get_channel_info(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """
        Get channel information.
        
        Args:
            channel_id: Slack channel ID
            
        Returns:
            Channel info dictionary or None if not found
        """
        try:
            response = self.web_client.conversations_info(channel=channel_id)
            
            if response.get('ok'):
                channel = response.get('channel', {})
                logger.debug(f"Retrieved channel info for {channel_id}: {channel.get('name', 'unknown')}")
                return channel
            else:
                error = response.get('error', 'Unknown error')
                logger.warning(f"Failed to get channel info for {channel_id}: {error}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting channel info from Slack: {e}", exc_info=True)
            return None
    
    def register_event_handler(self, event_type: str, handler):
        """
        Register an event handler for a specific event type.
        
        Args:
            event_type: Event type (e.g., 'app_mention', 'message')
            handler: Handler function that takes (client, req) parameters
        """
        self.socket_client.socket_mode_request_listeners.append(
            (event_type, handler)
        )
        logger.info(f"Registered event handler for {event_type}")

