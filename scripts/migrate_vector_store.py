#!/usr/bin/env python3
"""
Vector Store Migration Script

Migrate data between Qdrant (primary) and PostgreSQL (fallback) vector stores.

Supported migrations:
- PostgreSQL → Qdrant
- Qdrant → PostgreSQL

Usage:
    python scripts/migrate_vector_store.py --from postgres --to qdrant
    python scripts/migrate_vector_store.py --from qdrant --to postgres --batch-size 50
"""
import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any
import time

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import load_config
from src.utils.logger import setup_logger
from src.ai.rag.embedding_provider import create_embedding_provider
from src.ai.rag.vector_store import create_vector_store
from src.ai.rag.postgres_vector_store import PostgresVectorStore

logger = setup_logger(__name__)


def get_vector_store(backend: str, config, rag_config, embedding_provider):
    """Create vector store instance for given backend."""
    from src.ai.rag.vector_store import VectorStore
    
    collection_name = rag_config.collection_name
    
    if backend == "postgres":
        import os
        db_url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL') or config.database.url
        if not db_url:
            raise ValueError("PostgreSQL URL not configured")
        return PostgresVectorStore(db_url, collection_name, embedding_provider)
    
    elif backend == "qdrant":
        import os
        from src.ai.rag.core.vector_store import QdrantVectorStore
        url = os.getenv('QDRANT_URL') or os.getenv('QDRANT_ENDPOINT')
        api_key = os.getenv('QDRANT_API_KEY')
        if not url and not api_key:
            raise ValueError("Qdrant credentials (QDRANT_URL/API_KEY) not configured")
        return QdrantVectorStore(collection_name, embedding_provider, url=url, api_key=api_key)
    
    else:
        raise ValueError(f"Unknown backend: {backend}. Supported: 'postgres', 'qdrant'")


def extract_documents_postgres(store: PostgresVectorStore) -> List[Dict[str, Any]]:
    """Extract all documents from PostgreSQL."""
    logger.info("Extracting documents from PostgreSQL...")
    
    from sqlalchemy import create_engine, text
    
    engine = create_engine(store.db_url)
    documents = []
    
    with engine.connect() as conn:
        # Query all documents
        query = text("""
            SELECT e.id, e.document, e.cmetadata, e.embedding
            FROM langchain_pg_embedding e
            JOIN langchain_pg_collection c ON e.collection_id = c.uuid
            WHERE c.name = :collection_name
        """)
        
        results = conn.execute(query, {"collection_name": store.collection_name})
        
        for row in results:
            documents.append({
                'id': row.id,
                'content': row.document,
                'metadata': row.cmetadata or {},
                'embedding': list(row.embedding) if row.embedding else None
            })
    
    logger.info(f"Extracted {len(documents)} documents from PostgreSQL")
    return documents


def extract_documents_qdrant(store) -> List[Dict[str, Any]]:
    """Extract all documents from Qdrant."""
    logger.info("Extracting documents from Qdrant...")
    return store.get_all_documents()


