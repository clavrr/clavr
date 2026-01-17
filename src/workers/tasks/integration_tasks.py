"""
Integration-related Celery Tasks
Background tasks for periodic synchronization of third-party integrations (Slack, Notion, etc.)
"""
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

from ..celery_app import celery_app
from ..base_task import IdempotentTask
from src.utils.logger import setup_logger
from src.database import get_db_context
from src.database.models import UserIntegration, User
from src.utils.config import load_config

logger = setup_logger(__name__)

@celery_app.task(base=IdempotentTask, bind=True)
def sync_all_integrations(self) -> Dict[str, Any]:
    """
    Periodic task to trigger sync for all active user integrations.
    Replaces the distributed asyncio loops in individual crawlers.
    """
    logger.info("Starting global integration sync cycle")
    
    try:
        with get_db_context() as db:
            active_integrations = db.query(UserIntegration).filter(
                UserIntegration.is_active == True
            ).all()
            
            count = 0
            for integration in active_integrations:
                # Trigger individual sync task
                run_integration_sync.delay(integration.id)
                count += 1
                
        logger.info(f"Queued sync for {count} integrations")
        return {
            "status": "completed",
            "integrations_queued": count,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Global integration sync trigger failed: {e}")
        raise

@celery_app.task(base=IdempotentTask, bind=True)
def run_integration_sync(self, integration_id: int) -> Dict[str, Any]:
    """
    Run a single sync cycle for a specific integration.
    """
    logger.info(f"Running sync for integration {integration_id}")
    
    async def _async_sync():
        try:
            from src.database.async_database import get_async_db_context
            from api.dependencies import AppState
            from src.services.indexing.unified_indexer import get_unified_indexer
            
            config = load_config()
            
            async with get_async_db_context() as db:
                from sqlalchemy import select
                stmt = select(UserIntegration).where(UserIntegration.id == integration_id)
                result = await db.execute(stmt)
                integration = result.scalar_one_or_none()
                
                if not integration or not integration.is_active:
                    return {"status": "skipped", "reason": "Integration not found or inactive"}
                
                # Get user to ensure they exist
                stmt = select(User).where(User.id == integration.user_id)
                result = await db.execute(stmt)
                user = result.scalar_one_or_none()
                if not user:
                    return {"status": "skipped", "reason": "User not found"}

                # We need RAG engine and Graph Manager
                # In Celery worker, we might need to initialize these if not available
                # But typically they are available via AppState if initialized in worker boot
                
                from src.ai.rag import RAGEngine
                from src.services.indexing.graph import KnowledgeGraphManager
                
                rag_engine = RAGEngine(config=config, collection_name=f"user_{user.id}_integrations")
                graph_manager = KnowledgeGraphManager(config=config)
                
                # Now we need to create the specific crawler based on provider
                crawler = await _create_crawler(integration, config, rag_engine, graph_manager)
                
                if not crawler:
                    return {"status": "failed", "reason": f"Unsupported provider: {integration.provider}"}
                
                # Run ONE sync cycle
                count = await crawler.run_sync_cycle()
                
                return {
                    "status": "completed",
                    "items_indexed": count,
                    "provider": integration.provider,
                    "user_id": user.id
                }
        except Exception as e:
            logger.error(f"Sync failed for integration {integration_id}: {e}", exc_info=True)
            return {"status": "failed", "error": str(e)}

    # Run the async logic
    results = asyncio.run(_async_sync())
    
    return {
        "integration_id": integration_id,
        "results": results,
        "timestamp": datetime.utcnow().isoformat()
    }

async def _create_crawler(integration, config, rag_engine, graph_manager):
    """Helper to instantiate the correct crawler."""
    from src.services.indexing.unified_indexer import get_unified_indexer
    indexer_service = get_unified_indexer()
    
    # Dependencies required by crawlers
    topic_extractor = indexer_service.topic_extractor
    temporal_indexer = indexer_service.temporal_indexer
    relationship_manager = indexer_service.relationship_manager
    entity_resolver = indexer_service.resolution_service
    observer_service = indexer_service.observer_service
    
    if integration.provider == 'slack':
        from src.services.indexing.crawlers.slack import SlackCrawler
        from src.integrations.slack.client import SlackClient
        client = SlackClient(bot_token=integration.access_token, app_token=integration.refresh_token)
        return SlackCrawler(
            config=config, user_id=integration.user_id, rag_engine=rag_engine,
            graph_manager=graph_manager, slack_client=client,
            topic_extractor=topic_extractor, temporal_indexer=temporal_indexer,
            relationship_manager=relationship_manager, entity_resolver=entity_resolver,
            observer_service=observer_service
        )
        
    elif integration.provider == 'notion':
        from src.services.indexing.crawlers.notion import NotionCrawler
        from src.integrations.notion.client import NotionClient
        client = NotionClient(api_key=integration.access_token)
        return NotionCrawler(
            config=config, user_id=integration.user_id, rag_engine=rag_engine,
            graph_manager=graph_manager, notion_client=client,
            topic_extractor=topic_extractor, temporal_indexer=temporal_indexer,
            relationship_manager=relationship_manager, entity_resolver=entity_resolver,
            observer_service=observer_service
        )
        
    elif integration.provider == 'asana':
        from src.services.indexing.crawlers.asana import AsanaCrawler
        from src.integrations.asana.service import AsanaService
        service = AsanaService(config=config, access_token=integration.access_token)
        return AsanaCrawler(
            config=config, user_id=integration.user_id, rag_engine=rag_engine,
            graph_manager=graph_manager, asana_service=service,
            topic_extractor=topic_extractor, temporal_indexer=temporal_indexer,
            relationship_manager=relationship_manager, entity_resolver=entity_resolver,
            observer_service=observer_service
        )
    
    # Add more providers as needed
    return None
