"""
Indexing-related Celery Tasks
Background tasks for intelligent email indexing and RAG operations using IntelligentEmailIndexer
"""
from typing import Dict, Any, Optional
from datetime import datetime
import asyncio
import os

from ..celery_app import celery_app
from ..base_task import LongRunningTask, IdempotentTask
from ...utils.logger import setup_logger
from ...database import get_db_context, User
from ...utils.config import load_config
from ...core.credential_provider import CredentialFactory

logger = setup_logger(__name__)

# Configuration constants
CALENDAR_INDEXING_CONFIG = {
    'DAYS_BACK': int(os.getenv('CALENDAR_DAYS_BACK', '180')),
    'DAYS_AHEAD': int(os.getenv('CALENDAR_DAYS_AHEAD', '365')),
    'MAX_EVENTS': int(os.getenv('CALENDAR_MAX_EVENTS', '500'))
}

SYNC_CONFIG = {
    'MIN_SYNC_INTERVAL_SECONDS': int(os.getenv('MIN_SYNC_INTERVAL_SECONDS', '300'))  # 5 minutes
}


@celery_app.task(base=LongRunningTask, bind=True)
def index_user_emails(
    self,
    user_id: str,
    batch_size: int = 300,
    max_emails: int = 5000,
    is_incremental: bool = False
) -> Dict[str, Any]:
    """
    Index emails using IntelligentEmailIndexer with advanced parsing
    
    New approach:
    - Uses IntelligentEmailIndexer for structured knowledge extraction
    - Graph-based relationships between entities
    - LLM-powered intent extraction
    - Specialized attachment parsing (Docling integration)
    - Dual indexing: Graph (structured) + Vector (semantic)
    
    Args:
        user_id: User ID
        batch_size: Initial batch size for indexing (default: 300)
        max_emails: Maximum number of emails to index (default: 5000)
        is_incremental: If True, only index emails since last sync
        
    Returns:
        Indexing results with performance metrics
    """
    
    async def _async_index_user_emails():
        start_time = datetime.utcnow()
        logger.info("="*60)
        logger.info(f"🚀 STARTING INTELLIGENT EMAIL INDEXING FOR USER {user_id}")
        logger.info(f"Mode: {'Incremental' if is_incremental else 'Full'}, Initial batch: {batch_size}")
        logger.info("="*60)
        
        try:
            from ...services.indexing.indexer import start_user_background_indexing
            
            # Use the new IntelligentEmailIndexer approach
            with get_db_context() as db:
                # Verify user exists
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    raise ValueError(f"User {user_id} not found")
                
                # Update indexing status
                user.indexing_status = 'in_progress'
                user.indexing_started_at = datetime.utcnow()
                db.commit()
            
            config = load_config()
            
            # Start intelligent indexing using the new approach
            logger.info(f"Starting IntelligentEmailIndexer for user {user_id} with batch_size={batch_size}")
            
            # Create indexer and run initial batch synchronously
            from ...services.indexing.indexer import IntelligentEmailIndexer
            from ...ai.rag import RAGEngine
            
            # Create RAG engine for this user
            rag_engine = RAGEngine(
                config=config,
                collection_name=f"user_{user_id}_emails"
            )
            
            # Get Gmail client through service layer
            from ...services.factory import ServiceFactory
            
            with get_db_context() as db:
                # Use ServiceFactory to create EmailService (handles credential loading)
                service_factory = ServiceFactory(config=config)
                email_service = service_factory.create_email_service(
                    user_id=int(user_id),
                    db_session=db
                )
                
                if not email_service or not email_service.gmail_client:
                    raise ValueError(f"Failed to create Gmail service for user {user_id}")
                
                # Access the underlying client from the service (needed for low-level API calls)
                google_client = email_service.gmail_client
            
            # Create indexer
            indexer = IntelligentEmailIndexer(
                config=config,
                rag_engine=rag_engine,
                google_client=google_client,
                user_id=int(user_id),
                collection_name=f"user_{user_id}_emails",
                use_knowledge_graph=True
            )
            
            # Determine query based on incremental mode
            if is_incremental:
                # Incremental mode: only index emails since last sync
                with get_db_context() as db:
                    user = db.query(User).filter(User.id == user_id).first()
                    if user and user.last_indexed_timestamp:
                        # Build date-filtered query
                        date_str = user.last_indexed_timestamp.strftime('%Y/%m/%d')
                        query = f"after:{date_str}"
                        logger.info(f"Incremental mode: indexing emails after {date_str}")
                    else:
                        # No last timestamp, start with recent emails (last 30 days)
                        from datetime import timedelta
                        date_str = (datetime.utcnow() - timedelta(days=30)).strftime('%Y/%m/%d')
                        query = f"after:{date_str}"
                        logger.info(f"Incremental mode: no last_indexed_timestamp, starting with emails after {date_str}")
            else:
                # Full mode: start with newer emails first (last 30 days, then expand)
                # This ensures recent emails are indexed before old ones
                from datetime import timedelta
                date_str = (datetime.utcnow() - timedelta(days=30)).strftime('%Y/%m/%d')
                query = f"after:{date_str}"
                logger.info(f"Full mode: starting with recent emails (after {date_str}), prioritizing newer emails")
            
            # Index emails in batches until we reach max_emails or run out of unindexed emails
            total_indexed = 0
            batch_number = 0
            
            logger.info(f"Starting batch indexing: batch_size={batch_size}, max_emails={max_emails}, query={query}")
            logger.info(f"Indexer created: rag_engine={indexer.rag_engine is not None}, google_client={indexer.google_client is not None}")
            
            # Skip initial sample check - it's slow and not necessary
            # Just start indexing directly
            logger.info(f"Skipping initial sample check - starting indexing directly")
            estimated_total = max_emails
            
            # Update initial progress
            with get_db_context() as db:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    user.indexing_status = 'in_progress'
                    user.indexing_started_at = datetime.utcnow()
                    user.indexing_progress_percent = 0.0
                    db.commit()
            
            # Continue indexing in batches until we reach max_emails or run out
            page_token = None  # Start with no pagination token
            max_batches = 1000  # Safety limit to prevent infinite loops
            consecutive_empty_batches = 0
            max_consecutive_empty = 3  # Stop after 3 consecutive empty batches
            
            while total_indexed < max_emails and batch_number < max_batches:
                batch_number += 1
                remaining = max_emails - total_indexed
                current_batch_size = min(batch_size, remaining)
                
                logger.info(f"Processing batch #{batch_number}: batch_size={current_batch_size}, total_indexed={total_indexed}/{max_emails}, page_token={'yes' if page_token else 'no'}, query={query[:50] if query else 'None'}...")
                
                try:
                    # For all batches, use the batch method (it handles pagination correctly)
                    # Pass the query so incremental mode continues with date filter
                    batch_indexed, next_page_token = await indexer._index_unindexed_emails_batch(
                        limit=current_batch_size, 
                        page_token=page_token,
                        query=query  # Pass the query so incremental mode continues with date filter
                    )
                    
                    if batch_indexed == 0:
                        consecutive_empty_batches += 1
                        logger.info(f"No more unindexed emails found in this batch (consecutive empty: {consecutive_empty_batches}).")
                        
                        # If we have a next page token, try the next page
                        if next_page_token:
                            logger.info(f"Trying next page with token...")
                            page_token = next_page_token
                            # Reset consecutive empty counter when we have a next page
                            consecutive_empty_batches = 0
                            continue
                        else:
                            logger.info(f"No more pages available. Stopping after {total_indexed} emails indexed.")
                            break
                    else:
                        # Reset consecutive empty counter on success
                        consecutive_empty_batches = 0
                    
                    total_indexed += batch_indexed
                    logger.info(f"Batch #{batch_number} completed: {batch_indexed} emails indexed (total: {total_indexed}/{max_emails})")
                    
                    # Update progress after each batch
                    progress_percent = min(100.0, (total_indexed / max_emails) * 100.0)
                    try:
                        with get_db_context() as db:
                            user = db.query(User).filter(User.id == user_id).first()
                            if user:
                                user.indexing_progress_percent = progress_percent
                                user.total_emails_indexed = total_indexed
                                db.commit()
                    except Exception as db_error:
                        logger.warning(f"Failed to update progress in database: {db_error}")
                    
                    # Update page token for next iteration
                    page_token = next_page_token
                    
                    # Stop if we've reached max_emails
                    if total_indexed >= max_emails:
                        logger.info(f"Reached max_emails limit ({max_emails}). Stopping.")
                        break
                    
                    # Stop if we've had too many consecutive empty batches
                    if consecutive_empty_batches >= max_consecutive_empty:
                        logger.info(f"Stopping after {max_consecutive_empty} consecutive empty batches.")
                        break
                    
                except Exception as batch_error:
                    logger.error(f"Error during batch #{batch_number} indexing: {batch_error}", exc_info=True)
                    consecutive_empty_batches += 1
                    
                    # Continue to next batch instead of failing completely
                    # But if we've indexed nothing and this is a critical error, fail the task
                    if total_indexed == 0 and batch_number == 1:
                        # First batch failed completely - this is critical
                        raise
                    
                    # Try next page if available, otherwise break
                    if page_token:
                        logger.info(f"Retrying with next page token after error...")
                        # Don't reset page_token - use it for retry
                        continue
                    else:
                        logger.warning(f"No page token available, stopping after error.")
                        break
            
            if batch_number >= max_batches:
                logger.warning(f"Reached maximum batch limit ({max_batches}), stopping to prevent infinite loop")
            
            indexing_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Update completion status - use single transaction for atomic update
            with get_db_context() as db:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    user.indexing_status = 'completed'
                    user.indexing_completed_at = datetime.utcnow()
                    user.last_indexed_timestamp = datetime.utcnow()
                    user.indexing_progress_percent = 100.0
                    user.initial_indexing_complete = True
                    user.total_emails_indexed = total_indexed
                    # Also update last_email_synced_at for consistency
                    user.last_email_synced_at = datetime.utcnow()
                    db.commit()
                    logger.info(f"Updated user {user_id} indexing status to completed")
            
            logger.info(f"Intelligent indexing completed for user {user_id}: {total_indexed} emails indexed in {indexing_time:.1f}s ({batch_number} batches)")
            
            return {
                'user_id': user_id,
                'status': 'completed',
                'emails_indexed': total_indexed,
                'batches_processed': batch_number,
                'completion_time': datetime.utcnow().isoformat(),
                'indexing_time_seconds': int(indexing_time),
                'indexer_type': 'IntelligentEmailIndexer',
                'features': [
                    'knowledge_graph',
                    'llm_intent_extraction', 
                    'specialized_attachment_parsing',
                    'dual_indexing'
                ]
            }
            
        except Exception as exc:
            logger.error(f"Intelligent email indexing failed for user {user_id}: {exc}", exc_info=True)
            
            # Update user indexing status to failed - ensure status is always updated
            try:
                with get_db_context() as db:
                    user = db.query(User).filter(User.id == user_id).first()
                    if user:
                        user.indexing_status = 'failed'
                        user.indexing_completed_at = datetime.utcnow()
                        # Don't reset progress - keep it for debugging
                        db.commit()
                        logger.info(f"Updated user {user_id} indexing status to failed")
            except Exception as db_error:
                logger.error(f"Failed to update user status in database: {db_error}", exc_info=True)
            
            return {
                'user_id': user_id,
                'status': 'failed',
                'error': str(exc),
                'completion_time': datetime.utcnow().isoformat(),
                'indexer_type': 'IntelligentEmailIndexer'
            }
    
    # Run the async function
    return asyncio.run(_async_index_user_emails())


