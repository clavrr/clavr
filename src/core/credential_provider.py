"""
Centralized Credential Management for Google API Clients

Provides a single source of truth for credential loading, validation, and refresh.
Simplifies credential management across services, workers, and tools.

Architecture:
    Services/Workers → CredentialProvider → Credential Sources
                                           ├─ Database (user sessions)
                                           ├─ Token file (token.json)
                                           └─ Service account (future)

Usage:
    # Get credentials from database
    provider = CredentialProvider()
    creds = provider.get_credentials(user_id=123, db_session=db)
    
    # Get credentials from token file
    creds = provider.get_credentials(token_path='token.json')
    
    # Use factory for easy client creation
    factory = CredentialFactory(config)
    gmail = factory.create_gmail_client(user_id=123, db_session=db)
    calendar = factory.create_calendar_client(user_id=123, db_session=db)
"""
from typing import Optional
from google.oauth2.credentials import Credentials
from sqlalchemy.orm import Session
import os

from ..utils.logger import setup_logger
from ..utils.config import Config

logger = setup_logger(__name__)


class CredentialProvider:
    """
    Centralized credential provider
    
    Handles multiple credential sources with priority:
    1. User-specific credentials from database (preferred for multi-user)
    2. Token file (token.json) for CLI/testing/single-user
    3. Service account (future enhancement for background jobs)
    
    Features:
    - Automatic credential refresh
    - Multiple source support
    - Validation and error handling
    - Logging for audit trails
    """
    
    @staticmethod
    def get_credentials(
        user_id: Optional[int] = None,
        db_session: Optional[Session] = None,
        token_path: Optional[str] = None,
        auto_refresh: bool = True
    ) -> Optional[Credentials]:
        """
        Get credentials from the best available source
        
        Priority order:
        1. Database session credentials (if user_id and db_session provided)
        2. Token file (if token_path provided or token.json exists)
        3. None (if no source available)
        
        Args:
            user_id: User ID for database credentials (optional)
            db_session: SQLAlchemy database session (required if user_id provided)
            token_path: Path to token.json file (optional)
            auto_refresh: Automatically refresh expired credentials (default: True)
            
        Returns:
            Valid Google OAuth2 credentials or None
            
        Raises:
            ValueError: If user_id provided without db_session
            
        Example:
            # Database credentials
            creds = CredentialProvider.get_credentials(
                user_id=123,
                db_session=db
            )
            
            # File credentials
            creds = CredentialProvider.get_credentials(
                token_path='token.json'
            )
        """
        
        # Validate inputs
        if user_id and not db_session:
            raise ValueError("db_session is required when user_id is provided")
        
        # Priority 1: User-specific credentials from database
        if user_id and db_session:
            logger.debug(f"Loading credentials for user {user_id} from database")
            return CredentialProvider._get_user_credentials(
                user_id, db_session, auto_refresh
            )
        
        # Priority 2: Token file
        if token_path or os.path.exists('token.json'):
            path = token_path or 'token.json'
            logger.debug(f"Loading credentials from file: {path}")
            return CredentialProvider._get_file_credentials(
                path, auto_refresh
            )
        
        logger.warning("No credential source available")
        return None
    
    @staticmethod
    def _get_user_credentials(
        user_id: int,
        db: Session,
        auto_refresh: bool
    ) -> Optional[Credentials]:
        """
        Get credentials from database session
        
        Args:
            user_id: User ID
            db: Database session
            auto_refresh: Auto-refresh expired credentials
            
        Returns:
            Valid credentials or None
        """
        try:
            from ..database.models import Session as DBSession
            from ..auth.token_refresh import get_valid_credentials
            from datetime import datetime
            
            # Get user's active session with OAuth credentials
            session = db.query(DBSession).filter(
                DBSession.user_id == user_id,
                DBSession.gmail_access_token.isnot(None),
                DBSession.expires_at > datetime.utcnow()
            ).order_by(DBSession.created_at.desc()).first()
            
            if not session:
                logger.warning(f"No active session found for user {user_id}")
                return None
            
            # Get valid credentials (auto-refresh if needed)
            credentials = get_valid_credentials(db, session, auto_refresh=auto_refresh)
            
            if credentials:
                logger.info(f"✅ Loaded credentials for user {user_id}")
            else:
                logger.warning(f"Failed to get valid credentials for user {user_id}")
            
            return credentials
            
        except Exception as e:
            logger.error(f"Failed to get user credentials: {e}")
            return None
    
    @staticmethod
    def _get_file_credentials(
        token_path: str,
        auto_refresh: bool
    ) -> Optional[Credentials]:
        """
        Get credentials from token file
        
        Args:
            token_path: Path to token.json file
            auto_refresh: Auto-refresh expired credentials
            
        Returns:
            Valid credentials or None
        """
        try:
            if not os.path.exists(token_path):
                logger.debug(f"Token file not found: {token_path}")
                return None
            
            # Load credentials from file
            credentials = Credentials.from_authorized_user_file(token_path)
            
            # Refresh if expired and auto_refresh enabled
            if auto_refresh and credentials.expired and credentials.refresh_token:
                try:
                    from google.auth.transport.requests import Request
                    credentials.refresh(Request())
                    logger.info(f"✅ Refreshed credentials from {token_path}")
                except Exception as e:
                    logger.error(f"Failed to refresh credentials: {e}")
                    return None
            
            logger.info(f"✅ Loaded credentials from {token_path}")
            return credentials
            
        except Exception as e:
            logger.error(f"Failed to load credentials from {token_path}: {e}")
            return None
    
    @staticmethod
    def validate_credentials(credentials: Optional[Credentials]) -> bool:
        """
        Validate credentials are ready to use
        
        Args:
            credentials: Credentials to validate
            
        Returns:
            True if credentials are valid and not expired
        """
        if not credentials:
            return False
        
        if credentials.expired:
            if credentials.refresh_token:
                logger.debug("Credentials expired but have refresh token")
                return True
            else:
                logger.warning("Credentials expired and no refresh token")
                return False
        
        return True


