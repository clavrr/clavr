"""
Consolidation-related Celery Tasks
Background tasks for periodic knowledge graph and memory consolidation
"""
import asyncio
from typing import Dict, Any
from datetime import datetime

from ..celery_app import celery_app
from ..base_task import IdempotentTask
from src.utils.logger import setup_logger
from src.database import get_db_context
from src.database.models import User

logger = setup_logger(__name__)

@celery_app.task(base=IdempotentTask, bind=True)
def consolidate_all_users_memory(self) -> Dict[str, Any]:
    """
    Periodic task to consolidate semantic memory facts for all users.
    Replaces the internal asyncio loop in UnifiedIndexerService.
    """
    logger.info("Starting global memory consolidation cycle")
    
    try:
        with get_db_context() as db:
            users = db.query(User).all()
            user_ids = [user.id for user in users]
            
        count = 0
        for user_id in user_ids:
            # Trigger individual consolidation tasks
            consolidate_user_memory.delay(user_id)
            count += 1
            
        logger.info(f"Queued consolidation for {count} users")
        return {
            "status": "completed",
            "users_queued": count,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Global consolidation failed: {e}")
        raise

@celery_app.task(base=IdempotentTask, bind=True)
def consolidate_user_memory(self, user_id: int) -> Dict[str, Any]:
    """
    Consolidate memory facts for a specific user.
    """
    logger.info(f"Consolidating memory for user {user_id}")
    
    async def _async_consolidate():
        from src.database.async_database import get_async_db_context
        from src.ai.memory.semantic_memory import SemanticMemory
        
        async with get_async_db_context() as db:
            try:
                semantic_memory = SemanticMemory(db)
                
                from src.agents.constants import MEMORY_CATEGORIES
                
                # Consolidate key fact categories
                # Reuses logic from UnifiedIndexerService._run_consolidation_cycle
                results = {}
                
                for category in MEMORY_CATEGORIES:
                    await semantic_memory.consolidate_facts(user_id, category)
                    results[category] = "success"
                
                await db.commit()
                return results
            except Exception as e:
                logger.error(f"Memory consolidation failed for user {user_id}: {e}")
                return {"error": str(e)}

    # Run the async logic
    results = asyncio.run(_async_consolidate())
    
    return {
        "user_id": user_id,
        "status": "completed" if "error" not in results else "failed",
        "results": results,
        "timestamp": datetime.utcnow().isoformat()
    }
