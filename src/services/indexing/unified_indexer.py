"""
Unified Indexer Service

Acts as the central "Brain" that orchestrates data ingestion from all connected apps.
Instead of having scattered background tasks, this service manages the lifecycle
of all specific crawling agents (email, slack, notion, etc.).

Enhanced with:
- TemporalIndexer for time-based queries
- InsightService for proactive intelligence
- Fact consolidation for memory accuracy
"""
from __future__ import annotations
from typing import List, Optional, TYPE_CHECKING
import asyncio
from src.utils.logger import setup_logger
from src.services.indexing.base_indexer import BaseIndexer

logger = setup_logger(__name__)

from src.ai.memory.resolution import EntityResolutionService
from src.ai.memory.observer import GraphObserverService

if TYPE_CHECKING:
    from src.ai.autonomy.behavior_learner import BehaviorLearner
    from src.ai.temporal_reasoner import TemporalReasoner
    from src.services.indexing.graph.graph_health import GraphHealthMonitor
    from src.services.reasoning.reasoning_service import GraphReasoningService

class UnifiedIndexerService:
    """
    Central orchestration service for all background indexers.
    
    Enhanced with:
    - Temporal indexing for time-based queries
    - Insight service for proactive intelligence
    - Fact consolidation for memory accuracy
    - Relationship strength tracking and decay
    """
    
    def __init__(self):
        self.indexers: List[BaseIndexer] = []
        self.resolution_service: Optional[EntityResolutionService] = None
        self.observer_service: Optional[GraphObserverService] = None
        self.temporal_indexer = None  # Will be set in start_unified_indexing
        self.insight_service = None   # Will be set in start_unified_indexing
        self.relationship_manager = None  # Will be set in start_unified_indexing
        self.topic_extractor = None  # Will be set in start_unified_indexing
        self.temporal_reasoner: Optional[TemporalReasoner] = None
        self.health_monitor: Optional[GraphHealthMonitor] = None
        self.reasoning_service: Optional[GraphReasoningService] = None
        self.behavior_learner: Optional[BehaviorLearner] = None
        self.is_running = False
        self._consolidation_task: Optional[asyncio.Task] = None
        self.reactive_service = None
        
    def set_reactive_service(self, service):
        """Register the reactive graph service"""
        self.reactive_service = service
        logger.info("[UnifiedIndexer] ReactiveGraphService registered")
        
    def register_indexer(self, indexer: BaseIndexer):
        """Add an indexer to the fleet (sync)"""
        self.indexers.append(indexer)
        logger.info(f"[UnifiedIndexer] Registered {indexer.name}")

    async def register_and_start_indexer(self, indexer: BaseIndexer):
        """Add and immediately start an indexer (for dynamic registration)"""
        self.indexers.append(indexer)
        logger.info(f"[UnifiedIndexer] Registered dynamic indexer {indexer.name}")
        
        if self.is_running:
            try:
                await indexer.start()
                logger.info(f"[UnifiedIndexer] Started dynamic indexer {indexer.name}")
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Failed to start dynamic indexer {indexer.name}: {e}")

    def set_resolution_service(self, service: EntityResolutionService):
        """Register the entity resolution service"""
        self.resolution_service = service

    def set_observer_service(self, service: GraphObserverService):
        """Register the graph observer service"""
        self.observer_service = service

    def set_temporal_indexer(self, temporal_indexer):
        """Register the temporal indexer"""
        self.temporal_indexer = temporal_indexer
        logger.info("[UnifiedIndexer] TemporalIndexer registered")

    def set_insight_service(self, insight_service):
        """Register the insight service"""
        self.insight_service = insight_service
        logger.info("[UnifiedIndexer] InsightService registered")

    def set_relationship_manager(self, relationship_manager):
        """Register the relationship strength manager"""
        self.relationship_manager = relationship_manager
        logger.info("[UnifiedIndexer] RelationshipStrengthManager registered")

    def set_topic_extractor(self, topic_extractor):
        """Register the topic extractor"""
        self.topic_extractor = topic_extractor
        logger.info("[UnifiedIndexer] TopicExtractor registered")

    def set_behavior_learner(self, behavior_learner: BehaviorLearner):
        """Register the behavior learner"""
        self.behavior_learner = behavior_learner
        logger.info("[UnifiedIndexer] BehaviorLearner registered")

    def set_temporal_reasoner(self, temporal_reasoner: TemporalReasoner):
        """Register the temporal reasoner"""
        self.temporal_reasoner = temporal_reasoner
        logger.info("[UnifiedIndexer] TemporalReasoner registered")

    def set_health_monitor(self, health_monitor: GraphHealthMonitor):
        """Register the graph health monitor"""
        self.health_monitor = health_monitor
        logger.info("[UnifiedIndexer] GraphHealthMonitor registered")
    def set_reasoning_service(self, reasoning_service: GraphReasoningService):
        """Register the reasoning service"""
        self.reasoning_service = reasoning_service
        logger.info("[UnifiedIndexer] GraphReasoningService registered")

    async def start_all(self):
        """Start all registered indexers and resolution service"""
        if self.is_running:
            return
            
        logger.info(f"[UnifiedIndexer] Starting {len(self.indexers)} indexers...")
        for indexer in self.indexers:
            try:
                await indexer.start()
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Failed to start {indexer.name}: {e}")
        
        if self.resolution_service:
            try:
                await self.resolution_service.start()
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Failed to start EntityResolutionService: {e}")

        if self.observer_service:
            try:
                await self.observer_service.start()
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Failed to start GraphObserverService: {e}")

        if self.behavior_learner:
            try:
                await self.behavior_learner.start()
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Failed to start BehaviorLearner: {e}")

        # Start relationship strength decay job
        if self.relationship_manager:
            try:
                await self.relationship_manager.start_decay_job()
                logger.info("[UnifiedIndexer] RelationshipStrengthManager decay job started")
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Failed to start RelationshipStrengthManager: {e}")
        
        # Start reasoning service
        if self.reasoning_service:
            try:
                await self.reasoning_service.start()
                logger.info("[UnifiedIndexer] GraphReasoningService started")
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Failed to start GraphReasoningService: {e}")
                
        # Start reactive service
        if self.reactive_service:
            try:
                await self.reactive_service.start()
                logger.info("[UnifiedIndexer] ReactiveGraphService started")
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Failed to start ReactiveGraphService: {e}")

        # Note: Fact consolidation is now handled by Celery Beat
        logger.info("[UnifiedIndexer] Fact consolidation delegated to Celery")
                
        self.is_running = True
        
    async def stop_all(self):
        """Stop all indexers and resolution service"""
        logger.info("[UnifiedIndexer] Stopping all indexers...")
        for indexer in self.indexers:
            try:
                await indexer.stop()
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Error stopping {indexer.name}: {e}")
        
        if self.resolution_service:
            try:
                await self.resolution_service.stop()
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Error stopping EntityResolutionService: {e}")
        
        if self.observer_service:
            try:
                await self.observer_service.stop()
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Error stopping GraphObserverService: {e}")

        if self.behavior_learner:
            try:
                await self.behavior_learner.stop()
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Error stopping BehaviorLearner: {e}")

        # Stop relationship strength manager
        if self.relationship_manager:
            try:
                await self.relationship_manager.stop_decay_job()
                logger.info("[UnifiedIndexer] RelationshipStrengthManager stopped")
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Error stopping RelationshipStrengthManager: {e}")

        # Stop consolidation task
        if self._consolidation_task:
            self._consolidation_task.cancel()
            try:
                await self._consolidation_task
            except asyncio.CancelledError:
                pass
            logger.info("[UnifiedIndexer] Fact consolidation job stopped")

        self.is_running = False

    
    # _create_token_saver logic moved to src.auth.token_persistence

    async def configure_components(self, config, rag_engine, graph_manager, cross_stack_context=None):
        """Initialize all AI components, observers, and services."""
        from src.ai.memory.resolution import EntityResolutionService
        from src.ai.memory.observer import GraphObserverService
        from src.services.indexing.topic_extractor import TopicExtractor
        from src.ai.autonomy.behavior_learner import BehaviorLearner
        from src.ai.temporal_reasoner import TemporalReasoner
        
        # Pre-initialize graph schema
        self.config = config
        try:
            await graph_manager.initialize_schema()
        except Exception as e:
            logger.warning(f"[UnifiedIndexer] Schema initialization failed: {e}")
        
        # 1. TopicExtractor
        try:
            self.topic_extractor = TopicExtractor(config, graph_manager)
            logger.info("[UnifiedIndexer] TopicExtractor initialized")
        except Exception as e:
            logger.warning(f"[UnifiedIndexer] TopicExtractor unavailable: {e}")
        
        # 2. TemporalIndexer
        try:
            from src.services.indexing.temporal_indexer import TemporalIndexer
            self.temporal_indexer = TemporalIndexer(config, graph_manager, rag_engine)
            logger.info("[UnifiedIndexer] TemporalIndexer initialized")
        except Exception as e:
            logger.warning(f"[UnifiedIndexer] TemporalIndexer unavailable: {e}")
        
        # 3. InsightService
        try:
            from src.services.insights import init_insight_service
            self.insight_service = init_insight_service(config, graph_manager)
            logger.info("[UnifiedIndexer] InsightService initialized")
        except Exception as e:
            logger.warning(f"[UnifiedIndexer] InsightService unavailable: {e}")
        
        # 4. Entity Resolution
        try:
            self.resolution_service = EntityResolutionService(config, graph_manager)
            logger.info("[UnifiedIndexer] EntityResolutionService registered")
        except Exception as e:
            logger.error(f"[UnifiedIndexer] Failed to init EntityResolutionService: {e}")

        # 5. Graph Observer
        try:
            self.observer_service = GraphObserverService(config, graph_manager)
            if cross_stack_context:
                self.observer_service.set_cross_stack_context(cross_stack_context)
            logger.info("[UnifiedIndexer] GraphObserverService registered")
        except Exception as e:
            logger.error(f"[UnifiedIndexer] Failed to init GraphObserverService: {e}")

        # 6. Relationship Strength Manager
        try:
            from src.services.indexing.relationship_strength import RelationshipStrengthManager
            self.relationship_manager = RelationshipStrengthManager(config, graph_manager)
            logger.info("[UnifiedIndexer] RelationshipStrengthManager registered")
        except Exception as e:
            logger.warning(f"[UnifiedIndexer] RelationshipStrengthManager unavailable: {e}")

        # 7. Behavior Learner
        try:
            self.behavior_learner = BehaviorLearner(config, graph_manager)
            logger.info("[UnifiedIndexer] BehaviorLearner registered")
        except Exception as e:
            logger.warning(f"[UnifiedIndexer] BehaviorLearner unavailable: {e}")

        # 8. Temporal Reasoner
        try:
            self.temporal_reasoner = TemporalReasoner(config, graph_manager)
            logger.info("[UnifiedIndexer] TemporalReasoner registered")
        except Exception as e:
            logger.warning(f"[UnifiedIndexer] TemporalReasoner unavailable: {e}")

        # 9. Graph Health Monitor
        try:
            from src.services.indexing.graph.graph_health import GraphHealthMonitor
            self.health_monitor = GraphHealthMonitor(config, graph_manager)
            logger.info("[UnifiedIndexer] GraphHealthMonitor registered")
        except Exception as e:
            logger.warning(f"[UnifiedIndexer] GraphHealthMonitor unavailable: {e}")

        # 10. Graph Reasoning Service
        try:
            from src.services.reasoning.reasoning_service import init_reasoning_service
            self.reasoning_service = init_reasoning_service(config, graph_manager, rag_engine)
            logger.info("[UnifiedIndexer] GraphReasoningService initialized")
        except Exception as e:
            logger.warning(f"[UnifiedIndexer] GraphReasoningService unavailable: {e}")

        # 11. Reactive Graph Service
        try:
            from src.services.reasoning.reactive_service import init_reactive_service
            reactive_service = init_reactive_service(config)
            self.set_reactive_service(reactive_service)
            # Inject into Graph Manager for event emission
            graph_manager.set_reactive_service(reactive_service)
            logger.info("[UnifiedIndexer] ReactiveGraphService initialized and linked")
        except Exception as e:
            logger.warning(f"[UnifiedIndexer] ReactiveGraphService unavailable: {e}")

        # 12. Link InsightService dependencies
        if self.insight_service:
            try:
                if self.reasoning_service:
                    self.insight_service.set_reasoning_service(self.reasoning_service)
                if self.reactive_service:
                    self.insight_service.set_reactive_service(self.reactive_service)
                logger.info("[UnifiedIndexer] InsightService dependencies linked")
            except Exception as e:
                logger.warning(f"[UnifiedIndexer] Failed to link InsightService dependencies: {e}")

    async def _run_consolidation_cycle(self):
        """
        Manually trigger a consolidation cycle.
        Delegates to Celery for durability.
        """
        from src.workers.tasks.consolidation_tasks import consolidate_user_memory
        logger.info("[UnifiedIndexer] Triggering manual consolidation cycle via Celery")
        
        try:
            from src.database.models import User
            from sqlalchemy import select
            
            async with self.db as db:
                stmt = select(User)
                result = await db.execute(stmt)
                users = result.scalars().all()
                
                for user in users:
                    consolidate_user_memory.delay(user.id)
                
                logger.info(f"[UnifiedIndexer] Queued consolidation for {len(users)} users")
        except Exception as e:
            logger.error(f"[UnifiedIndexer] Failed to queue consolidation: {e}")

    async def analyze_user_communication_style(self, user_id: int):
        """
        Trigger a "Day One" analysis of the user's communication style.
        Scans sent emails to create a persistent style profile.
        """
        if not self.config:
            logger.warning("[UnifiedIndexer] Cannot analyze style: Config not initialized")
            return

        # find email crawler for user
        email_indexer = None
        for idx in self.indexers:
            if idx.user_id == user_id and idx.name == 'email':
                email_indexer = idx
                break
        
        if not email_indexer:
            logger.info(f"[UnifiedIndexer] No EmailCrawler found for user {user_id}, skipping style analysis")
            return

        try:
            from src.ai.style_analyzer import StyleAnalyzer
            from src.ai.memory.semantic_memory import SemanticMemory
            
            logger.info(f"[UnifiedIndexer] Starting style analysis for user {user_id}...")
            
            # Fetch sent messages
            # Use getattr to be safe if specific class isn't loaded
            if hasattr(email_indexer, 'fetch_recent_sent_messages'):
                texts = await email_indexer.fetch_recent_sent_messages(limit=25)
                
                if texts:
                    analyzer = StyleAnalyzer(self.config)
                    # Use semantic memory from indexer or create new wrapper
                    from src.database import get_async_db_context
                    
                    async with get_async_db_context() as db_session:
                        semantic_mem = SemanticMemory(db_session, email_indexer.rag_engine) # Use crawler's rag engine
                        await analyzer.analyze_and_extract_style(user_id, texts, semantic_mem)
                        
                    logger.info(f"[UnifiedIndexer] Style analysis completed for user {user_id}")
                else:
                    logger.info(f"[UnifiedIndexer] No sent messages found for user {user_id}")
            
        except Exception as e:
            logger.error(f"[UnifiedIndexer] Style analysis failed for user {user_id}: {e}")

