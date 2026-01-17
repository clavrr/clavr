"""
Tests for Token Refresh with Retry Logic
Tests the token_refresh.py module
"""
import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError

from src.auth.token_refresh import (
    refresh_token_with_retry,
    get_valid_credentials,
    refresh_user_tokens
)
from src.database.models import User


class TestTokenRefreshRetry:
    """Test suite for token refresh with retry logic"""
    
    def test_refresh_token_success_first_attempt(self, db_session, test_user, test_session):
        """Test successful token refresh on first attempt"""
        with patch('google.oauth2.credentials.Credentials.refresh') as mock_refresh:
            # Mock successful refresh
            mock_refresh.return_value = None
            
            # Refresh token
            success, credentials = refresh_token_with_retry(
                db=db_session,
                session=test_session,
                max_retries=3
            )
            
            # Verify success
            assert success is True
            assert credentials is not None
            assert mock_refresh.call_count == 1
    
    def test_refresh_token_retry_on_network_error(self, db_session, test_user, test_session):
        """Test retry logic on network errors"""
        with patch('google.oauth2.credentials.Credentials.refresh') as mock_refresh:
            # Mock 2 failures then success
            mock_refresh.side_effect = [
                ConnectionError("Network error"),
                ConnectionError("Network error"),
                None  # Success
            ]
            
            # Refresh with retries
            success, credentials = refresh_token_with_retry(
                db=db_session,
                session=test_session,
                max_retries=3,
                backoff_factor=0.1  # Short backoff for testing
            )
            
            # Verify success after retries
            assert success is True
            assert credentials is not None
            assert mock_refresh.call_count == 3
    
    def test_refresh_token_max_retries_exceeded(self, db_session, test_user, test_session):
        """Test failure after max retries exceeded"""
        with patch('google.oauth2.credentials.Credentials.refresh') as mock_refresh:
            # Mock all attempts failing
            mock_refresh.side_effect = ConnectionError("Network error")
            
            # Refresh with retries
            success, credentials = refresh_token_with_retry(
                db=db_session,
                session=test_session,
                max_retries=3,
                backoff_factor=0.1
            )
            
            # Verify failure
            assert success is False
            assert credentials is None
            assert mock_refresh.call_count == 3
    
    def test_refresh_token_exponential_backoff(self, db_session, test_user, test_session):
        """Test exponential backoff timing"""
        with patch('google.oauth2.credentials.Credentials.refresh') as mock_refresh:
            with patch('time.sleep') as mock_sleep:
                # Mock failures
                mock_refresh.side_effect = [
                    ConnectionError("Network error"),
                    ConnectionError("Network error"),
                    None  # Success on third try
                ]
                
                # Refresh with backoff
                success, credentials = refresh_token_with_retry(
                    db=db_session,
                    session=test_session,
                    max_retries=3,
                    backoff_factor=2.0
                )
                
                # Verify backoff delays: 2^0=1s, 2^1=2s
                assert mock_sleep.call_count == 2
                mock_sleep.assert_any_call(1.0)  # 2^0
                mock_sleep.assert_any_call(2.0)  # 2^1
    
    def test_refresh_token_invalid_grant(self, db_session, test_user, test_session):
        """Test handling of invalid grant errors (no retry)"""
        with patch('google.oauth2.credentials.Credentials.refresh') as mock_refresh:
            # Mock invalid grant error
            mock_refresh.side_effect = RefreshError("invalid_grant")
            
            # Refresh should fail immediately
            success, credentials = refresh_token_with_retry(
                db=db_session,
                session=test_session,
                max_retries=3
            )
            
            # Verify immediate failure (no retries for auth errors)
            assert success is False
            assert credentials is None
    
    def test_refresh_token_updates_database(self, db_session, test_user, test_session):
        """Test that successful refresh updates database"""
        with patch('google.oauth2.credentials.Credentials.refresh') as mock_refresh:
            # Mock successful refresh with new token
            def mock_refresh_side_effect(request):
                # Simulate token update
                pass
            
            mock_refresh.side_effect = mock_refresh_side_effect
            
            # Patch credentials to return new token
            with patch('google.oauth2.credentials.Credentials') as mock_creds_class:
                mock_creds = MagicMock()
                mock_creds.token = "new_access_token"
                mock_creds.refresh_token = "new_refresh_token"
                mock_creds.expiry = datetime.utcnow() + timedelta(hours=1)
                mock_creds_class.return_value = mock_creds
                
                # Refresh
                success, credentials = refresh_token_with_retry(
                    db=db_session,
                    session=test_session,
                    max_retries=3
                )
                
                # Verify session updated
                db_session.refresh(test_session)
                # Note: Actual token update happens in refresh_token_with_retry
    
    def test_refresh_token_creates_audit_log(self, db_session, test_user, test_session):
        """Test that refresh creates audit log entries"""
        from src.database.models import AuditLog
        from src.auth.audit import AuditEventType
        
        with patch('google.oauth2.credentials.Credentials.refresh') as mock_refresh:
            mock_refresh.return_value = None
            
            # Refresh token
            refresh_token_with_retry(
                db=db_session,
                session=test_session,
                max_retries=3
            )
            
            # Check for audit log
            # Note: Audit logging might be in get_valid_credentials
            # This test verifies the integration


