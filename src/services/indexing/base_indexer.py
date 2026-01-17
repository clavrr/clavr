"""
Base Indexer Class

Abstract base class for all application-specific indexers (Email, Slack, Notion, etc.).
Provides standardized:
- Background task management (start/stop)
- Error handling and backoff
- RAG/Graph integration access
- Topic extraction (TopicExtractor)
- Temporal linking (TemporalIndexer)
- Relationship strength tracking (RelationshipStrengthManager)
"""
from abc import ABC, abstractmethod
import asyncio
from typing import Optional, List, Dict, Any, Tuple, TYPE_CHECKING
from datetime import datetime

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.ai.rag import RAGEngine
from src.services.indexing.parsers.base import ParsedNode
from src.services.indexing.graph import KnowledgeGraphManager
from src.services.indexing.hybrid_index import HybridIndexCoordinator

# Type checking imports to avoid circular dependencies
if TYPE_CHECKING:
    from src.services.indexing.topic_extractor import TopicExtractor
    from src.services.indexing.temporal_indexer import TemporalIndexer
    from src.services.indexing.relationship_strength import RelationshipStrengthManager
    from src.services.indexing.cross_app_correlator import CrossAppCorrelator
    from src.ai.memory.resolution import EntityResolutionService
    from src.ai.memory.observer import GraphObserverService

logger = setup_logger(__name__)

