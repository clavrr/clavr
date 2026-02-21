"""
Slack Crawler

Background indexer that crawls Slack channels for history and updates the knowledge graph.
Works alongside the real-time event handler to ensure complete coverage.
"""
from typing import List, Any, Optional, Dict
from datetime import datetime, timedelta
import asyncio

from src.services.indexing.base_indexer import BaseIndexer
from src.services.indexing.parsers.base import ParsedNode, Relationship
from src.services.indexing.graph.schema import NodeType, RelationType
from src.integrations.slack.client import SlackClient
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class SlackCrawler(BaseIndexer):
    """
    Crawler that periodically fetches Slack history.
    """
    
    def __init__(self, config, user_id, rag_engine=None, graph_manager=None, slack_client=None, topic_extractor=None, temporal_indexer=None):
        super().__init__(config, user_id, rag_engine, graph_manager, topic_extractor, temporal_indexer)
        self.client = slack_client or SlackClient()
        from src.services.service_constants import ServiceConstants
        self.last_sync_time = datetime.now() - timedelta(days=ServiceConstants.INITIAL_LOOKBACK_DAYS)
        self._user_cache = {} # cache user info to reduce API calls
        self._channel_cache = {}
        
    @property
    def name(self) -> str:
        return "slack"
        
    async def fetch_delta(self) -> List[Any]:
        """
        Fetch all messages since last sync from all accessible channels.
        """
        if not self.client.web_client:
            logger.warning("[SlackCrawler] No WebClient available, skipping sync")
            return []
            
        new_items = []
        try:
            # 1. List Channels
            response = await asyncio.to_thread(
                self.client.web_client.conversations_list,
                types="public_channel,private_channel",
                limit=100
            )
            
            channels = response.get('channels', [])
            logger.info(f"[SlackCrawler] Found {len(channels)} channels to scan")
            
            oldest_ts = self.last_sync_time.timestamp()
            
            for channel in channels:
                channel_id = channel['id']
                channel_name = channel['name']
                is_member = channel.get('is_member', False)
                
                if not is_member:
                    continue
                    
                # Cache channel info
                self._channel_cache[channel_id] = channel
                
                # Fetch history
                try:
                    history = await asyncio.to_thread(
                        self.client.web_client.conversations_history,
                        channel=channel_id,
                        oldest=oldest_ts,
                        limit=100
                    )
                    
                    messages = history.get('messages', [])
                    if messages:
                        logger.debug(f"[SlackCrawler] Found {len(messages)} new messages in #{channel_name}")
                        for msg in messages:
                            # Attach context
                            msg['_channel_id'] = channel_id
                            msg['_channel_name'] = channel_name
                            new_items.append(msg)
                            
                except Exception as e:
                    logger.warning(f"[SlackCrawler] Failed to fetch history for #{channel_name}: {e}")
                    
            # Update sync time
            self.last_sync_time = datetime.now()
            return new_items
            
        except Exception as e:
            logger.error(f"[SlackCrawler] Fetch delta failed: {e}")
            return []
            
    async def transform_item(self, item: Any) -> Optional[List[ParsedNode]]:
        """
        Transform a Slack message dict into graph nodes.
        """
        try:
            nodes = []
            
            # Extract basic fields
            text = item.get('text', '')
            user_id = item.get('user')
            channel_id = item.get('_channel_id')
            ts = item.get('ts')
            
            if not text or not user_id or not ts:
                return None
                
            # 1. Resolve User (Person Node)
            person_node = await self._get_person_node(user_id)
            if person_node:
                nodes.append(person_node)
                
            # 2. Resolve Channel (Channel Node)
            channel_node = await self._get_channel_node(channel_id)
            if channel_node:
                nodes.append(channel_node)
                
            # 3. Create Message Node
            message_node_id = f"message_slack_{ts.replace('.', '_')}"
            
            # Relationships
            rels = []
            
            # POSTED relationship (Person -> Message)
            if person_node:
                rels.append(Relationship(
                    from_node=person_node.node_id,
                    to_node=message_node_id,
                    rel_type=RelationType.POSTED
                ))
                
                # COMMUNICATES_WITH — Slack message = interaction signal
                rels.append(Relationship(
                    from_node=f"User/{self.user_id}",
                    to_node=person_node.node_id,
                    rel_type=RelationType.COMMUNICATES_WITH,
                    properties={
                        'source': 'slack',
                        'last_interaction': datetime.fromtimestamp(float(ts)).isoformat(),
                        'strength': 0.2,  # Slack message = lightweight interaction signal
                    }
                ))
                
                # KNOWS — ensure User knows this Slack contact
                aliases = []
                person_name = person_node.properties.get('name')
                if person_name and person_name.strip():
                    aliases.append(person_name)
                    first_name = person_name.split()[0] if person_name.split() else None
                    if first_name and first_name != person_name:
                        aliases.append(first_name)
                
                rels.append(Relationship(
                    from_node=f"User/{self.user_id}",
                    to_node=person_node.node_id,
                    rel_type=RelationType.KNOWS,
                    properties={
                        'aliases': aliases,
                        'frequency': 1,
                        'source': 'slack',
                    }
                ))
            
            # IN_CHANNEL relationship (Message -> Channel)
            if channel_node:
                rels.append(Relationship(
                    from_node=message_node_id,
                    to_node=channel_node.node_id,
                    rel_type=RelationType.IN_CHANNEL
                ))
                
                # POSTED_IN relationship (Person -> Channel) - Shortcut for easy traversal
                if person_node:
                    rels.append(Relationship(
                        from_node=person_node.node_id,
                        to_node=channel_node.node_id,
                        rel_type=RelationType.POSTED_IN
                    ))

            message_node = ParsedNode(
                node_id=message_node_id,
                node_type=NodeType.MESSAGE,
                properties={
                    'text': text,
                    'slack_message_ts': ts,
                    'slack_user_id': user_id,
                    'slack_channel_id': channel_id,
                    'timestamp': datetime.fromtimestamp(float(ts)).isoformat(),
                    'source': 'slack'
                },
                relationships=rels,
                searchable_text=f"{text} (Posted by {person_node.properties.get('name', 'Unknown') if person_node else user_id} in #{channel_node.properties.get('name', 'unknown') if channel_node else channel_id})"
            )
            nodes.append(message_node)
            
            return nodes
            
        except Exception as e:
            logger.warning(f"[SlackCrawler] Transform failed: {e}")
            return None

    async def _get_person_node(self, user_id: str) -> Optional[ParsedNode]:
        """Fetch user info and return Person node (cached)"""
        if user_id in self._user_cache:
            return self._user_cache[user_id]
            
        info = self.client.get_user_info(user_id)
        if not info:
            return None
            
        profile = info.get('profile', {})
        name = profile.get('real_name') or info.get('name', 'Unknown')
        email = profile.get('email')
        
        # Use email-based ID if available for cross-source merging
        from src.services.indexing.node_id_utils import generate_person_id
        if email:
            node_id = generate_person_id(email=email)
        else:
            node_id = generate_person_id(source='slack', source_id=user_id)
        
        node = ParsedNode(
            node_id=node_id,
            node_type=NodeType.PERSON,
            properties={
                'name': name,
                'slack_user_id': user_id,
                'email': email,
                'title': profile.get('title'),
                'source': 'slack'
            },
            searchable_text=f"{name} {email or ''}"
        )
        self._user_cache[user_id] = node
        return node

    async def _get_channel_node(self, channel_id: str) -> Optional[ParsedNode]:
        """Get channel info and return Channel node"""
        # Channel info is already cached in fetch_delta usually
        info = self._channel_cache.get(channel_id)
        if not info:
            info = self.client.get_channel_info(channel_id)
            
        if not info:
            return None
            
        name = info.get('name', channel_id)
        
        node = ParsedNode(
            node_id=f"channel_slack_{channel_id}",
            node_type=NodeType.CHANNEL,
            properties={
                'name': name,
                'slack_channel_id': channel_id,
                'is_private': info.get('is_private', False),
                'source': 'slack'
            },
            searchable_text=f"#{name} (Slack Channel)"
        )
        return node
