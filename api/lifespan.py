"""
Application lifecycle management
"""
import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.database import init_db, init_async_db
from src.utils.logger import setup_logger
from api.dependencies import AppState

logger = setup_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager
    Replaces deprecated @app.on_event("startup")
    """
    # Startup
    try:
        # Initialize sync database for backward compatibility
        # NOTE: Sync DB is maintained alongside async DB because:
        # 1. Some legacy code paths use sync Session (e.g., ServiceFactory, get_db())
        # 2. Celery workers require sync DB operations
        # 3. Gradual migration to async is in progress (see DBSession + get_async_db)
        init_db()
        logger.info("[OK] Sync database initialized successfully")
        
        # Initialize async database (for async routes and operations)
        await init_async_db()
        logger.info("[OK] Async database initialized successfully")
        
        # Start background email indexing for authenticated users
        # MIGRATED: This is now handled by UnifiedIndexerService (see below)

        
        # Start Unified Indexer (Slack, Notion, etc.)
        try:
            from src.services.indexing.unified_indexer import start_unified_indexing
            from src.database import get_async_db_context
            
            config = AppState.get_config()
            rag_engine = AppState.get_rag_engine()
            cross_stack_context = AppState.get_cross_stack_context()
            
            # For now, let's try to get it from AppState or skip if not available
            graph_manager = getattr(AppState, 'get_knowledge_graph_manager', lambda: None)()
            
            if rag_engine and graph_manager:
                 async with get_async_db_context() as db:
                    await start_unified_indexing(db, config, rag_engine, graph_manager, cross_stack_context)
        except Exception as e:
            logger.warning(f"Could not start Unified Indexer: {e}")

        # Initialize ContactResolver (name → email resolution via Identity Graph)
        try:
            from src.services.contact_resolver import init_contact_resolver
            config = AppState.get_config()
            graph_manager = getattr(AppState, 'get_knowledge_graph_manager', lambda: None)()
            if graph_manager:
                init_contact_resolver(config, graph_manager)
                logger.info("[OK] ContactResolver initialized")
            else:
                logger.warning("[ContactResolver] Skipped — no graph manager available")
        except Exception as e:
            logger.warning(f"Could not initialize ContactResolver: {e}")

        # Initialize PersonalCRM (contact intelligence service)
        try:
            from src.services.crm.personal_crm import init_personal_crm
            config = AppState.get_config()
            graph_manager = getattr(AppState, 'get_knowledge_graph_manager', lambda: None)()
            relationship_manager = AppState.get_relationship_strength_manager()
            if graph_manager:
                init_personal_crm(config, graph_manager, relationship_manager)
                logger.info("[OK] PersonalCRM initialized")
            else:
                logger.warning("[PersonalCRM] Skipped — no graph manager available")
        except Exception as e:
            logger.warning(f"Could not initialize PersonalCRM: {e}")

        # Initialize ContactDeduplicator (merges duplicate Person nodes)
        try:
            from src.services.crm.deduplicator import init_deduplicator
            graph_manager = getattr(AppState, 'get_knowledge_graph_manager', lambda: None)()
            if graph_manager:
                init_deduplicator(graph_manager)
                logger.info("[OK] ContactDeduplicator initialized")
        except Exception as e:
            logger.warning(f"Could not initialize ContactDeduplicator: {e}")

        # Start background profile update service
        try:
            from src.services.profile_service import start_profile_service
            await start_profile_service()
            logger.info("[OK] Background profile update service started")
        except Exception as e:
            logger.warning(f"Could not start profile update service: {e}")
            # Don't fail startup if profile service fails to start
        
        # Start Relationship Decay Job
        try:
            relationship_manager = AppState.get_relationship_strength_manager()
            if relationship_manager:
                await relationship_manager.start_decay_job()
        except Exception as e:
            logger.warning(f"Could not start relationship decay job: {e}")
        
    except Exception as e:
        logger.error(f"[ERROR] Failed to initialize database: {e}", exc_info=True)
    
    yield

    
    try:
        from src.services.indexing.unified_indexer import stop_unified_indexing
        await stop_unified_indexing()
        logger.info("[OK] Unified Indexer stopped")
    except Exception as e:
        logger.warning(f"Error stopping Unified Indexer: {e}")
    
    try:
        from src.services.profile_service import stop_profile_service
        await stop_profile_service()
        logger.info("[OK] Background profile service stopped")
    except asyncio.CancelledError:
        # Expected during shutdown
        logger.info("Profile service cancellation handled during shutdown")
    except Exception as e:
        logger.warning(f"Error stopping profile service: {e}")

    # Stop Relationship Decay Job
    try:
        relationship_manager = AppState.get_relationship_strength_manager()
        if relationship_manager:
            await relationship_manager.stop_decay_job()
    except Exception as e:
        logger.warning(f"Error stopping relationship decay job: {e}")
    
    # Close database connections gracefully
    try:
        from src.database.database import close_db_connections
        from src.database.async_database import close_async_db_connections
        
        close_db_connections()
        await close_async_db_connections()
        logger.info("[OK] Database connections closed")
    except asyncio.CancelledError:
        # Expected during shutdown
        logger.info("Database connection closure cancelled during shutdown")
    except Exception as e:
        logger.warning(f"Error closing database connections: {e}")
    
    logger.info("Shutting down Email AI Agent API")
