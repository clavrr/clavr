"""Tasks package - Background task definitions"""

from typing import Optional, TYPE_CHECKING
from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from src.ai.rag import RAGEngine
    from src.utils.config import Config

logger = setup_logger(__name__)


# ============================================
# WORKER STATE (Singleton Pattern for Workers)
# ============================================

class WorkerState:
    """Worker state holder for singleton instances (Celery workers)"""
    _rag_engine: Optional['RAGEngine'] = None
    _config: Optional['Config'] = None
    
    @classmethod
    def get_config(cls):
        """Get or create config singleton for workers"""
        if cls._config is None:
            from src.utils.config import load_config
            cls._config = load_config()
            logger.info("[Worker Cache] Configuration loaded")
        return cls._config
    
    @classmethod
    def get_rag_engine(cls):
        """Get or create RAG engine singleton for workers"""
        if cls._rag_engine is None:
            from src.ai.rag import RAGEngine
            config = cls.get_config()
            cls._rag_engine = RAGEngine(config)
            logger.info("[Worker Cache] RAG engine initialized and cached")
        return cls._rag_engine
    
    @classmethod
    def reset(cls):
        """Reset all cached instances (for testing)"""
        cls._rag_engine = None
        cls._config = None
        logger.info("[Worker Cache] All cached instances reset")


# Email tasks
from .email_tasks import (
    sync_user_emails,
    sync_all_users_emails,
    send_email,
    batch_send_emails,
    archive_old_emails,
    cleanup_spam,
)

# Calendar tasks
from .calendar_tasks import (
    sync_user_calendar,
    create_event_with_notification,
    update_recurring_events,
    cleanup_old_calendar_events,
)

# Google Tasks tasks
from .tasks_tasks import (
    sync_user_tasks,
    create_task_with_notification,
    complete_task,
    delete_task,
    cleanup_completed_tasks,
    sync_all_task_lists,
)

# Indexing tasks
from .indexing_tasks import (
    index_user_emails,
    index_user_calendar,
    reindex_user_data,
    rebuild_vector_store,
    optimize_vector_store,
)

# Notification tasks
from .notification_tasks import (
    send_email_notification,
    send_calendar_invitation,
    send_task_reminder,
    send_digest_email,
    send_alert,
)

# Maintenance tasks
from .maintenance_tasks import (
    cleanup_expired_sessions,
    update_cache_statistics,
    cleanup_old_logs,
    backup_database,
    cleanup_celery_results,
    health_check_services,
    generate_usage_report,
)

# Export tasks
from .export_tasks import (
    generate_user_export_task,
    cleanup_expired_exports_task,
    generate_scheduled_export_task,
)

# Webhook tasks
from .webhook_tasks import (
    deliver_webhook_task,
    retry_failed_webhooks_task,
    cleanup_old_deliveries_task,
    trigger_email_received_webhook,
    trigger_calendar_event_created_webhook,
    trigger_task_completed_webhook,
    trigger_indexing_completed_webhook,
    trigger_export_completed_webhook,
)

# Workflow tasks
from .workflow_tasks import (
    run_workflow,
)

__all__ = [
    # Email
    'sync_user_emails',
    'sync_all_users_emails',
    'send_email',
    'batch_send_emails',
    'archive_old_emails',
    'cleanup_spam',
    # Calendar
    'sync_user_calendar',
    'create_event_with_notification',
    'update_recurring_events',
    'cleanup_old_calendar_events',
    # Google Tasks
    'sync_user_tasks',
    'create_task_with_notification',
    'complete_task',
    'delete_task',
    'cleanup_completed_tasks',
    'sync_all_task_lists',
    # Indexing
    'index_user_emails',
    'index_user_calendar',
    'reindex_user_data',
    'rebuild_vector_store',
    'optimize_vector_store',
    # Notifications
    'send_email_notification',
    'send_calendar_invitation',
    'send_task_reminder',
    'send_digest_email',
    'send_alert',
    # Maintenance
    'cleanup_expired_sessions',
    'update_cache_statistics',
    'cleanup_old_logs',
    'backup_database',
    'cleanup_celery_results',
    'health_check_services',
    'generate_usage_report',
    # Export
    'generate_user_export_task',
    'cleanup_expired_exports_task',
    'generate_scheduled_export_task',
    # Webhook
    'deliver_webhook_task',
    'retry_failed_webhooks_task',
    'cleanup_old_deliveries_task',
    'trigger_email_received_webhook',
    'trigger_calendar_event_created_webhook',
    'trigger_task_completed_webhook',
    'trigger_indexing_completed_webhook',
    'trigger_export_completed_webhook',
    'run_workflow',
]