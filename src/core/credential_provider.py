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
                logger.info(f"Loaded credentials for user {user_id}")
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
                    logger.info(f"Refreshed credentials from {token_path}")
                except Exception as e:
                    logger.error(f"Failed to refresh credentials: {e}")
                    return None
            
            logger.info(f"Loaded credentials from {token_path}")
            return credentials
            
        except Exception as e:
            logger.error(f"Failed to load credentials from {token_path}: {e}")
            return None
    
    @staticmethod
    def get_integration_credentials(
        user_id: int,
        provider: str,
        db_session: Optional[Session] = None,
        auto_refresh: bool = True
    ) -> Optional[Credentials]:
        """
        Get credentials from UserIntegration table for a specific provider.
        
        This is the preferred method for getting service-specific credentials
        (e.g., google_calendar, google_tasks, google_drive) as it uses the 
        integration-specific tokens with correct scopes.
        
        Args:
            user_id: User ID
            provider: Provider name (e.g., 'google_calendar', 'google_tasks', 'gmail', 'google_drive')
            db_session: Optional SQLAlchemy session (will create one if not provided)
            auto_refresh: Automatically refresh expired credentials
            
        Returns:
            Valid Google OAuth2 credentials or None
            
        Example:
            # Get calendar-specific credentials
            creds = CredentialProvider.get_integration_credentials(
                user_id=123,
                provider='google_calendar',
                db_session=db
            )
        """
        try:
            from ..database.models import UserIntegration
            from ..database import get_db_context
            from ..utils import decrypt_token
            import os
            
            # Use provided session or create new context
            if db_session:
                integration = db_session.query(UserIntegration).filter(
                    UserIntegration.user_id == user_id,
                    UserIntegration.provider == provider,
                    UserIntegration.is_active == True
                ).first()
            else:
                with get_db_context() as db:
                    integration = db.query(UserIntegration).filter(
                        UserIntegration.user_id == user_id,
                        UserIntegration.provider == provider,
                        UserIntegration.is_active == True
                    ).first()
            
            if not integration:
                logger.debug(f"No active integration found for user {user_id}, provider {provider}")
                return None
            
            if not integration.access_token:
                logger.warning(f"Integration {provider} for user {user_id} has no access token")
                return None
            
            # Try to decrypt tokens, fallback to raw value if not encrypted
            # (UserIntegration tokens may be stored unencrypted)
            try:
                access_token = decrypt_token(integration.access_token)
                refresh_token = decrypt_token(integration.refresh_token) if integration.refresh_token else None
            except Exception as e:
                # Tokens might be unencrypted - use directly
                logger.debug(f"Using unencrypted tokens for {provider} (decrypt failed: {e})")
                access_token = integration.access_token
                refresh_token = integration.refresh_token
            
            # Get OAuth client credentials
            client_id = os.getenv('GOOGLE_CLIENT_ID')
            client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
            
            if not client_id or not client_secret:
                logger.warning("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET not configured")
                return None
            
            # Determine scopes based on provider - prefer actual granted scopes
            scopes = None
            if integration.integration_metadata:
                metadata_scopes = integration.integration_metadata.get('scopes') or integration.integration_metadata.get('scope')
                if metadata_scopes:
                    if isinstance(metadata_scopes, str):
                        scopes = metadata_scopes.split(' ')
                    else:
                        scopes = metadata_scopes

            if not scopes:
                from ..auth.oauth import GMAIL_SCOPES, CALENDAR_SCOPES, TASKS_SCOPES, DRIVE_SCOPES
                scopes_map = {
                    'gmail': GMAIL_SCOPES,
                    'google_calendar': CALENDAR_SCOPES,
                    'google_tasks': TASKS_SCOPES,
                    'google_drive': DRIVE_SCOPES,
                }
                scopes = scopes_map.get(provider, [])
            
            # Create credentials object
            credentials = Credentials(
                token=access_token,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=scopes
            )
            
            # Set expiry from database
            if integration.expires_at:
                credentials.expiry = integration.expires_at
            
            # Refresh if needed
            if auto_refresh and credentials.expired and credentials.refresh_token:
                try:
                    from google.auth.transport.requests import Request
                    # Try refreshing with current scopes
                    credentials.refresh(Request())
                    logger.info(f"Refreshed {provider} credentials for user {user_id}")
                    
                    # Update tokens in database
                    from ..utils import encrypt_token
                    encrypted_access = encrypt_token(credentials.token)
                    encrypted_refresh = encrypt_token(credentials.refresh_token) if credentials.refresh_token else None
                    
                    if db_session:
                        integration.access_token = encrypted_access
                        if encrypted_refresh and encrypted_refresh != integration.refresh_token:
                            logger.info(f"Refresh token rotated for {provider} (user {user_id}) - saving new token")
                            integration.refresh_token = encrypted_refresh
                        
                        if credentials.expiry:
                            integration.expires_at = credentials.expiry.replace(tzinfo=None)
                        db_session.commit()
                    else:
                        with get_db_context() as db:
                            db_integration = db.query(UserIntegration).filter(
                                UserIntegration.id == integration.id
                            ).first()
                            if db_integration:
                                db_integration.access_token = encrypted_access
                                if encrypted_refresh and encrypted_refresh != db_integration.refresh_token:
                                    logger.info(f"Refresh token rotated for {provider} (user {user_id}) - saving new token")
                                    db_integration.refresh_token = encrypted_refresh
                                    
                                if credentials.expiry:
                                    db_integration.expires_at = credentials.expiry.replace(tzinfo=None)
                                db.commit()
                except Exception as e:
                    error_str = str(e).lower()
                    
                    # RETRY STRATEGY: Handle "invalid_scope" by retrying without explicit scopes
                    # This occurs when the token has a superset of permissions (e.g. 'tasks' full)
                    # but we requested a subset (e.g. 'tasks.readonly').
                    if 'invalid_scope' in error_str and scopes is not None:
                        logger.debug(f"Initial refresh for {provider} (user {user_id}) failed with invalid_scope. Retrying with implicit scopes...")
                        try:
                            # Re-initialize credentials without explicit scopes
                            # This allows Google to refresh with whatever scopes are associated with the token
                            credentials = Credentials(
                                token=access_token,
                                refresh_token=refresh_token,
                                token_uri="https://oauth2.googleapis.com/token",
                                client_id=client_id,
                                client_secret=client_secret,
                                scopes=None
                            )
                            credentials.refresh(Request())
                            logger.info(f"Refreshed {provider} credentials (implicit scopes) for user {user_id}")
                            
                            # Proceed to save updates
                            from ..utils import encrypt_token
                            encrypted_access = encrypt_token(credentials.token)
                            
                            if db_session:
                                integration.access_token = encrypted_access
                                if credentials.expiry:
                                    integration.expires_at = credentials.expiry.replace(tzinfo=None)
                                db_session.commit()
                            else:
                                with get_db_context() as db:
                                    db_integration = db.query(UserIntegration).filter(
                                        UserIntegration.id == integration.id
                                    ).first()
                                    if db_integration:
                                        db_integration.access_token = encrypted_access
                                        if credentials.expiry:
                                            db_integration.expires_at = credentials.expiry.replace(tzinfo=None)
                                        db.commit()
                            
                            # Return the successful credentials
                            return credentials
                            
                        except Exception as retry_err:
                            logger.error(f"Implicit refresh retry failed for {provider}: {retry_err}")
                            # Fall through to original error handling if retry fails
                    
                    # Check if this is a fatal auth error (invalid_grant means token is revoked/expired permanently)
                    if 'invalid_grant' in error_str or 'token has been expired or revoked' in error_str:
                        logger.error(f"[CredentialProvider] {provider} credentials for user {user_id} are INVALID (revoked/expired). User must re-authenticate.")
                        
                        # Mark integration as needing re-auth
                        try:
                            if db_session:
                                integration.is_active = False
                                db_session.commit()
                                logger.info(f"[CredentialProvider] Marked {provider} integration as inactive for user {user_id}")
                            else:
                                with get_db_context() as db:
                                    db_integration = db.query(UserIntegration).filter(
                                        UserIntegration.id == integration.id
                                    ).first()
                                    if db_integration:
                                        db_integration.is_active = False
                                        db.commit()
                                        logger.info(f"[CredentialProvider] Marked {provider} integration as inactive for user {user_id}")
                        except Exception as mark_err:
                            logger.warning(f"[CredentialProvider] Failed to mark integration as inactive: {mark_err}")
                        
                        # Return None - do NOT return invalid credentials
                        return None
                    else:
                        # For other errors (network issues, etc.), log warning but still return credentials
                        # They might work if the error was transient
                        logger.warning(f"Failed to refresh {provider} credentials (non-fatal): {e}")
            
            logger.debug(f"Loaded {provider} credentials for user {user_id} (scopes: {scopes})")
            return credentials
            
        except Exception as e:
            logger.error(f"Failed to get integration credentials for {provider}: {e}")
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
            # 1. Try specific integration credentials first (prioritizes UserIntegration table)
            if user_id:
                credentials = self.provider.get_integration_credentials(
                    user_id=user_id,
                    provider='gmail',
                    db_session=db_session
                )
            
            # 2. Fallback to generic credentials (session/file)
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
            # 1. Try specific integration credentials first
            if user_id:
                credentials = self.provider.get_integration_credentials(
                    user_id=user_id,
                    provider='google_calendar',
                    db_session=db_session
                )
            
            # 2. Fallback to generic credentials
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
            # 1. Try specific integration credentials first
            if user_id:
                credentials = self.provider.get_integration_credentials(
                    user_id=user_id,
                    provider='google_tasks',
                    db_session=db_session
                )
            
            # 2. Fallback to generic credentials
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
        # 1. Map service type to provider
        provider_map = {
            'email': 'gmail',
            'gmail': 'gmail',
            'calendar': 'google_calendar',
            'task': 'google_tasks',
            'tasks': 'google_tasks'
        }
        provider = provider_map.get(service_type.lower())

        if not credentials:
            # 2. Try specific integration credentials first
            if user_id and provider:
                credentials = self.provider.get_integration_credentials(
                    user_id=user_id,
                    provider=provider,
                    db_session=db_session
                )
            
            # 3. Fallback to generic credentials
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
