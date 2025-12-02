"""
Contact Resolver Role: Resolve names/IDs to contact information

Responsible for:
- Resolving Slack user IDs to email addresses
- Resolving names to email addresses via Neo4j graph
- Matching contacts across different systems
- Providing verified contact information to other roles
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from ...utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class ContactResolutionResult:
    """Result from contact resolution"""
    query: str
    resolved_email: Optional[str] = None
    resolved_name: Optional[str] = None
    resolution_method: Optional[str] = None  # 'slack_api', 'graph', 'email_search'
    success: bool = False
    error: Optional[str] = None
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class ContactResolverRole:
    """
    Contact Resolver Role: Resolves names/IDs to contact information
    
    The Contact Resolver is responsible for:
    - Resolving Slack user IDs to email addresses (via Slack API)
    - Resolving names to email addresses (via Neo4j graph)
    - Matching contacts across different systems
    - Providing verified contact information
    
    This implements the "Contact Resolver" role from the multi-role architecture.
    """
    
    def __init__(
        self,
        slack_client: Optional[Any] = None,
        graph_manager: Optional[Any] = None,
        email_service: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize ContactResolverRole
        
        Args:
            slack_client: Optional SlackClient for Slack API lookups
            graph_manager: Optional KnowledgeGraphManager for Neo4j graph lookups
            email_service: Optional EmailService for email-based lookups
            config: Optional configuration dictionary
        """
        self.slack_client = slack_client
        self.graph_manager = graph_manager
        self.email_service = email_service
        self.config = config or {}
        
        self.stats = {
            'resolutions_performed': 0,
            'slack_resolutions': 0,
            'graph_resolutions': 0,
            'email_resolutions': 0,
            'successful_resolutions': 0,
            'failed_resolutions': 0,
            'avg_confidence': 0.0
        }
        
        logger.info("ContactResolverRole initialized")
    
    async def resolve_contact(
        self,
        identifier: str,
        identifier_type: str = 'name',  # 'name', 'slack_id', 'email'
        user_id: Optional[int] = None
    ) -> ContactResolutionResult:
        """
        Resolve a contact identifier to email address
        
        Args:
            identifier: Contact identifier (name, Slack ID, or email)
            identifier_type: Type of identifier ('name', 'slack_id', 'email')
            user_id: Optional user ID for multi-user support
            
        Returns:
            ContactResolutionResult with resolution details
        """
        result = ContactResolutionResult(query=identifier)
        
        try:
            self.stats['resolutions_performed'] += 1
            
            # If already an email, return immediately
            if identifier_type == 'email' or '@' in identifier:
                result.resolved_email = identifier.lower()
                result.resolution_method = 'direct'
                result.success = True
                result.confidence = 1.0
                self.stats['successful_resolutions'] += 1
                return result
            
            # Tier 1: If Slack ID, use Slack API
            if identifier_type == 'slack_id' and self.slack_client:
                email = await self._resolve_via_slack_api(identifier)
                if email:
                    result.resolved_email = email
                    result.resolution_method = 'slack_api'
                    result.success = True
                    result.confidence = 0.9
                    self.stats['slack_resolutions'] += 1
                    self.stats['successful_resolutions'] += 1
                    return result
            
            # Tier 2: Use Neo4j graph lookup
            if self.graph_manager:
                email = await self._resolve_via_graph(identifier, user_id)
                if email:
                    result.resolved_email = email
                    result.resolution_method = 'graph'
                    result.success = True
                    result.confidence = 0.8
                    self.stats['graph_resolutions'] += 1
                    self.stats['successful_resolutions'] += 1
                    return result
            
            # Tier 3: Fallback to email search
            if self.email_service:
                email = await self._resolve_via_email_search(identifier)
                if email:
                    result.resolved_email = email
                    result.resolution_method = 'email_search'
                    result.success = True
                    result.confidence = 0.6
                    self.stats['email_resolutions'] += 1
                    self.stats['successful_resolutions'] += 1
                    return result
            
            # Resolution failed
            result.success = False
            result.error = f"Could not resolve {identifier_type} '{identifier}' to email"
            self.stats['failed_resolutions'] += 1
            logger.warning(f"[CONTACT_RESOLVER] Failed to resolve {identifier_type} '{identifier}'")
            
        except Exception as e:
            result.success = False
            result.error = str(e)
            self.stats['failed_resolutions'] += 1
            logger.error(f"[CONTACT_RESOLVER] Resolution error: {e}", exc_info=True)
        
        # Update average confidence
        if self.stats['successful_resolutions'] > 0:
            self.stats['avg_confidence'] = (
                (self.stats['avg_confidence'] * (self.stats['successful_resolutions'] - 1) + result.confidence) /
                self.stats['successful_resolutions']
            )
        
        return result
    
    async def _resolve_via_slack_api(self, slack_user_id: str) -> Optional[str]:
        """Resolve Slack user ID to email via Slack API"""
        try:
            if not self.slack_client:
                return None
            
            user_info = self.slack_client.get_user_info(slack_user_id)
            if user_info:
                profile = user_info.get('profile', {})
                email = profile.get('email')
                if email:
                    logger.debug(f"[CONTACT_RESOLVER] Resolved Slack user {slack_user_id} to {email}")
                    return email.lower()
            
            return None
            
        except Exception as e:
            logger.warning(f"[CONTACT_RESOLVER] Slack API resolution failed: {e}")
            return None
    
    async def _resolve_via_graph(self, name: str, user_id: Optional[int]) -> Optional[str]:
        """Resolve name to email via Neo4j graph"""
        try:
            if not self.graph_manager:
                return None
            
            # Use existing graph resolution function
            from ...core.calendar.utils import resolve_name_to_email_via_graph
            
            email = resolve_name_to_email_via_graph(
                name=name,
                graph_manager=self.graph_manager,
                user_id=user_id
            )
            
            if email:
                logger.debug(f"[CONTACT_RESOLVER] Resolved name '{name}' to {email} via graph")
            
            return email
            
        except Exception as e:
            logger.warning(f"[CONTACT_RESOLVER] Graph resolution failed: {e}")
            return None
    
    async def _resolve_via_email_search(self, name: str) -> Optional[str]:
        """Resolve name to email via email search"""
        try:
            if not self.email_service:
                return None
            
            # Search for emails from this person
            emails = self.email_service.search_emails(
                from_email=name,
                limit=5
            )
            
            if emails and len(emails) > 0:
                # Extract email from first result
                first_email = emails[0]
                sender = first_email.get('from', '')
                
                # Extract email from formats like "Name <email@domain.com>"
                import re
                email_match = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', sender)
                if email_match:
                    email = email_match.group(1).lower().strip()
                    logger.debug(f"[CONTACT_RESOLVER] Resolved name '{name}' to {email} via email search")
                    return email
            
            return None
            
        except Exception as e:
            logger.warning(f"[CONTACT_RESOLVER] Email search resolution failed: {e}")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get contact resolver statistics"""
        return self.stats.copy()

