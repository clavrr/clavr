"""
Smart Indexing Module - Optimized Email Indexing with Hybrid GraphRAG

This module extends IntelligentEmailIndexer with smart indexing capabilities:
- Timestamp-based filtering (no re-indexing old emails)
- New user optimization (last 30 days only)
- Incremental indexing for existing users
- Batch operations for efficiency
- Full integration with Hybrid GraphRAG (Pinecone + Neo4j)

Architecture:
- Uses HybridIndexCoordinator for dual indexing (vector + graph)
- Chunks documents before embedding (matches screenshot pattern)
- Links all chunks to Neo4j nodes via node_id

Version: 2.0.0
Date: November 18, 2025
"""
import os
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Set, Optional

from google.oauth2.credentials import Credentials

from ...utils.logger import setup_logger
from ...utils.config import Config, load_config
from ...database.models import User

logger = setup_logger(__name__)


class SmartIndexingMixin:
    """
    Mixin to add smart indexing capabilities to IntelligentEmailIndexer.
    
    Usage:
        class IntelligentEmailIndexer(SmartIndexingMixin, BaseIndexer):
            pass
    """
    
    async def start_smart_indexing(self, db_session):
        """
        Start smart indexing based on user state.
        
        Args:
            db_session: Database session for user metadata access (REQUIRED)
            
        Raises:
            ValueError: If user_id or db_session is not provided
        """
        if not self.user_id:
            raise ValueError("Smart indexing requires user_id")
        
        if not db_session:
            raise ValueError("Smart indexing requires db_session for user metadata")
        
        # Load user metadata
        user = db_session.query(User).filter(User.id == self.user_id).first()
        if not user:
            raise ValueError(f"User {self.user_id} not found in database")
        
        self.user = user
        self.db_session = db_session
        self.is_running = True
        
        # Determine indexing strategy
        if not user.initial_indexing_complete:
            # NEW USER: Smart initial indexing
            logger.info(f"New user detected: {user.email}")
            await self._smart_initial_indexing()
        elif user.last_indexed_timestamp:
            # EXISTING USER: Incremental indexing
            logger.info(f"Existing user: {user.email}, last indexed {user.last_indexed_timestamp}")
            await self._smart_incremental_indexing()
        else:
            # User exists but no timestamp (initial setup)
            logger.info(f"Setting up initial indexing for: {user.email}")
            await self._smart_initial_indexing()
        
        # Start periodic loops
        self._task = asyncio.create_task(self._smart_indexing_loop())
        self._inbox_task = asyncio.create_task(self._smart_inbox_loop())
        
        logger.info("Smart indexing started")
    
    async def _smart_initial_indexing(self):
        """
        Smart initial indexing for new users.
        
        Strategy:
        1. Index last 30 days only (most relevant)
        2. Prioritize: inbox → sent → important → starred
        3. Mark initial_indexing_complete when done
        """
        # Calculate date range
        days_to_index = 30  # Configurable via user settings
        start_date = datetime.now() - timedelta(days=days_to_index)
        date_str = start_date.strftime('%Y/%m/%d')
        
        logger.info(f"Indexing last {days_to_index} days (from {date_str})")
        
        # Priority folders with time filter
        priority_queries = [
            ("inbox", f"in:inbox newer_than:{days_to_index}d"),
            ("sent", f"in:sent newer_than:{days_to_index}d"),
            ("important", f"is:important newer_than:{days_to_index}d"),
            ("starred", f"is:starred newer_than:{days_to_index}d"),
        ]
        
        total_indexed = 0
        
        for folder_name, query in priority_queries:
            try:
                logger.info(f"Indexing {folder_name}...")
                count = await self._index_by_query(query, max_results=200)
                total_indexed += count
                logger.info(f"{folder_name}: {count} emails indexed")
                
            except Exception as e:
                logger.error(f"Error indexing {folder_name}: {e}")
        
        # Update user metadata
        self.user.initial_indexing_complete = True
        self.user.last_indexed_timestamp = datetime.now()
        self.user.total_emails_indexed = total_indexed
        self.user.indexing_date_range_start = start_date
        self.user.indexing_status = 'active'
        self.user.indexing_progress_percent = 100.0
        self.db_session.commit()
        
        logger.info(f"Initial indexing complete: {total_indexed} emails from last {days_to_index} days")
    
    async def _smart_incremental_indexing(self):
        """
        Incremental indexing for existing users.
        
        Only fetches emails newer than last_indexed_timestamp.
        """
        if not self.user.last_indexed_timestamp:
            logger.warning("No last_indexed_timestamp, falling back to initial indexing")
            return await self._smart_initial_indexing()
        
        # Build time-filtered query
        last_indexed = self.user.last_indexed_timestamp
        date_str = last_indexed.strftime('%Y/%m/%d')
        query = f"after:{date_str}"
        
        logger.info(f"Incremental indexing: emails after {date_str}")
        
        try:
            count = await self._index_by_query(query, max_results=500)
            
            if count > 0:
                # Update metadata
                self.user.last_indexed_timestamp = datetime.now()
                self.user.total_emails_indexed += count
                self.db_session.commit()
                logger.info(f"Incremental indexing complete: {count} new emails")
            else:
                logger.info("No new emails to index")
                
        except Exception as e:
            logger.error(f"Error in incremental indexing: {e}")
    
    async def _index_by_query(
        self,
        query: str,
        max_results: int = 100
    ) -> int:
        """
        Index emails matching a Gmail query.
        
        Optimized flow:
        1. List message IDs from Gmail
        2. Batch check which are already indexed
        3. Batch fetch only unindexed messages
        4. Index each email
        
        Returns:
            Number of emails successfully indexed
        """
        if not self.google_client or not self.google_client.is_available():
            return 0
        
        try:
            # Step 1: List message IDs
            results = self.google_client.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            if not messages:
                return 0
            
            logger.debug(f"Gmail returned {len(messages)} messages for query: {query}")
            
            # Step 2: Extract IDs and batch check indexed status
            message_ids = [msg['id'] for msg in messages]
            already_indexed = await self._batch_check_indexed(message_ids)
            unindexed_ids = [mid for mid in message_ids if mid not in already_indexed]
            
            if not unindexed_ids:
                logger.debug("All emails already indexed")
                return 0
            
            logger.info(f"Fetching {len(unindexed_ids)} new emails (skipped {len(already_indexed)} already indexed)")
            
            # Step 3: Batch fetch full messages
            emails = await self._batch_fetch_messages(unindexed_ids)
            
            # Step 4: Index each email
            indexed_count = 0
            for email in emails:
                try:
                    success = await self.index_email(email)
                    if success:
                        indexed_count += 1
                    await asyncio.sleep(self.rate_limit_delay)
                except Exception as e:
                    logger.error(f"Error indexing email {email.get('id', 'unknown')}: {e}")
            
            return indexed_count
            
        except Exception as e:
            logger.error(f"Error in _index_by_query: {e}")
            return 0
    
    async def _batch_check_indexed(self, message_ids: List[str]) -> Set[str]:
        """
        Batch check which messages are already indexed.
        
        Much more efficient than individual checks.
        Uses the same document ID format as EmailParser: Email_{hash}
        """
        if not message_ids:
            return set()
        
        indexed = set()
        
        # Convert message IDs to document IDs using the same format as EmailParser
        # Emails are stored as chunks (Email_{hash}_chunk_0, etc.), so we check for the first chunk
        import hashlib
        doc_ids = []
        msg_id_to_doc_id = {}
        for msg_id in message_ids:
            hash_obj = hashlib.md5(msg_id.encode())
            short_hash = hash_obj.hexdigest()[:12]
            base_doc_id = f"Email_{short_hash}"
            # Check for first chunk (emails are stored as chunks)
            first_chunk_id = f"{base_doc_id}_chunk_0"
            doc_ids.append(first_chunk_id)
            msg_id_to_doc_id[msg_id] = first_chunk_id
        
        # Try batch method if available
        if hasattr(self.rag_engine.vector_store, 'batch_document_exists'):
            try:
                import time
                batch_start = time.time()
                logger.info(f"Using batch_document_exists for {len(doc_ids)} documents...")
                
                # Pinecone batch fetch supports up to 1000 IDs, so we can do it in one call
                indexed_doc_ids = await asyncio.to_thread(
                    self.rag_engine.vector_store.batch_document_exists,
                    doc_ids
                )
                batch_time = time.time() - batch_start
                logger.info(f"Batch check returned {len(indexed_doc_ids)} indexed documents in {batch_time:.2f}s")
                
                # Convert back to message IDs
                for msg_id, doc_id in msg_id_to_doc_id.items():
                    if doc_id in indexed_doc_ids:
                        indexed.add(msg_id)
                logger.info(f"Batch check complete: {len(indexed)}/{len(message_ids)} emails already indexed")
                return indexed
            except Exception as e:
                logger.error(f"Batch check failed: {e}", exc_info=True)
                logger.warning(f"Falling back to individual checks (this will be slow)...")
        
        # Fallback: check individually
        for msg_id, doc_id in msg_id_to_doc_id.items():
            try:
                if self.rag_engine.vector_store.document_exists(doc_id):
                    indexed.add(msg_id)
            except Exception as e:
                logger.error(f"Error checking if {msg_id} (doc_id: {doc_id}) exists: {e}")
        
        return indexed
    
    async def _batch_fetch_messages(self, message_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Batch fetch full message details from Gmail.
        
        Uses Gmail batch API for efficiency.
        """
        if not message_ids:
            return []
        
        try:
            # Use existing batch method if available
            if hasattr(self.google_client, '_batch_get_messages_with_retry'):
                messages = self.google_client._batch_get_messages_with_retry(
                    message_ids=message_ids,
                    format='full'
                )
            else:
                # Fallback: fetch individually
                messages = []
                for msg_id in message_ids:
                    msg = self.google_client.service.users().messages().get(
                        userId='me',
                        id=msg_id,
                        format='full'
                    ).execute()
                    messages.append(msg)
            
            # Parse messages - use the indexer's parse method if available
            parsed_emails = []
            for msg in messages:
                try:
                    # Check if _parse_gmail_message exists (from IntelligentEmailIndexer)
                    if hasattr(self, '_parse_gmail_message'):
                        email_data = self._parse_gmail_message(msg)
                    else:
                        # Fallback: basic parsing
                        headers = {h['name'].lower(): h['value'] for h in msg.get('payload', {}).get('headers', [])}
                        email_data = {
                            'id': msg.get('id', ''),
                            'threadId': msg.get('threadId', ''),
                            'subject': headers.get('subject', ''),
                            'sender': headers.get('from', ''),
                            'to': headers.get('to', ''),
                            'date': headers.get('date', ''),
                            'body': '',  # Would need to extract from payload
                            'labels': msg.get('labelIds', []),
                            'has_attachments': False,  # Would need to check payload
                            'folder': 'inbox'
                        }
                    parsed_emails.append(email_data)
                except Exception as e:
                    logger.error(f"Error parsing message: {e}")
            
            return parsed_emails
            
        except Exception as e:
            logger.error(f"Error batch fetching messages: {e}")
            return []
    
    async def _smart_indexing_loop(self):
        """
        Smart main indexing loop - incremental updates only.
        
        Continuously checks for new emails using timestamp-based queries.
        """
        while self.is_running:
            try:
                await self._smart_incremental_indexing()
                await asyncio.sleep(self.indexing_interval)
                
            except asyncio.CancelledError:
                logger.info("Smart indexing loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in smart indexing loop: {e}")
                await asyncio.sleep(60)
    
    async def _smart_inbox_loop(self):
        """
        Smart inbox indexing loop.
        
        Only checks for emails after last indexed timestamp.
        """
        await asyncio.sleep(5)  # Initial delay
        
        while self.is_running:
            try:
                # Time-filtered inbox query
                last_indexed = self.user.last_indexed_timestamp
                date_str = last_indexed.strftime('%Y/%m/%d')
                query = f"in:inbox after:{date_str}"
                
                count = await self._index_by_query(query, max_results=50)
                
                if count > 0:
                    # Update timestamp
                    self.user.last_indexed_timestamp = datetime.now()
                    self.user.total_emails_indexed += count
                    self.db_session.commit()
                    logger.info(f"Inbox: {count} new emails indexed")
                
                await asyncio.sleep(self.inbox_interval)
                
            except asyncio.CancelledError:
                logger.info("Smart inbox loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in smart inbox loop: {e}")
                await asyncio.sleep(30)


async def start_smart_user_indexing(
    user_id: int,
    access_token: str,
    refresh_token: Optional[str] = None,
    config: Optional[Config] = None,
    db_session = None
):
    """
    Start smart background indexing for a user with Hybrid GraphRAG.
    
    This is the recommended entry point for new implementations.
    
    Architecture:
    - Pinecone (Vector DB) for semantic search
    - Neo4j (Graph DB) for relational reasoning
    - Chunks all content before embedding
    - Links chunks to graph nodes via node_id
    
    Args:
        user_id: User ID
        access_token: Gmail OAuth access token
        refresh_token: Gmail OAuth refresh token
        config: Configuration object
        db_session: Database session for user metadata
        
    Raises:
        ValueError: If required OAuth credentials are missing
    """
    from .indexer import IntelligentEmailIndexer
    from ...core.email.google_client import GoogleGmailClient
    from ...ai.rag import RAGEngine
    
    # Load config
    config = config or load_config("config/config.yaml")
    
    # Get OAuth credentials from environment
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    
    if not client_id or not client_secret:
        raise ValueError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in environment variables"
        )
    
    # Create Gmail client with OAuth credentials
    credentials = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )
    
    google_client = GoogleGmailClient(config=config, credentials=credentials)
    
    # Create RAG engine for user's collection (Pinecone primary, PostgreSQL fallback)
    collection_name = f"user_{user_id}_emails"
    rag_engine = RAGEngine(config, collection_name=collection_name)
    
    # Create indexer with Hybrid GraphRAG capabilities
    # This automatically initializes:
    # - EmailParser for NER-like entity extraction
    # - HybridIndexCoordinator for graph + vector indexing
    # - Knowledge graph with Neo4j backend
    indexer = IntelligentEmailIndexer(
        config=config,
        rag_engine=rag_engine,
        google_client=google_client,
        llm_client=None,  # Will be created internally
        user_id=user_id,
        collection_name=collection_name,
        use_knowledge_graph=True  # Enable Pinecone + Neo4j hybrid mode
    )
    
    # Start smart indexing with timestamp-based optimization
    await indexer.start_smart_indexing(db_session=db_session)
    
    logger.info(
        f"Smart indexing started for user {user_id} "
        f"(Hybrid GraphRAG: Pinecone + Neo4j)"
    )