@celery_app.task(base=LongRunningTask, bind=True)
def incremental_email_sync(
    self,
    user_id: str
) -> Dict[str, Any]:
    """
    Incrementally sync new emails for a user using IntelligentEmailIndexer
    
    This task should be run periodically to keep the email index up-to-date with new messages.
    Uses the new IntelligentEmailIndexer for better parsing and graph construction.
    
    Args:
        user_id: User ID
        
    Returns:
        Sync results with number of new emails indexed
    """
    import asyncio
    
    async def _async_incremental_sync():
        logger.info(f"Starting incremental email sync for user {user_id}")
        
        try:
            from ...services.incremental_sync import IncrementalEmailSync
            
            with get_db_context() as db:
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    raise ValueError(f"User {user_id} not found")
                
                if not user.initial_indexing_complete:
                    logger.info(f"Skipping incremental sync - initial indexing not complete for user {user_id}")
                    return {
                        'user_id': user_id,
                        'status': 'skipped',
                        'reason': 'initial_indexing_incomplete'
                    }
                
                if user.last_indexed_timestamp:
                    time_since_last_sync = datetime.utcnow() - user.last_indexed_timestamp
                    if time_since_last_sync.total_seconds() < SYNC_CONFIG['MIN_SYNC_INTERVAL_SECONDS']:
                        logger.info(f"Skipping incremental sync - last sync was {time_since_last_sync.total_seconds()}s ago")
                        return {
                            'user_id': user_id,
                            'status': 'skipped',
                            'reason': 'too_soon',
                            'seconds_since_last_sync': int(time_since_last_sync.total_seconds())
                        }
            
            # Use the new incremental sync service with IntelligentEmailIndexer
            sync_service = IncrementalEmailSync()
            result = await sync_service.sync_user_emails(user_id)
            
            logger.info(f"Incremental sync completed for user {user_id}: {result}")
            return result
            
        except Exception as exc:
            logger.error(f"Incremental email sync failed for user {user_id}: {exc}", exc_info=True)
            return {
                'user_id': user_id,
                'status': 'failed',
                'error': str(exc),
                'completion_time': datetime.utcnow().isoformat()
            }
    
    return asyncio.run(_async_incremental_sync())


