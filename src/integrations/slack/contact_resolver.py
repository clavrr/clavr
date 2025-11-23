"""
Slack Contact Resolver

Resolves Slack user IDs/names to email addresses using Slack API and Neo4j graph.
Implements the Contact Resolver role from the architecture.
"""
from typing import Optional, Dict, Any
import asyncio

from .client import SlackClient
from ...utils.logger import setup_logger
from ...core.calendar.utils import resolve_name_to_email_via_graph

logger = setup_logger(__name__)


class SlackContactResolver:
    """
    Contact Resolver for Slack integration.
    
    Resolves Slack user IDs/names to email addresses using:
    1. Slack API (users:read.email scope) - gets email from Slack
    2. Neo4j graph lookup - matches email to Person nodes in graph
    
    This implements the Contact Resolver role from the architecture.
    """
    
    def __init__(
        self,
        slack_client: SlackClient,
        graph_manager: Optional[Any] = None,
        user_id: Optional[int] = None
    ):
        """
        Initialize Slack contact resolver.
        
        Args:
            slack_client: SlackClient instance for API calls
            graph_manager: Optional KnowledgeGraphManager for Neo4j queries
            user_id: Optional user ID for multi-user support
        """
        self.slack_client = slack_client
        self.graph_manager = graph_manager
        self.user_id = user_id
        
        logger.info("Slack contact resolver initialized")
    
    def resolve_slack_user_to_email(self, slack_user_id: str) -> Optional[str]:
        """
        Resolve Slack user ID to email address using Slack API.
        
        Uses users:read.email scope to get user email.
        This is the first step in contact resolution.
        
        Args:
            slack_user_id: Slack user ID (e.g., "U1234567890")
            
        Returns:
            Email address or None if not found
        """
        try:
            user_info = self.slack_client.get_user_info(slack_user_id)
            
            if not user_info:
                logger.warning(f"Could not get user info for Slack user {slack_user_id}")
                return None
            
            # Extract email from user profile
            profile = user_info.get('profile', {})
            email = profile.get('email')
            
            if email:
                logger.info(f"Resolved Slack user {slack_user_id} to email {email}")
                return email.lower()
            else:
                logger.warning(f"No email found for Slack user {slack_user_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error resolving Slack user to email: {e}", exc_info=True)
            return None
    
    def resolve_name_to_email(
        self,
        name: str,
        slack_user_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Resolve a name to email address using two-tier approach:
        1. If slack_user_id provided: Use Slack API to get email
        2. Use Neo4j graph lookup to find email by name
        
        This implements the Contact Resolver role from the architecture.
        
        Args:
            name: Person's name (e.g., "John", "Jane Smith")
            slack_user_id: Optional Slack user ID for direct lookup
            
        Returns:
            Email address or None if not found
        """
        # Tier 1: If Slack user ID provided, use Slack API directly
        if slack_user_id:
            email = self.resolve_slack_user_to_email(slack_user_id)
            if email:
                return email
        
        # Tier 2: Use Neo4j graph lookup (Contact Resolver role)
        if self.graph_manager:
            try:
                # Use existing graph resolution function
                email = resolve_name_to_email_via_graph(
                    name=name,
                    graph_manager=self.graph_manager,
                    user_id=self.user_id
                )
                
                if email:
                    logger.info(f"Resolved name '{name}' to email '{email}' via Neo4j graph")
                    return email
                    
            except Exception as e:
                logger.warning(f"Graph lookup failed for '{name}': {e}")
        
        logger.debug(f"Could not resolve name '{name}' to email")
        return None
    
    async def resolve_name_to_email_async(
        self,
        name: str,
        slack_user_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Async version of resolve_name_to_email.
        
        Args:
            name: Person's name
            slack_user_id: Optional Slack user ID
            
        Returns:
            Email address or None
        """
        # Run sync function in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.resolve_name_to_email,
            name,
            slack_user_id
        )
    
    def get_slack_user_email(self, slack_user_id: str) -> Optional[str]:
        """
        Get email address for a Slack user ID.
        
        Convenience method that wraps resolve_slack_user_to_email.
        
        Args:
            slack_user_id: Slack user ID
            
        Returns:
            Email address or None
        """
        return self.resolve_slack_user_to_email(slack_user_id)

