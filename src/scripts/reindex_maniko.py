import asyncio
import sys
import logging
import os
from datetime import datetime, timedelta

# Setup path to include src
sys.path.append(os.getcwd())

from src.database import get_async_db_context
from src.database.models import User, UserIntegration
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.ai.rag.core.rag_engine import RAGEngine
from src.utils.config import Config, load_config
from src.services.indexing.crawlers.email import EmailCrawler
from src.core.credential_provider import CredentialProvider
from src.core import GoogleGmailClient
from sqlalchemy import select, update
from src.services.indexing.topic_extractor import TopicExtractor
from src.ai.llm_factory import LLMFactory

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

async def reindex_maniko():
    """
    Script to trigger a full re-index for maniko@clavr.me (User ID 7).
    """
    user_id = 7
    email = "maniko@clavr.me"
    
    logger.info(f"Starting full re-index for {email} (User {user_id})...")
    
    config = load_config()
    graph_manager = KnowledgeGraphManager(config=config)
    rag_engine = RAGEngine(config)
    
    # 1. Reset Postgres State
    logger.info("Step 1: Resetting index state in Postgres...")
    async with get_async_db_context() as db:
        stmt = update(User).where(User.id == user_id).values(
            last_indexed_timestamp=None,
            initial_indexing_complete=False,
            total_emails_indexed=0
        )
        await db.execute(stmt)
        await db.commit()
    logger.info("Postgres state reset.")

    # 2. Clear existing ArangoDB data for this user
    logger.info("Step 2: Clearing existing ArangoDB graph data...")
    # Clean up both correct user_id (7) and legacy/incorrect user_id (3)
    user_ids_to_clean = [user_id, 3]
    
    # Collections to clear for full graph rebuild with new relationships
    collections_to_clear = [
        'Email',
        'Person', 
        'Identity',
        'ActionItem',
        'Topic',
        'Receipt',
        'Contact'
    ]
    
    try:
        # Clear nodes from each collection
        for collection in collections_to_clear:
            try:
                # Try to clear by user_id first
                aql_delete = f"FOR d IN {collection} FILTER d.user_id IN @user_ids REMOVE d IN {collection}"
                graph_manager.db.aql.execute(aql_delete, bind_vars={'user_ids': user_ids_to_clean})
                logger.info(f"Cleared {collection} nodes for users {user_ids_to_clean}")
            except Exception as e:
                # If collection doesn't exist or has different structure, skip
                logger.debug(f"Could not clear {collection}: {e}")
        
        # Also clean up edges that reference these nodes
        edge_collections = ['FROM', 'TO', 'CC', 'HAS_IDENTITY', 'KNOWS', 'CONTAINS', 'DISCUSSES']
        for edge_coll in edge_collections:
            try:
                # Delete orphaned edges
                aql_delete_edges = f"FOR e IN {edge_coll} REMOVE e IN {edge_coll}"
                graph_manager.db.aql.execute(aql_delete_edges)
                logger.info(f"Cleared {edge_coll} edge collection")
            except Exception as e:
                logger.debug(f"Could not clear {edge_coll} edges: {e}")
        
        logger.info(f"ArangoDB graph data cleared for users {user_ids_to_clean}.")
    except Exception as e:
        logger.error(f"ArangoDB clear failed: {e}")

    # 3. Clear existing Qdrant data for this user
    logger.info("Step 3: Clearing existing Qdrant data for this user...")
    if hasattr(rag_engine.vector_store, 'client'): 
        try:
            from qdrant_client.http import models
            client = rag_engine.vector_store.client
            collection_name = rag_engine.vector_store.collection_name or 'email-knowledge'
            
            # Ensure indices exist (CRITICAL for filtering)
            for field, schema in [
                ("user_id", models.PayloadSchemaType.INTEGER),
                ("sender", models.PayloadSchemaType.TEXT),
                ("doc_type", models.PayloadSchemaType.KEYWORD),
                ("subject", models.PayloadSchemaType.TEXT),
                ("content", models.PayloadSchemaType.TEXT)
            ]:
                try:
                    client.create_payload_index(
                        collection_name=collection_name,
                        field_name=field,
                        field_schema=schema
                    )
                    logger.info(f"Qdrant: Created '{field}' index.")
                except Exception as e:
                    logger.debug(f"Index creation for {field} status: {e}")

            client.delete(
                collection_name=collection_name,
                points_selector=models.Filter(
                    should=[
                        models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
                        models.FieldCondition(key="user_id", match=models.MatchValue(value=3)),
                        models.FieldCondition(key="sender_email", match=models.MatchValue(value=email)),
                        # CRITICAL: Clean "ghost" data with missing user_id (found in verification)
                        models.FieldCondition(key="doc_type", match=models.MatchValue(value="email")),
                        models.FieldCondition(key="doc_type", match=models.MatchValue(value="document")),
                        models.FieldCondition(key="doc_type", match=models.MatchValue(value="attachment"))
                    ]
                )
            )
            logger.info(f"Qdrant data cleared for user_ids {user_ids_to_clean}, email {email}, and all doc_type=email/document.")
        except Exception as e:
            logger.error(f"Qdrant clear failed: {e}")

    # 4. Trigger Sync
    logger.info("Step 4: Triggering EmailCrawler sync...")
    try:
        async with get_async_db_context() as db:
            # Manually fetch since AsyncCredentialProvider might look for 'google' instead of 'gmail'
            stmt = select(UserIntegration).where(
                UserIntegration.user_id == user_id,
                UserIntegration.provider == 'gmail'
            )
            res = await db.execute(stmt)
            integration = res.scalars().first()
            
            if not integration:
                logger.error(f"No Gmail integration found for user {user_id}. Trying 'google'...")
                stmt = select(UserIntegration).where(
                    UserIntegration.user_id == user_id,
                    UserIntegration.provider == 'google'
                )
                res = await db.execute(stmt)
                integration = res.scalars().first()

            if not integration:
                logger.error("Could not find any Google/Gmail integration for user. Skipping sync.")
                return

            # Helper to get valid creds
            from src.core.async_credential_provider import AsyncCredentialProvider
            creds = await AsyncCredentialProvider.get_credentials(user_id=user_id, db_session=db)
            
            if not creds:
                # Manual credential building if provider name was the issue
                from google.oauth2.credentials import Credentials
                from src.utils.encryption import decrypt_token
                
                # Get scopes from integration or default to all
                scopes = integration.integration_metadata.get('scopes')
                if not scopes:
                    from src.auth.oauth import SCOPES
                    scopes = SCOPES

                # Decrypt tokens
                decrypted_access = decrypt_token(integration.access_token)
                decrypted_refresh = decrypt_token(integration.refresh_token)

                creds = Credentials(
                    token=decrypted_access,
                    refresh_token=decrypted_refresh,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=os.getenv('GOOGLE_CLIENT_ID'),
                    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
                    scopes=scopes
                )
                if integration.expires_at:
                    creds.expiry = integration.expires_at
                
                # Check if we can refresh
                if creds.expired and creds.refresh_token:
                    from google.auth.transport.requests import Request
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, lambda: creds.refresh(Request()))
                    # Update integration
                    integration.access_token = creds.token
                    if creds.expiry:
                        integration.expires_at = creds.expiry.replace(tzinfo=None)
                    await db.commit()

            if not creds or not creds.valid:
                logger.error(f"Invalid or expired credentials. Valid: {creds.valid if creds else 'N/A'}")
                if creds:
                    logger.error(f"Scopes: {creds.scopes}")
                    logger.error(f"Expiry: {creds.expiry}")
                return

            gmail_client = GoogleGmailClient(config=config, credentials=creds)
            logger.info(f"Gmail Client initialized. Service: {gmail_client.service}")
            logger.info(f"Gmail Client is_available: {gmail_client.is_available()}")
            
            if not gmail_client.is_available():
                logger.error(f"Gmail Client failed is_available survey.")
                if gmail_client.credentials:
                    logger.error(f"Required scopes: {gmail_client._get_required_scopes()}")
                    logger.error(f"Current scopes: {gmail_client.credentials.scopes}")
                else:
                    logger.error("No credentials attached to gmail_client!")

            logger.info("Starting crawler.run_sync_cycle()...")
            # Initialize TopicExtractor
            topic_extractor = TopicExtractor(
                config=config,
                graph_manager=graph_manager
            )
            
            crawler = EmailCrawler(
                config=config,
                user_id=user_id,
                rag_engine=rag_engine,
                graph_manager=graph_manager,
                google_client=gmail_client,
                topic_extractor=topic_extractor
            )
            
            logger.info("Starting crawler.run_sync_cycle()...")
            # For a full re-sync, we want to ensure it pulls enough history
            # The crawler uses INITIAL_INDEXING_DAYS (default 30)
            items_indexed = await crawler.run_sync_cycle()
            logger.info(f"Sync complete. Indexed {items_indexed} items.")
            
            if items_indexed:
                logger.info(f"Successfully processed {items_indexed} items into graph and vector store.")

    except Exception as e:
        logger.error(f"Crawler trigger failed: {e}", exc_info=True)

    logger.info("Re-indexing task finished.")

if __name__ == "__main__":
    asyncio.run(reindex_maniko())