@celery_app.task(base=IdempotentTask, bind=True)
def sync_all_users_emails(self) -> Dict[str, Any]:
    """
    Trigger incremental sync for all users who have completed initial indexing
    
    This task should be run periodically via Celery Beat
    
    Returns:
        Summary of sync tasks queued
    """
    logger.info("Starting batch incremental sync for all users")
    
    try:
        with get_db_context() as db:
            users = db.query(User).filter(
                (User.initial_indexing_complete == True) | (User.indexing_status == 'completed'),
                User.indexing_status != 'failed'
            ).all()
            
            synced_count = 0
            skipped_count = 0
            
            for user in users:
                try:
                    task = incremental_email_sync.delay(str(user.id))
                    logger.info(f"Queued incremental sync for user {user.id} (task: {task.id})")
                    synced_count += 1
                except Exception as e:
                    logger.error(f"Failed to queue sync for user {user.id}: {e}")
                    skipped_count += 1
            
            logger.info(f"Batch sync complete: {synced_count} queued, {skipped_count} skipped")
            
            return {
                'status': 'completed',
                'total_users': len(users),
                'synced': synced_count,
                'skipped': skipped_count,
                'timestamp': datetime.utcnow().isoformat()
            }
            
    except Exception as exc:
        logger.error(f"Batch incremental sync failed: {exc}")
        raise