class BaseIndexer(ABC):
    """
    Abstract base class for background indexing services.
    
    Subclasses must implement:
    - name (property)
    - fetch_delta() -> List[Any]
    - transform_item(item) -> ParsedNode
    
    Features:
    - Automatic topic extraction from content
    - Temporal linking to TimeBlock nodes
    - Relationship strength reinforcement
    """
    
    def __init__(
        self, 
        config: Config, 
        user_id: int,
        rag_engine: Optional[RAGEngine] = None,
        graph_manager: Optional[KnowledgeGraphManager] = None,
        topic_extractor: Optional['TopicExtractor'] = None,
        temporal_indexer: Optional['TemporalIndexer'] = None,
        relationship_manager: Optional['RelationshipStrengthManager'] = None,
        cross_app_correlator: Optional['CrossAppCorrelator'] = None,
        entity_resolver: Optional['EntityResolutionService'] = None,
        observer_service: Optional['GraphObserverService'] = None
    ):
        self.config = config
        self.user_id = user_id
        self.rag_engine = rag_engine
        self.graph_manager = graph_manager
        self.topic_extractor = topic_extractor  # Extract topics during indexing
        self.temporal_indexer = temporal_indexer  # Link events to TimeBlocks
        self.relationship_manager = relationship_manager  # Track relationship strength
        self.cross_app_correlator = cross_app_correlator  # Cross-app correlation
        self.entity_resolver = entity_resolver  # Event-driven entity resolution
        self.observer_service = observer_service  # Real-time insight generation
        
        # Initialize hybrid coordinator if both engines are available
        if rag_engine and graph_manager:
            self.hybrid_index = HybridIndexCoordinator(
                graph_manager=graph_manager,
                rag_engine=rag_engine
            )
        else:
            self.hybrid_index = None
            
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        
        # Use centralized constant for sync interval
        from src.services.service_constants import ServiceConstants
        self.sync_interval = ServiceConstants.SYNC_INTERVAL_DEFAULT
        
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the indexer (e.g. 'slack', 'notion')"""
        raise NotImplementedError("Subclasses must implement the 'name' property")
        
    async def start(self):
        """Start the background indexing loop"""
        if self.is_running:
            return
            
        # Check if we should use Celery instead of internal loop
        # We prefer Celery for durability in production
        import os
        if os.getenv('USE_CELERY_FOR_INDEXING', 'true').lower() == 'true':
            logger.info(f"[{self.name}] Indexer durability delegated to Celery for user {self.user_id}")
            self.is_running = True # Mark as running to indicate it's 'active'
            return

        self.is_running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"[{self.name}] Internal asyncio loop started for user {self.user_id}")
        
    async def stop(self):
        """Stop the background indexing loop"""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"[{self.name}] Indexer stopped")
        
    async def _run_loop(self):
        """Main loop that calls sync methods periodically"""
        while self.is_running:
            try:
                logger.debug(f"[{self.name}] Starting sync cycle")
                count = await self.run_sync_cycle()
                logger.debug(f"[{self.name}] Sync cycle complete. Indexed {count} items.")
                
                # Wait for next cycle
                await asyncio.sleep(self.sync_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.name}] Error in sync loop: {e}", exc_info=True)
                await asyncio.sleep(60) # Backoff on error
                
    async def run_sync_cycle(self) -> int:
        """
        Execute one full sync cycle: fetch -> transform -> index
        Returns number of items indexed.
        """
        try:
            # 1. Fetch new data
            items = await self.fetch_delta()
            if not items:
                return 0
                
            indexed_count = 0
            
            # 2. Process each item
            for item in items:
                try:
                    # Transform to standardized node(s)
                    result = await self.transform_item(item)
                    if not result:
                        continue
                        
                    # Handle both single node and list of nodes
                    if isinstance(result, list):
                        nodes = result
                    else:
                        nodes = [result]
                        
                    if not nodes:
                        continue
                        
                    # Index into Graph + Vector
                    if self.hybrid_index:
                        # Graph Mode
                        success, _ = await self.hybrid_index.index_batch(nodes)
                        if success:
                            indexed_count += len(nodes)
                            # Extract topics from indexed content
                            await self._extract_topics_for_nodes(nodes)
                            # Link to TimeBlocks for temporal queries
                            await self._link_temporal_for_nodes(nodes)
                            # Reinforce relationship strengths
                            await self._reinforce_relationships_for_nodes(nodes)
                            # Cross-app correlation (find related content across apps)
                            await self._correlate_across_apps(nodes)
                            # Create pending relationships (OWNER_OF, STORED_IN, etc.)
                            await self._create_pending_relationships_for_nodes(nodes)
                            
                            # Event-Driven Intelligence (P1)
                            for node in nodes:
                                # 1. Resolve immediately (link Persons instantly)
                                if self.entity_resolver:
                                    await self.entity_resolver.resolve_immediately(node)
                                    
                                # 2. Generate immediate insights (conflicts, urgent items)
                                if self.observer_service:
                                    await self.observer_service.generate_immediate_insight(node)
                    elif self.rag_engine:
                        # Vector Only Fallback
                        for node in nodes:
                            await self._index_vector_only(node)
                            indexed_count += 1
                        
                except Exception as e:
                    logger.warning(f"[{self.name}] Failed to process item: {e}")
                    continue
                    
            return indexed_count
            
        except Exception as e:
            logger.error(f"[{self.name}] Sync cycle failed: {e}")
            return 0
            
    async def _index_vector_only(self, node: ParsedNode):
        """Fallback for when graph is not enabled"""
        if not node.searchable_text or not self.rag_engine:
            return
            
        metadata = node.properties.copy()
        metadata['node_id'] = node.node_id
        metadata['node_type'] = node.node_type
        # Add graph bridge ID
        metadata['graph_node_id'] = node.node_id 
        
        await asyncio.to_thread(
            self.rag_engine.index_document,
            node.node_id,
            node.searchable_text,
            metadata
        )

    async def _extract_topics_for_nodes(self, nodes: List[ParsedNode]):
        """
        Extract topics from indexed nodes using TopicExtractor.
        
        Only processes content-bearing nodes (Email, Message, Document).
        Topic extraction is non-blocking - failures don't affect indexing.
        """
        if not self.topic_extractor:
            return
            
        # Node types that contain meaningful content for topic extraction
        content_types = {'Email', 'Message', 'Document', 'Calendar_Event'}
        
        for node in nodes:
            try:
                # Skip non-content nodes (Contacts, Actions, etc.)
                if node.node_type not in content_types:
                    continue
                    
                # Need searchable text for topic extraction
                if not node.searchable_text or len(node.searchable_text) < 50:
                    continue
                    
                # Extract topics (non-blocking)
                await self.topic_extractor.extract_topics(
                    content=node.searchable_text,
                    source=self.name,
                    source_node_id=node.node_id,
                    user_id=self.user_id
                )
            except Exception as e:
                # Topic extraction failure should not block indexing
                logger.debug(f"[{self.name}] Topic extraction failed for {node.node_id}: {e}")

    async def _link_temporal_for_nodes(self, nodes: List[ParsedNode]):
        """
        Link nodes to TimeBlock nodes for temporal queries.
        
        Enables queries like "What happened last week?" by creating
        OCCURRED_DURING relationships between content nodes and TimeBlocks.
        """
        if not self.temporal_indexer:
            return
            
        for node in nodes:
            try:
                # Get timestamp from node properties
                timestamp_str = node.properties.get('timestamp') or node.properties.get('created_at') or node.properties.get('date')
                if not timestamp_str:
                    continue
                
                # Parse timestamp
                if isinstance(timestamp_str, str):
                    from datetime import datetime
                    try:
                        # Try ISO format first
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    except ValueError:
                        # Try other common formats
                        try:
                            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            continue
                else:
                    timestamp = timestamp_str
                
                # Link to Day granularity TimeBlock
                await self.temporal_indexer.link_event_to_timeblock(
                    event_id=node.node_id,
                    timestamp=timestamp,
                    granularity="day",
                    user_id=self.user_id
                )
                
            except Exception as e:
                # Temporal linking failure should not block indexing
                logger.debug(f"[{self.name}] Temporal linking failed for {node.node_id}: {e}")

    async def _reinforce_relationships_for_nodes(self, nodes: List[ParsedNode]):
        """
        Reinforce relationship strengths for nodes with relationships.
        
        This enables intelligent ranking of search results by connection strength.
        Strong relationships (frequent interactions) are prioritized in queries.
        """
        if not self.relationship_manager:
            return
            
        for node in nodes:
            try:
                # Get relationships from the node
                relationships = getattr(node, 'relationships', [])
                if not relationships:
                    continue
                    
                for rel in relationships:
                    # Reinforce each relationship
                    await self.relationship_manager.reinforce_relationship(
                        from_id=rel.from_node,
                        to_id=rel.to_node,
                        rel_type=rel.rel_type,
                        interaction_weight=1.0  # Default weight, can be customized
                    )
                    
            except Exception as e:
                # Relationship reinforcement failure should not block indexing
                logger.debug(f"[{self.name}] Relationship reinforcement failed for {node.node_id}: {e}")

    async def _correlate_across_apps(self, nodes: List[ParsedNode]):
        """
        Find and create cross-app correlations for indexed nodes.
        
        Uses semantic similarity to discover related content from other apps
        and creates RELATED_TO relationships in the graph.
        
        This enables "Show me everything about X" queries to aggregate
        related content from email, Slack, Notion, calendar, etc.
        """
        if not self.cross_app_correlator:
            return
            
        for node in nodes:
            try:
                # Find and create correlations (non-blocking)
                await self.cross_app_correlator.correlate_on_index(node)
            except Exception as e:
                # Correlation failure should not block indexing
                logger.debug(f"[{self.name}] Cross-app correlation failed for {node.node_id}: {e}")

    async def _create_pending_relationships_for_nodes(self, nodes: List[ParsedNode]):
        """
        Create pending relationships that were scheduled during transform.
        
        This handles:
        - Person -[OWNER_OF]-> Document (creates Person node if needed)
        - Document -[STORED_IN]-> Folder
        - Folder -[STORED_IN]-> Folder (nested folders)
        
        Relationships are stored in node._pending_relationships by the crawler.
        """
        if not self.graph_manager:
            return
            
        from src.services.indexing.graph.schema import NodeType, RelationType
        
        for node in nodes:
            try:
                # Get pending relationships from the node (set by transform_item)
                pending_rels = getattr(node, '_pending_relationships', [])
                if not pending_rels:
                    continue
                    
                for rel_data in pending_rels:
                    try:
                        from_id = rel_data.get('from_id')
                        to_id = rel_data.get('to_id')
                        rel_type = rel_data.get('rel_type')
                        properties = rel_data.get('properties', {})
                        
                        # Check if we need to create the "from" node first (e.g., Person)
                        create_from = rel_data.get('_create_from_node')
                        if create_from:
                            # Check if Person node exists; create if not
                            existing = self.graph_manager.get_node(create_from['node_id'])
                            if not existing:
                                self.graph_manager.add_node(
                                    node_id=create_from['node_id'],
                                    node_type=create_from['node_type'],
                                    properties=create_from['properties']
                                )
                                logger.debug(f"[{self.name}] Created {create_from['node_type']} node: {create_from['node_id']}")
                        
                        # Check if target node exists (for STORED_IN relationships)
                        # Folder nodes might not exist yet if processed in wrong order
                        if rel_type == RelationType.STORED_IN:
                            target_exists = self.graph_manager.get_node(to_id)
                            if not target_exists:
                                # Create a placeholder Folder node
                                # Real folder data will update it when folder is processed
                                folder_id = to_id.replace('folder_', '')
                                await self.graph_manager.add_node(
                                    node_id=to_id,
                                    node_type=NodeType.FOLDER,
                                    properties={"name": "Unknown Folder", "folder_id": folder_id}
                                )
                                logger.debug(f"[{self.name}] Created placeholder Folder: {to_id}")
                        
                        # Create the relationship
                        await self.graph_manager.add_relationship(
                            from_node=from_id,
                            to_node=to_id,
                            rel_type=rel_type,
                            properties=properties
                        )
                        logger.debug(f"[{self.name}] Created {rel_type} relationship: {from_id} -> {to_id}")
                        
                    except Exception as rel_error:
                        logger.debug(f"[{self.name}] Failed to create relationship: {rel_error}")
                        
            except Exception as e:
                # Relationship creation failure should not block indexing
                logger.debug(f"[{self.name}] Pending relationship creation failed for {node.node_id}: {e}")

    @abstractmethod
    async def fetch_delta(self) -> List[Any]:
        """
        Fetch items that have changed since last sync.
        Should handle its own cursors/timestamps.
        """
        pass
        
    @abstractmethod
    async def transform_item(self, item: Any) -> Optional[List[ParsedNode] | ParsedNode]:
        """
        Convert raw API item to generic ParsedNode(s).
        Return None if item should be skipped.
        """
        pass

