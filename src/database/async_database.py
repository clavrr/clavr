"""
Async Database Connection and Session Management

This module provides async database operations for non-blocking I/O.
Works alongside the sync database module for backward compatibility.

Usage:
    # In async FastAPI endpoints
    from src.database.async_database import get_async_db
    
    @router.post("/chat")
    async def chat(db: AsyncSession = Depends(get_async_db)):
        # Use async database operations
        result = await db.execute(select(User))
        users = result.scalars().all()
"""
import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine
)
from sqlalchemy import text, event
from sqlalchemy.pool import AsyncAdaptedQueuePool

from ..utils.logger import setup_logger

logger = setup_logger(__name__)

# Lazy-loaded async engine and session factory
_async_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def _get_async_database_url() -> str:
    """
    Get async DATABASE_URL from environment, converting to async driver if needed.
    
    Returns:
        Async database connection URL (postgresql+asyncpg://)
    """
    # Try to load .env file if dotenv is available
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except ImportError:
        pass
    
    # Check environment variable
    db_url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')
    
    if not db_url:
        # Default to SQLite (not recommended for async, but supported)
        logger.warning(
            "No DATABASE_URL found. Using SQLite (not recommended for async operations). "
            "Set DATABASE_URL to postgresql:// for production."
        )
        return 'sqlite+aiosqlite:///./notely_agent.db'
    
    # Convert sync PostgreSQL URL to async
    if db_url.startswith('postgresql://') or db_url.startswith('postgres://'):
        # Replace with asyncpg driver
        async_url = db_url.replace('postgresql://', 'postgresql+asyncpg://')
        async_url = async_url.replace('postgres://', 'postgresql+asyncpg://')
        return async_url
    elif db_url.startswith('sqlite://'):
        # Convert to aiosqlite for async SQLite
        return db_url.replace('sqlite://', 'sqlite+aiosqlite://')
    else:
        # Already async URL or unsupported
        return db_url


def get_async_engine() -> AsyncEngine:
    """
    Get or create async database engine (lazy-loaded with optimized pooling).
    
    Connection pooling configuration:
    - PostgreSQL: AsyncAdaptedQueuePool (5-20 connections)
    - SQLite: No pooling (single connection)
    
    Returns:
        AsyncEngine instance
    """
    global _async_engine
    
    if _async_engine is None:
        async_db_url = _get_async_database_url()
        
        if 'sqlite' in async_db_url:
            # SQLite async (aiosqlite)
            _async_engine = create_async_engine(
                async_db_url,
                echo=False,  # Set to True for SQL debugging
                connect_args={"check_same_thread": False}
            )
            logger.info("Async database engine created: SQLite+aiosqlite (local)")
        else:
            # PostgreSQL async (asyncpg)
            _async_engine = create_async_engine(
                async_db_url,
                pool_size=5,              # Minimum connections in pool
                max_overflow=10,          # Max additional connections
                pool_timeout=30,          # Wait time before timeout
                pool_recycle=3600,        # Recycle connections after 1 hour
                pool_pre_ping=True,       # Test connections before use
                poolclass=AsyncAdaptedQueuePool,
                echo=False
            )
            
            # Add connection logging for monitoring
            @event.listens_for(_async_engine.sync_engine, "connect")
            def receive_connect(dbapi_conn, connection_record):
                logger.debug("Async database connection established")
            
            logger.info(
                "Async database engine created: PostgreSQL+asyncpg "
                "(pool_size=5, max_overflow=10)"
            )
    
    return _async_engine