@celery_app.task(base=IdempotentTask, bind=True)
def reindex_user_data(
    self,
    user_id: str,
    include_emails: bool = True,
    include_calendar: bool = True
) -> Dict[str, Any]:
    """
    Reindex all data for a user
    
    Args:
        user_id: User ID
        include_emails: Whether to reindex emails
        include_calendar: Whether to reindex calendar
        
    Returns:
        Reindexing results
    """
    logger.info(f"Starting full reindex for user {user_id}")
    
    results = {
        'user_id': user_id,
        'emails': None,
        'calendar': None,
        'status': 'completed'
    }
    
    try:
        if include_emails:
            # Queue email indexing
            email_task = index_user_emails.delay(user_id)
            results['emails'] = {
                'task_id': email_task.id,
                'status': 'queued'
            }
        
        if include_calendar:
            # Queue calendar indexing
            calendar_task = index_user_calendar.delay(user_id)
            results['calendar'] = {
                'task_id': calendar_task.id,
                'status': 'queued'
            }
        
        logger.info(f"Reindex tasks queued for user {user_id}")
        return results
        
    except Exception as exc:
        logger.error(f"Reindexing failed for user {user_id}: {exc}")
        raise


@celery_app.task(base=LongRunningTask, bind=True)
def index_user_calendar(self, user_id: str) -> Dict[str, Any]:
    """
    Index calendar events for a user in the vector store
    
    Args:
        user_id: User ID
        
    Returns:
        Indexing results
    """
    logger.info(f"Starting calendar indexing for user {user_id}")
    
    try:
        from ...ai.rag import RAGEngine
        from ...integrations.google_calendar.service import CalendarService
        
        # Use CredentialFactory for simplified credential loading
        with get_db_context() as db:
            # Verify user exists
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            # Create service using CredentialFactory
            config = load_config()
            factory = CredentialFactory(config)
            calendar_service = factory.create_service('calendar', user_id=user_id, db_session=db)
        
        # Use cached RAG engine from worker state
        from . import WorkerState
        rag_engine = WorkerState.get_rag_engine()
        
        # Get all calendar events using configurable date ranges
        events = calendar_service.list_events(
            days_back=CALENDAR_INDEXING_CONFIG['DAYS_BACK'], 
            days_ahead=CALENDAR_INDEXING_CONFIG['DAYS_AHEAD'], 
            max_results=CALENDAR_INDEXING_CONFIG['MAX_EVENTS']
        )
        
        indexed_count = 0
        failed_count = 0
        
        for event in events:
            try:
                # Extract event details
                event_id = event.get('id', '')
                summary = event.get('summary', '')
                description = event.get('description', '')
                location = event.get('location', '')
                start = event.get('start', {})
                end = event.get('end', {})
                
                # Build content from event details
                content_parts = [summary]
                if description:
                    content_parts.append(description)
                if location:
                    content_parts.append(f"Location: {location}")
                
                content = "\n\n".join(content_parts)
                
                # Index event with proper doc_id
                rag_engine.index_document(
                    doc_id=f"calendar_{user_id}_{event_id}",
                    content=content,
                    metadata={
                        'event_id': event_id,
                        'user_id': user_id,
                        'summary': summary,
                        'start': start,
                        'end': end,
                        'description': description,
                        'location': location,
                        'doc_type': 'calendar_event'
                    }
                )
                indexed_count += 1
                
            except Exception as exc:
                logger.warning(f"Failed to index event {event.get('id')}: {exc}")
                failed_count += 1
        
        logger.info(
            f"Calendar indexing completed for user {user_id}: "
            f"{indexed_count} indexed, {failed_count} failed"
        )
        
        return {
            'user_id': user_id,
            'total_events': len(events),
            'indexed': indexed_count,
            'failed': failed_count,
            'status': 'completed'
        }
        
    except Exception as exc:
        logger.error(f"Calendar indexing failed for user {user_id}: {exc}")
        raise


