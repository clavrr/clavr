"""
Database Utilities - Centralized utility functions for database operations

Consolidates common functionality to avoid duplication and improve maintainability.
"""
from typing import Generator, Optional, TypeVar, Type
from contextlib import contextmanager
from sqlalchemy.orm import Session

from ..utils.logger import setup_logger
from .database import get_session_local

logger = setup_logger(__name__)

T = TypeVar('T')


# SESSION MANAGEMENT

@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    Context manager for database sessions (for non-FastAPI contexts).
    
    Automatically handles session creation and cleanup, including rollback on errors.
    
    Usage:
        with get_db_context() as db:
            user = db.query(User).first()
            db.commit()
    
    Note: For FastAPI route handlers, use `get_db()` dependency injection instead.
    """
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_session_safe() -> Generator[Session, None, None]:
    """
    Get database session for background tasks with proper cleanup.
    
    This is a generator that yields a session and automatically closes it.
    Use with `next()` in try/finally blocks for manual session management.
    
    Usage:
        db_gen = get_db_session_safe()
        db = next(db_gen)
        try:
            # Use db
            pass
        finally:
            db.close()
    
    Note: Prefer `get_db_context()` context manager for cleaner code.
    """
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# QUERY HELPERS

def get_or_create(
    db: Session,
    model: Type[T],
    defaults: Optional[dict] = None,
    **kwargs
) -> tuple[T, bool]:
    """
    Get an instance of a model or create it if it doesn't exist.
    
    Args:
        db: Database session
        model: SQLAlchemy model class
        defaults: Dictionary of default values for creation
        **kwargs: Filter criteria for lookup
        
    Returns:
        Tuple of (instance, created) where created is True if instance was created
    
    Example:
        user, created = get_or_create(db, User, email='user@example.com', defaults={'name': 'New User'})
    """
    instance = db.query(model).filter_by(**kwargs).first()
    if instance:
        return instance, False
    
    if defaults:
        kwargs.update(defaults)
    
    instance = model(**kwargs)
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance, True


def safe_query(db: Session, query_func, default=None):
    """
    Safely execute a database query with error handling.
    
    Args:
        db: Database session
        query_func: Function that executes the query (e.g., lambda: db.query(User).first())
        default: Default value to return on error
        
    Returns:
        Query result or default value on error
    
    Example:
        user = safe_query(db, lambda: db.query(User).filter_by(email=email).first())
    """
    try:
        return query_func()
    except Exception as e:
        logger.warning(f"Database query failed: {e}", exc_info=True)
        return default


# ============================================================================
# TRANSACTION HELPERS
# ============================================================================

@contextmanager
def transaction(db: Session):
    """
    Context manager for database transactions.
    
    Automatically commits on success or rolls back on error.
    
    Usage:
        with transaction(db):
            user = User(email='test@example.com')
            db.add(user)
            # Automatically commits if no exception
    """
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise

