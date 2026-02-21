"""
Async Credential Management for Google API Clients

Provides explicit async support for credential loading and refresh,
designed to work with FastAPI async routes and SQLAlchemy AsyncSession.

Architecture:
    AsyncCredentialFactory → AsyncCredentialProvider → Refresh Logic (in executor)
"""
import asyncio
import os
from typing import Optional, Any
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..utils.logger import setup_logger
from ..utils.config import Config
from ..database.models import Session as DBSession
from ..auth.token_refresh import refresh_token_if_needed, get_valid_credentials_async
from .credential_provider import CredentialProvider

logger = setup_logger(__name__)

class AsyncCredentialProvider:
    """
    Async-native credential provider.
    Uses AsyncSession for DB operations and offloads blocking auth calls to executor.
    """
    
    @staticmethod
    async def get_credentials(
        user_id: Optional[int] = None,
        db_session: Optional[AsyncSession] = None,
        token_path: Optional[str] = None,
        auto_refresh: bool = True
    ) -> Optional[Credentials]:
        """
        Get credentials asynchronously.
        
        Args:
            user_id: User ID (requires db_session)
            db_session: AsyncSession (SQLAlchemy)
            token_path: Path to token.json
            auto_refresh: Whether to refresh expired tokens of using DB source
            
        Returns:
            Valid Credentials object or None
        """
        if user_id and not db_session:
            raise ValueError("db_session is required when user_id is provided")
        
        # Priority 1: DB Credentials
        if user_id and db_session:
            return await AsyncCredentialProvider._get_user_credentials(
                user_id, db_session, auto_refresh
            )
            
        # Priority 2: File Credentials (blocking IO, run in executor)
        if token_path or os.path.exists('token.json'):
            path = token_path or 'token.json'
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, 
                lambda: CredentialProvider._get_file_credentials(path, auto_refresh)
            )
            
        return None

    @staticmethod
    async def _get_user_credentials(
        user_id: int,
        db: AsyncSession,
        auto_refresh: bool
    ) -> Optional[Credentials]:
        """Fetch and refresh user credentials using async DB session"""
        try:
            # 1. Try to get from UserIntegration (New Flow)
            try:
                from ..database.models import UserIntegration
                from ..auth.oauth import SCOPES
                
                stmt_int = select(UserIntegration).where(
                    UserIntegration.user_id == user_id,
                    UserIntegration.provider == 'gmail'
                )
                res_int = await db.execute(stmt_int)
                integration = res_int.scalars().first()
                
                if integration and integration.access_token:
                    logger.debug(f"Found Google credentials in UserIntegration for user {user_id}")
                    
                    client_id = os.getenv('GOOGLE_CLIENT_ID')
                    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
                    
                    if client_id and client_secret:
                        creds = Credentials(
                            token=integration.access_token,
                            refresh_token=integration.refresh_token,
                            token_uri="https://oauth2.googleapis.com/token",
                            client_id=client_id,
                            client_secret=client_secret,
                            scopes=SCOPES
                        )
                        
                        if integration.expires_at:
                            creds.expiry = integration.expires_at
                            
                        # Refresh if needed
                        if auto_refresh and creds.expired and creds.refresh_token:
                            logger.info(f"Refreshing UserIntegration token for user {user_id}")
                            loop = asyncio.get_event_loop()
                            
                            async def refresh_and_update():
                                def refresh_sync():
                                    try:
                                        creds.refresh(Request())
                                        return True
                                    except Exception as e:
                                        if 'invalid_scope' in str(e).lower():
                                            logger.debug(f"Async refresh failed with invalid_scope for user {user_id}. Retrying with implicit scopes...")
                                            # Try again without explicit scopes
                                            creds.scopes = None
                                            creds.refresh(Request())
                                            return True
                                        raise e

                                try:
                                    await loop.run_in_executor(None, refresh_sync)
                                    # Update DB (integration object is already updated in memory by the execute results)
                                    integration.access_token = creds.token
                                    if creds.expiry:
                                        integration.expires_at = creds.expiry.replace(tzinfo=None)
                                    await db.commit()
                                except Exception as e:
                                    logger.error(f"Failed to refresh UserIntegration token for user {user_id}: {e}")
                                    return None

                            await refresh_and_update()
                                
                        return creds
            except Exception as e:
                logger.warning(f"Failed to check UserIntegration: {e}")

            # Backward compatibility removed: strictly require UserIntegration
            logger.warning(f"No Google integration found for user {user_id} (Session fallback removed)")
            return None



        except Exception as e:
            logger.error(f"Async credential fetch failed: {e}", exc_info=True)
            return None


class AsyncCredentialFactory:
    """
    Factory for creating services with async credential loading.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.provider = AsyncCredentialProvider()
        
    async def create_service(
        self,
        service_type: str,
        user_id: Optional[int] = None,
        db_session: Optional[AsyncSession] = None,
        credentials: Optional[Credentials] = None,
        token_path: Optional[str] = None
    ) -> Any:
        """
        Create a service instance asynchronously.
        
        Args:
            service_type: 'email', 'calendar', 'task'
            user_id: User ID
            db_session: AsyncSession
            
        Returns:
            Service instance (EmailService, CalendarService, TaskService)
        """
        if not credentials:
            credentials = await self.provider.get_credentials(
                user_id=user_id,
                db_session=db_session,
                token_path=token_path
            )
            
        # Services themselves are sync wrappers around clients usually, 
        # but they accept the credentials object.
        # Constructing the service is fast (just init), so we can do it directly.
        
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
            raise ValueError(f"Unknown service type: {service_type}")