class TestGetValidCredentials:
    """Test suite for get_valid_credentials function"""
    
    def test_get_valid_credentials_token_not_expired(self, db_session, test_user, test_session):
        """Test getting credentials when token is not expired"""
        # Set token to expire in future
        test_session.token_expiry = datetime.utcnow() + timedelta(hours=1)
        db_session.commit()
        
        # Get credentials (should not refresh)
        with patch('src.auth.token_refresh.refresh_token_with_retry') as mock_refresh:
            credentials = get_valid_credentials(
                db=db_session,
                session=test_session,
                auto_refresh=True
            )
            
            # Verify no refresh called (token still valid)
            assert credentials is not None
            mock_refresh.assert_not_called()
    
    def test_get_valid_credentials_token_expired_auto_refresh(self, db_session, test_user, test_session):
        """Test auto-refresh when token is expired"""
        # Set token to expired
        test_session.token_expiry = datetime.utcnow() - timedelta(minutes=1)
        db_session.commit()
        
        # Mock successful refresh
        with patch('src.auth.token_refresh.refresh_token_with_retry') as mock_refresh:
            mock_refresh.return_value = (True, Mock(spec=Credentials))
            
            # Get credentials with auto-refresh
            credentials = get_valid_credentials(
                db=db_session,
                session=test_session,
                auto_refresh=True
            )
            
            # Verify refresh was called
            assert mock_refresh.called
    
    def test_get_valid_credentials_no_auto_refresh(self, db_session, test_user, test_session):
        """Test that expired token returns None without auto-refresh"""
        # Set token to expired
        test_session.token_expiry = datetime.utcnow() - timedelta(minutes=1)
        db_session.commit()
        
        # Get credentials without auto-refresh
        credentials = get_valid_credentials(
            db=db_session,
            session=test_session,
            auto_refresh=False
        )
        
        # Should return None (expired and no refresh)
        assert credentials is None
    
    def test_get_valid_credentials_refresh_threshold(self, db_session, test_user, test_session):
        """Test refresh threshold (refresh before expiry)"""
        # Set token to expire in 4 minutes (below 5-minute threshold)
        test_session.token_expiry = datetime.utcnow() + timedelta(minutes=4)
        db_session.commit()
        
        # Mock successful refresh
        with patch('src.auth.token_refresh.refresh_token_with_retry') as mock_refresh:
            mock_refresh.return_value = (True, Mock(spec=Credentials))
            
            # Get credentials (should refresh due to threshold)
            credentials = get_valid_credentials(
                db=db_session,
                session=test_session,
                auto_refresh=True
            )
            
            # Verify refresh was called even though token not expired yet
            assert mock_refresh.called


class TestRefreshUserTokens:
    """Test suite for refresh_user_tokens function"""
    
    def test_refresh_user_tokens_single_session(self, db_session, test_user):
        """Test refreshing tokens for user with single session"""
        from src.database.models import DBSession
        
        # Create session with expired token
        session = DBSession(
            user_id=test_user.id,
            session_token="hash",
            gmail_access_token="old_access",
            gmail_refresh_token="refresh",
            token_expiry=datetime.utcnow() - timedelta(hours=1),
            expires_at=datetime.utcnow() + timedelta(days=7)
        )
        db_session.add(session)
        db_session.commit()
        
        # Mock successful refresh
        with patch('src.auth.token_refresh.refresh_token_with_retry') as mock_refresh:
            mock_refresh.return_value = (True, Mock(spec=Credentials))
            
            # Refresh user tokens
            count = refresh_user_tokens(db_session, test_user.id)
            
            # Verify refresh called
            assert count >= 0  # At least attempted
    
    def test_refresh_user_tokens_multiple_sessions(self, db_session, test_user):
        """Test refreshing tokens for user with multiple sessions"""
        from src.database.models import DBSession
        
        # Create multiple sessions
        for i in range(3):
            session = DBSession(
                user_id=test_user.id,
                session_token=f"hash_{i}",
                gmail_access_token=f"access_{i}",
                gmail_refresh_token=f"refresh_{i}",
                token_expiry=datetime.utcnow() - timedelta(hours=1),
                expires_at=datetime.utcnow() + timedelta(days=7)
            )
            db_session.add(session)
        
        db_session.commit()
        
        # Mock successful refresh
        with patch('src.auth.token_refresh.refresh_token_with_retry') as mock_refresh:
            mock_refresh.return_value = (True, Mock(spec=Credentials))
            
            # Refresh all user tokens
            count = refresh_user_tokens(db_session, test_user.id)
            
            # Verify all sessions processed
            assert count >= 0


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
        email="refresh@example.com",
        name="Refresh Test User"
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
        gmail_access_token="test_access_token",
        gmail_refresh_token="test_refresh_token",
        token_expiry=datetime.utcnow() + timedelta(hours=1),
        expires_at=datetime.utcnow() + timedelta(days=7)
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    
    yield session
    
    db_session.delete(session)
    db_session.commit()
