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


        # Start fact consolidation background job
        self._consolidation_task = asyncio.create_task(self._run_consolidation_loop())
        logger.info("[UnifiedIndexer] Fact consolidation job started")
                
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

    async def _run_consolidation_loop(self):
        """
        Background job that consolidates semantic memory facts.
        
        Runs daily to:
        - Remove duplicate facts
        - Resolve contradictions
        - Reinforce consistent facts
        """
        # Initial delay to let system stabilize
        await asyncio.sleep(300)  # 5 minutes
        
        consolidation_interval = 86400  # 24 hours
        
        while self.is_running:
            try:
                await self._run_consolidation_cycle()
            except Exception as e:
                logger.error(f"[UnifiedIndexer] Consolidation cycle failed: {e}")
            
            await asyncio.sleep(consolidation_interval)
    
    async def _run_consolidation_cycle(self):
        """Run one consolidation cycle for all active users."""
        try:
            from src.database.async_database import get_async_db_context
            from src.database.models import User
            from src.ai.memory.semantic_memory import SemanticMemory
            from sqlalchemy import select
            
            # Retrieve all users for consolidation
            async with get_async_db_context() as db:
                stmt = select(User)
                result = await db.execute(stmt)
                users = result.scalars().all()
                
                for user in users:
                    try:
                        semantic_memory = SemanticMemory(db)
                        
                        # Consolidate key fact categories
                        for category in ['preference', 'contact', 'work', 'general']:
                            await semantic_memory.consolidate_facts(user.id, category)
                        
                        logger.debug(f"[UnifiedIndexer] Consolidated facts for user {user.id}")
                    except Exception as e:
                        logger.warning(f"[UnifiedIndexer] Consolidation failed for user {user.id}: {e}")
                
                await db.commit()
                logger.info(f"[UnifiedIndexer] Consolidation cycle complete for {len(users)} users")
                
        except ImportError as e:
            logger.debug(f"[UnifiedIndexer] Consolidation skipped (dependencies missing): {e}")
        except Exception as e:
            logger.error(f"[UnifiedIndexer] Consolidation cycle error: {e}")

# Global instance
_unified_indexer: Optional[UnifiedIndexerService] = None

def get_unified_indexer() -> UnifiedIndexerService:
    global _unified_indexer
    if _unified_indexer is None:
        _unified_indexer = UnifiedIndexerService()
    return _unified_indexer

