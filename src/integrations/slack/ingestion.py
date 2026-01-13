"""
Slack Ingestion Pipeline

Converts Slack messages, files, and threads into structured knowledge for the graph.
Implements the "Effortless Context Capture" architecture:
1. Extract Entities (Person, Channel nodes)
2. Extract Relationships (MENTIONED, POSTED_IN, REACTED_TO)
3. Vectorize Unstructured Data (message/thread text to Qdrant)
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
import asyncio

from .client import SlackClient
from ...utils.logger import setup_logger
from ...utils.config import load_config

logger = setup_logger(__name__)


class SlackIngestionPipeline:
    """
    Ingestion pipeline for Slack messages.
    
    Converts Slack conversations into structured knowledge:
    - Creates Person and Channel nodes in ArangoDB
    - Records relationships (MENTIONED, POSTED_IN, REACTED_TO)
    - Vectorizes message/thread text to Qdrant for semantic retrieval
    """
    
    def __init__(
        self,
        slack_client: SlackClient,
        graph_manager: Optional[Any] = None,
        rag_engine: Optional[Any] = None,
        config: Optional[Any] = None
    ):
        """
        Initialize Slack ingestion pipeline.
        
        Args:
            slack_client: SlackClient instance
            graph_manager: Optional KnowledgeGraphManager for ArangoDB
            rag_engine: Optional RAGEngine for Qdrant vectorization
            config: Optional configuration object
        """
        self.slack_client = slack_client
        self.graph_manager = graph_manager
        self.rag_engine = rag_engine
        self.config = config or load_config()
        
        logger.info("Slack ingestion pipeline initialized")
    
    async def ingest_message(
        self,
        message_data: Dict[str, Any],
        channel_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Ingest a Slack message into the knowledge graph.
        
        Performs:
        1. Extract Entities: Creates Person and Channel nodes
        2. Extract Relationships: Records MENTIONED, POSTED_IN, REACTED_TO
        3. Vectorize: Sends message/thread text to Qdrant
        
        Args:
            message_data: Slack message event data
            channel_data: Optional channel information
            
        Returns:
            True if ingestion successful, False otherwise
        """
        try:
            message_text = message_data.get('text', '')
            user_id = message_data.get('user')
            channel_id = message_data.get('channel')
            thread_ts = message_data.get('thread_ts')  # If in thread
            ts = message_data.get('ts')  # Message timestamp
            mentions = message_data.get('mentions', [])  # User IDs mentioned
            
            logger.info(f"[SLACK] Ingesting message from user {user_id} in channel {channel_id}")
            
            # Step 1: Extract Entities (Person and Channel nodes)
            await self._extract_entities(user_id, channel_id, channel_data)
            
            # Step 2: Extract Relationships (pass message_text for Message node creation)
            await self._extract_relationships(
                user_id=user_id,
                channel_id=channel_id,
                mentions=mentions,
                thread_ts=thread_ts,
                message_ts=ts,
                message_text=message_text  # Pass message_text here
            )
            
            # Step 3: Vectorize Unstructured Data
            await self._vectorize_message(
                message_text=message_text,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                message_ts=ts
            )
            
            logger.info(f"[SLACK] Successfully ingested message {ts}")
            return True
            
        except Exception as e:
            logger.error(f"[SLACK] Error ingesting message: {e}", exc_info=True)
            return False
    
    async def _extract_entities(
        self,
        user_id: str,
        channel_id: str,
        channel_data: Optional[Dict[str, Any]] = None
    ):
        """
        Extract entities: Create Person and Channel nodes in ArangoDB.
        
        Args:
            user_id: Slack user ID
            channel_id: Slack channel ID
            channel_data: Optional channel information
        """
        if not self.graph_manager:
            logger.debug("No graph manager available, skipping entity extraction")
            return
        
        try:
            # Get user info from Slack API
            user_info = self.slack_client.get_user_info(user_id)
            if user_info:
                profile = user_info.get('profile', {})
                email = profile.get('email')
                name = profile.get('real_name') or profile.get('display_name') or user_info.get('name', '')
                
                # Create Person node
                await self._create_person_node(
                    slack_user_id=user_id,
                    email=email,
                    name=name,
                    slack_profile=profile
                )
            
            # Get channel info
            if not channel_data:
                channel_data = self.slack_client.get_channel_info(channel_id)
            
            if channel_data:
                channel_name = channel_data.get('name', channel_id)
                
                # Create Channel node
                await self._create_channel_node(
                    slack_channel_id=channel_id,
                    channel_name=channel_name,
                    channel_data=channel_data
                )
                
        except Exception as e:
            logger.warning(f"Error extracting entities: {e}")
    
    async def _create_person_node(
        self,
        slack_user_id: str,
        email: Optional[str],
        name: str,
        slack_profile: Dict[str, Any]
    ):
        """Create Person node in ArangoDB"""
        if not self.graph_manager:
            return
        
        try:
            from ...services.indexing.graph.schema import NodeType, RelationType
            
            # Create Person node properties
            person_props = {
                'slack_user_id': slack_user_id,
                'name': name,
                'slack_display_name': slack_profile.get('display_name', ''),
                'slack_real_name': slack_profile.get('real_name', ''),
                'slack_image': slack_profile.get('image_512', ''),
                'source': 'slack'
            }
            
            # Generate unique node ID
            person_node_id = f"person_slack_{slack_user_id}"
            
            # Create Person node
            person_created = await asyncio.to_thread(
                self.graph_manager.add_node,
                node_id=person_node_id,
                node_type=NodeType.PERSON,
                properties=person_props
            )
            
            if not person_created:
                logger.warning(f"Failed to create Person node for {slack_user_id}")
                return
            
            # If email available, create EmailAddress node and link
            if email:
                email_node_id = f"email_{email.lower().replace('@', '_at_').replace('.', '_')}"
                email_props = {
                    'email_address': email.lower(),
                    'source': 'slack'
                }
                
                email_created = await asyncio.to_thread(
                    self.graph_manager.add_node,
                    node_id=email_node_id,
                    node_type=NodeType.EMAIL_ADDRESS,
                    properties=email_props
                )
                
                if email_created:
                    # Create HAS_EMAIL relationship
                    await asyncio.to_thread(
                        self.graph_manager.add_relationship,
                        from_node=person_node_id,
                        to_node=email_node_id,
                        rel_type=RelationType.HAS_EMAIL
                    )
            
            logger.debug(f"Created Person node for Slack user {slack_user_id}")
            
        except Exception as e:
            logger.warning(f"Error creating Person node: {e}")
    
    async def _create_channel_node(
        self,
        slack_channel_id: str,
        channel_name: str,
        channel_data: Dict[str, Any]
    ):
        """Create Channel node in ArangoDB"""
        if not self.graph_manager:
            return
        
        try:
            from ...services.indexing.graph.schema import NodeType
            
            channel_props = {
                'slack_channel_id': slack_channel_id,
                'name': channel_name,
                'is_private': channel_data.get('is_private', False),
                'is_archived': channel_data.get('is_archived', False),
                'topic': channel_data.get('topic', {}).get('value', ''),
                'purpose': channel_data.get('purpose', {}).get('value', ''),
                'workspace_id': channel_data.get('workspace_id', ''),
                'member_count': channel_data.get('num_members', 0),
                'created': channel_data.get('created', ''),
                'source': 'slack'
            }
            
            # Generate unique node ID
            channel_node_id = f"channel_slack_{slack_channel_id}"
            
            # Create Channel node
            channel_created = await asyncio.to_thread(
                self.graph_manager.add_node,
                node_id=channel_node_id,
                node_type=NodeType.CHANNEL,
                properties=channel_props
            )
            
            if channel_created:
                logger.debug(f"Created Channel node for {channel_name}")
            else:
                logger.warning(f"Failed to create Channel node for {channel_name}")
            
        except Exception as e:
            logger.warning(f"Error creating Channel node: {e}")
    
    async def _extract_relationships(
        self,
        user_id: str,
        channel_id: str,
        mentions: List[str],
        thread_ts: Optional[str],
        message_ts: str,
        message_text: str = ''
    ):
        """
        Extract relationships: MENTIONED, POSTED_IN, REACTED_TO.
        
        Args:
            user_id: Slack user ID who posted
            channel_id: Channel where message was posted
            mentions: List of user IDs mentioned in message
            thread_ts: Thread timestamp if in thread
            message_ts: Message timestamp
        """
        if not self.graph_manager:
            logger.debug("No graph manager available, skipping relationship extraction")
            return
        
        try:
            from ...services.indexing.graph.schema import NodeType, RelationType
            
            # Find Person node ID for the user who posted
            person_node_id = await asyncio.to_thread(
                self._find_person_node_id,
                slack_user_id=user_id
            )
            
            if not person_node_id:
                logger.debug(f"Could not find Person node for user {user_id}, skipping relationships")
                return
            
            # Find Channel node ID
            channel_node_id = await asyncio.to_thread(
                self._find_channel_node_id,
                slack_channel_id=channel_id
            )
            
            # Create POSTED_IN relationship: Person -> Channel
            if channel_node_id:
                await asyncio.to_thread(
                    self.graph_manager.add_relationship,
                    from_node=person_node_id,
                    to_node=channel_node_id,
                    rel_type=RelationType.POSTED_IN
                )
                logger.debug(f"Created POSTED_IN relationship: User {user_id} -> Channel {channel_id}")
            
            # Create MENTIONED relationships: Person -> Person (for each mention)
            for mentioned_user_id in mentions:
                if mentioned_user_id == user_id:
                    continue  # Skip self-mentions
                
                mentioned_person_node_id = await asyncio.to_thread(
                    self._find_person_node_id,
                    slack_user_id=mentioned_user_id
                )
                
                if mentioned_person_node_id:
                    await asyncio.to_thread(
                        self.graph_manager.add_relationship,
                        from_node=person_node_id,
                        to_node=mentioned_person_node_id,
                        rel_type=RelationType.MENTIONED
                    )
                    logger.debug(f"Created MENTIONED relationship: User {user_id} -> User {mentioned_user_id}")
            
            # Create Message node and POSTED relationship
            message_node_id = await asyncio.to_thread(
                self._create_message_node,
                message_ts=message_ts,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                message_text=message_text
            )
            
            if message_node_id:
                # Person POSTED Message
                await asyncio.to_thread(
                    self.graph_manager.add_relationship,
                    from_node=person_node_id,
                    to_node=message_node_id,
                    rel_type=RelationType.POSTED
                )
                
                # Message IN_CHANNEL Channel
                if channel_node_id:
                    await asyncio.to_thread(
                        self.graph_manager.add_relationship,
                        from_node=message_node_id,
                        to_node=channel_node_id,
                        rel_type=RelationType.IN_CHANNEL
                    )
                
                # If in thread, create NEXT_IN_THREAD relationship
                if thread_ts:
                    parent_message_node_id = await asyncio.to_thread(
                        self._find_message_node_id,
                        message_ts=thread_ts
                    )
                    if parent_message_node_id:
                        await asyncio.to_thread(
                            self.graph_manager.add_relationship,
                            from_node=message_node_id,
                            to_node=parent_message_node_id,
                            rel_type=RelationType.NEXT_IN_THREAD
                        )
            
            # Note: REACTED_TO relationships would come from reaction events, not message events
            
        except Exception as e:
            logger.warning(f"Error extracting relationships: {e}")
    
    def _find_person_node_id(self, slack_user_id: str) -> Optional[str]:
        """Find Person node ID by Slack user ID"""
        if not self.graph_manager:
            return None
        
        try:
            # Query ArangoDB for Person node with slack_user_id (AQL)
            query = """
            FOR p IN Person 
                FILTER p.slack_user_id == @slack_user_id
                LIMIT 1
                RETURN { node_id: p._id, slack_user_id: p.slack_user_id }
            """
            result = self.graph_manager.query(query, {'slack_user_id': slack_user_id})
            if result and len(result) > 0:
                # Return the node ID (could be ArangoDB internal ID or our custom ID)
                # For consistency, use our custom ID format
                return f"person_slack_{slack_user_id}"
            return None
        except Exception as e:
            logger.debug(f"Error finding Person node: {e}")
            return None
    
    def _find_channel_node_id(self, slack_channel_id: str) -> Optional[str]:
        """Find Channel node ID by Slack channel ID"""
        if not self.graph_manager:
            return None
        
        try:
            query = """
            FOR c IN Channel 
                FILTER c.slack_channel_id == @slack_channel_id
                LIMIT 1
                RETURN { node_id: c._id, slack_channel_id: c.slack_channel_id }
            """
            result = self.graph_manager.query(query, {'slack_channel_id': slack_channel_id})
            if result and len(result) > 0:
                return f"channel_slack_{slack_channel_id}"
            return None
        except Exception as e:
            logger.debug(f"Error finding Channel node: {e}")
            return None
    
    async def _create_message_node(
        self,
        message_ts: str,
        user_id: str,
        channel_id: str,
        thread_ts: Optional[str],
        message_text: str = ''
    ) -> Optional[str]:
        """Create Message node in ArangoDB and return node ID"""
        if not self.graph_manager:
            return None
        
        try:
            from ...services.indexing.graph.schema import NodeType
            
            message_node_id = f"message_slack_{message_ts.replace('.', '_')}"
            message_props = {
                'slack_message_ts': message_ts,
                'text': message_text or '',  # Required property
                'slack_user_id': user_id,
                'slack_channel_id': channel_id,
                'slack_thread_ts': thread_ts or '',
                'is_thread_reply': thread_ts is not None,
                'timestamp': datetime.utcnow().isoformat(),
                'source': 'slack'
            }
            
            message_created = await asyncio.to_thread(
                self.graph_manager.add_node,
                node_id=message_node_id,
                node_type=NodeType.MESSAGE,
                properties=message_props
            )
            
            if message_created:
                return message_node_id
            return None
            
        except Exception as e:
            logger.warning(f"Error creating Message node: {e}")
            return None
    
    def _find_message_node_id(self, message_ts: str) -> Optional[str]:
        """Find Message node ID by timestamp"""
        if not self.graph_manager:
            return None
        
        try:
            query = """
            FOR m IN Message 
                FILTER m.slack_message_ts == @message_ts
                LIMIT 1
                RETURN { node_id: m._id, message_ts: m.slack_message_ts }
            """
            result = self.graph_manager.query(query, {'message_ts': message_ts})
            if result and len(result) > 0:
                return f"message_slack_{message_ts.replace('.', '_')}"
            return None
        except Exception as e:
            logger.debug(f"Error finding Message node: {e}")
            return None
    
    async def _vectorize_message(
        self,
        message_text: str,
        user_id: str,
        channel_id: str,
        thread_ts: Optional[str],
        message_ts: str
    ):
        """
        Vectorize message/thread text and send to Qdrant.
        
        Implements Step 3 of Knowledge Graph Hydration:
        - Sends unstructured message/thread text to Qdrant for semantic retrieval
        - Preserves metadata for context
        
        Args:
            message_text: Message text content
            user_id: Slack user ID
            channel_id: Channel ID
            thread_ts: Thread timestamp if in thread
            message_ts: Message timestamp
        """
        if not self.rag_engine:
            logger.debug("No RAG engine available, skipping vectorization")
            return
        
        if not message_text or len(message_text.strip()) < 10:
            logger.debug("Message too short, skipping vectorization")
            return
        
        try:
            # Generate unique document ID for this message
            doc_id = f"slack_message_{channel_id}_{message_ts.replace('.', '_')}"
            
            # Prepare metadata for retrieval context
            metadata = {
                'source': 'slack',
                'slack_user_id': user_id,
                'slack_channel_id': channel_id,
                'slack_message_ts': message_ts,
                'slack_thread_ts': thread_ts or '',
                'is_thread_reply': thread_ts is not None,
                'timestamp': datetime.utcnow().isoformat(),
                'doc_type': 'slack_message'
            }
            
            # Index document using RAG engine
            # Uses the index_document method which:
            # 1. Chunks the content intelligently
            # 2. Generates embeddings
            # 3. Stores in Qdrant (or configured vector store)
            # 4. Preserves metadata for filtering and context
            await asyncio.to_thread(
                self.rag_engine.index_document,
                doc_id,
                message_text,
                metadata
            )
            
            logger.info(f"Vectorized Slack message {message_ts} ({len(message_text)} chars)")
            
        except Exception as e:
            logger.warning(f"Error vectorizing Slack message {message_ts}: {e}")

