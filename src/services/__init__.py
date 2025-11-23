"""
Services - Core Services (Gmail/Calendar/Tasks Services Moved to Integrations)

Active Services:
- RAGService: High-level RAG service with caching and LLM enhancement
- IntelligentEmailIndexer: Intelligent email indexing with knowledge graph
- IncrementalEmailSync: Incremental email synchronization service
- ProfileUpdateService: Background profile update service
- ProfileCache: LRU cache for user writing profiles

MIGRATION NOTE:
Gmail, Calendar, and Task services have been migrated to src/integrations/ for better
organization with other platform integrations:
- EmailService → src/integrations/gmail/service.py
- CalendarService → src/integrations/google_calendar/service.py
- TaskService → src/integrations/google_tasks/service.py
"""

from .rag_service import RAGService
from .indexing.indexer import (
    IntelligentEmailIndexer,
    get_background_indexer,
    start_background_indexing,
    start_user_background_indexing,
    stop_background_indexing,
)
from .incremental_sync import IncrementalEmailSync
from .profile_service import (
    ProfileUpdateService,
    get_profile_service,
    start_profile_service,
    stop_profile_service,
)
from .profile_cache import ProfileCache, get_profile_cache
from .config_manager import ConfigManager, get_config_manager, configure_service_from_manager
from .factory import ServiceFactory, create_service_factory

__all__ = [
    # RAG Service
    "RAGService",
    # Email Indexing
    "IntelligentEmailIndexer",
    "get_background_indexer",
    "start_background_indexing",
    "start_user_background_indexing",
    "stop_background_indexing",
    "IncrementalEmailSync",
    # Profile Services
    "ProfileUpdateService",
    "get_profile_service",
    "start_profile_service",
    "stop_profile_service",
    "ProfileCache",
    "get_profile_cache",
    # Service Management
    "ConfigManager",
    "get_config_manager",
    "configure_service_from_manager",
    "ServiceFactory",
    "create_service_factory",
]