async def start_unified_indexing(db_session, config, rag_engine, graph_manager):
    """
    Start the unified indexer and register all active integrations.
    
    Enhanced with TemporalIndexer and InsightService for Phase 1 improvements.
    """
    from src.database.models import UserIntegration
    from src.services.indexing.crawlers.slack import SlackCrawler
    from src.ai.memory.resolution import EntityResolutionService
    from src.ai.memory.observer import GraphObserverService
    from src.services.indexing.topic_extractor import TopicExtractor
    from src.ai.autonomy.behavior_learner import BehaviorLearner
    from src.ai.temporal_reasoner import TemporalReasoner
    
    indexer_service = get_unified_indexer()
    
    # Pre-initialize graph schema to prevent AQL errors on missing collections
    try:
        await graph_manager.initialize_schema()
    except Exception as e:
        logger.warning(f"[UnifiedIndexer] Schema initialization failed: {e}")
    
    # 0. Initialize TopicExtractor for auto topic extraction
    topic_extractor = None
    try:
        topic_extractor = TopicExtractor(config, graph_manager)
        logger.info("[UnifiedIndexer] TopicExtractor initialized")
    except Exception as e:
        logger.warning(f"[UnifiedIndexer] TopicExtractor unavailable: {e}")
    
    # 0a. Initialize TemporalIndexer for time-based queries
    temporal_indexer = None
    try:
        from src.services.indexing.temporal_indexer import TemporalIndexer
        temporal_indexer = TemporalIndexer(config, graph_manager, rag_engine)
        indexer_service.set_temporal_indexer(temporal_indexer)
        logger.info("[UnifiedIndexer] TemporalIndexer initialized")
    except Exception as e:
        logger.warning(f"[UnifiedIndexer] TemporalIndexer unavailable: {e}")
    
    # 0b. Initialize InsightService for proactive intelligence
    try:
        from src.services.insights import init_insight_service
        insight_service = init_insight_service(config, graph_manager)
        indexer_service.set_insight_service(insight_service)
        logger.info("[UnifiedIndexer] InsightService initialized")
    except Exception as e:
        logger.warning(f"[UnifiedIndexer] InsightService unavailable: {e}")
    
    # 0c. Initialize and register Entity Resolution Service
    try:
        resolution_service = EntityResolutionService(config, graph_manager)
        indexer_service.set_resolution_service(resolution_service)
        logger.info("[UnifiedIndexer] EntityResolutionService registered")
    except Exception as e:
        logger.error(f"[UnifiedIndexer] Failed to init EntityResolutionService: {e}")

    # 0d. Initialize and register Graph Observer Service
    try:
        observer_service = GraphObserverService(config, graph_manager)
        indexer_service.set_observer_service(observer_service)
        logger.info("[UnifiedIndexer] GraphObserverService registered")
    except Exception as e:
        logger.error(f"[UnifiedIndexer] Failed to init GraphObserverService: {e}")

    # 0e. Initialize and register Relationship Strength Manager
    relationship_manager = None
    try:
        from src.services.indexing.relationship_strength import RelationshipStrengthManager
        relationship_manager = RelationshipStrengthManager(config, graph_manager)
        indexer_service.set_relationship_manager(relationship_manager)
        logger.info("[UnifiedIndexer] RelationshipStrengthManager registered")
    except Exception as e:
        logger.warning(f"[UnifiedIndexer] RelationshipStrengthManager unavailable: {e}")

    # 0g. Initialize and register Behavior Learner
    behavior_learner = None
    try:
        behavior_learner = BehaviorLearner(config, graph_manager)
        indexer_service.set_behavior_learner(behavior_learner)
        logger.info("[UnifiedIndexer] BehaviorLearner registered")
    except Exception as e:
        logger.warning(f"[UnifiedIndexer] BehaviorLearner unavailable: {e}")

    # 0h. Initialize and register Temporal Reasoner
    temporal_reasoner = None
    try:
        temporal_reasoner = TemporalReasoner(config, graph_manager)
        indexer_service.set_temporal_reasoner(temporal_reasoner)
        logger.info("[UnifiedIndexer] TemporalReasoner registered")
    except Exception as e:
        logger.warning(f"[UnifiedIndexer] TemporalReasoner unavailable: {e}")

    # 0i. Initialize and register Graph Health Monitor
    health_monitor = None
    try:
        from src.services.indexing.graph.graph_health import GraphHealthMonitor
        health_monitor = GraphHealthMonitor(config, graph_manager)
        indexer_service.set_health_monitor(health_monitor)
        logger.info("[UnifiedIndexer] GraphHealthMonitor registered")
    except Exception as e:
        logger.warning(f"[UnifiedIndexer] GraphHealthMonitor unavailable: {e}")

    # 0j. Initialize and register Graph Reasoning Service
    reasoning_service = None
    try:
        from src.services.reasoning.reasoning_service import init_reasoning_service
        reasoning_service = init_reasoning_service(config, graph_manager, rag_engine)
        indexer_service.set_reasoning_service(reasoning_service)
        logger.info("[UnifiedIndexer] GraphReasoningService initialized")
    except Exception as e:
        logger.warning(f"[UnifiedIndexer] GraphReasoningService unavailable: {e}")

    # 0k. Initialize and register Reactive Graph Service
    reactive_service = None
    try:
        from src.services.reasoning.reactive_service import init_reactive_service
        reactive_service = init_reactive_service(config)
        indexer_service.set_reactive_service(reactive_service)
        # Inject into Graph Manager for event emission
        graph_manager.set_reactive_service(reactive_service)
        logger.info("[UnifiedIndexer] ReactiveGraphService initialized and linked")
    except Exception as e:
        logger.warning(f"[UnifiedIndexer] ReactiveGraphService unavailable: {e}")

    # 0l. Inject dependencies into InsightService
    if indexer_service.insight_service:
        try:
            if reasoning_service:
                indexer_service.insight_service.set_reasoning_service(reasoning_service)
            if reactive_service:
                indexer_service.insight_service.set_reactive_service(reactive_service)
            logger.info("[UnifiedIndexer] InsightService dependencies linked")
        except Exception as e:
            logger.warning(f"[UnifiedIndexer] Failed to link InsightService dependencies: {e}")

    # 0f. Store topic_extractor in service for access by crawlers
    indexer_service.set_topic_extractor(topic_extractor)
    
    # 1. Fetch all active integrations (Slack, Notion, Asana, etc.)
    integrations = db_session.query(UserIntegration).all()
    
    count = 0
    for integration in integrations:
        try:
            if integration.provider == 'slack':
                # Create SlackCrawler
                from src.integrations.slack.client import SlackClient
                client = SlackClient(bot_token=integration.access_token, app_token=integration.refresh_token) 
                
                crawler = SlackCrawler(
                    config=config,
                    user_id=integration.user_id,
                    rag_engine=rag_engine,
                    graph_manager=graph_manager,
                    slack_client=client,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    entity_resolver=indexer_service.resolution_service,
                    observer_service=indexer_service.observer_service
                )
                
                indexer_service.register_indexer(crawler)
                count += 1
                logger.info(f"[UnifiedIndexer] Registered SlackCrawler for user {integration.user_id}")
            
            elif integration.provider == 'notion':
                # Create NotionCrawler
                try:
                    from src.services.indexing.crawlers.notion import NotionCrawler
                    from src.integrations.notion.client import NotionClient
                    
                    notion_client = NotionClient(api_key=integration.access_token)
                    
                    crawler = NotionCrawler(
                        config=config,
                        user_id=integration.user_id,
                        rag_engine=rag_engine,
                        graph_manager=graph_manager,
                        notion_client=notion_client,
                        topic_extractor=topic_extractor,
                        temporal_indexer=temporal_indexer,
                        relationship_manager=relationship_manager,
                        entity_resolver=indexer_service.resolution_service,
                        observer_service=indexer_service.observer_service
                    )
                    
                    indexer_service.register_indexer(crawler)
                    count += 1
                    logger.info(f"[UnifiedIndexer] Registered NotionCrawler for user {integration.user_id}")
                except Exception as e:
                    logger.warning(f"[UnifiedIndexer] Failed to create NotionCrawler: {e}")
            
            elif integration.provider == 'asana':
                # Create AsanaCrawler
                try:
                    from src.services.indexing.crawlers.asana import AsanaCrawler
                    from src.integrations.asana.service import AsanaService
                    
                    asana_service = AsanaService(
                        config=config,
                        access_token=integration.access_token
                    )
                    
                    crawler = AsanaCrawler(
                        config=config,
                        user_id=integration.user_id,
                        rag_engine=rag_engine,
                        graph_manager=graph_manager,
                        asana_service=asana_service,
                        topic_extractor=topic_extractor,
                        temporal_indexer=temporal_indexer,
                        relationship_manager=relationship_manager,
                        entity_resolver=indexer_service.resolution_service,
                        observer_service=indexer_service.observer_service
                    )
                    
                    indexer_service.register_indexer(crawler)
                    count += 1
                    logger.info(f"[UnifiedIndexer] Registered AsanaCrawler for user {integration.user_id}")
                except Exception as e:
                    logger.warning(f"[UnifiedIndexer] Failed to create AsanaCrawler: {e}")
                
            elif integration.provider == 'gmail':
                # Create EmailCrawler
                from src.services.indexing.crawlers.email import EmailCrawler
                from src.core.email.google_client import GoogleGmailClient
                from src.core.credential_provider import CredentialProvider

                google_creds = CredentialProvider.get_integration_credentials(
                    user_id=integration.user_id,
                    provider='gmail',
                    auto_refresh=True
                )
                
                if google_creds:
                    # Create token saver for UserIntegration table
                    def create_integration_token_saver(integration_id: int):
                        def save_tokens(creds):
                            try:
                                from src.database import get_db_context
                                from src.utils import encrypt_token
                                from sqlalchemy import update
                                from src.database.models import UserIntegration
                                
                                with get_db_context() as db:
                                    enc_access = encrypt_token(creds.token)
                                    enc_refresh = encrypt_token(creds.refresh_token) if creds.refresh_token else None
                                    
                                    values = {
                                        "access_token": enc_access,
                                        "expires_at": creds.expiry.replace(tzinfo=None) if creds.expiry else None
                                    }
                                    if enc_refresh:
                                        values["refresh_token"] = enc_refresh
                                        
                                    db.execute(
                                        update(UserIntegration)
                                        .where(UserIntegration.id == integration_id)
                                        .values(**values)
                                    )
                                    db.commit()
                                    logger.info(f"[UnifiedIndexer] Persisted refreshed tokens for integration {integration_id}")
                            except Exception as e:
                                logger.error(f"[UnifiedIndexer] Failed to persist tokens for integration {integration_id}: {e}")
                        return save_tokens
                    
                    token_saver = create_integration_token_saver(integration.id)
                    
                    google_client = GoogleGmailClient(
                        config=config, 
                        credentials=google_creds,
                        token_update_callback=token_saver
                    )
                    crawler = EmailCrawler(
                        config=config,
                        user_id=integration.user_id,
                        rag_engine=rag_engine,
                        graph_manager=graph_manager,
                        google_client=google_client,
                        topic_extractor=topic_extractor,
                        temporal_indexer=temporal_indexer,
                        relationship_manager=relationship_manager,
                        entity_resolver=indexer_service.resolution_service,
                        observer_service=indexer_service.observer_service
                    )
                    indexer_service.register_indexer(crawler)
                    count += 1
                    logger.info(f"[UnifiedIndexer] Registered EmailCrawler (Integration) for user {integration.user_id}")
            
            elif integration.provider == 'google_drive':
                # Create DriveCrawler
                from src.services.indexing.crawlers.drive import DriveCrawler
                from src.integrations.google_drive.service import GoogleDriveService
                from src.core.credential_provider import CredentialProvider

                google_creds = CredentialProvider.get_integration_credentials(
                    user_id=integration.user_id,
                    provider='google_drive',
                    auto_refresh=True
                )
                
                if google_creds:
                    # Create token saver for UserIntegration table
                    def create_integration_token_saver(integration_id: int):
                        def save_tokens(creds):
                            try:
                                from src.database import get_db_context
                                from src.utils import encrypt_token
                                from sqlalchemy import update
                                from src.database.models import UserIntegration
                                
                                with get_db_context() as db:
                                    enc_access = encrypt_token(creds.token)
                                    enc_refresh = encrypt_token(creds.refresh_token) if creds.refresh_token else None
                                    
                                    values = {
                                        "access_token": enc_access,
                                        "expires_at": creds.expiry.replace(tzinfo=None) if creds.expiry else None
                                    }
                                    if enc_refresh:
                                        values["refresh_token"] = enc_refresh
                                        
                                    db.execute(
                                        update(UserIntegration)
                                        .where(UserIntegration.id == integration_id)
                                        .values(**values)
                                    )
                                    db.commit()
                                    logger.info(f"[UnifiedIndexer] Persisted refreshed tokens for integration {integration_id}")
                            except Exception as e:
                                logger.error(f"[UnifiedIndexer] Failed to persist tokens for integration {integration_id}: {e}")
                        return save_tokens
                    
                    token_saver = create_integration_token_saver(integration.id)
                    
                    drive_service = GoogleDriveService(
                        config=config, 
                        credentials=google_creds,
                        token_update_callback=token_saver
                    )
                    crawler = DriveCrawler(
                        config=config,
                        user_id=integration.user_id,
                        rag_engine=rag_engine,
                        graph_manager=graph_manager,
                        drive_service=drive_service,
                        topic_extractor=topic_extractor,
                        temporal_indexer=temporal_indexer,
                        relationship_manager=relationship_manager,
                        entity_resolver=indexer_service.resolution_service,
                        observer_service=indexer_service.observer_service
                    )
                    indexer_service.register_indexer(crawler)
                    count += 1
                    logger.info(f"[UnifiedIndexer] Registered DriveCrawler (Integration) for user {integration.user_id}")
                
        except Exception as e:
            logger.error(f"[UnifiedIndexer] Failed to register integration {integration.id}: {e}")

    # 2. Fetch authenticated Gmail users (Legacy Auth model)
    try:
        from src.database.models import User, Session as DBSession
        from src.services.indexing.crawlers.email import EmailCrawler
        from src.services.indexing.crawlers.drive import DriveCrawler
        from src.core.email.google_client import GoogleGmailClient
        from src.integrations.google_drive.service import GoogleDriveService
        from src.auth.token_refresh import get_valid_credentials
        from google.oauth2.credentials import Credentials
        import os
        
        # Check if email indexing enabled
        if os.getenv("AUTO_START_INDEXING", "false").lower() == "true":
             # Find users with gmail access tokens
             authenticated_users = db_session.query(User).join(DBSession).filter(
                DBSession.gmail_access_token.isnot(None)
             ).distinct().all()
             
             for user in authenticated_users:
                 try:
                     # Get valid session
                     user_session = db_session.query(DBSession).filter(
                        DBSession.user_id == user.id,
                        DBSession.gmail_access_token.isnot(None)
                     ).order_by(DBSession.id.desc()).first()
                     
                     if user_session:
                        # Define token saver closure
                        def create_token_saver(session_id: int):
                            def save_tokens(creds):
                                try:
                                    from src.database import get_db_context
                                    from src.utils import encrypt_token
                                    from sqlalchemy import update
                                    from src.database.models import Session
                                    
                                    with get_db_context() as db:
                                        # Encrypt new tokens
                                        enc_access = encrypt_token(creds.token)
                                        enc_refresh = encrypt_token(creds.refresh_token) if creds.refresh_token else None
                                        
                                        # Prepare update values
                                        values = {
                                            "gmail_access_token": enc_access,
                                            "token_expiry": creds.expiry.replace(tzinfo=None) if creds.expiry else None
                                        }
                                        if enc_refresh:
                                            values["gmail_refresh_token"] = enc_refresh
                                            
                                        db.execute(
                                            update(Session)
                                            .where(Session.id == session_id)
                                            .values(**values)
                                        )
                                        db.commit()
                                        logger.info(f"[UnifiedIndexer] Persisted refreshed tokens for session {session_id}")
                                except Exception as e:
                                    logger.error(f"[UnifiedIndexer] Failed to persist tokens for session {session_id}: {e}")
                            return save_tokens

                        token_saver = create_token_saver(user_session.id)

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
                                
                                # Fix: Initialize Gmail/Drive clients with token_update_callback
                                google_client = GoogleGmailClient(
                                    config=config, 
                                    credentials=google_creds,
                                    token_update_callback=token_saver
                                )
                                
                                email_crawler = EmailCrawler(
                                    config=config,
                                    user_id=user.id,
                                    rag_engine=rag_engine,
                                    graph_manager=graph_manager,
                                    google_client=google_client,
                                    topic_extractor=topic_extractor,
                                    temporal_indexer=temporal_indexer,
                                    relationship_manager=relationship_manager,
                                    entity_resolver=indexer_service.resolution_service,
                                    observer_service=indexer_service.observer_service
                                )
                                
                                indexer_service.register_indexer(email_crawler)
                                count += 1
                                logger.info(f"[UnifiedIndexer] Registered EmailCrawler for user {user.id}")

                                # 2b. Register DriveCrawler
                                drive_service = GoogleDriveService(
                                    config=config, 
                                    credentials=google_creds,
                                    token_update_callback=token_saver
                                )
                                drive_crawler = DriveCrawler(
                                    config=config,
                                    user_id=user.id,
                                    rag_engine=rag_engine,
                                    graph_manager=graph_manager,
                                    drive_service=drive_service,
                                    topic_extractor=topic_extractor,
                                    temporal_indexer=temporal_indexer,
                                    relationship_manager=relationship_manager,
                                    entity_resolver=indexer_service.resolution_service,
                                    observer_service=indexer_service.observer_service
                                )
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
        active_users = db_session.query(User).all()
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

async def stop_unified_indexing():
    """Stop the unified indexer"""
    global _unified_indexer
    if _unified_indexer:
        await _unified_indexer.stop_all()
