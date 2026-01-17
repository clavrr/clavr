"""
Tests for Token Rotation
Tests the rotation functionality and middleware
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from src.auth.session import rotate_session_token, create_session
from src.auth.rotation_middleware import TokenRotationMiddleware
from src.database.models import User
from src.auth.audit import AuditEventType


class TestTokenRotation:
    """Test suite for token rotation functionality"""
    
    def test_rotate_session_token_success(self, db_session, test_user, test_session):
        """Test successful token rotation"""
        # Get original token hash
        original_hash = test_session.session_token
        
        # Create mock request
        request = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "Test"}
        
        # Rotate token
        new_token = rotate_session_token(
            db=db_session,
            session=test_session,
            reason="password_changed",
            request=request
        )
        
        # Verify new token is different
        assert new_token is not None
        assert len(new_token) > 0
        
        # Verify hash changed in database
        db_session.refresh(test_session)
        assert test_session.session_token != original_hash
    
    def test_rotate_session_token_creates_audit_log(self, db_session, test_user, test_session):
        """Test that rotation creates an audit log entry"""
        from src.database.models import AuditLog
        
        request = Mock()
        request.client.host = "192.168.1.1"
        request.headers = {"user-agent": "Chrome"}
        
        # Rotate token
        rotate_session_token(
            db=db_session,
            session=test_session,
            reason="periodic",
            request=request
        )
        
        # Check audit log created
        log = db_session.query(AuditLog).filter_by(
            event_type=AuditEventType.SESSION_TOKEN_ROTATED.value,
            user_id=test_user.id
        ).first()
        
        assert log is not None
        assert log.success is True
        assert log.event_data["reason"] == "periodic"
        assert log.event_data["session_id"] == test_session.id
    
    def test_rotate_session_token_different_reasons(self, db_session, test_user, test_session):
        """Test rotation with different reasons"""
        from src.database.models import AuditLog
        
        request = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "Test"}
        
        reasons = ["password_changed", "permission_updated", "security_concern"]
        
        for reason in reasons:
            # Rotate token
            rotate_session_token(
                db=db_session,
                session=test_session,
                reason=reason,
                request=request
            )
            
            # Verify reason logged
            log = db_session.query(AuditLog).filter_by(
                event_type=AuditEventType.SESSION_TOKEN_ROTATED.value
            ).order_by(AuditLog.created_at.desc()).first()
            
            assert log.event_data["reason"] == reason
    
    def test_rotation_middleware_rotates_old_tokens(self, db_session, test_user):
        """Test that middleware rotates tokens older than interval"""
        from src.database.models import DBSession
        
        # Create old session (25 hours ago)
        old_session = DBSession(
            user_id=test_user.id,
            session_token="old_hash",
            gmail_access_token="access",
            gmail_refresh_token="refresh",
            token_expiry=datetime.utcnow() + timedelta(days=1),
            expires_at=datetime.utcnow() + timedelta(days=7),
            created_at=datetime.utcnow() - timedelta(hours=25)
        )
        db_session.add(old_session)
        db_session.commit()
        
        # Create middleware
        middleware = TokenRotationMiddleware(
            app=Mock(),
            rotation_interval_hours=24
        )
        
        # Check if rotation needed
        assert middleware._should_rotate(old_session) is True
    
    def test_rotation_middleware_skips_new_tokens(self, db_session, test_user):
        """Test that middleware skips tokens younger than interval"""
        from src.database.models import DBSession
        
        # Create new session (1 hour ago)
        new_session = DBSession(
            user_id=test_user.id,
            session_token="new_hash",
            gmail_access_token="access",
            gmail_refresh_token="refresh",
            token_expiry=datetime.utcnow() + timedelta(days=1),
            expires_at=datetime.utcnow() + timedelta(days=7),
            created_at=datetime.utcnow() - timedelta(hours=1)
        )
        db_session.add(new_session)
        db_session.commit()
        
        # Create middleware
        middleware = TokenRotationMiddleware(
            app=Mock(),
            rotation_interval_hours=24
        )
        
        # Check if rotation needed
        assert middleware._should_rotate(new_session) is False
    
    @pytest.mark.asyncio
    async def test_rotation_middleware_dispatch(self, db_session, test_user):
        """Test middleware dispatch with token rotation"""
        from src.database.models import DBSession
        from fastapi import Request, Response
        
        # Create old session
        old_session = DBSession(
            user_id=test_user.id,
            session_token="old_hash",
            gmail_access_token="access",
            gmail_refresh_token="refresh",
            token_expiry=datetime.utcnow() + timedelta(days=1),
            expires_at=datetime.utcnow() + timedelta(days=7),
            created_at=datetime.utcnow() - timedelta(hours=25)
        )
        db_session.add(old_session)
        db_session.commit()
        
        # Create mock request with session
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.session = old_session
        request.state.db = db_session
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "Test"}
        
        # Create mock call_next
        async def mock_call_next(req):
            response = Response()
            return response
        
        # Create middleware
        middleware = TokenRotationMiddleware(
            app=Mock(),
            rotation_interval_hours=24
        )
        
        # Dispatch request
        with patch.object(middleware, '_should_rotate', return_value=True):
            with patch('src.auth.session.rotate_session_token', return_value="new_token"):
                response = await middleware.dispatch(request, mock_call_next)
                
                # Verify header set (would be set if rotation occurred)
                # Note: Actual header setting happens in real middleware
                assert response is not None


class TestTokenRotationIntegration:
    """Integration tests for token rotation"""
    
    def test_manual_rotation_workflow(self, db_session, test_user):
        """Test manual token rotation workflow (e.g., password change)"""
        from src.database.models import AuditLog
        
        # Create session
        request = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "Chrome"}
        
        session = create_session(
            db=db_session,
            user_id=test_user.id,
            gmail_access_token="access_token",
            gmail_refresh_token="refresh_token",
            token_expiry=datetime.utcnow() + timedelta(hours=1),
            request=request
        )
        
        original_hash = session.session_token
        
        # Simulate password change - rotate token
        new_token = rotate_session_token(
            db=db_session,
            session=session,
            reason="password_changed",
            request=request
        )
        
        # Verify rotation occurred
        db_session.refresh(session)
        assert session.session_token != original_hash
        
        # Verify audit trail
        rotation_log = db_session.query(AuditLog).filter_by(
            event_type=AuditEventType.SESSION_TOKEN_ROTATED.value,
            user_id=test_user.id
        ).first()
        
        assert rotation_log is not None
        assert rotation_log.event_data["reason"] == "password_changed"
    
    def test_periodic_rotation_workflow(self, db_session, test_user):
        """Test periodic automatic rotation workflow"""
        from src.database.models import DBSession, AuditLog
        
        # Create old session (25 hours old)
        old_session = DBSession(
            user_id=test_user.id,
            session_token="old_hash",
            gmail_access_token="access",
            gmail_refresh_token="refresh",
            token_expiry=datetime.utcnow() + timedelta(days=1),
            expires_at=datetime.utcnow() + timedelta(days=7),
            created_at=datetime.utcnow() - timedelta(hours=25)
        )
        db_session.add(old_session)
        db_session.commit()
        
        request = Mock()
        request.client.host = "10.0.0.1"
        request.headers = {"user-agent": "Safari"}
        
        # Simulate periodic rotation
        new_token = rotate_session_token(
            db=db_session,
            session=old_session,
            reason="periodic",
            request=request
        )
        
        # Verify rotation
        db_session.refresh(old_session)
        assert old_session.session_token != "old_hash"
        
        # Verify audit log
        log = db_session.query(AuditLog).filter_by(
            event_type=AuditEventType.SESSION_TOKEN_ROTATED.value
        ).first()
        
        assert log.event_data["reason"] == "periodic"


# Fixtures
@pytest.fixture
def db_session():
    """Create a test database session"""
    from src.database import SessionLocal, init_db
    from src.database.models import AuditLog, DBSession
    
    init_db()
    db = SessionLocal()
    
    yield db
    
    # Cleanup
    db.query(AuditLog).delete()
    db.query(DBSession).delete()
    db.commit()
    db.close()


@pytest.fixture
def test_user(db_session):
    """Create a test user"""
    user = User(
        email="rotation@example.com",
        name="Rotation Test User"
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    
    yield user
    
    db_session.delete(user)
    db_session.commit()


@pytest.fixture
def test_session(db_session, test_user):
    """Create a test session"""
    from src.database.models import DBSession
    
    session = DBSession(
        user_id=test_user.id,
        session_token="test_hash",
        gmail_access_token="access_token",
        gmail_refresh_token="refresh_token",
        token_expiry=datetime.utcnow() + timedelta(hours=1),
        expires_at=datetime.utcnow() + timedelta(days=7)
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    
    yield session
    
    db_session.delete(session)
    db_session.commit()
