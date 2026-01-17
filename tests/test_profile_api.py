"""
Integration Tests for Profile API Endpoints

Tests the profile management API endpoints:
- POST /api/profile/build
- GET /api/profile
- DELETE /api/profile
"""
import pytest
import pytest_asyncio
import asyncio
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timedelta

from api.main import app
from src.database import get_async_db_context
from src.database.models import User, UserWritingProfile, Session as DBSession, InteractionSession
from src.utils import hash_token


@pytest.fixture(scope="module")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def cleanup_test_data():
    """Clear test data BEFORE each test to ensure a clean slate."""
    async with get_async_db_context() as db:
        from sqlalchemy import delete, select
        # Use hashed token for cleanup
        hashed_token = hash_token('test_session_token_profile')
        
        # Find the test user IDs and their sessions
        result = await db.execute(select(User.id).where(
            (User.email == 'test_profile@example.com') | 
            (User.google_id == 'test_google_id_profile')
        ))
        user_ids = result.scalars().all()
        
        # Also find any profiles we might have missed
        profile_result = await db.execute(select(UserWritingProfile.user_id))
        all_profile_user_ids = profile_result.scalars().all()
        
        if user_ids:
            # Delete dependent data first
            await db.execute(delete(DBSession).where(DBSession.user_id.in_(user_ids)))
            await db.execute(delete(UserWritingProfile).where(UserWritingProfile.user_id.in_(user_ids)))
            await db.execute(delete(InteractionSession).where(InteractionSession.user_id.in_(user_ids)))
            await db.execute(delete(User).where(User.id.in_(user_ids)))
        
        # Also cleanup by hardcoded tokens just in case
        await db.execute(delete(DBSession).where(DBSession.session_token == hashed_token))
        await db.commit()
    yield


@pytest_asyncio.fixture(autouse=True)
async def cleanup_db():
    """Clear async database connections after each test to avoid loop mismatch."""
    yield
    from src.database.async_database import close_async_db_connections
    await close_async_db_connections()

@pytest.fixture(autouse=True)
async def clear_cache():
    """Clear the profile cache and session middleware cache between tests to avoid state leakage"""
    # Clear profile cache
    from src.services.profile_cache import get_profile_cache
    cache = get_profile_cache()
    await cache.clear()
    
    # Clear session middleware cache (class variable)
    from api.middleware import SessionMiddleware
    SessionMiddleware._session_cache.clear()
    
    yield


