"""
Tests for Audit Logging System
Tests the audit.py module functionality
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock
from sqlalchemy.orm import Session

from src.auth.audit import (
    log_auth_event,
    AuditEventType,
    get_user_audit_logs,
    get_failed_login_attempts,
    get_security_summary
)
from src.database.models import AuditLog, User


class TestAuditLogging:
    """Test suite for audit logging functionality"""
    
    def test_log_auth_event_success(self, db_session, test_user):
        """Test logging a successful authentication event"""
        # Create mock request
        request = Mock()
        request.client.host = "192.168.1.1"
        request.headers = {"user-agent": "Mozilla/5.0"}
        
        # Log event
        log_auth_event(
            db=db_session,
            event_type=AuditEventType.LOGIN_SUCCESS,
            user_id=test_user.id,
            success=True,
            request=request,
            oauth_provider="google"
        )
        
        # Verify log created
        log = db_session.query(AuditLog).filter_by(
            user_id=test_user.id,
            event_type=AuditEventType.LOGIN_SUCCESS.value
        ).first()
        
        assert log is not None
        assert log.success is True
        assert log.ip_address == "192.168.1.1"
        assert log.user_agent == "Mozilla/5.0"
        assert log.event_data["oauth_provider"] == "google"
    
    def test_log_auth_event_failure(self, db_session):
        """Test logging a failed authentication event"""
        request = Mock()
        request.client.host = "10.0.0.1"
        request.headers = {"user-agent": "BadBot/1.0"}
        
        # Log failed login
        log_auth_event(
            db=db_session,
            event_type=AuditEventType.LOGIN_FAILURE,
            user_id=None,  # No user for failed login
            success=False,
            error_message="Invalid credentials",
            request=request
        )
        
        # Verify log created
        log = db_session.query(AuditLog).filter_by(
            event_type=AuditEventType.LOGIN_FAILURE.value
        ).first()
        
        assert log is not None
        assert log.success is False
        assert log.user_id is None
        assert log.error_message == "Invalid credentials"
        assert log.ip_address == "10.0.0.1"
    
    def test_log_auth_event_without_request(self, db_session, test_user):
        """Test logging event without request object"""
        log_auth_event(
            db=db_session,
            event_type=AuditEventType.TOKEN_REFRESH_SUCCESS,
            user_id=test_user.id,
            success=True,
            request=None  # No request object
        )
        
        log = db_session.query(AuditLog).filter_by(
            user_id=test_user.id,
            event_type=AuditEventType.TOKEN_REFRESH_SUCCESS.value
        ).first()
        
        assert log is not None
        assert log.ip_address is None
        assert log.user_agent is None
    
    def test_log_auth_event_with_custom_data(self, db_session, test_user):
        """Test logging event with custom event data"""
        request = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "Test"}
        
        log_auth_event(
            db=db_session,
            event_type=AuditEventType.ADMIN_ACTION,
            user_id=test_user.id,
            success=True,
            request=request,
            action="delete_user",
            target_user_id=999,
            reason="policy_violation"
        )
        
        log = db_session.query(AuditLog).filter_by(
            user_id=test_user.id,
            event_type=AuditEventType.ADMIN_ACTION.value
        ).first()
        
        assert log is not None
        assert log.event_data["action"] == "delete_user"
        assert log.event_data["target_user_id"] == 999
        assert log.event_data["reason"] == "policy_violation"
    
    def test_get_user_audit_logs(self, db_session, test_user):
        """Test retrieving user audit logs"""
        request = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "Test"}
        
        # Create multiple logs
        for i in range(10):
            log_auth_event(
                db=db_session,
                event_type=AuditEventType.LOGIN_SUCCESS,
                user_id=test_user.id,
                success=True,
                request=request
            )
        
        # Get logs with limit
        logs = get_user_audit_logs(db_session, test_user.id, limit=5)
        
        assert len(logs) == 5
        assert all(log.user_id == test_user.id for log in logs)
        
        # Verify chronological order (newest first)
        for i in range(len(logs) - 1):
            assert logs[i].created_at >= logs[i + 1].created_at
    
    def test_get_user_audit_logs_event_type_filter(self, db_session, test_user):
        """Test filtering audit logs by event type"""
        request = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "Test"}
        
        # Create different event types
        log_auth_event(
            db=db_session,
            event_type=AuditEventType.LOGIN_SUCCESS,
            user_id=test_user.id,
            success=True,
            request=request
        )
        log_auth_event(
            db=db_session,
            event_type=AuditEventType.LOGOUT,
            user_id=test_user.id,
            success=True,
            request=request
        )
        
        # Filter by login success
        logs = get_user_audit_logs(
            db_session,
            test_user.id,
            event_type=AuditEventType.LOGIN_SUCCESS
        )
        
        assert len(logs) == 1
        assert logs[0].event_type == AuditEventType.LOGIN_SUCCESS.value
    
    def test_get_failed_login_attempts(self, db_session):
        """Test retrieving failed login attempts"""
        request = Mock()
        request.client.host = "192.168.1.100"
        request.headers = {"user-agent": "Test"}
        
        # Create failed login attempts
        for i in range(3):
            log_auth_event(
                db=db_session,
                event_type=AuditEventType.LOGIN_FAILURE,
                user_id=None,
                success=False,
                error_message="Invalid password",
                request=request
            )
        
        # Get failed attempts for IP
        failed = get_failed_login_attempts(
            db_session,
            ip_address="192.168.1.100",
            hours=1
        )
        
        assert len(failed) == 3
        assert all(log.success is False for log in failed)
        assert all(log.ip_address == "192.168.1.100" for log in failed)
    
    def test_get_failed_login_attempts_time_filter(self, db_session):
        """Test failed login attempts time filtering"""
        request = Mock()
        request.client.host = "10.0.0.1"
        request.headers = {"user-agent": "Test"}
        
        # Create old failed attempt (2 hours ago)
        old_log = AuditLog(
            event_type=AuditEventType.LOGIN_FAILURE.value,
            success=False,
            ip_address="10.0.0.1",
            user_agent="Test",
            created_at=datetime.utcnow() - timedelta(hours=2)
        )
        db_session.add(old_log)
        
        # Create recent failed attempt
        log_auth_event(
            db=db_session,
            event_type=AuditEventType.LOGIN_FAILURE,
            user_id=None,
            success=False,
            request=request
        )
        
        db_session.commit()
        
        # Get failed attempts in last hour (should only get recent one)
        failed = get_failed_login_attempts(
            db_session,
            ip_address="10.0.0.1",
            hours=1
        )
        
        assert len(failed) == 1
    
    def test_get_security_summary(self, db_session, test_user):
        """Test security summary generation"""
        request = Mock()
        request.client.host = "192.168.1.1"
        request.headers = {"user-agent": "Test"}
        
        # Create various events
        log_auth_event(
            db=db_session,
            event_type=AuditEventType.LOGIN_SUCCESS,
            user_id=test_user.id,
            success=True,
            request=request
        )
        log_auth_event(
            db=db_session,
            event_type=AuditEventType.LOGIN_FAILURE,
            user_id=None,
            success=False,
            request=request
        )
        log_auth_event(
            db=db_session,
            event_type=AuditEventType.TOKEN_REFRESH_FAILURE,
            user_id=test_user.id,
            success=False,
            request=request
        )
        
        db_session.commit()
        
        # Get summary
        summary = get_security_summary(db_session, hours=24)
        
        assert summary["total_events"] == 3
        assert summary["failed_events"] == 2
        assert summary["successful_events"] == 1
        assert "192.168.1.1" in summary["failed_logins_by_ip"]
        assert summary["failed_logins_by_ip"]["192.168.1.1"] == 1
    
    def test_rate_limit_exceeded_logging(self, db_session, test_user):
        """Test logging rate limit exceeded events"""
        request = Mock()
        request.client.host = "1.2.3.4"
        request.headers = {"user-agent": "SpamBot"}
        request.url.path = "/auth/google/login"
        
        log_auth_event(
            db=db_session,
            event_type=AuditEventType.RATE_LIMIT_EXCEEDED,
            user_id=test_user.id,
            success=False,
            request=request,
            endpoint="/auth/google/login",
            limit="10/minute"
        )
        
        log = db_session.query(AuditLog).filter_by(
            event_type=AuditEventType.RATE_LIMIT_EXCEEDED.value
        ).first()
        
        assert log is not None
        assert log.success is False
        assert log.event_data["endpoint"] == "/auth/google/login"
        assert log.event_data["limit"] == "10/minute"
    
    def test_session_token_rotated_logging(self, db_session, test_user):
        """Test logging session token rotation"""
        request = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "Chrome"}
        
        log_auth_event(
            db=db_session,
            event_type=AuditEventType.SESSION_TOKEN_ROTATED,
            user_id=test_user.id,
            success=True,
            request=request,
            reason="periodic",
            session_id=123
        )
        
        log = db_session.query(AuditLog).filter_by(
            event_type=AuditEventType.SESSION_TOKEN_ROTATED.value
        ).first()
        
        assert log is not None
        assert log.event_data["reason"] == "periodic"
        assert log.event_data["session_id"] == 123


# Fixtures are now in conftest.py
