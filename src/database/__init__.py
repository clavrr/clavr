"""
Database models and operations for multi-user support

Main exports:
- Base: SQLAlchemy declarative base for all models
- Models: User, Session, ConversationMessage, BlogPost, UserSettings, AuditLog, OAuthState, UserWritingProfile, WebhookSubscription, WebhookDelivery
- Session management: 
  - Sync: get_db (FastAPI dependency), get_db_context (context manager)
  - Async: get_async_db (FastAPI dependency), get_async_db_context (context manager)
- Initialization: init_db (sync), init_async_db (async)
- Utilities: See utils.py for query helpers and transaction management
"""

from .models import (
    Base,
    User,
    Session,
    ConversationMessage,
    BlogPost,
    UserSettings,
    AuditLog,
    OAuthState,
    UserWritingProfile
)
from .webhook_models import WebhookSubscription, WebhookDelivery, WebhookEventType, WebhookDeliveryStatus
from .database import get_db, get_db_session, init_db
from .async_database import get_async_db, get_async_db_context, init_async_db, AsyncSession
from .utils import get_db_context, get_db_session_safe, get_or_create, safe_query, transaction

__all__ = [
    # Base
    'Base',  # SQLAlchemy declarative base
    # Models
    'User',
    'Session',
    'ConversationMessage',
    'BlogPost',
    'UserSettings',
    'AuditLog',
    'OAuthState',
    'UserWritingProfile',
    'WebhookSubscription',
    'WebhookDelivery',
    'WebhookEventType',
    'WebhookDeliveryStatus',
    # Sync Session management
    'get_db',  # FastAPI dependency
    'get_db_session',  # Deprecated, use get_db_context instead
    'get_db_context',  # Context manager for non-FastAPI contexts
    'get_db_session_safe',  # Generator for manual session management
    # Async Session management
    'get_async_db',  # FastAPI dependency for async routes
    'get_async_db_context',  # Context manager for async background tasks
    'AsyncSession',  # Type for async database sessions
    # Initialization
    'init_db',  # Sync initialization
    'init_async_db',  # Async initialization
    # Utilities
    'get_or_create',
    'safe_query',
    'transaction',
]

