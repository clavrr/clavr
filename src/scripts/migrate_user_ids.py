import asyncio
import sys
import logging
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

# Setup path to include src
sys.path.append(os.getcwd())

from src.database import get_async_db_context
from src.database.models import UserIntegration, User
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.ai.rag.core.rag_engine import RAGEngine
from src.utils.config import Config, load_config
from src.core import GoogleGmailClient
from sqlalchemy import select, text
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

async def migrate_user_ids():
    """
    Final migration script to backfill user_id to Email nodes in ArangoDB, Qdrant, and Postgres.
    """
    logger.info("Starting Data Isolation Migration (v4 - Enhanced)...")
    
    config = load_config()
    
    # Initialize services
    graph_manager = KnowledgeGraphManager(config=config)
    rag_engine = RAGEngine(config)
    
    # 1. Probing ArangoDB
    logger.info("--- Probing ArangoDB for unique senders ---")
    try:
        aql_probe = "FOR doc IN Email COLLECT sender = doc.sender_email WITH COUNT INTO count RETURN { sender, count }"
        cursor_probe = graph_manager.db.aql.execute(aql_probe)
        senders = [doc for doc in cursor_probe]
        for s in senders:
            logger.info(f"ArangoDB Sender: {s.get('sender')} (Count: {s.get('count')})")
    except Exception as e:
        logger.error(f"ArangoDB probe failed: {e}")

    # 2. Build Mapping from Users table
    user_mappings = []
    async with get_async_db_context() as db:
        stmt_users = select(User)
        res_users = await db.execute(stmt_users)
        all_users = res_users.scalars().all()
        for u in all_users:
            if u.email:
                user_mappings.append({'user_id': u.id, 'email': u.email.lower()})
        
        logger.info(f"Loaded {len(user_mappings)} user mappings from database")

    if not user_mappings:
        logger.warning("No users found! Aborting.")
        return

    # 3. Update ArangoDB
    logger.info("--- Updating ArangoDB ---")
    for mapping in user_mappings:
        user_id = mapping['user_id']
        email = mapping['email']
        
        aql_sent = """
        FOR doc IN Email
            FILTER doc.sender_email == @email
            UPDATE doc WITH { user_id: @user_id } IN Email
            RETURN OLD._key
        """
        try:
            cursor_sent = graph_manager.db.aql.execute(aql_sent, bind_vars={'email': email, 'user_id': user_id})
            updated_sent = [doc for doc in cursor_sent]
            if updated_sent:
                logger.info(f"ArangoDB: Updated {len(updated_sent)} SENT emails for user {user_id} ({email})")
        except Exception as e:
            logger.error(f"ArangoDB SENT update failed: {e}")

        aql_received = """
        FOR doc IN Email
            FILTER @email IN doc.recipients OR @email IN doc.cc
            UPDATE doc WITH { user_id: @user_id } IN Email
            RETURN OLD._key
        """
        try:
            cursor_received = graph_manager.db.aql.execute(aql_received, bind_vars={'email': email, 'user_id': user_id})
            updated_received = [doc for doc in cursor_received]
            if updated_received:
                logger.info(f"ArangoDB: Updated {len(updated_received)} RECEIVED emails for user {user_id} ({email})")
        except Exception as e:
            logger.error(f"ArangoDB RECEIVED update failed: {e}")

    # 4. Update Qdrant
    logger.info("--- Updating Qdrant ---")
    if hasattr(rag_engine.vector_store, 'client'): 
        try:
            from qdrant_client.http import models
            client = rag_engine.vector_store.client
            collection_name = rag_engine.vector_store.collection_name or 'email-knowledge'

            # Try to create keyword index for recipients if it fails again
            try:
                client.create_payload_index(
                    collection_name=collection_name,
                    field_name="recipients",
                    field_schema=models.PayloadSchemaType.KEYWORD
                )
                logger.info("Qdrant: Created keyword index for 'recipients'")
            except Exception as e:
                logger.debug(f"Qdrant: Note - index creation skipped or already exists: {e}")

            for mapping in user_mappings:
                user_id = mapping['user_id']
                email = mapping['email']
                
                # Update by sender_email
                try:
                    res = client.set_payload(
                        collection_name=collection_name,
                        payload={'user_id': user_id},
                        points=models.Filter(
                            must=[models.FieldCondition(key="sender_email", match=models.MatchValue(value=email))]
                        )
                    )
                    logger.info(f"Qdrant: Payload set for SENT emails of {email} -> {user_id}")
                except Exception as e:
                    logger.error(f"Qdrant SENT update failed for {email}: {e}")

                # Update by recipients (requires matching within list)
                try:
                    client.set_payload(
                        collection_name=collection_name,
                        payload={'user_id': user_id},
                        points=models.Filter(
                            must=[models.FieldCondition(key="recipients", match=models.MatchAny(any=[email]))]
                        )
                    )
                    logger.info(f"Qdrant: Payload set for RECEIVED emails of {email} -> {user_id}")
                except Exception as e:
                    logger.warning(f"Qdrant RECEIVED update failed for {email}: {e}")
        except Exception as e:
            logger.error(f"Failed to connect to Qdrant: {e}")

    # 5. Update Postgres (langchain_pg_embedding)
    logger.info("--- Updating Postgres Vector Store ---")
    async with get_async_db_context() as db:
        try:
            stmt_coll = text("SELECT uuid FROM langchain_pg_collection WHERE name = 'email-knowledge'")
            res_coll = await db.execute(stmt_coll)
            coll_row = res_coll.first()
            if coll_row:
                coll_id = coll_row[0]
                for mapping in user_mappings:
                    user_id = mapping['user_id']
                    email = mapping['email']
                    
                    # Update metadata for sent emails
                    # Use CAST to ensure data types are handled correctly by asyncpg
                    stmt_upd_sent = text("""
                        UPDATE langchain_pg_embedding 
                        SET cmetadata = cmetadata || jsonb_build_object('user_id', CAST(:user_id AS INT))
                        WHERE collection_id = CAST(:coll_id AS UUID)
                        AND cmetadata->>'sender_email' = :email
                    """)
                    await db.execute(stmt_upd_sent, {"user_id": user_id, "coll_id": coll_id, "email": email})
                    
                    # Update metadata for received emails
                    stmt_upd_rec = text("""
                        UPDATE langchain_pg_embedding 
                        SET cmetadata = cmetadata || jsonb_build_object('user_id', CAST(:user_id AS INT))
                        WHERE collection_id = CAST(:coll_id AS UUID)
                        AND cmetadata->'recipients' ? :email
                    """)
                    await db.execute(stmt_upd_rec, {"user_id": user_id, "coll_id": coll_id, "email": email})
                    await db.commit()
                logger.info("Postgres vector store updated successfully")
            else:
                logger.info("Collection 'email-knowledge' not found in Postgres vector store.")
        except Exception as e:
            logger.error(f"Postgres vector store update failed: {e}")

    logger.info("Migration Complete!")

if __name__ == "__main__":
    asyncio.run(migrate_user_ids())