@celery_app.task(base=LongRunningTask, bind=True)
def rebuild_vector_store(self) -> Dict[str, Any]:
    """
    Rebuild the entire vector store from scratch
    
    Returns:
        Rebuild results
    """
    logger.info("Starting vector store rebuild")
    
    try:
        from ...ai.rag import RAGEngine
        from ...utils.config import load_config
        
        # Use cached RAG engine from worker state
        from . import WorkerState
        rag_engine = WorkerState.get_rag_engine()
        
        # Get all users with completed initial indexing
        with get_db_context() as db:
            users = db.query(User).filter(
                User.initial_indexing_complete == True,
                User.indexing_status.notin_(['failed', 'in_progress'])
            ).all()
            total_users = len(users)
        
        # Clear existing vector store
        rag_engine.clear()
        logger.info(f"Vector store cleared, rebuilding for {total_users} users")
        
        # Queue reindex for each user
        for i, user in enumerate(users):
            self.update_state(
                state='PROGRESS',
                meta={
                    'current': i,
                    'total': total_users,
                    'percent': (i / total_users) * 100,
                    'current_user': user.email
                }
            )
            
            reindex_user_data.delay(str(user.id))
        
        logger.info(f"Vector store rebuild queued for {total_users} users")
        
        return {
            'total_users': total_users,
            'status': 'completed',
            'completion_time': datetime.utcnow().isoformat()
        }
        
    except Exception as exc:
        logger.error(f"Vector store rebuild failed: {exc}")
        raise