class CredentialFactory:
    """
    Factory for creating Google API clients with proper credentials
    
    Simplifies client creation by handling credential loading automatically.
    Supports all Google API clients: Gmail, Calendar, Tasks.
    
    Features:
    - Automatic credential loading
    - Support for multiple credential sources
    - Type-safe client creation
    - Centralized error handling
    
    Example:
        config = load_config()
        factory = CredentialFactory(config)
        
        # Create clients with database credentials
        gmail = factory.create_gmail_client(user_id=123, db_session=db)
        calendar = factory.create_calendar_client(user_id=123, db_session=db)
        tasks = factory.create_tasks_client(user_id=123, db_session=db)
        
        # Create clients with file credentials
        gmail = factory.create_gmail_client(token_path='token.json')
    """
    
    def __init__(self, config: Config):
        """
        Initialize credential factory
        
        Args:
            config: Application configuration
        """
        self.config = config
        self.provider = CredentialProvider()
    
    def create_gmail_client(
        self,
        user_id: Optional[int] = None,
        db_session: Optional[Session] = None,
        credentials: Optional[Credentials] = None,
        token_path: Optional[str] = None
    ):
        """
        Create GoogleGmailClient with auto credential loading
        
        Args:
            user_id: User ID for database credentials
            db_session: Database session (required if user_id provided)
            credentials: Pre-loaded credentials (skips auto-loading)
            token_path: Path to token file
            
        Returns:
            GoogleGmailClient instance
            
        Example:
            # Database credentials
            client = factory.create_gmail_client(user_id=123, db_session=db)
            
            # File credentials
            client = factory.create_gmail_client(token_path='token.json')
            
            # Pre-loaded credentials
            client = factory.create_gmail_client(credentials=my_creds)
        """
        from ..core.email.google_client import GoogleGmailClient
        
        if not credentials:
            credentials = self.provider.get_credentials(
                user_id=user_id,
                db_session=db_session,
                token_path=token_path
            )
        
        return GoogleGmailClient(self.config, credentials=credentials)
    
    def create_calendar_client(
        self,
        user_id: Optional[int] = None,
        db_session: Optional[Session] = None,
        credentials: Optional[Credentials] = None,
        token_path: Optional[str] = None
    ):
        """
        Create GoogleCalendarClient with auto credential loading
        
        Args:
            user_id: User ID for database credentials
            db_session: Database session (required if user_id provided)
            credentials: Pre-loaded credentials (skips auto-loading)
            token_path: Path to token file
            
        Returns:
            GoogleCalendarClient instance
            
        Example:
            client = factory.create_calendar_client(user_id=123, db_session=db)
        """
        from ..core.calendar.google_client import GoogleCalendarClient
        
        if not credentials:
            credentials = self.provider.get_credentials(
                user_id=user_id,
                db_session=db_session,
                token_path=token_path
            )
        
        return GoogleCalendarClient(self.config, credentials=credentials)
    
    def create_tasks_client(
        self,
        user_id: Optional[int] = None,
        db_session: Optional[Session] = None,
        credentials: Optional[Credentials] = None,
        token_path: Optional[str] = None
    ):
        """
        Create GoogleTasksClient with auto credential loading
        
        Args:
            user_id: User ID for database credentials
            db_session: Database session (required if user_id provided)
            credentials: Pre-loaded credentials (skips auto-loading)
            token_path: Path to token file
            
        Returns:
            GoogleTasksClient instance
            
        Example:
            client = factory.create_tasks_client(user_id=123, db_session=db)
        """
        from ..core.tasks.google_client import GoogleTasksClient
        
        if not credentials:
            credentials = self.provider.get_credentials(
                user_id=user_id,
                db_session=db_session,
                token_path=token_path
            )
        
        return GoogleTasksClient(self.config, credentials=credentials)
    
    def create_service(
        self,
        service_type: str,
        user_id: Optional[int] = None,
        db_session: Optional[Session] = None,
        credentials: Optional[Credentials] = None,
        token_path: Optional[str] = None
    ):
        """
        Create any service with auto credential loading
        
        Args:
            service_type: Type of service ('email', 'calendar', 'task')
            user_id: User ID for database credentials
            db_session: Database session (required if user_id provided)
            credentials: Pre-loaded credentials (skips auto-loading)
            token_path: Path to token file
            
        Returns:
            Service instance (EmailService, CalendarService, or TaskService)
            
        Raises:
            ValueError: If service_type is unknown
            
        Example:
            email_service = factory.create_service('email', user_id=123, db_session=db)
            calendar_service = factory.create_service('calendar', user_id=123, db_session=db)
        """
        if not credentials:
            credentials = self.provider.get_credentials(
                user_id=user_id,
                db_session=db_session,
                token_path=token_path
            )
        
        if service_type.lower() == 'email':
            from ..integrations.gmail.service import EmailService
            return EmailService(config=self.config, credentials=credentials)
        
        elif service_type.lower() == 'calendar':
            from ..integrations.google_calendar.service import CalendarService
            return CalendarService(config=self.config, credentials=credentials)
        
        elif service_type.lower() in ['task', 'tasks']:
            from ..integrations.google_tasks.service import TaskService
            return TaskService(config=self.config, credentials=credentials)
        
        else:
            raise ValueError(
                f"Unknown service type: {service_type}. "
                f"Valid types: 'email', 'calendar', 'task'"
            )