def get_async_session_local() -> async_sessionmaker[AsyncSession]:
    """
    Get or create async session factory (lazy-loaded).
    
    Returns:
        async_sessionmaker instance
    """
    global _AsyncSessionLocal
    
    if _AsyncSessionLocal is None:
        engine = get_async_engine()
        _AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,  # Prevent unnecessary queries after commit
            autocommit=False,
            autoflush=False
        )
    
    return _AsyncSessionLocal


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Async database session dependency for FastAPI.
    
    Provides automatic session management:
    - Opens async session
    - Yields to route handler
    - Automatically closes session (even on error)
    
    Usage:
        @router.post("/chat")
        async def chat_endpoint(db: AsyncSession = Depends(get_async_db)):
            result = await db.execute(select(User))
            users = result.scalars().all()
            return users
    
    Yields:
        AsyncSession instance
    """
    AsyncSessionLocal = get_async_session_local()
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_async_db():
    """
    Initialize database tables (async version).
    
    Creates all tables defined in models.py and applies migrations.
    For PostgreSQL, ensures pg_trgm and pgvector extensions.
    
    Note: Table creation is idempotent (safe to run multiple times).
    """
    try:
        from .models import Base
        
        engine = get_async_engine()
        
        # Create all tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("[OK] Async database tables created successfully")
        
        # Apply migrations (async version)
        await _apply_async_migrations(engine)
        
        # Ensure PostgreSQL extensions (pg_trgm for text search, pgvector for vectors)
        if 'postgresql' in _get_async_database_url():
            await _ensure_postgres_extensions()
    
    except Exception as e:
        logger.error(f"[ERROR] Failed to create async database tables: {e}", exc_info=True)
        raise


async def _apply_async_migrations(engine: AsyncEngine):
    """
    Apply database migrations for missing columns (async version).
    
    Handles schema updates when models are modified.
    This mirrors the sync _apply_migrations function.
    """
    from sqlalchemy import inspect, text
    
    try:
        async with engine.begin() as conn:
            # Get table names
            inspector = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
            async_db_url = _get_async_database_url()
            is_sqlite = 'sqlite' in async_db_url
            
            # Check if users table exists
            if 'users' in inspector:
                # Get existing columns
                existing_columns = await conn.run_sync(
                    lambda sync_conn: [col['name'] for col in inspect(sync_conn).get_columns('users')]
                )
                
                # Check and add last_email_synced_at if missing
                if 'last_email_synced_at' not in existing_columns:
                    logger.info("Adding missing column: users.last_email_synced_at")
                    column_type = "DATETIME" if is_sqlite else "TIMESTAMP"
                    await conn.execute(text(f"ALTER TABLE users ADD COLUMN last_email_synced_at {column_type}"))
                    if not is_sqlite:
                        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_last_sync ON users(last_email_synced_at)"))
                    logger.info("[OK] Migration applied: added last_email_synced_at column")
                    # Refresh columns list
                    existing_columns = await conn.run_sync(
                        lambda sync_conn: [col['name'] for col in inspect(sync_conn).get_columns('users')]
                    )
                
                # Check and add is_admin if missing
                if 'is_admin' not in existing_columns:
                    logger.info("Adding missing column: users.is_admin")
                    default_value = "0" if is_sqlite else "FALSE"
                    await conn.execute(text(f"ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT {default_value} NOT NULL"))
                    if not is_sqlite:
                        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_is_admin ON users(is_admin)"))
                    logger.info("[OK] Migration applied: added is_admin column")
            
            # Check if user_settings table exists
            if 'user_settings' not in inspector:
                logger.info("Creating user_settings table")
                if is_sqlite:
                    create_table_sql = """
                        CREATE TABLE user_settings (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL UNIQUE,
                            email_notifications BOOLEAN NOT NULL DEFAULT 0,
                            push_notifications BOOLEAN NOT NULL DEFAULT 0,
                            dark_mode BOOLEAN NOT NULL DEFAULT 1,
                            language VARCHAR(10) NOT NULL DEFAULT 'en',
                            region VARCHAR(10) NOT NULL DEFAULT 'US',
                            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                        )
                    """
                else:
                    create_table_sql = """
                        CREATE TABLE user_settings (
                            id SERIAL PRIMARY KEY,
                            user_id INTEGER NOT NULL UNIQUE,
                            email_notifications BOOLEAN NOT NULL DEFAULT FALSE,
                            push_notifications BOOLEAN NOT NULL DEFAULT FALSE,
                            dark_mode BOOLEAN NOT NULL DEFAULT TRUE,
                            language VARCHAR(10) NOT NULL DEFAULT 'en',
                            region VARCHAR(10) NOT NULL DEFAULT 'US',
                            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            CONSTRAINT fk_user_settings_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                        )
                    """
                await conn.execute(text(create_table_sql))
                if not is_sqlite:
                    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_settings_user_id ON user_settings(user_id)"))
                logger.info("[OK] Migration applied: created user_settings table")
            
            # Check if user_writing_profiles table exists
            if 'user_writing_profiles' not in inspector:
                logger.info("Creating user_writing_profiles table")
                if is_sqlite:
                    create_table_sql = """
                        CREATE TABLE user_writing_profiles (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL UNIQUE,
                            profile_data TEXT NOT NULL,
                            sample_size INTEGER DEFAULT 0,
                            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            last_rebuilt_at TIMESTAMP,
                            confidence_score REAL,
                            needs_refresh BOOLEAN DEFAULT 0,
                            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                        )
                    """
                else:
                    create_table_sql = """
                        CREATE TABLE user_writing_profiles (
                            id SERIAL PRIMARY KEY,
                            user_id INTEGER NOT NULL UNIQUE,
                            profile_data JSONB NOT NULL,
                            sample_size INTEGER DEFAULT 0,
                            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            last_rebuilt_at TIMESTAMP,
                            confidence_score DOUBLE PRECISION,
                            needs_refresh BOOLEAN DEFAULT FALSE,
                            CONSTRAINT fk_user_writing_profiles_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                        )
                    """
                await conn.execute(text(create_table_sql))
                if not is_sqlite:
                    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_writing_profiles_user_id ON user_writing_profiles(user_id)"))
                    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_writing_profiles_needs_refresh ON user_writing_profiles(needs_refresh)"))
                logger.info("[OK] Migration applied: created user_writing_profiles table")
    
    except Exception as e:
        logger.warning(f"Async migration check failed (non-critical): {e}")


async def _ensure_postgres_extensions():
    """
    Ensure required PostgreSQL extensions are installed.
    
    Extensions:
    - pg_trgm: Trigram text search (for similarity queries)
    - vector: pgvector extension (for vector storage)
    """
    engine = get_async_engine()
    
    async with engine.begin() as conn:
        try:
            # Check and create pg_trgm extension
            result = await conn.execute(text("""
                SELECT EXISTS(
                    SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'
                );
            """))
            exists = result.scalar()
            
            if not exists:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
                logger.info("[OK] pg_trgm extension created")
            
            # Check and create vector extension (pgvector)
            result = await conn.execute(text("""
                SELECT EXISTS(
                    SELECT 1 FROM pg_extension WHERE extname = 'vector'
                );
            """))
            exists = result.scalar()
            
            if not exists:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                logger.info("[OK] pgvector extension created")
        
        except Exception as e:
            if "permission denied" in str(e).lower():
                logger.warning(
                    "[WARNING] Cannot create PostgreSQL extensions automatically. "
                    "Please run as superuser:\n"
                    "  psql -d your_database -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'\n"
                    "  psql -d your_database -c 'CREATE EXTENSION IF NOT EXISTS vector;'"
                )
            else:
                logger.debug(f"Extension check failed (non-critical): {e}")


async def close_async_db_connections():
    """
    Close all async database connections and dispose engine.
    
    Useful for cleanup in tests or application shutdown.
    """
    global _async_engine, _AsyncSessionLocal
    
    if _async_engine:
        await _async_engine.dispose()
        logger.info("Async database connections closed")
    
    _async_engine = None
    _AsyncSessionLocal = None


# Context manager for non-FastAPI contexts
class AsyncDatabaseContext:
    """
    Async context manager for database sessions outside FastAPI.
    
    Usage:
        async with AsyncDatabaseContext() as db:
            result = await db.execute(select(User))
            users = result.scalars().all()
    """
    
    def __init__(self):
        self.session: AsyncSession | None = None
    
    async def __aenter__(self) -> AsyncSession:
        AsyncSessionLocal = get_async_session_local()
        self.session = AsyncSessionLocal()
        return self.session
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()


def get_async_db_context() -> AsyncDatabaseContext:
    """
    Get async database session context manager for background tasks.
    
    Usage:
        async def background_task():
            async with get_async_db_context() as db:
                result = await db.execute(select(User))
                users = result.scalars().all()
    
    Returns:
        AsyncDatabaseContext instance
    """
    return AsyncDatabaseContext()