@celery_app.task(base=IdempotentTask, bind=True)
def optimize_vector_store(self) -> Dict[str, Any]:
    """
    Optimize the vector store by removing duplicates and compacting
    
    Returns:
        Optimization results
    """
    logger.info("Starting vector store optimization")
    
    try:
        from ...ai.rag import RAGEngine
        from ...utils.config import load_config
        
        # Use cached RAG engine from worker state
        from . import WorkerState
        rag_engine = WorkerState.get_rag_engine()
        
        # Perform optimization based on vector store implementation
        try:
            result = rag_engine.optimize()
            optimization_details = result if isinstance(result, dict) else {'message': str(result)}
        except AttributeError:
            # Vector store doesn't have optimize method - perform basic cleanup
            logger.info("Vector store doesn't support optimization, performing basic maintenance")
            optimization_details = {
                'message': 'Basic maintenance completed - optimization not supported by current vector store',
                'action': 'maintenance_only'
            }
        except Exception as opt_error:
            logger.warning(f"Vector store optimization failed, continuing anyway: {opt_error}")
            optimization_details = {
                'message': f'Optimization failed: {str(opt_error)}',
                'action': 'failed'
            }
        
        logger.info("Vector store optimization completed")
        
        return {
            'status': 'completed',
            'completion_time': datetime.utcnow().isoformat(),
            'details': optimization_details
        }
        
    except Exception as exc:
        logger.error(f"Vector store optimization failed: {exc}")
        raise


