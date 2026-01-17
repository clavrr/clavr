"""
Database connection and session management
Optimized with proper connection pooling and lazy loading
"""
import os
from typing import Generator
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool, QueuePool

from .models import Base
from ..utils.logger import setup_logger

logger = setup_logger(__name__)

def _get_database_url():
    """
    Get DATABASE_URL from environment, loading .env file if needed
    
    Returns:
        Database connection URL
    """
    # Try to load .env file if dotenv is available
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)  # Don't override existing env vars
    except ImportError:
        pass  # dotenv not available, use system environment
    
    # Check environment variable
    db_url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')
    if db_url:
        return db_url
    
    # Default to SQLite
    return 'sqlite:///./clavr.db'

# Database URL from environment or default to SQLite
# Get it dynamically to ensure .env file is loaded
DATABASE_URL = _get_database_url()

# Lazy-loaded engine and session factory
_engine = None
_SessionLocal = None


def get_engine():
    """
    Get or create database engine (lazy-loaded with optimized pooling)
    
    Connection pooling configuration:
    - SQLite: StaticPool (single-threaded)
    - PostgreSQL: QueuePool (5-20 connections)
    """
    global _engine, DATABASE_URL
    
    # Reload DATABASE_URL to pick up any .env changes
    DATABASE_URL = _get_database_url()
    
    if _engine is None:
        if DATABASE_URL.startswith('sqlite'):
            # SQLite: single connection, no pooling
            _engine = create_engine(
                DATABASE_URL,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False  # Set to True for SQL debugging
            )
            logger.info(f"Database engine created: SQLite (local)")
        else:
            # PostgreSQL: connection pooling optimized for production
            _engine = create_engine(
                DATABASE_URL,
                pool_size=5,              # Minimum connections in pool
                max_overflow=10,          # Max additional connections
                pool_timeout=30,          # Wait time before timeout
                pool_recycle=3600,        # Recycle connections after 1 hour
                pool_pre_ping=True,       # Test connections before use
                poolclass=QueuePool,
                echo=False
            )
            
            # Add connection logging for monitoring
            @event.listens_for(_engine, "connect")
            def receive_connect(dbapi_conn, connection_record):
                logger.debug("Database connection established")
            
            @event.listens_for(_engine, "checkout")
            def receive_checkout(dbapi_conn, connection_record, connection_proxy):
                logger.debug("Connection checked out from pool")
            
            logger.info(f"Database engine created: PostgreSQL (pool_size=5, max_overflow=10)")
    
    return _engine


def get_session_local():
    """Get or create session factory (lazy-loaded)"""
    global _SessionLocal
    
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine,
            expire_on_commit=False  # Prevent unnecessary queries after commit
        )
    
    return _SessionLocal


def _ensure_pgvector_extension(engine):
    """
    Ensure pgvector extension is installed for PostgreSQL databases.
    This is required for vector database functionality.
    """
    if not DATABASE_URL.startswith('postgresql'):
        return
    
    try:
        with engine.begin() as conn:  # begin() automatically commits or rolls back
            # Check if extension exists
            result = conn.execute(text("""
                SELECT EXISTS(
                    SELECT 1 
                    FROM pg_extension 
                    WHERE extname = 'vector'
                );
            """))
            exists = result.scalar()
            
            if not exists:
                try:
                    # Try to create the extension
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                    logger.info("[OK] pgvector extension created")
                except Exception as e:
                    # Rollback will happen automatically, but we handle the error
                    if "permission denied" in str(e).lower() or "must be superuser" in str(e).lower():
                        logger.warning(
                            "[WARNING] Cannot create pgvector extension automatically.\n"
                            "Please run as PostgreSQL superuser:\n"
                            "  psql -d your_database -c 'CREATE EXTENSION IF NOT EXISTS vector;'\n"
                            "Or run: python scripts/setup_postgres_vector.py"
                        )
                    else:
                        logger.warning(f"[WARNING] Could not create pgvector extension: {e}")
                    raise  # Re-raise to trigger rollback
            else:
                logger.debug("pgvector extension already installed")
    except Exception as e:
        # Only log as debug if it's a permission issue (expected in some setups)
        if "permission denied" in str(e).lower() or "must be superuser" in str(e).lower():
            logger.debug(f"pgvector extension requires superuser privileges: {e}")
        else:
            logger.debug(f"pgvector extension check failed (non-critical): {e}")


def _create_index_safe(connection, index_sql: str, is_sqlite: bool):
    """
    Safely create an index, handling SQLite limitations.
    
    Args:
        connection: Database connection
        index_sql: SQL statement to create index
        is_sqlite: Whether database is SQLite
    """
    if is_sqlite:
        # SQLite doesn't support IF NOT EXISTS for indexes, so we'll skip if it fails
        try:
            connection.execute(text(index_sql))
        except Exception as e:
            logger.debug(f"Index creation skipped (may already exist): {e}")
    else:
        connection.execute(text(index_sql))





def init_db():
    """
    Initialize database tables
    Creates all tables defined in models.py and applies migrations
    For PostgreSQL, also ensures pgvector extension is installed
    """
    try:
        engine = get_engine()
        
        # Ensure pgvector extension for PostgreSQL (required for vector storage)
        if DATABASE_URL.startswith('postgresql'):
            _ensure_pgvector_extension(engine)
        
        Base.metadata.create_all(bind=engine)
        logger.info("[OK] Database tables created successfully")
        

    except Exception as e:
        logger.error(f"[ERROR] Failed to create database tables: {e}", exc_info=True)
        raise


def get_db() -> Generator[Session, None, None]:
    """
    Database session dependency for FastAPI
    
    Provides automatic session management:
    - Opens session
    - Yields to route handler
    - Automatically closes session (even on error)
    
    Usage:
        @app.get("/")
        def endpoint(db: Session = Depends(get_db)):
            user = db.query(User).first()
            return user
    """
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session() -> Generator[Session, None, None]:
    """
    Get database session for background tasks.
    
    DEPRECATED: Use `get_db_context()` from `utils.py` for non-FastAPI contexts instead.
    This function is kept for backward compatibility.
    
    For FastAPI route handlers, use `get_db()` dependency injection.
    For background tasks or non-FastAPI contexts, use `get_db_context()` context manager.
    """
    return get_db()


def close_db_connections():
    """
    Close all database connections and dispose engine
    Useful for cleanup in tests or shutdown
    """
    global _engine, _SessionLocal
    
    if _engine:
        _engine.dispose()
        logger.info("Database connections closed")
    
    _engine = None
    _SessionLocal = None
