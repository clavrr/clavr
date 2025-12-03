"""
Incremental Email Synchronization Service
Syncs only new emails since last check to improve performance
Enhanced with NLP support and Gmail API integration
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from ..utils.logger import setup_logger
from ..utils.config import load_config
from ..database import get_db_context
from ..database.models import User, Session as DBSession
from .indexing.indexer import IntelligentEmailIndexer
from ..ai.rag import RAGEngine

logger = setup_logger(__name__)


class IncrementalEmailSync:
    """
    Handles incremental email synchronization for users
    
    Key improvements:
    - Only syncs emails since last sync timestamp
    - Background periodic checking (every 15 minutes)
    - Manual trigger support
    - Efficient duplicate detection
    - NLP-based date parsing
    - Rate limiting protection
    """
    
    def __init__(self):
        self.config = load_config("config/config.yaml")
        self.sync_interval = 900  # 15 minutes in seconds
        self.is_running = False
        
        # Initialize NLP for better date parsing
        self.date_parser = None
        self._init_nlp()
        
        # Rate limiting (Gmail API: 1 billion quota units per day)
        self.rate_limit_delay = 0.1  # 100ms between requests
    
    def _init_nlp(self):
        """Initialize NLP utilities for flexible date parsing"""
        try:
            from ..utils import FlexibleDateParser
            self.date_parser = FlexibleDateParser()
            logger.info("NLP date parser initialized for incremental sync")
        except Exception as e:
            logger.warning(f"NLP initialization failed: {e}")
        
    async def sync_user_emails(
        self, 
        user_id: int, 
        since: Optional[datetime] = None,
        force_full: bool = False
    ) -> Dict:
        """
        Sync emails for a specific user
        
        Args:
            user_id: User ID to sync
            since: Only sync emails after this timestamp (None = use last sync time)
            force_full: Force full re-index of recent emails
            
        Returns:
            Sync statistics
        """
        logger.info(f"Starting incremental sync for user {user_id}")
        
        try:
            with get_db_context() as db:
                # Get user from database
                user = db.query(User).filter(User.id == user_id).first()
                
                if not user:
                    return {'status': 'error', 'message': 'User not found'}
                
                # Get active session with tokens
                session = db.query(DBSession).filter(
                    DBSession.user_id == user_id,
                    DBSession.expires_at > datetime.utcnow()
                ).order_by(DBSession.created_at.desc()).first()
                
                if not session or not session.gmail_access_token:
                    return {'status': 'error', 'message': 'No valid Gmail session'}
                
                # Determine sync range
                if force_full:
                    since = None
                    limit = 300
                elif since:
                    limit = 1000  # Fetch more emails to filter by date
                else:
                    # Use last sync time from user record
                    since = getattr(user, 'last_email_synced_at', None)
                    if since and not force_full:
                        limit = 500  # Reasonable limit for incremental sync
                    else:
                        limit = 300  # First time sync
                
                # Initialize indexer using new IntelligentEmailIndexer
                # Use service layer to get Gmail client
                from ..services.factory import ServiceFactory
                
                config = self.config
                service_factory = ServiceFactory(config=config)
                email_service = service_factory.create_email_service(
                    user_id=user.id,
                    db_session=db
                )
                
                if not email_service or not email_service.gmail_client:
                    raise ValueError(f"Failed to create Gmail service for user {user.id}")
                
                gmail_client = email_service.gmail_client
                
                indexer = IntelligentEmailIndexer(
                    config=config,
                    google_client=gmail_client,
                    user_id=user.id,
                    collection_name=f"user_{user.id}_emails"
                )
                
                # Sync emails with date filter
                stats = await self._sync_with_date_filter(
                    indexer, 
                    since=since,
                    limit=limit
                )
                
                # Update last sync timestamp and other metadata
                if 'last_synced_email_date' in stats:
                    user.last_email_synced_at = stats['last_synced_email_date']
                    user.last_indexed_timestamp = stats['last_synced_email_date']
                
                # Update index count
                user.index_count = stats.get('total_indexed', 0)
                if stats.get('total_indexed', 0) > 0:
                    user.total_emails_indexed = (user.total_emails_indexed or 0) + stats.get('total_indexed', 0)
                    user.indexing_status = 'completed'
                
                db.commit()
                logger.info(f"✓ Incremental sync completed for user {user_id}: {stats}")
                return stats
                
        except Exception as e:
            logger.error(f"Incremental sync failed for user {user_id}: {e}", exc_info=True)
            return {'status': 'error', 'message': str(e)}
    
    async def _sync_with_date_filter(
        self,
        indexer: IntelligentEmailIndexer,
        since: Optional[datetime] = None,
        limit: int = 300
    ) -> Dict:
        """
        Sync emails filtering by date
        
        Args:
            indexer: IntelligentEmailIndexer instance (in per-user mode)
            since: Only sync emails after this date
            limit: Maximum emails to fetch
            
        Returns:
            Sync statistics with last email date
        """
        from email.utils import parsedate_to_datetime
        
        stats = {
            'total_fetched': 0,
            'total_indexed': 0,
            'total_skipped': 0,
            'total_failed': 0,
            'sync_type': 'incremental' if since else 'full'
        }
        
        try:
            # Build Gmail query based on date filter
            if since:
                # Use date filter in Gmail query for efficiency
                date_str = since.strftime('%Y/%m/%d')
                query = f"after:{date_str}"
            else:
                query = "in:all"
            
            # Fetch unindexed emails using the indexer's method
            # This method already filters out already-indexed emails
            emails, next_page_token = await indexer._get_unindexed_emails(
                query=query,
                max_results=limit,
                page_token=None
            )
            stats['total_fetched'] = len(emails)
            
            if not emails:
                stats['last_synced_email_date'] = datetime.utcnow()
                return stats
            
            # Additional date filtering if needed (for emails fetched without date query)
            if since and not query.startswith("after:"):
                filtered_emails = []
                for email in emails:
                    try:
                        # Use NLP date parser if available, fallback to email.utils
                        if self.date_parser:
                            email_date = self.date_parser.parse(email.get('date', ''))
                        else:
                            email_date = parsedate_to_datetime(email.get('date', ''))
                        
                        if email_date and email_date > since:
                            filtered_emails.append(email)
                        else:
                            stats['total_skipped'] += 1
                    except Exception as e:
                        # If date parsing fails, include the email
                        logger.debug(f"Date parsing failed for email {email.get('id', 'unknown')}: {e}")
                        filtered_emails.append(email)
                
                emails = filtered_emails
                logger.info(f"Filtered to {len(emails)} new emails since {since}")
            
            # Apply rate limiting
            await asyncio.sleep(self.rate_limit_delay)
            
            # Index emails individually (indexer doesn't have batch method)
            indexed_count = 0
            skipped_count = 0
            failed_count = 0
            
            for email in emails:
                try:
                    success = await indexer.index_email(email)
                    if success:
                        indexed_count += 1
                    else:
                        skipped_count += 1
                    await asyncio.sleep(self.rate_limit_delay)
                except Exception as e:
                    logger.warning(f"Failed to index email {email.get('id', 'unknown')}: {e}")
                    failed_count += 1
            
            stats['total_indexed'] = indexed_count
            stats['total_skipped'] += skipped_count
            stats['total_failed'] = failed_count
            
            # Get the most recent email date (for timestamp tracking)
            if emails:
                try:
                    # Find the most recent email by date
                    most_recent_date = None
                    for email in emails:
                        try:
                            if self.date_parser:
                                email_date = self.date_parser.parse(email.get('date', ''))
                            else:
                                email_date = parsedate_to_datetime(email.get('date', ''))
                            
                            if email_date and (most_recent_date is None or email_date > most_recent_date):
                                most_recent_date = email_date
                        except Exception as e:
                            logger.debug(f"Failed to parse email date: {e}")
                            continue
                    
                    if most_recent_date:
                        stats['last_synced_email_date'] = most_recent_date
                    else:
                        stats['last_synced_email_date'] = datetime.utcnow()
                except Exception as e:
                    logger.warning(f"Error determining last synced email date: {e}")
                    stats['last_synced_email_date'] = datetime.utcnow()
            else:
                # No new emails, but update timestamp to current time
                stats['last_synced_email_date'] = datetime.utcnow()
            
            return stats
            
        except Exception as e:
            logger.error(f"Date-filtered sync failed: {e}", exc_info=True)
            raise
    
    async def sync_all_users(self) -> Dict:
        """
        Sync all active users' emails
        
        Returns:
            Summary statistics
        """
        logger.info("Starting bulk sync for all users")
        
        with get_db_context() as db:
            users = db.query(User).filter(
                User.email_indexed == True,
                User.indexing_status == 'completed'
            ).all()
            
            results = {
                'total_users': len(users),
                'successful': 0,
                'failed': 0,
                'details': []
            }
            
            for user in users:
                try:
                    stats = await self.sync_user_emails(user.id)
                    if stats.get('status') != 'error':
                        results['successful'] += 1
                    else:
                        results['failed'] += 1
                    results['details'].append({
                        'user_id': user.id,
                        'email': user.email,
                        'stats': stats
                    })
                except Exception as e:
                    logger.error(f"Failed to sync user {user.id}: {e}")
                    results['failed'] += 1
                    results['details'].append({
                        'user_id': user.id,
                        'email': user.email,
                        'error': str(e)
                    })
            
            logger.info(f"Bulk sync completed: {results['successful']}/{results['total_users']} successful")
            return results
    
    @staticmethod
    async def start_periodic_sync(num_workers: int = 2):
        """
        Start background periodic sync workers
        
        Args:
            num_workers: Number of concurrent sync workers
        """
        sync_service = IncrementalEmailSync()
        sync_service.is_running = True
        
        logger.info(f"Starting periodic email sync (every {sync_service.sync_interval}s) with {num_workers} workers")
        
        while sync_service.is_running:
            try:
                # Run sync in background
                await sync_service.sync_all_users()
                
                # Wait before next sync
                await asyncio.sleep(sync_service.sync_interval)
                
            except KeyboardInterrupt:
                logger.info("Periodic sync stopped by user")
                sync_service.is_running = False
                break
            except Exception as e:
                logger.error(f"Periodic sync error: {e}", exc_info=True)
                # Wait shorter time on error before retry
                await asyncio.sleep(60)
        
        logger.info("Periodic sync service stopped")
    
    async def trigger_manual_sync(self, user_id: Optional[int] = None) -> Dict:
        """
        Manually trigger email sync for a user or all users
        
        Args:
            user_id: Specific user to sync (None = all users)
            
        Returns:
            Sync results
        """
        if user_id:
            return await self.sync_user_emails(user_id)
        else:
            return await self.sync_all_users()