@celery_app.task(base=IdempotentTask, bind=True)
def index_new_email_notification(
    self,
    user_id: str,
    history_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    resource_state: Optional[str] = None
) -> Dict[str, Any]:
    """
    Handle Gmail push notification and trigger immediate indexing of new emails
    
    This task is triggered when Gmail sends a push notification indicating
    that new emails have arrived. It fetches the new emails and indexes them
    immediately for real-time searchability.
    
    Args:
        user_id: User ID whose emails need to be indexed
        history_id: Gmail history ID (optional, used to fetch new emails)
        channel_id: Gmail watch channel ID (for logging)
        resource_state: Resource state from notification (e.g., 'add', 'sync')
    
    Returns:
        Dict with indexing results
    """
    logger.info("="*60)
    logger.info(f"📧 PROCESSING GMAIL PUSH NOTIFICATION FOR USER {user_id}")
    logger.info(f"History ID: {history_id}, Channel: {channel_id}, State: {resource_state}")
    logger.info("="*60)
    
    async def _async_index_new_emails():
        try:
            from ...services.indexing.indexer import IntelligentEmailIndexer
            from ...ai.rag import RAGEngine
            from ...utils.config import load_config
            from ...core.credential_provider import CredentialFactory
            from ...services.factory import ServiceFactory
            
            config = load_config()
            
            with get_db_context() as db:
                # Verify user exists
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    raise ValueError(f"User {user_id} not found")
                
                # Get user's Gmail credentials
                credential_provider = CredentialFactory.create_provider(
                    provider_type='google',
                    user_id=user_id
                )
                
                if not credential_provider or not credential_provider.has_credentials():
                    logger.warning(f"User {user_id} does not have Gmail credentials")
                    return {
                        'status': 'skipped',
                        'reason': 'no_credentials',
                        'user_id': user_id
                    }
                
                # Create Gmail client using ServiceFactory
                # ServiceFactory needs to be instantiated first
                service_factory = ServiceFactory(config=config)
                email_service = service_factory.create_email_service(
                    user_id=user_id,
                    db_session=db
                )
                
                if not email_service or not email_service.gmail_client:
                    logger.error(f"Failed to create Gmail client for user {user_id}")
                    return {
                        'status': 'error',
                        'reason': 'gmail_client_failed',
                        'user_id': user_id
                    }
                
                # Create RAG engine
                rag_engine = RAGEngine(
                    config=config,
                    collection_name=f"user_{user_id}_emails"
                )
                
                # Create indexer
                indexer = IntelligentEmailIndexer(
                    config=config,
                    rag_engine=rag_engine,
                    google_client=email_service.gmail_client,
                    user_id=user_id
                )
                
                # Fetch new emails since last indexed timestamp
                # Use a recent date filter to get only new emails
                last_indexed = user.last_indexed_timestamp
                if last_indexed:
                    # Query for emails after last indexed time
                    date_str = last_indexed.strftime('%Y/%m/%d')
                    query = f"in:inbox after:{date_str}"
                else:
                    # If no last_indexed timestamp, get emails from last 24 hours
                    from datetime import timedelta
                    date_str = (datetime.utcnow() - timedelta(days=1)).strftime('%Y/%m/%d')
                    query = f"in:inbox after:{date_str}"
                
                logger.info(f"Fetching new emails with query: {query}")
                
                # Get unindexed emails (this method filters out already-indexed emails)
                unindexed_emails, _ = await indexer._get_unindexed_emails(
                    query=query,
                    max_results=50  # Limit to 50 for real-time indexing
                )
                
                if not unindexed_emails:
                    logger.info("No new unindexed emails found")
                    return {
                        'status': 'completed',
                        'emails_indexed': 0,
                        'user_id': user_id,
                        'message': 'No new emails to index'
                    }
                
                logger.info(f"Found {len(unindexed_emails)} new emails to index")
                
                # Index each email
                indexed_count = 0
                failed_count = 0
                
                for email_data in unindexed_emails:
                    try:
                        await indexer.index_email(email_data)
                        indexed_count += 1
                        logger.debug(f"✅ Indexed email: {email_data.get('id', 'unknown')}")
                    except Exception as e:
                        failed_count += 1
                        logger.error(
                            f"❌ Failed to index email {email_data.get('id', 'unknown')}: {e}",
                            exc_info=True
                        )
                
                # Update user's last_indexed_timestamp
                with get_db_context() as db_update:
                    user_update = db_update.query(User).filter(User.id == user_id).first()
                    if user_update:
                        user_update.last_indexed_timestamp = datetime.utcnow()
                        user_update.total_emails_indexed = (
                            (user_update.total_emails_indexed or 0) + indexed_count
                        )
                        db_update.commit()
                
                logger.info(
                    f"✅ Real-time indexing completed: "
                    f"{indexed_count} indexed, {failed_count} failed"
                )
                
                return {
                    'status': 'completed',
                    'emails_indexed': indexed_count,
                    'emails_failed': failed_count,
                    'user_id': user_id,
                    'timestamp': datetime.utcnow().isoformat()
                }
                
        except Exception as e:
            logger.error(f"❌ Error in real-time email indexing: {e}", exc_info=True)
            return {
                'status': 'error',
                'error': str(e),
                'user_id': user_id
            }
    
    # Run async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(_async_index_new_emails())
        return result
    finally:
        loop.close()