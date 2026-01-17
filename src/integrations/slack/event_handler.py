"""
Slack Event Handler

Handles Slack events, specifically @clavr mentions.
Extracts user query and dispatches to orchestrator.
"""
import re
from typing import Dict, Any, Optional
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from .client import SlackClient
from .orchestrator import clavr_orchestrator
from .config import SlackConfig
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class SlackEventHandler:
    """
    Handles Slack events, specifically app_mention events.
    
    Processes @clavr mentions and routes them to the orchestrator.
    """
    
    def __init__(self, slack_client: SlackClient, config: Optional[Any] = None, db: Optional[Any] = None):
        """
        Initialize Slack event handler.
        
        Args:
            slack_client: SlackClient instance
            config: Optional configuration object
            db: Optional database session
        """
        self.slack_client = slack_client
        self.config = config
        self.db = db
        self.bot_name = SlackConfig.BOT_NAME
        self.bot_user_id = SlackConfig.BOT_USER_ID
        
        logger.info(f"Slack event handler initialized (bot_name={self.bot_name})")
    
    def handle_app_mention(self, client: SlackClient, req: SocketModeRequest):
        """
        Handle app_mention event (when @clavr is mentioned).
        
        This is the main entry point for Slack interactions.
        
        Args:
            client: SlackClient instance
            req: SocketModeRequest containing event payload
        """
        try:
            # Extract event data
            event = req.payload.get('event', {})
            user_id = event.get('user')  # Slack user ID
            channel_id = event.get('channel')
            text = event.get('text', '')
            thread_ts = event.get('ts')  # Message timestamp (for threading)
            
            logger.info(f"[SLACK] Received app_mention from user {user_id} in channel {channel_id}")
            logger.debug(f"[SLACK] Event text: {text}")
            
            # Extract user query (remove @clavr mention)
            user_query = self._extract_user_query(text)
            
            if not user_query:
                logger.warning("[SLACK] No query found after removing bot mention")
                response_text = "Hi! I'm here to help. What would you like me to do?"
                self.slack_client.post_message(channel_id, response_text, thread_ts=thread_ts)
                req.respond(SocketModeResponse(envelope_id=req.envelope_id))
                return
            
            logger.info(f"[SLACK] Processing query: {user_query}")
            
            # Acknowledge the event immediately (Slack requires quick acknowledgment)
            req.respond(SocketModeResponse(envelope_id=req.envelope_id))
            
            # Process query asynchronously
            import asyncio
            asyncio.create_task(
                self._process_query_async(user_query, user_id, channel_id, thread_ts)
            )
            
        except Exception as e:
            logger.error(f"[SLACK] Error handling app_mention: {e}", exc_info=True)
            # Try to respond with error message
            try:
                event = req.payload.get('event', {})
                channel_id = event.get('channel')
                thread_ts = event.get('ts')
                error_msg = "Sorry, I encountered an error processing your request. Please try again."
                self.slack_client.post_message(channel_id, error_msg, thread_ts=thread_ts)
            except Exception as notify_err:
                logger.debug(f"[SLACK] Failed to send error message to channel: {notify_err}")
    
    async def _process_query_async(
        self,
        user_query: str,
        slack_user_id: str,
        channel_id: str,
        thread_ts: Optional[str] = None
    ):
        """
        Process user query asynchronously and post response to Slack.
        
        Args:
            user_query: User's query text
            slack_user_id: Slack user ID
            channel_id: Slack channel ID
            thread_ts: Optional thread timestamp
        """
        try:
            # Post "thinking" message
            thinking_msg = self.slack_client.post_message(
                channel_id,
                "Thinking...",
                thread_ts=thread_ts
            )
            thinking_ts = thinking_msg.get('ts') if thinking_msg.get('ok') else None
            
            # Process query through orchestrator
            response = await clavr_orchestrator(
                user_query=user_query,
                slack_user_id=slack_user_id,
                slack_channel_id=channel_id,
                config=self.config,
                db=self.db,
                slack_client=self.slack_client
            )
            
            # Update thinking message with actual response (or post new message)
            if thinking_ts:
                # Update the thinking message
                try:
                    self.slack_client.web_client.chat_update(
                        channel=channel_id,
                        ts=thinking_ts,
                        text=response
                    )
                except Exception as e:
                    logger.warning(f"Failed to update message, posting new one: {e}")
                    self.slack_client.post_message(channel_id, response, thread_ts=thread_ts)
            else:
                # Post new message
                self.slack_client.post_message(channel_id, response, thread_ts=thread_ts)
            
            logger.info(f"[SLACK] Posted response to channel {channel_id}")
            
        except Exception as e:
            logger.error(f"[SLACK] Error processing query: {e}", exc_info=True)
            error_msg = f"Sorry, I encountered an error: {str(e)}"
            self.slack_client.post_message(channel_id, error_msg, thread_ts=thread_ts)
    
    def _extract_user_query(self, text: str) -> str:
        """
        Extract user query from Slack message text, removing @clavr mention.
        
        Args:
            text: Full message text including @clavr mention
            
        Returns:
            Cleaned user query without bot mention
        """
        # Remove @clavr or @<bot_user_id> mentions
        # Pattern: <@U1234567890> or @clavr
        text = re.sub(r'<@[A-Z0-9]+>', '', text)  # Remove user ID mentions
        text = re.sub(rf'@{self.bot_name}', '', text, flags=re.IGNORECASE)  # Remove bot name mention
        
        # Clean up whitespace
        text = text.strip()
        
        return text

