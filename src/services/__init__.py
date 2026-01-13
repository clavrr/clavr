"""
Services - Core Services (Gmail/Calendar/Tasks Services Moved to Integrations)

Active Services:
- RAGService: High-level RAG service with caching and LLM enhancement
- UnifiedIndexerService: Central orchestration for all background indexers
- ProfileUpdateService: Background profile update service
- ProfileCache: LRU cache for user writing profiles
- ContactResolver: Resolve contact information across sources
- ContextService: Context assembly for agent queries
- GraphSearchService: Graph-based search across user data

MIGRATION NOTE:
Gmail, Calendar, and Task services have been migrated to src/integrations/ for better
organization with other platform integrations:
- EmailService → src/integrations/gmail/service.py
- CalendarService → src/integrations/google_calendar/service.py
- TaskService → src/integrations/google_tasks/service.py
"""

from .rag_service import RAGService
from .indexing.unified_indexer import (
    UnifiedIndexerService,
    get_unified_indexer,
    start_unified_indexing,
    stop_unified_indexing,
)
from .profile_service import (
    ProfileUpdateService,
    get_profile_service,
    start_profile_service,
    stop_profile_service,
)
from .profile_cache import ProfileCache, get_profile_cache
from .config_manager import ConfigManager, get_config_manager, configure_service_from_manager
from .factory import ServiceFactory, create_service_factory
from .contact_resolver import ContactResolver
from .context_service import ContextService
from .graph_search_service import GraphSearchService
from .service_constants import ServiceConstants

__all__ = [
    # RAG Service
    "RAGService",
    # Email Indexing (now via UnifiedIndexer)
    "UnifiedIndexerService",
    "get_unified_indexer",
    "start_unified_indexing",
    "stop_unified_indexing",
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
    # Additional Services
    "ContactResolver",
    "ContextService",
    "GraphSearchService",
    "ServiceConstants",
]


