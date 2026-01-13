"""
Service Factory - Centralized service creation with credential management

Provides a single point of service instantiation with automatic credential loading,
dependency injection, and configuration management.

Usage:
    factory = ServiceFactory(config)
    
    # Create services with database credentials
    email_service = factory.create_email_service(user_id=123, db_session=db)
    calendar_service = factory.create_calendar_service(user_id=123, db_session=db)
    task_service = factory.create_task_service(user_id=123, db_session=db)
    
    # Create services with token file credentials
    email_service = factory.create_email_service(token_path='token.json')
    
    # Create services without credentials (limited functionality)
    rag_service = factory.create_rag_service()
"""
from typing import Optional, Any
from sqlalchemy.orm import Session

from ..core.credential_provider import CredentialProvider
from ..utils.config import Config
from ..utils.logger import setup_logger
# Services have been moved to integrations/ for better organization
from ..integrations.gmail.service import EmailService
from ..integrations.gmail.exceptions import (
    EmailServiceException,
    ServiceUnavailableException
)
from ..integrations.google_calendar.service import CalendarService
from ..integrations.google_calendar.exceptions import (
    CalendarServiceException,
    AuthenticationException as CalendarAuthenticationException
)
from ..integrations.google_tasks.service import TaskService
from ..integrations.google_tasks.exceptions import (
    TaskServiceException,
    AuthenticationException as TaskAuthenticationException
)
from ..integrations.notion.service import NotionService
from ..integrations.notion.exceptions import (
    NotionServiceException,
    ServiceUnavailableException as NotionServiceUnavailableException
)
from .rag_service import RAGService

# Create base exception aliases for backward compatibility
ServiceException = EmailServiceException  # Base exception for factory
AuthenticationException = TaskAuthenticationException  # Use task auth exception as base

logger = setup_logger(__name__)


