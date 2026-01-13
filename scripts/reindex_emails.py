#!/usr/bin/env python3
"""
Email Re-Indexing Script

This script clears and re-indexes emails to fix missing metadata in the vector store.
The fix in rag_graph_bridge.py ensures new emails get proper metadata fields like:
- is_unread, email_id, timestamp, labels, thread_id, has_attachments, folder

Usage:
    python scripts/reindex_emails.py [--user-id USER_ID] [--days DAYS]
    
Options:
    --user-id: User ID to re-index (default: all users with email tokens)
    --days: Number of days of emails to re-index (default: 30)
    --clear-only: Only reset indexing state, let natural sync handle re-indexing
"""
import asyncio
import argparse
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.config import load_config
from src.utils.logger import setup_logger
from src.database import get_db_context
from src.database.models import User, Session
from sqlalchemy import select

logger = setup_logger(__name__)


async def clear_email_documents(rag_engine, user_id: int = None):
    """Clear existing email documents from vector store by resetting user indexing state."""
    logger.info(f"Clearing email indexing state...")
    
    try:
        # Get stats before
        stats_before = rag_engine.get_stats()
        total_before = stats_before.get('total_documents', 'unknown')
        logger.info(f"Documents before clearing: {total_before}")
        
        # Reset the user's last_indexed_timestamp to force re-indexing
        with get_db_context() as db:
            if user_id:
                result = db.execute(select(User).where(User.id == user_id))
                users = [result.scalars().first()]
            else:
                result = db.execute(select(User))
                users = result.scalars().all()
            
            count = 0
            for user in users:
                if user:
                    # Reset the last_indexed_timestamp to force re-indexing
                    user.last_indexed_timestamp = None
                    user.total_emails_indexed = 0
                    user.initial_indexing_complete = False
                    logger.info(f"Reset indexing state for user {user.id} ({user.email})")
                    count += 1
                    
            db.commit()
            
        logger.info(f"✅ Cleared indexing state for {count} users")
        return True
        
    except Exception as e:
        logger.error(f"Failed to clear email indexing state: {e}", exc_info=True)
        return False


async def trigger_email_reindex(config, user_id: int, days: int = 30):
    """Trigger email re-indexing for a user."""
    from src.ai.rag import RAGEngine
    from src.services.indexing.crawlers.email import EmailCrawler
    from src.core.email.google_client import GoogleGmailClient
    
    logger.info(f"Starting email re-index for user {user_id} (last {days} days)...")
    
    try:
        # Get RAG engine
        try:
            from api.dependencies import AppState
            rag_engine = AppState.get_rag_engine()
        except:
            rag_engine = None
            
        if not rag_engine:
            rag_engine = RAGEngine(config)
            
        # Get user's Gmail credentials from Session
        with get_db_context() as db:
            result = db.execute(
                select(Session)
                .where(Session.user_id == user_id)
                .where(Session.gmail_access_token.isnot(None))
                .order_by(Session.last_active_at.desc())
                .limit(1)
            )
            session = result.scalars().first()
            
            if not session or not session.gmail_access_token:
                logger.warning(f"No Gmail token found for user {user_id}")
                return False
                
            # Initialize Gmail client
            credentials = {
                'token': session.gmail_access_token,
                'refresh_token': session.gmail_refresh_token,
                'token_uri': 'https://oauth2.googleapis.com/token',
                'client_id': config.google.client_id,
                'client_secret': config.google.client_secret,
            }
            
        google_client = GoogleGmailClient(credentials)
        
        if not google_client.is_available():
            logger.error(f"Gmail client not available for user {user_id}")
            return False
            
        # Initialize EmailCrawler
        crawler = EmailCrawler(
            config=config,
            user_id=user_id,
            rag_engine=rag_engine,
            google_client=google_client
        )
        
        # Override initial indexing days
        crawler.INITIAL_INDEXING_DAYS = days
        
        # Run sync cycle
        logger.info(f"Running email crawler sync cycle for user {user_id}...")
        count = await crawler.run_sync_cycle()
        
        logger.info(f"✅ Re-indexed {count} emails for user {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to re-index emails for user {user_id}: {e}", exc_info=True)
        return False


async def main():
    parser = argparse.ArgumentParser(description='Re-index emails with fixed metadata')
    parser.add_argument('--user-id', type=int, help='User ID to re-index (default: all users)')
    parser.add_argument('--days', type=int, default=30, help='Days of emails to re-index (default: 30)')
    parser.add_argument('--clear-only', action='store_true', help='Only clear state, do not re-index')
    args = parser.parse_args()
    
    config = load_config()
    
    print("=" * 60)
    print("Email Re-Indexing Script")
    print("=" * 60)
    print(f"Target user ID: {args.user_id or 'all users'}")
    print(f"Days to re-index: {args.days}")
    print()
    
    # Step 1: Clear existing indexing state
    from src.ai.rag import RAGEngine
    rag_engine = RAGEngine(config)
    
    await clear_email_documents(rag_engine, args.user_id)
    
    if args.clear_only:
        print("\n✅ Cleared indexing state. Emails will be re-indexed on next server request.")
        print("   Restart the server and send a message to trigger re-indexing.")
        return
    
    # Step 2: Get users to re-index
    with get_db_context() as db:
        if args.user_id:
            result = db.execute(select(User).where(User.id == args.user_id))
            users = [result.scalars().first()]
        else:
            # Get users with Gmail tokens
            result = db.execute(
                select(User)
                .join(Session, User.id == Session.user_id)
                .where(Session.gmail_access_token.isnot(None))
                .distinct()
            )
            users = result.scalars().all()
    
    if not users or not users[0]:
        print("No users found to re-index")
        return
        
    print(f"\nFound {len(users)} users to re-index")
    
    # Step 3: Re-index each user
    success_count = 0
    for user in users:
        if user:
            print(f"\n→ Processing user {user.id} ({user.email})...")
            success = await trigger_email_reindex(config, user.id, args.days)
            if success:
                success_count += 1
    
    print("\n" + "=" * 60)
    print(f"✅ Re-indexing complete: {success_count}/{len(users)} users")
    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())