# Global instance
_unified_indexer: Optional[UnifiedIndexerService] = None

def get_unified_indexer() -> UnifiedIndexerService:
    global _unified_indexer
    if _unified_indexer is None:
        _unified_indexer = UnifiedIndexerService()
    return _unified_indexer

async def start_unified_indexing(db_session, config, rag_engine, graph_manager, cross_stack_context=None):
    """
    Start the unified indexer and register all active integrations.
    
    Enhanced with TemporalIndexer and InsightService for Phase 1 improvements.
    """
    from src.database.models import UserIntegration
    from src.services.indexing.factory import IndexerFactory
    from src.services.indexing.indexing_constants import (
        PROVIDER_SLACK, PROVIDER_NOTION, PROVIDER_ASANA, 
        PROVIDER_GMAIL, PROVIDER_GOOGLE_DRIVE,
        PROVIDER_CALENDAR, PROVIDER_GOOGLE_TASKS, PROVIDER_GOOGLE_KEEP, PROVIDER_LINEAR,
        CRAWLER_EMAIL, CRAWLER_DRIVE, CRAWLER_SLACK, CRAWLER_NOTION, CRAWLER_ASANA,
        CRAWLER_CALENDAR, CRAWLER_TASKS, CRAWLER_KEEP, CRAWLER_LINEAR
    )
    
    indexer_service = get_unified_indexer()
    
    # Initialize all sub-services and AI components
    await indexer_service.configure_components(config, rag_engine, graph_manager, cross_stack_context)
    
    # Extract common components for easier access in the loop
    topic_extractor = indexer_service.topic_extractor
    temporal_indexer = indexer_service.temporal_indexer
    relationship_manager = indexer_service.relationship_manager
    
    
    from sqlalchemy import select
    
    # 1. Fetch all active integrations (Slack, Notion, Asana, etc.)
    result = await db_session.execute(select(UserIntegration))
    integrations = result.scalars().all()
    
    count = 0
    for integration in integrations:
        try:
            crawler = None
            creds = None
            crawler_type = None

            if integration.provider == PROVIDER_SLACK:
                crawler_type = CRAWLER_SLACK
                # Pass object with access_token/refresh_token attributes or dict
                creds = integration # UserIntegration object has access_token/refresh_token
                
            elif integration.provider == PROVIDER_NOTION:
                crawler_type = CRAWLER_NOTION
                creds = integration.access_token # Just the token string
                
            elif integration.provider == PROVIDER_ASANA:
                crawler_type = CRAWLER_ASANA
                creds = integration.access_token

            elif integration.provider == PROVIDER_GMAIL:
                # Handled via CredentialProvider which does refresh tokens etc.
                from src.core.credential_provider import CredentialProvider
                creds = CredentialProvider.get_integration_credentials(
                    user_id=integration.user_id,
                    provider=PROVIDER_GMAIL,
                    auto_refresh=True
                )
                crawler_type = CRAWLER_EMAIL
                if not creds:
                    continue

                # Token saver for gmail
                from src.auth.token_persistence import create_token_saver_callback
                token_saver = create_token_saver_callback(integration.id, "integration")
                
                crawler = IndexerFactory.create_crawler(
                    crawler_type=crawler_type,
                    config=config,
                    creds=creds,
                    user_id=integration.user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=indexer_service.resolution_service,
                    observer_service=indexer_service.observer_service,
                    token_saver_callback=token_saver
                )
                
            elif integration.provider == PROVIDER_GOOGLE_DRIVE:
                from src.core.credential_provider import CredentialProvider
                creds = CredentialProvider.get_integration_credentials(
                    user_id=integration.user_id,
                    provider=PROVIDER_GOOGLE_DRIVE,
                    auto_refresh=True
                )
                crawler_type = CRAWLER_DRIVE
                if not creds:
                    continue
                    
                # Token saver for drive
                from src.auth.token_persistence import create_token_saver_callback
                token_saver = create_token_saver_callback(integration.id, "integration")
                
                crawler = IndexerFactory.create_crawler(
                    crawler_type=crawler_type,
                    config=config,
                    creds=creds,
                    user_id=integration.user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=indexer_service.resolution_service,
                    observer_service=indexer_service.observer_service,
                    token_saver_callback=token_saver
                )
                
            elif integration.provider == PROVIDER_CALENDAR:
                from src.core.credential_provider import CredentialProvider
                creds = CredentialProvider.get_integration_credentials(
                    user_id=integration.user_id,
                    provider=PROVIDER_CALENDAR,
                    auto_refresh=True
                )
                crawler_type = CRAWLER_CALENDAR
                if not creds:
                    continue
                    
                from src.auth.token_persistence import create_token_saver_callback
                token_saver = create_token_saver_callback(integration.id, "integration")
                
                crawler = IndexerFactory.create_crawler(
                    crawler_type=crawler_type,
                    config=config,
                    creds=creds,
                    user_id=integration.user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=indexer_service.resolution_service,
                    observer_service=indexer_service.observer_service,
                    token_saver_callback=token_saver
                )
                
            elif integration.provider == PROVIDER_GOOGLE_TASKS:
                from src.core.credential_provider import CredentialProvider
                creds = CredentialProvider.get_integration_credentials(
                    user_id=integration.user_id,
                    provider=PROVIDER_GOOGLE_TASKS,
                    auto_refresh=True
                )
                crawler_type = CRAWLER_TASKS
                if not creds:
                    continue
                    
                from src.auth.token_persistence import create_token_saver_callback
                token_saver = create_token_saver_callback(integration.id, "integration")
                
                crawler = IndexerFactory.create_crawler(
                    crawler_type=crawler_type,
                    config=config,
                    creds=creds,
                    user_id=integration.user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=indexer_service.resolution_service,
                    observer_service=indexer_service.observer_service,
                    token_saver_callback=token_saver
                )
                
            elif integration.provider == PROVIDER_GOOGLE_KEEP:
                from src.core.credential_provider import CredentialProvider
                creds = CredentialProvider.get_integration_credentials(
                    user_id=integration.user_id,
                    provider=PROVIDER_GOOGLE_KEEP,
                    auto_refresh=True
                )
                crawler_type = CRAWLER_KEEP
                if not creds:
                    continue
                    
                from src.auth.token_persistence import create_token_saver_callback
                token_saver = create_token_saver_callback(integration.id, "integration")
                
                crawler = IndexerFactory.create_crawler(
                    crawler_type=crawler_type,
                    config=config,
                    creds=creds,
                    user_id=integration.user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=indexer_service.resolution_service,
                    observer_service=indexer_service.observer_service,
                    token_saver_callback=token_saver
                )
                
            elif integration.provider == PROVIDER_LINEAR:
                crawler_type = CRAWLER_LINEAR
                creds = integration
                
                crawler = IndexerFactory.create_crawler(
                    crawler_type=crawler_type,
                    config=config,
                    creds=creds,
                    user_id=integration.user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=indexer_service.resolution_service,
                    observer_service=indexer_service.observer_service
                )

            # Create crawler for generic types (Slack, Notion, Asana) using Factory if not already created
            if not crawler and crawler_type and creds:
                 crawler = IndexerFactory.create_crawler(
                    crawler_type=crawler_type,
                    config=config,
                    creds=creds,
                    user_id=integration.user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=indexer_service.resolution_service,
                    observer_service=indexer_service.observer_service
                )

            if crawler:
                indexer_service.register_indexer(crawler)
                count += 1
                logger.info(f"[UnifiedIndexer] Registered {crawler_type} for user {integration.user_id}")
            
        except Exception as e:
            logger.error(f"[UnifiedIndexer] Failed to register integration {integration.id}: {e}")

    # 2. Fetch authenticated Gmail users (Legacy Auth model)
    try:
        from src.database.models import User, Session as DBSession
        from src.auth.token_refresh import get_valid_credentials
        from google.oauth2.credentials import Credentials
        import os
        
        # Check if email indexing enabled
        if os.getenv("AUTO_START_INDEXING", "false").lower() == "true":
             # Find users with gmail access tokens
             query = select(User).join(DBSession).filter(
                DBSession.gmail_access_token.isnot(None)
             ).distinct()
             
             result = await db_session.execute(query)
             authenticated_users = result.scalars().all()
             
             for user in authenticated_users:
                 try:
                     # Get valid session
                     sess_query = select(DBSession).filter(
                        DBSession.user_id == user.id,
                        DBSession.gmail_access_token.isnot(None)
                     ).order_by(DBSession.id.desc())
                     
                     sess_result = await db_session.execute(sess_query)
                     user_session = sess_result.scalars().first()
                     
                     if user_session:
                        # Define token saver closure
                        from src.auth.token_persistence import create_token_saver_callback
                        token_saver = create_token_saver_callback(user_session.id, "session")

                        # Get credentials
                        creds_obj = get_valid_credentials(db_session, user_session, auto_refresh=True)
                        if creds_obj:
                            client_id = os.getenv('GOOGLE_CLIENT_ID')
                            client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
                            
                            if client_id and client_secret:
                                google_creds = Credentials(
                                    token=creds_obj.token,
                                    refresh_token=creds_obj.refresh_token,
                                    token_uri="https://oauth2.googleapis.com/token",
                                    client_id=client_id,
                                    client_secret=client_secret,
                                    scopes=creds_obj.scopes
                                )
                                
                                # Register Email Crawler via Factory
                                email_crawler = IndexerFactory.create_crawler(
                                    crawler_type=CRAWLER_EMAIL,
                                    config=config,
                                    creds=google_creds,
                                    user_id=user.id,
                                    rag_engine=rag_engine,
                                    graph_manager=graph_manager,
                                    topic_extractor=topic_extractor,
                                    temporal_indexer=temporal_indexer,
                                    relationship_manager=relationship_manager,
                                    entity_resolver=indexer_service.resolution_service,
                                    observer_service=indexer_service.observer_service,
                                    token_saver_callback=token_saver
                                )
                                
                                if email_crawler:
                                    indexer_service.register_indexer(email_crawler)
                                    count += 1
                                    logger.info(f"[UnifiedIndexer] Registered EmailCrawler for user {user.id}")

                                # Register Drive Crawler via Factory
                                drive_crawler = IndexerFactory.create_crawler(
                                    crawler_type=CRAWLER_DRIVE,
                                    config=config,
                                    creds=google_creds,
                                    user_id=user.id,
                                    rag_engine=rag_engine,
                                    graph_manager=graph_manager,
                                    topic_extractor=topic_extractor,
                                    temporal_indexer=temporal_indexer,
                                    relationship_manager=relationship_manager,
                                    entity_resolver=indexer_service.resolution_service,
                                    observer_service=indexer_service.observer_service,
                                    token_saver_callback=token_saver
                                )
                                
                                if drive_crawler:
                                    indexer_service.register_indexer(drive_crawler)
                                    count += 1
                                    logger.info(f"[UnifiedIndexer] Registered DriveCrawler for user {user.id}")
                 except Exception as e:
                     logger.error(f"[UnifiedIndexer] Failed to register email crawler for user {user.id}: {e}")
                     
    except Exception as e:
        logger.error(f"[UnifiedIndexer] Failed to process legacy Gmail integrations: {e}")
        
    # 3. Register Environmental Crawlers (Weather/Maps) for all active users
    try:
        from src.database.models import User
        active_users = (await db_session.execute(select(User))).scalars().all()
        for user in active_users:
            try:
                from src.services.indexing.crawlers.weather import WeatherCrawler
                from src.services.indexing.crawlers.maps import MapsCrawler
                
                weather_crawler = WeatherCrawler(config, graph_manager, user.id)
                maps_crawler = MapsCrawler(config, graph_manager, user.id)
                
                indexer_service.register_indexer(weather_crawler)
                indexer_service.register_indexer(maps_crawler)
                count += 2
                logger.info(f"[UnifiedIndexer] Registered Env Crawlers for user {user.id}")
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Failed to register Env Crawlers for user {user.id}: {e}")
    except Exception as e:
        logger.error(f"[UnifiedIndexer] Failed to process Env Crawlers: {e}")
            
    if count > 0:
        await indexer_service.start_all()
        logger.info(f"[UnifiedIndexer] Started {count} indexers")
        
        # Trigger 'Day One' Style Analysis for all users
        # Runs in background to avoid blocking
        users_to_analyze = {idx.user_id for idx in indexer_service.indexers}
        for uid in users_to_analyze:
            asyncio.create_task(indexer_service.analyze_user_communication_style(uid))

async def stop_unified_indexing():
    """Stop the unified indexer"""
    global _unified_indexer
    if _unified_indexer:
        await _unified_indexer.stop_all()
