"""
Tests for Celery Job Queue Implementation
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

# Mark all tests in this module for Celery
pytestmark = pytest.mark.celery


class TestCeleryApp:
    """Tests for Celery application configuration"""
    
    def test_celery_app_creation(self):
        """Test Celery app is created correctly"""
        from src.workers.celery_app import celery_app
        
        assert celery_app is not None
        assert celery_app.main == 'notely_agent'
    
    def test_celery_config(self):
        """Test Celery configuration"""
        from src.workers.celery_app import celery_app
        
        # Check basic config
        assert celery_app.conf.task_serializer == 'json'
        assert celery_app.conf.result_serializer == 'json'
        assert celery_app.conf.timezone == 'UTC'
        assert celery_app.conf.enable_utc is True
    
    def test_task_queues_configured(self):
        """Test task queues are configured"""
        from src.workers.celery_app import celery_app
        
        queue_names = [q.name for q in celery_app.conf.task_queues]
        
        assert 'default' in queue_names
        assert 'email' in queue_names
        assert 'calendar' in queue_names
        assert 'indexing' in queue_names
        assert 'notifications' in queue_names
        assert 'priority' in queue_names
    
    def test_task_routes_configured(self):
        """Test task routing is configured"""
        from src.workers.celery_app import celery_app
        
        routes = celery_app.conf.task_routes
        
        assert 'src.workers.tasks.email_tasks.*' in routes
        assert routes['src.workers.tasks.email_tasks.*']['queue'] == 'email'
    
    def test_beat_schedule_configured(self):
        """Test periodic tasks are configured"""
        from src.workers.celery_app import celery_app
        
        schedule = celery_app.conf.beat_schedule
        
        assert 'sync-emails-every-5-minutes' in schedule
        assert 'cleanup-expired-sessions-hourly' in schedule
    
    def test_get_celery_app(self):
        """Test get_celery_app helper"""
        from src.workers.celery_app import get_celery_app
        
        app = get_celery_app()
        assert app is not None
        assert app.main == 'notely_agent'


class TestBaseTask:
    """Tests for BaseTask class"""
    
    def test_base_task_imports(self):
        """Test BaseTask can be imported"""
        from src.workers.base_task import BaseTask, PriorityTask, LongRunningTask
        
        assert BaseTask is not None
        assert PriorityTask is not None
        assert LongRunningTask is not None
    
    def test_base_task_retry_config(self):
        """Test BaseTask has retry configuration"""
        from src.workers.base_task import BaseTask
        
        assert hasattr(BaseTask, 'autoretry_for')
        assert hasattr(BaseTask, 'retry_kwargs')
        assert BaseTask.retry_backoff is True
    
    def test_priority_task_config(self):
        """Test PriorityTask configuration"""
        from src.workers.base_task import PriorityTask
        
        assert PriorityTask.queue == 'priority'
        assert PriorityTask.priority == 9
    
    def test_long_running_task_config(self):
        """Test LongRunningTask configuration"""
        from src.workers.base_task import LongRunningTask
        
        assert hasattr(LongRunningTask, 'soft_time_limit')
        assert hasattr(LongRunningTask, 'time_limit')
        assert LongRunningTask.soft_time_limit == 3600  # 1 hour


class TestTaskStatus:
    """Tests for task status helpers"""
    
    @patch('src.workers.celery_app.AsyncResult')
    def test_get_task_status(self, mock_async_result):
        """Test getting task status"""
        from src.workers.celery_app import get_task_status
        
        # Mock task result
        mock_result = Mock()
        mock_result.state = 'SUCCESS'
        mock_result.status = 'SUCCESS'
        mock_result.ready.return_value = True
        mock_result.result = {'data': 'test'}
        mock_result.info = {}
        mock_result.failed.return_value = False
        mock_result.traceback = None
        
        mock_async_result.return_value = mock_result
        
        status = get_task_status('test-task-id')
        
        assert status['task_id'] == 'test-task-id'
        assert status['state'] == 'SUCCESS'
        assert status['result'] == {'data': 'test'}
    
    @patch('src.workers.celery_app.celery_app.control.revoke')
    def test_cancel_task(self, mock_revoke):
        """Test cancelling a task"""
        from src.workers.celery_app import cancel_task
        
        result = cancel_task('test-task-id', terminate=False)
        
        assert result is True
        mock_revoke.assert_called_once_with('test-task-id')
    
    @patch('src.workers.celery_app.celery_app.control.revoke')
    def test_terminate_task(self, mock_revoke):
        """Test terminating a task"""
        from src.workers.celery_app import cancel_task
        
        result = cancel_task('test-task-id', terminate=True)
        
        assert result is True
        mock_revoke.assert_called_once_with('test-task-id', terminate=True, signal='SIGKILL')


class TestEmailTasks:
    """Tests for email tasks"""
    
    def test_email_tasks_import(self):
        """Test email tasks can be imported"""
        from src.workers.tasks.email_tasks import (
            sync_user_emails,
            sync_all_users_emails,
            send_email,
            batch_send_emails,
            archive_old_emails,
            cleanup_spam
        )
        
        assert sync_user_emails is not None
        assert sync_all_users_emails is not None
        assert send_email is not None
    
    def test_sync_user_emails_signature(self):
        """Test sync_user_emails task signature"""
        from src.workers.tasks.email_tasks import sync_user_emails
        
        # Task should be registered
        assert sync_user_emails.name == 'src.workers.tasks.email_tasks.sync_user_emails'
    
    @pytest.mark.asyncio
    @patch('src.workers.tasks.email_tasks.GoogleGmailClient')
    @patch('src.workers.tasks.email_tasks.get_db_session')
    async def test_sync_user_emails_execution(self, mock_db, mock_client):
        """Test sync_user_emails execution (mock)"""
        from src.workers.tasks.email_tasks import sync_user_emails
        
        # Mock database
        mock_session = MagicMock()
        mock_user = Mock()
        mock_user.id = 'user_123'
        mock_session.query.return_value.filter.return_value.first.return_value = mock_user
        mock_db.return_value.__enter__.return_value = mock_session
        
        # Mock email client
        mock_client_instance = Mock()
        mock_client_instance.list_messages.return_value = [
            {'id': '1', 'subject': 'Test 1'},
            {'id': '2', 'subject': 'Test 2'}
        ]
        mock_client.return_value = mock_client_instance
        
        # Execute task eagerly (synchronously)
        with patch.dict('os.environ', {'CELERY_TASK_ALWAYS_EAGER': 'true'}):
            result = sync_user_emails('user_123')
            
            assert result['user_id'] == 'user_123'
            assert result['status'] == 'success'
            assert result['emails_synced'] == 2


class TestCalendarTasks:
    """Tests for calendar tasks"""
    
    def test_calendar_tasks_import(self):
        """Test calendar tasks can be imported"""
        from src.workers.tasks.calendar_tasks import (
            sync_user_calendar,
            create_event_with_notification,
            update_recurring_events,
            cleanup_old_calendar_events
        )
        
        assert sync_user_calendar is not None
        assert create_event_with_notification is not None


class TestIndexingTasks:
    """Tests for indexing tasks"""
    
    def test_indexing_tasks_import(self):
        """Test indexing tasks can be imported"""
        from src.workers.tasks.indexing_tasks import (
            index_user_emails,
            index_user_calendar,
            reindex_user_data,
            rebuild_vector_store,
            optimize_vector_store
        )
        
        assert index_user_emails is not None
        assert reindex_user_data is not None


class TestNotificationTasks:
    """Tests for notification tasks"""
    
    def test_notification_tasks_import(self):
        """Test notification tasks can be imported"""
        from src.workers.tasks.notification_tasks import (
            send_email_notification,
            send_calendar_invitation,
            send_task_reminder,
            send_digest_email,
            send_alert
        )
        
        assert send_email_notification is not None
        assert send_alert is not None
    
    def test_send_email_notification_is_priority(self):
        """Test email notification is high priority"""
        from src.workers.tasks.notification_tasks import send_email_notification
        
        # Should use PriorityTask base
        assert 'Priority' in str(send_email_notification.__class__.__bases__)


class TestMaintenanceTasks:
    """Tests for maintenance tasks"""
    
    def test_maintenance_tasks_import(self):
        """Test maintenance tasks can be imported"""
        from src.workers.tasks.maintenance_tasks import (
            cleanup_expired_sessions,
            update_cache_statistics,
            cleanup_old_logs,
            backup_database,
            health_check_services,
            generate_usage_report
        )
        
        assert cleanup_expired_sessions is not None
        assert health_check_services is not None
    
    @patch('src.workers.tasks.maintenance_tasks.get_db_session')
    def test_cleanup_expired_sessions_execution(self, mock_db):
        """Test cleanup_expired_sessions execution"""
        from src.workers.tasks.maintenance_tasks import cleanup_expired_sessions
        
        # Mock database
        mock_session = MagicMock()
        mock_query = Mock()
        mock_query.filter.return_value.delete.return_value = 5
        mock_session.query.return_value = mock_query
        mock_db.return_value.__enter__.return_value = mock_session
        
        # Execute task
        with patch.dict('os.environ', {'CELERY_TASK_ALWAYS_EAGER': 'true'}):
            result = cleanup_expired_sessions()
            
            assert result['deleted_count'] == 5
            assert result['status'] == 'completed'


class TestTaskChaining:
    """Tests for task chaining and workflows"""
    
    def test_task_chain_creation(self):
        """Test creating task chains"""
        from celery import chain
        from src.workers.tasks.email_tasks import sync_user_emails
        from src.workers.tasks.indexing_tasks import index_user_emails
        
        # Create chain
        workflow = chain(
            sync_user_emails.si('user_123'),
            index_user_emails.si('user_123')
        )
        
        assert workflow is not None
    
    def test_task_group_creation(self):
        """Test creating task groups"""
        from celery import group
        from src.workers.tasks.email_tasks import sync_user_emails
        
        # Create group
        job = group(
            sync_user_emails.s('user_1'),
            sync_user_emails.s('user_2'),
            sync_user_emails.s('user_3'),
        )
        
        assert job is not None


class TestTaskScheduling:
    """Tests for task scheduling"""
    
    def test_eta_scheduling(self):
        """Test scheduling with ETA"""
        from src.workers.tasks.notification_tasks import send_task_reminder
        from datetime import datetime, timedelta
        
        eta = datetime.utcnow() + timedelta(hours=1)
        
        # Create task with ETA (don't execute)
        signature = send_task_reminder.apply_async(
            args=['user_123', 'task_456', 'Test Task', '2025-11-20'],
            eta=eta,
            # Don't actually execute
            link_error=None
        )
        
        assert signature is not None
    
    def test_countdown_scheduling(self):
        """Test scheduling with countdown"""
        from src.workers.tasks.notification_tasks import send_alert
        
        # Schedule for 60 seconds from now
        signature = send_alert.apply_async(
            args=['user_123', 'test_alert', 'Test message'],
            countdown=60
        )
        
        assert signature is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
