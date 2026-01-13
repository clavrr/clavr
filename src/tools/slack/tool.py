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

class SlackTool(BaseTool):
    """
    Slack interaction tool wrapping Slack integration services.
    
    Actions:
    - list: List recent messages in a channel
    - search: Search for messages or users
    - send: Send a new message to a channel or user
    - reply: Reply to a specific thread
    """
    
    name: str = "slack"
    description: str = "Slack interaction (send messages, list channels, search). Use this for Slack-related queries."
    args_schema: Type[BaseModel] = SlackInput
    
    config: Optional[Config] = Field(default=None, exclude=True)
    user_id: int = Field(default=1, exclude=True)
    _slack_client: Any = None
    
    def __init__(self, config: Optional[Config] = None, user_id: int = 1, **kwargs):
        super().__init__(**kwargs)
        self.config = config or load_config()
        self.user_id = user_id
        self._slack_client = None

    @property
    def slack_client(self):
        """Lazy initialization of Slack client."""
        if self._slack_client is None:
            try:
                from ...integrations.slack.client import SlackClient
                self._slack_client = SlackClient()
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
                    return f"✅ Message sent to Slack channel {channel}."
                return f"❌ Failed to send message: {resp.get('error', 'Unknown error')}"

            elif action == "reply":
                channel = kwargs.get("channel")
                thread_ts = kwargs.get("thread_ts")
                text = query or kwargs.get("text")
                if not channel or not thread_ts or not text:
                    return "Error: channel, thread_ts, and text are required for 'reply' action."
                
                resp = self.slack_client.post_message(channel=channel, text=text, thread_ts=thread_ts)
                if resp.get('ok'):
                    return "✅ Reply sent to Slack thread."
                return f"❌ Failed to send reply: {resp.get('error', 'Unknown error')}"

            elif action == "search":
                # For now, searching is a placeholder as the client doesn't have a search method yet
                # We can use the orchestrator logic or direct API if needed
                return f"🔍 Searching Slack for '{query}'... (Feature refinement in progress)"

            elif action == "list":
                # Listing channels or recent messages
                return "📋 Listing recent Slack activity... (Feature refinement in progress)"

            else:
                return f"Unknown action: {action}. Supported: send, reply, search, list"

        except Exception as e:
            logger.error(f"Slack tool error: {e}", exc_info=True)
            return f"Error executing Slack action: {str(e)}"

    async def _arun(self, action: str = "list", query: str = "", **kwargs) -> str:
        """Async execution."""
        return await asyncio.to_thread(self._run, action=action, query=query, **kwargs)
