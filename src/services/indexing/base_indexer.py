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
import time
from typing import Optional, List, Dict, Any, Tuple, TYPE_CHECKING
from datetime import datetime

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.ai.rag import RAGEngine
from src.services.indexing.parsers.base import ParsedNode
from src.services.indexing.graph import KnowledgeGraphManager
from src.services.indexing.hybrid_index import HybridIndexCoordinator
from src.services.indexing.enrichment_pipeline import EnrichmentPipeline

# Type checking imports to avoid circular dependencies
if TYPE_CHECKING:
    from src.services.indexing.topic_extractor import TopicExtractor
    from src.services.indexing.temporal_indexer import TemporalIndexer
    from src.services.indexing.relationship_strength import RelationshipStrengthManager
    from src.services.indexing.cross_app_correlator import CrossAppCorrelator
    from src.ai.memory.resolution import EntityResolutionService
    from src.ai.memory.observer import GraphObserverService

logger = setup_logger(__name__)

from dataclasses import dataclass, field

@dataclass
class IndexingStats:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    errors: int = 0
    skipped: int = 0
    failed_items: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class IndexingResult:
    success: bool
    stats: IndexingStats
    errors: Optional[List[str]] = None

# Constants for retry/backoff
INITIAL_BACKOFF_SECONDS = 60
MAX_BACKOFF_SECONDS = 3600  # 1 hour
CIRCUIT_BREAKER_THRESHOLD = 10  # consecutive errors before pausing
PROCESSING_BATCH_SIZE = 10  # items processed concurrently


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
        observer_service: Optional['GraphObserverService'] = None,
        **kwargs
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
        self.token_saver_callback = kwargs.get('token_saver_callback')

        
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
        self._consecutive_errors = 0
        self._last_heartbeat: float = 0.0
        self._last_stats: Optional[IndexingStats] = None
        
        # Persistent sync state (replaces in-memory caches)
        self._persisted_cache: Dict[str, Any] = {}  # Loaded from CrawlerState.item_cache
        self._state_loaded = False
        
        # Shared enrichment pipeline (replaces inline enrichment methods)
        self._enrichment = EnrichmentPipeline(
            indexer_name=self.name,
            user_id=user_id,
            topic_extractor=topic_extractor,
            temporal_indexer=temporal_indexer,
            relationship_manager=relationship_manager,
            cross_app_correlator=cross_app_correlator,
            graph_manager=graph_manager,
        )
        
        # Use centralized constant for sync interval
        from src.services.service_constants import ServiceConstants
        self.sync_interval = ServiceConstants.SYNC_INTERVAL_DEFAULT
    
    async def load_crawler_state(self) -> Dict[str, Any]:
        """
        Load persisted sync state from CrawlerState table.
        Returns the item_cache dict (item_id → update_timestamp).
        """
        try:
            from src.database import get_async_db_context
            from src.database.models import CrawlerState
            from sqlalchemy import select
            
            async with get_async_db_context() as db:
                result = await db.execute(
                    select(CrawlerState).where(
                        CrawlerState.user_id == self.user_id,
                        CrawlerState.crawler_name == self.name
                    )
                )
                state = result.scalar_one_or_none()
                
                if state:
                    self._persisted_cache = state.item_cache or {}
                    self._state_loaded = True
                    logger.debug(
                        f"[{self.name}] Loaded {len(self._persisted_cache)} cached items from DB"
                    )
                    return self._persisted_cache
                    
        except Exception as e:
            logger.debug(f"[{self.name}] Could not load crawler state: {e}")
        
        self._state_loaded = True
        return {}
    
    async def save_crawler_state(self, items_processed: int = 0):
        """
        Persist current sync state to CrawlerState table.
        Called automatically after each sync cycle.
        """
        try:
            from src.database import get_async_db_context
            from src.database.models import CrawlerState
            from sqlalchemy import select
            
            async with get_async_db_context() as db:
                result = await db.execute(
                    select(CrawlerState).where(
                        CrawlerState.user_id == self.user_id,
                        CrawlerState.crawler_name == self.name
                    )
                )
                state = result.scalar_one_or_none()
                
                if state:
                    state.item_cache = self._persisted_cache
                    state.last_sync_time = datetime.utcnow()
                    state.items_processed = (state.items_processed or 0) + items_processed
                else:
                    state = CrawlerState(
                        user_id=self.user_id,
                        crawler_name=self.name,
                        item_cache=self._persisted_cache,
                        last_sync_time=datetime.utcnow(),
                        items_processed=items_processed,
                    )
                    db.add(state)
                
                await db.commit()
                
        except Exception as e:
            logger.debug(f"[{self.name}] Could not save crawler state: {e}")
        
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
        
    def is_healthy(self) -> bool:
        """Check if the indexer loop is alive and responsive."""
        if not self.is_running:
            return False
        if self._last_heartbeat == 0.0:
            return True  # Not started yet
        return (time.time() - self._last_heartbeat) < self.sync_interval * 2

    async def _run_loop(self):
        """Main loop that calls sync methods periodically with exponential backoff."""
        while self.is_running:
            try:
                self._last_heartbeat = time.time()
                logger.debug(f"[{self.name}] Starting sync cycle")
                result = await self.run_sync_cycle()
                self._last_stats = result.stats
                logger.debug(
                    f"[{self.name}] Sync cycle complete. "
                    f"created={result.stats.created} errors={result.stats.errors} skipped={result.stats.skipped}"
                )
                
                # Reset consecutive errors on success
                self._consecutive_errors = 0
                
                # Wait for next cycle
                await asyncio.sleep(self.sync_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_errors += 1
                backoff = min(
                    INITIAL_BACKOFF_SECONDS * (2 ** (self._consecutive_errors - 1)),
                    MAX_BACKOFF_SECONDS
                )
                logger.error(
                    f"[{self.name}] Error in sync loop (attempt {self._consecutive_errors}): {e}",
                    exc_info=True
                )
                
                # Circuit breaker: pause indexer after too many consecutive failures
                if self._consecutive_errors >= CIRCUIT_BREAKER_THRESHOLD:
                    logger.error(
                        f"[{self.name}] Circuit breaker tripped after {self._consecutive_errors} "
                        f"consecutive failures. Pausing indexer for user {self.user_id}."
                    )
                    self.is_running = False
                    return
                
                await asyncio.sleep(backoff)
                
    async def _process_single_item(self, item: Any) -> Tuple[List[ParsedNode], Optional[str]]:
        """
        Process a single item: transform -> dedup check -> index -> enrich.
        Returns (indexed_nodes, error_message_or_None).
        """
        try:
            # Transform to standardized node(s)
            result = await self.transform_item(item)
            if not result:
                return [], None
                
            nodes = result if isinstance(result, list) else [result]
            if not nodes:
                return [], None
            
            # Content hash dedup: skip duplicate content from different sources
            if self.graph_manager:
                import hashlib
                deduped_nodes = []
                for node in nodes:
                    if node.searchable_text and len(node.searchable_text) > 50:
                        content_hash = hashlib.sha256(
                            node.searchable_text[:500].encode()
                        ).hexdigest()[:16]
                        
                        # Store hash in node properties for future lookups
                        node.properties['_content_hash'] = content_hash
                        
                        # Quick check: does a node with this hash already exist?
                        try:
                            existing = await self.graph_manager.execute_query(
                                """
                                FOR n IN @@collection
                                    FILTER n._content_hash == @hash
                                    FILTER n.user_id == @user_id
                                    LIMIT 1
                                    RETURN n._id
                                """,
                                {
                                    '@collection': node.node_type if isinstance(node.node_type, str) else node.node_type.value,
                                    'hash': content_hash,
                                    'user_id': self.user_id,
                                }
                            )
                            if existing:
                                logger.debug(
                                    f"[{self.name}] Skipping duplicate content (hash={content_hash[:8]})"
                                )
                                continue
                        except Exception:
                            pass  # On query error, proceed with indexing
                    
                    deduped_nodes.append(node)
                
                nodes = deduped_nodes
                if not nodes:
                    return [], None
                
            # Index into Graph + Vector
            if self.hybrid_index:
                success, _ = await self.hybrid_index.index_batch(nodes)
                if not success:
                    return [], f"hybrid_index.index_batch failed"
                    
                # Run shared enrichment pipeline
                await self._enrichment.enrich_nodes(nodes)
                
                return nodes, None
                
            elif self.rag_engine:
                for node in nodes:
                    await self._index_vector_only(node)
                return nodes, None
            else:
                return [], "No index target (hybrid_index or rag_engine)"
                
        except Exception as e:
            item_id = item.get('id', 'unknown') if isinstance(item, dict) else 'unknown'
            return [], f"Item {item_id}: {e}"

    async def run_sync_cycle(self) -> IndexingResult:
        """
        Execute one full sync cycle: fetch -> transform -> index.
        
        Items are processed in concurrent batches for throughput.
        Returns IndexingResult with stats and error details.
        """
        stats = IndexingStats()
        
        try:
            # 0. Load persisted sync state if not yet loaded
            if not self._state_loaded:
                await self.load_crawler_state()
            
            # 1. Fetch new data
            items = await self.fetch_delta()
            if not items:
                return IndexingResult(success=True, stats=stats)
            
            all_indexed_nodes: List[ParsedNode] = []
            
            # 2. Process items in concurrent batches
            for batch_start in range(0, len(items), PROCESSING_BATCH_SIZE):
                batch = items[batch_start:batch_start + PROCESSING_BATCH_SIZE]
                
                results = await asyncio.gather(
                    *[self._process_single_item(item) for item in batch],
                    return_exceptions=True
                )
                
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        stats.errors += 1
                        error_msg = f"Batch exception: {result}"
                        stats.failed_items.append({"batch_index": batch_start + i, "error": error_msg})
                        logger.warning(f"[{self.name}] {error_msg}")
                        continue
                    
                    nodes, error = result
                    if error:
                        stats.errors += 1
                        stats.failed_items.append({"batch_index": batch_start + i, "error": error})
                        logger.warning(f"[{self.name}] Failed to process item: {error}")
                    elif nodes:
                        stats.created += len(nodes)
                        all_indexed_nodes.extend(nodes)
                    else:
                        stats.skipped += 1
            
            # 3. Batch event-driven intelligence across ALL indexed nodes
            if all_indexed_nodes:
                await self._batch_event_driven_intelligence(all_indexed_nodes)
            
            # 4. Log high failure rates as errors
            if items and stats.errors > len(items) * 0.3:
                logger.error(
                    f"[{self.name}] HIGH FAILURE RATE: {stats.errors}/{len(items)} items failed. "
                    f"First errors: {stats.failed_items[:3]}"
                )
            
            # 5. Persist sync state after successful processing
            if stats.created > 0:
                await self.save_crawler_state(items_processed=stats.created)
            
            return IndexingResult(
                success=stats.errors == 0,
                stats=stats,
                errors=[fi['error'] for fi in stats.failed_items] if stats.failed_items else None
            )
            
        except Exception as e:
            logger.error(f"[{self.name}] Sync cycle failed: {e}")
            stats.errors += 1
            return IndexingResult(success=False, stats=stats, errors=[str(e)])

    async def _batch_event_driven_intelligence(self, nodes: List[ParsedNode]):
        """
        Run entity resolution and observer insights in parallel batches
        instead of per-node sequential calls.
        """
        tasks = []
        for node in nodes:
            if self.entity_resolver:
                tasks.append(self.entity_resolver.resolve_immediately(node))
            if self.observer_service:
                tasks.append(self.observer_service.generate_immediate_insight(node))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            errors = [r for r in results if isinstance(r, Exception)]
            if errors:
                logger.debug(
                    f"[{self.name}] {len(errors)}/{len(tasks)} event-driven intelligence tasks failed"
                )
            
    async def _index_vector_only(self, node: ParsedNode):
        """Fallback for when graph is not enabled"""
        if not node.searchable_text or not self.rag_engine:
            return
            
        metadata = node.properties.copy()
        metadata['node_id'] = node.node_id
        metadata['node_type'] = node.node_type
        # Add graph bridge ID (H1: ensures bridge works in fallback path)
        metadata['graph_node_id'] = node.node_id 
        # Add doc_type and source for metadata filtering (V2 compatibility)
        metadata['doc_type'] = metadata.get('doc_type', node.node_type.lower() if isinstance(node.node_type, str) else node.node_type)
        metadata['source'] = metadata.get('source', self.name)
        metadata['user_id'] = metadata.get('user_id', self.user_id)
        
        await asyncio.to_thread(
            self.rag_engine.index_document,
            node.node_id,
            node.searchable_text,
            metadata
        )

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

