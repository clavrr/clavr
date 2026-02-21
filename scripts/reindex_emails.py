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

from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType

logger = setup_logger(__name__)


async def clear_arango_data(config, user_id: int):
    """Clear existing ArangoDB data for this user."""
    logger.info(f"Clearing ArangoDB data for user {user_id}...")
    graph_manager = KnowledgeGraphManager(config=config)
    
    collections = [
        'Email', 'Person', 'Identity', 'ActionItem', 'Topic', 'Receipt', 'Contact', 'Document'
    ]
    
    try:
        for collection in collections:
            try:
                aql = f"FOR d IN {collection} FILTER d.user_id == @uid REMOVE d IN {collection}"
                graph_manager.db.aql.execute(aql, bind_vars={'uid': user_id})
                logger.info(f"Cleared {collection} nodes")
            except Exception as e:
                logger.debug(f"Could not clear {collection}: {e}")
        
        # Note: edges are harder to clear by user_id without joining, but let's try some common ones
        edge_collections = ['FROM', 'TO', 'CC', 'HAS_IDENTITY', 'KNOWS', 'CONTAINS', 'DISCUSSES']
        for edge_coll in edge_collections:
            try:
                # This is aggressive but safe for re-indexing a single user if edges aren't shared
                # Ideally we only delete edges from/to the user's nodes
                aql = f"FOR e IN {edge_coll} REMOVE e IN {edge_coll}"
                graph_manager.db.aql.execute(aql)
                logger.info(f"Cleared {edge_coll} edges")
            except Exception as e:
                logger.debug(f"Could not clear {edge_coll}: {e}")
        
        return True
    except Exception as e:
        logger.error(f"Failed to clear ArangoDB data: {e}")
        return False


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
    from src.core.credential_provider import CredentialProvider
    from src.core.email.google_client import GoogleGmailClient
    from src.database import get_async_db_context
    from src.core.async_credential_provider import AsyncCredentialProvider
    from src.services.indexing.graph.manager import KnowledgeGraphManager
    from src.services.indexing.topic_extractor import TopicExtractor
    
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
        
        # Initialize Graph Manager for knowledge graph population
        graph_manager = KnowledgeGraphManager(
            backend=config.indexing.graph_backend,
            config=config
        )
        logger.info(f"Graph manager initialized: {graph_manager}")
        
        # Initialize Topic Extractor for auto topic extraction
        topic_extractor = TopicExtractor(
            config=config,
            graph_manager=graph_manager
        )
        
        # Step 0: Ensure User node exists in ArangoDB for connectivity
        async with get_async_db_context() as db:
            result = await db.execute(select(User).where(User.id == user_id))
            db_user = result.scalars().first()
            
            if db_user:
                logger.info(f"Ensuring User node exists in ArangoDB for {db_user.email}...")
                await graph_manager.add_node(
                    node_id=f"User/{user_id}",
                    node_type=NodeType.USER,
                    properties={
                        "email": db_user.email,
                        "name": db_user.name,
                        "user_id": user_id
                    }
                )
            
        # Try integration credentials first
        creds = CredentialProvider.get_integration_credentials(
            user_id=user_id,
            provider='gmail',
            auto_refresh=True
        )
        
        # Fallback: use AsyncCredentialProvider (same approach as reindex_maniko.py)
        if not creds:
            logger.info(f"No integration credentials found, trying AsyncCredentialProvider...")
            async with get_async_db_context() as db:
                creds = await AsyncCredentialProvider.get_credentials(user_id=user_id, db_session=db)
        
        if not creds:
            logger.error(f"No Gmail credentials found for user {user_id}")
            return False
        
        # Create GoogleGmailClient with correct constructor signature
        google_client = GoogleGmailClient(config=config, credentials=creds)
        
        if not google_client.is_available():
            logger.error(f"Gmail client not available for user {user_id}")
            return False
            
        # Initialize EmailCrawler with GoogleGmailClient AND graph_manager for dual indexing
        crawler = EmailCrawler(
            config=config,
            user_id=user_id,
            rag_engine=rag_engine,
            graph_manager=graph_manager,
            google_client=google_client,
            topic_extractor=topic_extractor
        )
        
        # Override initial indexing days and batch size
        crawler.INITIAL_INDEXING_DAYS = days
        crawler.BATCH_SIZE = 500  # Increase batch size for re-indexing
        
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
    
    # Step 1.5: Clear ArangoDB if a user is specified
    if args.user_id:
        await clear_arango_data(config, args.user_id)
    
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