class ServiceFactory:
    """
    Factory for creating services with proper credential management
    
    Features:
    - Automatic credential loading
    - Dependency injection
    - Configuration management
    - Error handling and logging
    - Service caching (optional)
    """
    
    def __init__(self, config: Config, enable_caching: bool = False):
        """
        Initialize service factory
        
        Args:
            config: Application configuration
            enable_caching: Whether to cache service instances
        """
        self.config = config
        self.enable_caching = enable_caching
        self.credential_provider = CredentialProvider()
        
        # Service cache (optional)
        self._service_cache = {} if enable_caching else None
        
        logger.debug("[SERVICE_FACTORY] Initialized")
    
    def _get_cache_key(self, service_type: str, user_id: Optional[int] = None, 
                       token_path: Optional[str] = None) -> str:
        """Generate cache key for service instance"""
        if user_id:
            return f"{service_type}_user_{user_id}"
        elif token_path:
            return f"{service_type}_token_{token_path}"
        else:
            return f"{service_type}_no_auth"
    
    def _get_cached_service(self, cache_key: str) -> Optional[Any]:
        """Get cached service if caching enabled"""
        if self._service_cache and cache_key in self._service_cache:
            logger.debug(f"[SERVICE_FACTORY] Using cached service: {cache_key}")
            return self._service_cache[cache_key]
        return None
    
    def _cache_service(self, cache_key: str, service: Any):
        """Cache service if caching enabled"""
        if self._service_cache:
            self._service_cache[cache_key] = service
            logger.debug(f"[SERVICE_FACTORY] Cached service: {cache_key}")
    
    def clear_cache(self, service_type: Optional[str] = None, user_id: Optional[int] = None):
        """Clear service cache for a specific service type/user or all services"""
        if not self._service_cache:
            return
        
        if service_type and user_id:
            # Clear specific service for specific user
            cache_key = self._get_cache_key(service_type, user_id)
            if cache_key in self._service_cache:
                del self._service_cache[cache_key]
                logger.info(f"[SERVICE_FACTORY] Cleared cache for {cache_key}")
        elif service_type:
            # Clear all services of a specific type
            keys_to_remove = [k for k in self._service_cache.keys() if k.startswith(f"{service_type}_")]
            for key in keys_to_remove:
                del self._service_cache[key]
            logger.info(f"[SERVICE_FACTORY] Cleared cache for {len(keys_to_remove)} {service_type} services")
        else:
            # Clear all cached services
            self._service_cache.clear()
            logger.info(f"[SERVICE_FACTORY] Cleared all cached services")
    
    def _get_credentials(self, user_id: Optional[int] = None, 
                        db_session: Optional[Session] = None,
                        token_path: Optional[str] = None) -> Optional[Any]:
        """Get credentials using credential provider"""
        try:
            if user_id and db_session:
                return self.credential_provider.get_credentials(
                    user_id=user_id, 
                    db_session=db_session
                )
            elif token_path:
                return self.credential_provider.get_credentials(token_path=token_path)
            else:
                return None
        except Exception as e:
            logger.error(f"[SERVICE_FACTORY] Failed to get credentials: {e}")
            return None
    
    def _create_credentialed_service(
        self,
        service_type: str,
        service_class: type,
        user_id: Optional[int] = None,
        db_session: Optional[Session] = None,
        token_path: Optional[str] = None,
        require_credentials: bool = False,
        **service_kwargs
    ) -> Any:
        """
        Generic method to create services that require credentials.
        Eliminates duplication across create_email_service, create_calendar_service, etc.
        
        Args:
            service_type: Service type name (e.g., "email", "calendar", "task")
            service_class: Service class to instantiate
            user_id: User ID for database credentials
            db_session: Database session
            token_path: Path to token file
            require_credentials: Whether credentials are required (raises exception if missing)
            **service_kwargs: Additional keyword arguments to pass to service constructor
            
        Returns:
            Service instance
            
        Raises:
            AuthenticationException: If require_credentials=True and credentials not provided
            ServiceException: If service creation fails
        """
        cache_key = self._get_cache_key(service_type, user_id, token_path)
        
        # Check cache
        cached_service = self._get_cached_service(cache_key)
        if cached_service:
            return cached_service
        
        try:
            # Get credentials
            credentials = self._get_credentials(user_id, db_session, token_path)
            
            if require_credentials and not credentials:
                raise AuthenticationException(
                    f"Google {service_type.title()} credentials required. "
                    "Please provide user_id + db_session or token_path.",
                    service_name=f"{service_type}_factory"
                )
            
            # Create service with common parameters
            service_kwargs['config'] = self.config
            service_kwargs['credentials'] = credentials
            
            service = service_class(**service_kwargs)
            
            # Cache if enabled
            self._cache_service(cache_key, service)
            
            logger.info(f"[SERVICE_FACTORY] Created {service_class.__name__} for {cache_key}")
            return service
            
        except AuthenticationException:
            raise
        except Exception as e:
            logger.error(f"[SERVICE_FACTORY] Failed to create {service_class.__name__}: {e}")
            raise ServiceException(
                f"Failed to create {service_class.__name__}: {str(e)}",
                service_name=f"{service_type}_factory"
            )
    
    def _create_uncredentialed_service(
        self,
        service_type: str,
        service_class: type,
        **service_kwargs
    ) -> Any:
        """
        Generic method to create services that don't require credentials.
        
        Args:
            service_type: Service type name (e.g., "rag")
            service_class: Service class to instantiate
            **service_kwargs: Keyword arguments to pass to service constructor
            
        Returns:
            Service instance
            
        Raises:
            ServiceException: If service creation fails
        """
        cache_key = self._get_cache_key(service_type)
        
        # Check cache
        cached_service = self._get_cached_service(cache_key)
        if cached_service:
            return cached_service
        
        try:
            # Create service with common parameters
            service_kwargs['config'] = self.config
            service = service_class(**service_kwargs)
            
            # Cache if enabled
            self._cache_service(cache_key, service)
            
            logger.info(f"[SERVICE_FACTORY] Created {service_class.__name__}")
            return service
            
        except Exception as e:
            logger.error(f"[SERVICE_FACTORY] Failed to create {service_class.__name__}: {e}")
            raise ServiceException(
                f"Failed to create {service_class.__name__}: {str(e)}",
                service_name=f"{service_type}_factory"
            )
    
    # ===================================================================
    # EMAIL SERVICE
    # ===================================================================
    
    def create_email_service(
        self,
        user_id: Optional[int] = None,
        db_session: Optional[Session] = None,
        token_path: Optional[str] = None,
        rag_engine: Optional[Any] = None
    ) -> EmailService:
        """
        Create email service with automatic credential loading
        
        Args:
            user_id: User ID for database credentials
            db_session: Database session
            token_path: Path to token file
            rag_engine: Optional RAG engine for semantic search
            
        Returns:
            Configured EmailService instance
        """
        return self._create_credentialed_service(
            service_type="email",
            service_class=EmailService,
            user_id=user_id,
            db_session=db_session,
            token_path=token_path,
            require_credentials=False,
            rag_engine=rag_engine
        )
    
    # ===================================================================
    # CALENDAR SERVICE
    # ===================================================================
    
    def create_calendar_service(
        self,
        user_id: Optional[int] = None,
        db_session: Optional[Session] = None,
        token_path: Optional[str] = None
    ) -> CalendarService:
        """
        Create calendar service with automatic credential loading
        
        Args:
            user_id: User ID for database credentials
            db_session: Database session
            token_path: Path to token file
            
        Returns:
            Configured CalendarService instance
        """
        return self._create_credentialed_service(
            service_type="calendar",
            service_class=CalendarService,
            user_id=user_id,
            db_session=db_session,
            token_path=token_path,
            require_credentials=False
        )
    
    # ===================================================================
    # TASK SERVICE
    # ===================================================================
    
    def create_task_service(
        self,
        user_id: Optional[int] = None,
        db_session: Optional[Session] = None,
        token_path: Optional[str] = None
    ) -> TaskService:
        """
        Create task service with automatic credential loading
        
        Args:
            user_id: User ID for database credentials
            db_session: Database session
            token_path: Path to token file
            
        Returns:
            Configured TaskService instance
            
        Raises:
            AuthenticationException: If credentials not provided
        """
        return self._create_credentialed_service(
            service_type="task",
            service_class=TaskService,
            user_id=user_id,
            db_session=db_session,
            token_path=token_path,
            require_credentials=True
        )
    
    # ===================================================================
    # RAG SERVICE
    # ===================================================================
    
    def create_rag_service(
        self,
        collection_name: str = "email-knowledge"
    ) -> RAGService:
        """
        Create RAG service (no credentials required)
        
        Args:
            collection_name: RAG collection name
            
        Returns:
            Configured RAGService instance
        """
        return self._create_uncredentialed_service(
            service_type="rag",
            service_class=RAGService,
            collection_name=collection_name
        )
    
    # ===================================================================
    # UTILITY METHODS
    # ===================================================================
    
    def get_cache_stats(self) -> dict:
        """Get cache statistics"""
        if not self._service_cache:
            return {"caching": False}
        
        return {
            "caching": True,
            "cached_services": len(self._service_cache),
            "service_types": list(set(
                key.split('_')[0] for key in self._service_cache.keys()
            ))
        }


# ===================================================================
# CONVENIENCE FUNCTIONS
# ===================================================================

def create_service_factory(config: Config, enable_caching: bool = False) -> ServiceFactory:
    """
    Create a service factory instance
    
    Args:
        config: Application configuration
        enable_caching: Whether to enable service caching
        
    Returns:
        ServiceFactory instance
    """
    return ServiceFactory(config, enable_caching=enable_caching)