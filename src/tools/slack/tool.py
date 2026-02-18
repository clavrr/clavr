"""
Slack Tool - LangChain tool for Slack interaction
"""
import asyncio
from typing import Optional, Any, Type
from langchain.tools import BaseTool
from pydantic import Field, BaseModel

from ...utils.logger import setup_logger
from ...utils.config import Config, load_config

logger = setup_logger(__name__)

class SlackInput(BaseModel):
    """Input for SlackTool."""
    action: str = Field(description="Action to perform (list, search, send, reply)")
    query: Optional[str] = Field(default="", description="Query or message text")
    channel: Optional[str] = Field(default=None, description="Channel ID or name")
    user: Optional[str] = Field(default=None, description="User ID or name")
    thread_ts: Optional[str] = Field(default=None, description="Thread timestamp for replies")
    limit: Optional[int] = Field(default=10, description="Result limit")
    status_text: Optional[str] = Field(default=None, description="Status text for set_status action")
    status_emoji: Optional[str] = Field(default=None, description="Status emoji for set_status action")
    expiration: Optional[int] = Field(default=0, description="Status expiration timestamp (0 for none)")

class SlackTool(BaseTool):
    """
    Slack interaction tool wrapping Slack integration services.
    
    Actions:
    - list: List recent messages in a channel
    - search: Search for messages or users
    - send: Send a new message to a channel or user
    - reply: Reply to a specific thread
    - set_status: Set user's status (text and emoji)
    """
    
    name: str = "slack"
    description: str = "Slack interaction (send messages, list channels, search). Use this for Slack-related queries."
    args_schema: Type[BaseModel] = SlackInput
    
    config: Optional[Config] = Field(default=None, exclude=True)
    user_id: int = Field(description="User ID - required for multi-tenancy", exclude=True)
    _slack_client: Any = None
    
    def __init__(self, config: Optional[Config] = None, user_id: int = None, **kwargs):
        if user_id is None:
            raise ValueError("user_id is required for SlackTool - cannot default to 1 for multi-tenancy")
        kwargs['user_id'] = user_id
        if config:
            kwargs['config'] = config
        super().__init__(**kwargs)
        self.config = config or load_config()
        self.user_id = user_id
        self._slack_client = None

    @property
    def slack_client(self):
        """Lazy initialization of Slack client with user-specific OAuth token."""
        if self._slack_client is None:
            try:
                from ...integrations.slack.client import SlackClient
                from ...core.integration_tokens import get_integration_token
                
                # Get user-specific token from UserIntegration
                access_token = get_integration_token(self.user_id, 'slack')
                if not access_token:
                    logger.debug(f"[SlackTool] No Slack token for user {self.user_id}")
                    return None
                
                # Use OAuth token (no Socket Mode for OAuth-based bots)
                self._slack_client = SlackClient(bot_token=access_token, skip_socket_mode=True)
            except Exception as e:
                logger.error(f"Failed to initialize SlackClient: {e}")
                self._slack_client = None
        return self._slack_client

    def _run(self, action: str = "list", query: str = "", **kwargs) -> str:
        """Execute Slack tool action."""
        if not self.slack_client:
            return "[INTEGRATION_REQUIRED] Slack permission not granted. Please enable Slack integration in Settings."

        try:
            if action == "send":
                channel = kwargs.get("channel") or "general"
                text = query or kwargs.get("text")
                if not text:
                    return "Error: Message text is required for 'send' action."
                
                resp = self.slack_client.post_message(channel=channel, text=text)
                if resp.get('ok'):
                    return f"Message sent to Slack channel {channel}."
                return f"Failed to send message: {resp.get('error', 'Unknown error')}"

            elif action == "reply":
                channel = kwargs.get("channel")
                thread_ts = kwargs.get("thread_ts")
                text = query or kwargs.get("text")
                if not channel or not thread_ts or not text:
                    return "Error: channel, thread_ts, and text are required for 'reply' action."
                
                resp = self.slack_client.post_message(channel=channel, text=text, thread_ts=thread_ts)
                if resp.get('ok'):
                    return "Reply sent to Slack thread."
                return f"Failed to send reply: {resp.get('error', 'Unknown error')}"

            elif action == "search":
                # For now, searching is a placeholder as the client doesn't have a search method yet
                # We can use the orchestrator logic or direct API if needed
                return f"Searching Slack for '{query}'... (Feature refinement in progress)"

            elif action == "list":
                # Listing channels or recent messages
                return "Listing recent Slack activity... (Feature refinement in progress)"

            elif action == "set_status":
                status_text = kwargs.get("status_text", "")
                status_emoji = kwargs.get("status_emoji", "")
                expiration = kwargs.get("expiration", 0)
                
                # Resolve Slack user ID from internal user_id
                slack_user_id = self._resolve_slack_user_id()
                
                if not slack_user_id:
                    return "Error: Could not resolve your Slack user ID. Please ensure Slack integration is configured."

                # Get user's OAuth token for status updates (requires users.profile:write scope)
                from ...core.integration_tokens import get_integration_token
                user_token = get_integration_token(self.user_id, 'slack')
                
                if not user_token:
                    return "[INTEGRATION_REQUIRED] Slack permission not granted. Please reconnect Slack with the 'users.profile:write' scope."

                resp = self.slack_client.set_user_status(
                    user_id=slack_user_id,
                    status_text=status_text,
                    status_emoji=status_emoji,
                    expiration=expiration,
                    user_token=user_token
                )
                
                if resp.get('ok'):
                    return f"Status updated to: {status_emoji} {status_text}"
                return f"Failed to update status: {resp.get('error', 'Unknown error')}"

            else:
                return f"Unknown action: {action}. Supported: send, reply, search, list"

        except Exception as e:
            logger.error(f"Slack tool error: {e}", exc_info=True)
            return f"Error executing Slack action: {str(e)}"
    
    def _resolve_slack_user_id(self) -> Optional[str]:
        """
        Resolve internal user_id to Slack user ID.
        
        Strategy:
        1. Check UserIntegration.integration_metadata for cached slack_user_id
        2. Fall back to Slack API lookup by email if not cached
        3. Cache result in integration_metadata for future lookups
        
        Returns:
            Slack user ID string (e.g. 'U1234567890') or None
        """
        try:
            from ...database import get_db_context
            from ...database.models import UserIntegration, User
            
            with get_db_context() as db:
                # Check for cached Slack ID in UserIntegration metadata
                integration = db.query(UserIntegration).filter(
                    UserIntegration.user_id == self.user_id,
                    UserIntegration.provider == 'slack'
                ).first()
                
                if integration and integration.integration_metadata:
                    cached_id = integration.integration_metadata.get('slack_user_id')
                    if cached_id:
                        logger.debug(f"[SlackTool] Found cached Slack ID for user {self.user_id}")
                        return cached_id
                
                # Fall back to Slack API lookup by email
                user = db.query(User).filter(User.id == self.user_id).first()
                if not user or not user.email:
                    logger.warning(f"[SlackTool] No email found for user {self.user_id}")
                    return None
                
                # Query Slack API by email
                if self.slack_client and getattr(self.slack_client, 'web_client', None):
                    try:
                        resp = self.slack_client.web_client.users_lookupByEmail(email=user.email)
                        
                        if resp.get('ok'):
                            slack_user_id = resp.get('user', {}).get('id')
                            logger.info(f"[SlackTool] Resolved Slack ID for {user.email}: {slack_user_id}")
                            
                            # Cache in integration metadata for future lookups
                            if slack_user_id and integration:
                                meta = dict(integration.integration_metadata or {})
                                meta['slack_user_id'] = slack_user_id
                                integration.integration_metadata = meta
                                db.commit()
                                logger.debug(f"[SlackTool] Cached Slack ID in UserIntegration")
                            
                            return slack_user_id
                        else:
                            logger.warning(f"[SlackTool] Slack lookup failed for {user.email}: {resp.get('error')}")
                    except Exception as api_err:
                        logger.debug(f"[SlackTool] Slack API lookup failed: {api_err}")
                
        except Exception as e:
            logger.warning(f"[SlackTool] Failed to resolve Slack user ID: {e}")
        
        return None

    async def _arun(self, action: str = "list", query: str = "", **kwargs) -> str:
        """Async execution."""
        return await asyncio.to_thread(self._run, action=action, query=query, **kwargs)