def migrate_vector_store(
    from_backend: str,
    to_backend: str,
    batch_size: int = 100,
    dry_run: bool = False,
    clear_target: bool = False
):
    """
    Migrate data from one vector store to another.
    
    Args:
        from_backend: Source backend (chromadb, postgres, pinecone, weaviate)
        to_backend: Target backend (chromadb, postgres, pinecone, weaviate)
        batch_size: Number of documents to migrate per batch
        dry_run: If True, only show what would be migrated without actually migrating
        clear_target: If True, clear target store before migration
    """
    logger.info("="*80)
    logger.info(f"VECTOR STORE MIGRATION: {from_backend.upper()} → {to_backend.upper()}")
    logger.info("="*80)
    
    # Load configuration
    config = load_config()
    rag_config = config.rag
    
    # Create embedding provider
    logger.info("Initializing embedding provider...")
    embedding_provider = create_embedding_provider(rag_config)
    
    # Create source and target stores
    logger.info(f"Connecting to source: {from_backend}")
    source_store = get_vector_store(from_backend, config, rag_config, embedding_provider)
    
    logger.info(f"Connecting to target: {to_backend}")
    target_store = get_vector_store(to_backend, config, rag_config, embedding_provider)
    
    # Get source statistics
    source_stats = source_store.get_stats()
    logger.info(f"Source stats: {source_stats}")
    
    # Clear target if requested
    if clear_target and not dry_run:
        logger.warning("Clearing target vector store...")
        if hasattr(target_store, 'clear_namespace'):
            target_store.clear_namespace()
        elif hasattr(target_store, 'clear_collection'):
            target_store.clear_collection()
    
    # Extract documents from source
    if from_backend == "postgres":
        documents = extract_documents_postgres(source_store)
    elif from_backend == "qdrant":
        documents = extract_documents_qdrant(source_store)
    else:
        logger.error(f"Migration from {from_backend} not supported")
        logger.error("Supported: 'postgres', 'qdrant'")
        return
    
    if not documents:
        logger.warning("No documents found in source store!")
        return
    
    logger.info(f"Found {len(documents)} documents to migrate")
    
    if dry_run:
        logger.info("DRY RUN - No changes will be made")
        logger.info(f"Would migrate {len(documents)} documents")
        logger.info(f"Sample document: {documents[0]}")
        return
    
    # Migrate in batches
    total_migrated = 0
    total_batches = (len(documents) + batch_size - 1) // batch_size
    
    logger.info(f"Starting migration in {total_batches} batches of {batch_size}...")
    
    start_time = time.time()
    
    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        
        logger.info(f"Migrating batch {batch_num}/{total_batches} ({len(batch)} documents)...")
        
        try:
            # Prepare documents for insertion
            batch_docs = []
            for doc in batch:
                batch_docs.append({
                    'id': doc['id'],
                    'content': doc['content'],
                    'metadata': doc['metadata']
                })
            
            # Insert batch
            target_store.add_documents(batch_docs)
            total_migrated += len(batch)
            
            logger.info(f"✓ Batch {batch_num} complete ({total_migrated}/{len(documents)})")
            
        except Exception as e:
            logger.error(f"✗ Batch {batch_num} failed: {e}")
            logger.error("Continuing with next batch...")
            continue
    
    # Final statistics
    elapsed = time.time() - start_time
    target_stats = target_store.get_stats()
    
    logger.info("="*80)
    logger.info("MIGRATION COMPLETE")
    logger.info("="*80)
    logger.info(f"Total documents migrated: {total_migrated}/{len(documents)}")
    logger.info(f"Time elapsed: {elapsed:.2f}s ({total_migrated/elapsed:.1f} docs/sec)")
    logger.info(f"Target stats: {target_stats}")
    
    # Close connections
    if hasattr(target_store, 'close'):
        target_store.close()


def main():
    parser = argparse.ArgumentParser(
        description="Migrate data between vector stores",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Migrate from PostgreSQL to Qdrant
  python scripts/migrate_vector_store.py --from postgres --to qdrant
  
  # Migrate from Qdrant to PostgreSQL with custom batch size
  python scripts/migrate_vector_store.py --from qdrant --to postgres --batch-size 50
  
  # Dry run to see what would be migrated
  python scripts/migrate_vector_store.py --from postgres --to qdrant --dry-run
  
  # Clear target before migration
  python scripts/migrate_vector_store.py --from postgres --to qdrant --clear-target

Supported backends:
  - postgres (PostgreSQL with pgvector) - FALLBACK
  - qdrant (high-performance vector database) - PRIMARY
        """
    )
    
    parser.add_argument(
        '--from',
        dest='from_backend',
        required=True,
        choices=['postgres', 'qdrant'],
        help='Source vector store backend'
    )
    
    parser.add_argument(
        '--to',
        dest='to_backend',
        required=True,
        choices=['postgres', 'qdrant'],
        help='Target vector store backend'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Number of documents per batch (default: 100)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be migrated without making changes'
    )
    
    parser.add_argument(
        '--clear-target',
        action='store_true',
        help='Clear target store before migration (DESTRUCTIVE!)'
    )
    
    args = parser.parse_args()
    
    # Validate
    if args.from_backend == args.to_backend:
        logger.error("Source and target backends must be different!")
        sys.exit(1)
    
    try:
        migrate_vector_store(
            from_backend=args.from_backend,
            to_backend=args.to_backend,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            clear_target=args.clear_target
        )
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
