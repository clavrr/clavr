"""
Maintenance-related Celery Tasks
Background tasks for system maintenance
"""
import os
import time
from typing import Dict, Any
from datetime import datetime, timedelta

from ..celery_app import celery_app
from ..base_task import BaseTask, IdempotentTask
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


@celery_app.task(base=BaseTask, bind=True)
def health_check_task(self) -> Dict[str, Any]:
    """
    Simple health check task to verify Celery worker is responsive
    
    Returns:
        Health check result with timestamp
    """
    return {
        'status': 'healthy',
        'message': 'Celery worker is running and responsive',
        'timestamp': datetime.utcnow().isoformat(),
        'worker_id': self.request.id
    }


@celery_app.task(base=IdempotentTask, bind=True)
def cleanup_expired_sessions(self) -> Dict[str, Any]:
    """
    Clean up expired user sessions
    
    Returns:
        Cleanup results
    """
    logger.info("Starting expired sessions cleanup")
    
    try:
        from ...database import get_db_context
        from ...database.models import Session
        
        with get_db_context() as db:
            # Delete expired sessions
            deleted_count = db.query(Session).filter(
                Session.expires_at < datetime.utcnow()
            ).delete()
            
            db.commit()
        
        logger.info(f"Cleaned up {deleted_count} expired sessions")
        
        return {
            'deleted_count': deleted_count,
            'status': 'completed',
            'cleanup_time': datetime.utcnow().isoformat()
        }
        
    except Exception as exc:
        logger.error(f"Session cleanup failed: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def update_cache_statistics(self) -> Dict[str, Any]:
    """
    Update cache statistics and metrics
    
    Returns:
        Statistics update results
    """
    logger.info("Updating cache statistics")
    
    try:
        from ...utils import CacheStats
        
        # Build stats dictionary from CacheStats class attributes
        stats = {
            'hits': CacheStats.hits,
            'misses': CacheStats.misses,
            'errors': CacheStats.errors,
            'hit_rate': CacheStats.hit_rate(),
            'total_requests': CacheStats.hits + CacheStats.misses
        }
        
        logger.info(f"Cache statistics updated: {stats}")
        
        return {
            'stats': stats,
            'status': 'completed',
            'update_time': datetime.utcnow().isoformat()
        }
        
    except Exception as exc:
        logger.error(f"Cache statistics update failed: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def cleanup_old_logs(self, days_old: int = 30) -> Dict[str, Any]:
    """
    Clean up old log files
    
    Args:
        days_old: Delete logs older than this many days
        
    Returns:
        Cleanup results
    """
    logger.info(f"Cleaning up logs older than {days_old} days")
    
    try:
        import glob
        
        log_dir = 'logs'
        cutoff_time = time.time() - (days_old * 24 * 60 * 60)
        
        deleted_count = 0
        
        # Find and delete old log files
        for log_file in glob.glob(f"{log_dir}/*.log"):
            if os.path.getmtime(log_file) < cutoff_time:
                os.remove(log_file)
                deleted_count += 1
        
        logger.info(f"Deleted {deleted_count} old log files")
        
        return {
            'deleted_count': deleted_count,
            'status': 'completed'
        }
        
    except Exception as exc:
        logger.error(f"Log cleanup failed: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def backup_database(self) -> Dict[str, Any]:
    """
    Create a database backup
    
    Returns:
        Backup results
    """
    logger.info("Starting database backup")
    
    try:
        import subprocess
        from ...utils.config import load_config
        
        config = load_config()
        db_url = os.getenv('DATABASE_URL', '')
        
        # Generate backup filename
        backup_file = f"backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.sql"
        backup_path = f"backups/{backup_file}"
        
        # Create backups directory if it doesn't exist
        os.makedirs('backups', exist_ok=True)
        
        # Perform backup (PostgreSQL example)
        if 'postgresql' in db_url:
            subprocess.run([
                'pg_dump',
                db_url,
                '-f', backup_path
            ], check=True)
        
        logger.info(f"Database backup created: {backup_path}")
        
        return {
            'backup_file': backup_file,
            'backup_path': backup_path,
            'status': 'completed',
            'backup_time': datetime.utcnow().isoformat()
        }
        
    except Exception as exc:
        logger.error(f"Database backup failed: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def cleanup_celery_results(self, days_old: int = 7) -> Dict[str, Any]:
    """
    Clean up old Celery task results
    
    Args:
        days_old: Delete results older than this many days
        
    Returns:
        Cleanup results
    """
    logger.info(f"Cleaning up Celery results older than {days_old} days")
    
    try:
        from celery.result import AsyncResult
        from ..celery_app import celery_app
        
        # Get all task IDs from result backend
        # This is backend-specific implementation
        
        # For now, just delete expired results
        celery_app.backend.cleanup()
        
        logger.info("Celery results cleaned up")
        
        return {
            'status': 'completed',
            'cleanup_time': datetime.utcnow().isoformat()
        }
        
    except Exception as exc:
        logger.error(f"Celery results cleanup failed: {exc}")
        raise


@celery_app.task(base=IdempotentTask, bind=True)
def health_check_services(self) -> Dict[str, Any]:
    """
    Perform health checks on all services
    
    Returns:
        Health check results
    """
    logger.info("Running service health checks")
    
    try:
        import redis
        from sqlalchemy import text
        
        health_status = {
            'database': False,
            'redis': False,
            'rag_engine': False,
            'celery': True,  # If this task is running, Celery is working
        }
        
        # Check database
        try:
            from ...database import get_db_context
            with get_db_context() as db:
                db.execute(text("SELECT 1"))
            health_status['database'] = True
        except Exception as exc:
            logger.error(f"Database health check failed: {exc}")
        
        # Check Redis
        try:
            r = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))
            r.ping()
            health_status['redis'] = True
        except Exception as exc:
            logger.error(f"Redis health check failed: {exc}")
        
        # Check RAG engine
        try:
            from ...ai.rag import RAGEngine
            from ...utils.config import load_config
            # Use cached RAG engine from worker state
            from . import WorkerState
            rag = WorkerState.get_rag_engine()
            # Perform a simple query
            rag.query("test", top_k=1)
            health_status['rag_engine'] = True
        except Exception as exc:
            logger.error(f"RAG engine health check failed: {exc}")
        
        all_healthy = all(health_status.values())
        
        logger.info(f"Health check completed: {'All services healthy' if all_healthy else 'Some services unhealthy'}")
        
        return {
            'services': health_status,
            'all_healthy': all_healthy,
            'check_time': datetime.utcnow().isoformat(),
            'status': 'completed'
        }
        
    except Exception as exc:
        logger.error(f"Health check failed: {exc}")
        raise


@celery_app.task(base=BaseTask, bind=True)
def generate_usage_report(self, period: str = 'daily') -> Dict[str, Any]:
    """
    Generate usage report for monitoring
    
    Args:
        period: Report period ('daily', 'weekly', 'monthly')
        
    Returns:
        Usage report
    """
    logger.info(f"Generating {period} usage report")
    
    try:
        from ...database import get_db_context
        from ...database import User
        from ...database.models import Session as DBSession
        
        with get_db_context() as db:
            # Get user statistics
            total_users = db.query(User).count()
            active_users = db.query(User).filter(
                User.indexing_status == 'active'
            ).count()
            
            # Get session statistics
            active_sessions = db.query(DBSession).filter(
                DBSession.expires_at > datetime.utcnow()
            ).count()
            
            expired_sessions = db.query(DBSession).filter(
                DBSession.expires_at <= datetime.utcnow()
            ).count()
        
        report = {
            'period': period,
            'user_stats': {
                'total_users': total_users,
                'active_users': active_users,
                'inactive_users': total_users - active_users
            },
            'session_stats': {
                'active_sessions': active_sessions,
                'expired_sessions': expired_sessions,
                'total_sessions': active_sessions + expired_sessions
            },
            'generated_at': datetime.utcnow().isoformat()
        }
        
        logger.info(f"{period.capitalize()} usage report generated")
        
        return report
        
    except Exception as exc:
        logger.error(f"Usage report generation failed: {exc}")
        raise
