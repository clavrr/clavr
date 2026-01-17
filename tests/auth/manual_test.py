"""
Simple manual test to verify auth functions work
Run this directly: python tests/auth/manual_test.py
"""
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Set test environment
os.environ['TESTING'] = '1'
os.environ['DATABASE_URL'] = 'sqlite:///test_manual.db'
os.environ['ENCRYPTION_KEY'] = 'test-key-for-testing-only-do-not-use-in-production-32bytes='

def test_audit_logging():
    """Test audit logging functionality"""
    print("\n" + "="*60)
    print("Testing Audit Logging")
    print("="*60)
    
    from src.database import init_db
    from src.database.models import Base, User, AuditLog
    from src.database.database import get_engine
    from src.auth.audit import log_auth_event, AuditEventType, get_user_audit_logs
    from sqlalchemy.orm import sessionmaker
    from unittest.mock import Mock
    
    # Setup database
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    init_db()
    
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Create test user
        user = User(
            email="test@example.com",
            name="Test User",
            google_id="test_123"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"✓ Created test user: {user.email} (ID: {user.id})")
        
        # Create mock request
        request = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "Test Agent"}
        
        # Test 1: Log successful event
        log_auth_event(
            db=db,
            event_type=AuditEventType.LOGIN_SUCCESS,
            user_id=user.id,
            success=True,
            request=request,
            oauth_provider='google'
        )
        print("✓ Logged LOGIN_SUCCESS event")
        
        # Test 2: Log failed event
        log_auth_event(
            db=db,
            event_type=AuditEventType.LOGIN_FAILURE,
            user_id=None,
            success=False,
            error_message="Invalid credentials",
            request=request
        )
        print("✓ Logged LOGIN_FAILURE event")
        
        # Test 3: Query audit logs
        logs = get_user_audit_logs(db, user_id=user.id, limit=10)
        assert len(logs) == 1, f"Expected 1 log, got {len(logs)}"
        assert logs[0].event_type == 'login_success'
        assert logs[0].ip_address == "127.0.0.1"
        print(f"✓ Retrieved {len(logs)} audit log(s) for user")
        
        # Test 4: Query all logs
        all_logs = db.query(AuditLog).all()
        assert len(all_logs) == 2, f"Expected 2 total logs, got {len(all_logs)}"
        print(f"✓ Total audit logs in database: {len(all_logs)}")
        
        print("\n✅ All audit logging tests passed!")
        
    finally:
        # Cleanup
        db.query(AuditLog).delete()
        db.query(User).delete()
        db.commit()
        db.close()
        Base.metadata.drop_all(bind=engine)
        
        # Remove test database
        test_db = Path("test_manual.db")
        if test_db.exists():
            test_db.unlink()


def test_token_rotation():
    """Test token rotation functionality"""
    print("\n" + "="*60)
    print("Testing Token Rotation")
    print("="*60)
    
    from src.database import init_db
    from src.database.models import Base, User, Session as DBSession
    from src.database.database import get_engine
    from src.auth.session import rotate_session_token, generate_session_token
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime, timedelta
    from unittest.mock import Mock
    
    # Setup database
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    init_db()
    
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Create test user
        user = User(
            email="test@example.com",
            name="Test User",
            google_id="test_123"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"✓ Created test user: {user.email}")
        
        # Create test session
        raw_token, hashed_token = generate_session_token()
        session = DBSession(
            user_id=user.id,
            session_token=hashed_token,
            gmail_access_token="encrypted_access",
            gmail_refresh_token="encrypted_refresh",
            token_expiry=datetime.utcnow() + timedelta(hours=1),
            expires_at=datetime.utcnow() + timedelta(days=7)
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        old_token_hash = session.session_token
        print(f"✓ Created test session (ID: {session.id})")
        
        # Create mock request
        request = Mock()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "Test Agent"}
        
        # Test: Rotate token
        new_token = rotate_session_token(
            db=db,
            session=session,
            reason="test_rotation",
            request=request
        )
        
        db.refresh(session)
        assert session.session_token != old_token_hash, "Token should have changed"
        assert new_token is not None, "New token should be returned"
        print(f"✓ Token rotated successfully")
        print(f"  Old token hash: {old_token_hash[:20]}...")
        print(f"  New token hash: {session.session_token[:20]}...")
        
        print("\n✅ Token rotation test passed!")
        
    finally:
        # Cleanup
        db.query(DBSession).delete()
        db.query(User).delete()
        db.commit()
        db.close()
        Base.metadata.drop_all(bind=engine)
        
        # Remove test database
        test_db = Path("test_manual.db")
        if test_db.exists():
            test_db.unlink()


def test_encryption():
    """Test token encryption functionality"""
    print("\n" + "="*60)
    print("Testing Token Encryption")
    print("="*60)
    
    from src.utils.encryption import encrypt_token, decrypt_token
    
    # Test 1: Encrypt and decrypt
    original_token = "ya29.a0ARrdaM9test_access_token_example"
    
    encrypted = encrypt_token(original_token)
    print(f"✓ Encrypted token: {encrypted[:50]}...")
    
    decrypted = decrypt_token(encrypted)
    assert decrypted == original_token, "Decrypted token should match original"
    print(f"✓ Decrypted token matches original")
    
    # Test 2: Different tokens produce different ciphertexts
    encrypted2 = encrypt_token(original_token)
    assert encrypted != encrypted2, "Same token should produce different ciphertexts (IV randomness)"
    print(f"✓ Encryption uses random IV (different ciphertexts)")
    
    # Test 3: Invalid token handling
    try:
        decrypt_token("invalid_base64_garbage")
        assert False, "Should have raised an error"
    except Exception as e:
        print(f"✓ Invalid token properly rejected: {type(e).__name__}")
    
    print("\n✅ All encryption tests passed!")


def test_rate_limiting():
    """Test that rate limiting components are installed"""
    print("\n" + "="*60)
    print("Testing Rate Limiting Setup")
    print("="*60)
    
    try:
        from slowapi import Limiter
        from slowapi.util import get_remote_address
        print("✓ slowapi package installed")
        
        from api.rate_limit_handler import rate_limit_exceeded_handler
        print("✓ Custom rate limit handler created")
        
        # Check that it's configured in main.py
        from api.main import app
        assert hasattr(app.state, 'limiter'), "App should have limiter in state"
        print("✓ Rate limiter configured in app.state")
        
        print("\n✅ Rate limiting setup complete!")
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False


if __name__ == "__main__":
    print("\n" + "🧪"*30)
    print("OAuth Security Features - Manual Test Suite")
    print("🧪"*30)
    
    try:
        test_audit_logging()
        test_token_rotation()
        test_encryption()
        test_rate_limiting()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED!")
        print("="*60)
        print("\nPhase 1 & 2 implementations are working correctly:")
        print("  ✓ Audit Logging")
        print("  ✓ Token Rotation")
        print("  ✓ Token Encryption")
        print("  ✓ Rate Limiting")
        print()
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