# Fixtures
@pytest_asyncio.fixture
async def test_user():
    """Create a test user"""
    async with get_async_db_context() as db:
        from src.database.async_database import _get_async_database_url
        print(f"\nDEBUG: DATABASE_URL={_get_async_database_url()}")
        
        # Cleanup any leftover test data from previous failed runs
        from sqlalchemy import delete
        await db.execute(delete(User).where(User.email == 'test_profile@example.com'))
        await db.execute(delete(User).where(User.google_id == 'test_google_id_profile'))
        await db.commit()
        
        user = User(
            google_id='test_google_id_profile',
            email='test_profile@example.com',
            name='Test User'
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        print(f"DEBUG: Created test user id={user.id}")
        
        yield user
        
        # Cleanup
        try:
            await db.delete(user)
            await db.commit()
        except:
            await db.rollback()


@pytest_asyncio.fixture
async def test_session(test_user):
    """Create a test session for the user"""
    async with get_async_db_context() as db:
        # Use unique raw token for each test to avoid cache collisions
        raw_token = f'test_session_token_{test_user.id}'
        hashed_token = hash_token(raw_token)
        
        # Cleanup any leftover session data
        from sqlalchemy import delete
        await db.execute(delete(DBSession).where(DBSession.session_token == hashed_token))
        await db.commit()
        
        session = DBSession(
            user_id=test_user.id,
            session_token=hashed_token,
            gmail_access_token='test_access_token',
            gmail_refresh_token='test_refresh_token',
            expires_at=datetime.utcnow() + timedelta(days=1)
        )
        # Attach raw token for tests to use in headers
        session.raw_token = raw_token
        
        db.add(session)
        await db.commit()
        await db.refresh(session)
        
        yield session
        
        # Cleanup
        try:
            await db.delete(session)
            await db.commit()
        except:
            await db.rollback()


@pytest_asyncio.fixture
async def client():
    """Create async HTTP client"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# Test Profile Building
@pytest.mark.asyncio
@pytest.mark.integration
async def test_build_profile_success(client, test_session):
    """Test successful profile build initiation"""
    response = await client.post(
        "/api/profile/build",
        json={"max_emails": 50, "force_rebuild": False},
        cookies={"session_token": test_session.raw_token}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] in ["building", "complete"]
    assert "message" in data


@pytest.mark.asyncio
@pytest.mark.integration
async def test_build_profile_without_auth(client):
    """Test profile build without authentication"""
    response = await client.post(
        "/api/profile/build",
        json={"max_emails": 50}
    )
    
    # Should require authentication
    assert response.status_code in [401, 403]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_build_profile_invalid_max_emails(client, test_session):
    """Test profile build with invalid max_emails parameter"""
    response = await client.post(
        "/api/profile/build",
        json={"max_emails": 1000},  # Exceeds limit
        cookies={"session_token": test_session.raw_token}
    )
    
    # Should reject invalid parameters
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_build_profile_force_rebuild(client, test_session, test_user):
    """Test force rebuild of existing profile"""
    # Create existing profile
    async with get_async_db_context() as db:
        profile = UserWritingProfile(
            user_id=test_user.id,
            profile_data={"sample": "data"},
            sample_size=10,
            last_rebuilt_at=datetime.utcnow()
        )
        db.add(profile)
        await db.commit()
    
    # Force rebuild
    response = await client.post(
        "/api/profile/build",
        json={"max_emails": 50, "force_rebuild": True},
        cookies={"session_token": test_session.raw_token}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "building"
    
    # Cleanup
    async with get_async_db_context() as db:
        await db.delete(profile)
        await db.commit()


# Test Profile Retrieval
@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_profile_exists(client, test_session, test_user):
    """Test getting an existing profile"""
    # Create profile
    async with get_async_db_context() as db:
        profile = UserWritingProfile(
            user_id=test_user.id,
            profile_data={"writing_style": {"tone": "friendly"}},
            sample_size=50,
            confidence_score=0.9,
            last_rebuilt_at=datetime.utcnow()
        )
        db.add(profile)
        await db.commit()
    
    # Get profile
    response = await client.get(
        "/api/profile",
        cookies={"session_token": test_session.raw_token}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["user_id"] == test_user.id
    assert data["sample_size"] == 50
    assert data["confidence_score"] == 0.9
    assert "writing_style" in data["profile_data"]
    
    # Cleanup
    async with get_async_db_context() as db:
        await db.delete(profile)
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_profile_not_found(client, test_session):
    """Test getting a profile that doesn't exist"""
    response = await client.get(
        "/api/profile",
        cookies={"session_token": test_session.raw_token}
    )
    
    # Should return 404
    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_profile_without_auth(client):
    """Test getting profile without authentication"""
    response = await client.get("/api/profile")
    
    # Should require authentication
    assert response.status_code in [401, 403]


# Test Profile Deletion
@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_profile_exists(client, test_session, test_user):
    """Test deleting an existing profile"""
    # Create profile
    async with get_async_db_context() as db:
        profile = UserWritingProfile(
            user_id=test_user.id,
            profile_data={"test": "data"},
            sample_size=10
        )
        db.add(profile)
        await db.commit()
        profile_id = profile.id
    
    # Delete profile
    response = await client.delete(
        "/api/profile",
        cookies={"session_token": test_session.raw_token}
    )
    
    assert response.status_code == 204
    
    # Verify deletion
    async with get_async_db_context() as db:
        from sqlalchemy import select
        stmt = select(UserWritingProfile).where(UserWritingProfile.id == profile_id)
        result = await db.execute(stmt)
        deleted_profile = result.scalar_one_or_none()
        
        assert deleted_profile is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_profile_not_found(client, test_session):
    """Test deleting a profile that doesn't exist"""
    response = await client.delete(
        "/api/profile",
        cookies={"session_token": test_session.raw_token}
    )
    
    # Should still return 204 (idempotent)
    assert response.status_code == 204


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_profile_without_auth(client):
    """Test deleting profile without authentication"""
    response = await client.delete("/api/profile")
    
    # Should require authentication
    assert response.status_code in [401, 403]


# Test Auto-Reply Integration
@pytest.mark.asyncio
@pytest.mark.integration
async def test_auto_reply_with_profile(client, test_session, test_user):
    """Test auto-reply uses profile when available"""
    # Create profile
    async with get_async_db_context() as db:
        profile = UserWritingProfile(
            user_id=test_user.id,
            profile_data={
                "writing_style": {
                    "tone": "friendly",
                    "formality_level": "semi-formal"
                },
                "response_patterns": {
                    "greetings": [{"greeting": "Hi", "count": 10}],
                    "closings": [{"closing": "Best regards", "count": 10}]
                }
            },
            sample_size=50,
            confidence_score=0.9
        )
        db.add(profile)
        await db.commit()
    
    # Generate auto-reply
    response = await client.post(
        "/api/ai/auto-reply",
        json={
            "email_content": "Can we meet tomorrow?",
            "email_subject": "Quick sync",
            "sender_name": "John",
            "sender_email": "john@example.com",
            "num_options": 3
        },
        cookies={"session_token": test_session.raw_token}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert data["personalized"] is True  # Profile was used!
    assert len(data["replies"]) == 3
    
    # Cleanup
    async with get_async_db_context() as db:
        await db.delete(profile)
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_auto_reply_without_profile(client, test_session):
    """Test auto-reply without profile (generic response)"""
    # Generate auto-reply (no profile exists)
    response = await client.post(
        "/api/ai/auto-reply",
        json={
            "email_content": "Can we meet tomorrow?",
            "email_subject": "Quick sync",
            "sender_name": "John",
            "sender_email": "john@example.com",
            "num_options": 3
        },
        cookies={"session_token": test_session.raw_token}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert data["personalized"] is False  # No profile available
    assert len(data["replies"]) == 3


# End-to-End Workflow Tests
@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_full_profile_workflow(client, test_session, test_user):
    """Test complete profile workflow: build -> get -> use -> delete"""
    # Step 1: Build profile
    build_response = await client.post(
        "/api/profile/build",
        json={"max_emails": 50},
        cookies={"session_token": test_session.raw_token}
    )
    assert build_response.status_code == 200
    
    # Step 2: Wait for build (in real test, would poll or use webhooks)
    await asyncio.sleep(2)  # Simulate background task completion
    
    # Step 3: Get profile
    get_response = await client.get(
        "/api/profile",
        cookies={"session_token": test_session.raw_token}
    )
    
    if get_response.status_code == 200:
        profile_data = get_response.json()
        assert "profile_data" in profile_data
        
        # Step 4: Use profile in auto-reply
        reply_response = await client.post(
            "/api/ai/auto-reply",
            json={
                "email_content": "Thanks for the update",
                "email_subject": "Re: Project",
                "sender_name": "Jane",
                "sender_email": "jane@example.com"
            },
            cookies={"session_token": test_session.raw_token}
        )
        assert reply_response.status_code == 200
    
    # Step 5: Delete profile
    delete_response = await client.delete(
        "/api/profile",
        cookies={"session_token": test_session.raw_token}
    )
    assert delete_response.status_code == 204
    
    # Step 6: Verify deletion
    verify_response = await client.get(
        "/api/profile",
        cookies={"session_token": test_session.raw_token}
    )
    assert verify_response.status_code == 404


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
