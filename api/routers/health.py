"""
Health and Status Endpoints
Enhanced with dependency checking and detailed diagnostics
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional
from datetime import datetime
import time
import psutil
import os

from src.database import get_async_db_context
from src.utils.config import load_config
from src.ai.rag import RAGEngine
from src.utils.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter(tags=["health"])

# Track API start time for uptime calculation
API_START_TIME = time.time()


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Comprehensive health check endpoint with dependency validation
    
    Returns:
        Detailed system health status
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": int(time.time() - API_START_TIME),
        "dependencies": {}
    }
    
    # Check configuration
    try:
        config = load_config("config/config.yaml")
        health_status["dependencies"]["config"] = {"status": "ok", "provider": config.ai.provider}
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["dependencies"]["config"] = {"status": "error", "error": str(e)}
    
    # Check database
    try:
        async with get_async_db_context() as db:
            # Simple query to test connection
            from sqlalchemy import text
            await db.execute(text("SELECT 1"))
            health_status["dependencies"]["database"] = {"status": "ok"}
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["dependencies"]["database"] = {"status": "error", "error": str(e)}
    
    # Check RAG engine
    try:
        # Use cached RAG engine from AppState
        from ..dependencies import AppState
        rag = AppState.get_rag_engine()
        health_status["dependencies"]["rag"] = {"status": "ok"}
    except Exception as e:
        logger.warning(f"RAG engine health check failed: {e}")
        health_status["dependencies"]["rag"] = {"status": "error", "error": str(e)}
    
    # Check LLM provider
    try:
        from src.ai.llm_factory import LLMFactory
        config = load_config("config/config.yaml")
        llm = LLMFactory.get_llm_for_provider(config, temperature=0.1)
        health_status["dependencies"]["llm"] = {
            "status": "ok",
            "provider": config.ai.provider,
            "model": config.ai.model
        }
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["dependencies"]["llm"] = {"status": "error", "error": str(e)}
    
    # Check Celery worker (CRITICAL for email indexing)
    try:
        from src.workers.celery_app import celery_app
        inspect = celery_app.control.inspect(timeout=2.0)
        stats = inspect.stats()
        
        if not stats:
            health_status["status"] = "degraded"
            health_status["dependencies"]["celery"] = {
                "status": "error",
                "error": "No Celery workers running",
                "fix": "Run: ./scripts/start_celery.sh"
            }
        else:
            active_tasks = inspect.active()
            worker_count = len(stats.keys())
            total_active = sum(len(tasks) for tasks in (active_tasks.values() if active_tasks else []))
            
            health_status["dependencies"]["celery"] = {
                "status": "ok",
                "workers": worker_count,
                "active_tasks": total_active,
                "message": f"{worker_count} worker(s) running"
            }
    except Exception as e:
        logger.warning(f"Celery health check failed: {e}")
        health_status["status"] = "degraded"
        health_status["dependencies"]["celery"] = {
            "status": "error",
            "error": str(e),
            "fix": "Start worker: ./scripts/start_celery.sh"
        }
    
    # System resources (if psutil is available)
    try:
        health_status["system"] = {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent
        }
    except Exception:
        pass  # psutil not available or failed
    
    return health_status


@router.get("/")
async def root() -> Dict[str, str]:
    """
    Root endpoint
    
    Returns:
        API information
    """
    return {
        "message": "Email AI Agent API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/health"
    }


@router.get("/api/stats")
@router.get("/stats")  # Alias for backwards compatibility
async def get_stats() -> Dict[str, Any]:
    """
    Get API usage statistics
    
    Returns:
        Usage statistics with query counts, active users, uptime, and performance metrics
    """
    try:
        from src.utils import get_stats_tracker
        
        tracker = await get_stats_tracker()
        stats = await tracker.get_stats()
        
        return {
            "total_queries": stats.total_queries,
            "active_users_today": stats.active_users_today,
            "active_users_this_week": stats.active_users_this_week,
            "uptime_hours": stats.uptime_hours,
            "cache_hit_rate_percent": stats.cache_hit_rate,
            "avg_response_time_ms": stats.avg_response_time_ms,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        # Fallback to basic stats
        return {
            "total_queries": 0,
            "active_users_today": 0,
            "active_users_this_week": 0,
            "uptime_hours": int(time.time() - API_START_TIME) / 3600,
            "cache_hit_rate_percent": 0.0,
            "avg_response_time_ms": 0.0,
            "timestamp": datetime.now().isoformat(),
            "note": "Stats tracking unavailable - using fallback"
        }

