"""
Pytest configuration for auth tests
"""
import pytest
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Set test environment
os.environ['TESTING'] = '1'
os.environ['DATABASE_URL'] = 'sqlite:///test_auth.db'
os.environ['ENCRYPTION_KEY'] = 'test-key-for-testing-only-do-not-use-in-production-32bytes='


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment"""
    # Initialize test database
    from src.database import init_db
    from src.database.models import Base
    from src.database.database import get_engine
    
    # Get engine and create all tables
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db()
    
    yield
    
    # Cleanup
    Base.metadata.drop_all(bind=engine)
    
    # Remove test database file
    test_db_path = Path("test_auth.db")
    if test_db_path.exists():
        test_db_path.unlink()


@pytest.fixture
def db_session():
    """Provide a database session for tests"""
    from src.database.database import get_engine
    from sqlalchemy.orm import sessionmaker
    
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture
def test_user(db_session):
    """Create a test user"""
    from src.database.models import User
    
    user = User(
        email="test@example.com",
        name="Test User",
        google_id="test_google_123"
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    
    yield user
    
    # Cleanup
    db_session.delete(user)
    db_session.commit()


@pytest.fixture
def test_session(db_session, test_user):
    """Create a test session"""
    from src.database.models import Session
    from datetime import datetime, timedelta
    
    session = Session(
        user_id=test_user.id,
        session_token="test_hashed_token_123",
        gmail_access_token="test_encrypted_access_token",
        gmail_refresh_token="test_encrypted_refresh_token",
        token_expiry=datetime.utcnow() + timedelta(hours=1),
        expires_at=datetime.utcnow() + timedelta(days=7)
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    
    yield session
    
    # Cleanup
    db_session.delete(session)
    db_session.commit()


@pytest.fixture
def mock_request():
    """Create a mock FastAPI Request object"""
    from unittest.mock import Mock
    
    request = Mock()
    request.client.host = "127.0.0.1"
    request.headers = {"user-agent": "Test Agent"}
    
    return request
