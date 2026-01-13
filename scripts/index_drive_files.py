#!/usr/bin/env python
"""
Drive Files Indexing Script

Indexes Google Drive files (starred + recent) into Qdrant drive-files collection
for semantic search in DriveTool.

Usage:
    source email_agent/bin/activate
    python scripts/index_drive_files.py --user-id 3
"""
import asyncio
import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.utils.logger import setup_logger
from src.utils.config import load_config
from src.database import get_db_context
from src.database.models import User

logger = setup_logger(__name__)


async def index_drive_files(user_id: int, limit: int = 100):
    """
    Index Drive files for a user into the drive-files Qdrant collection.
    """
    config = load_config()
    
    print(f"\n{'='*60}")
    print(f"🚀 INDEXING DRIVE FILES FOR USER {user_id}")
    print(f"{'='*60}\n")
    
    # 1. Get user credentials
    from src.core.credential_provider import CredentialProvider
    
    with get_db_context() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            print(f"❌ User {user_id} not found")
            return
        
        print(f"✓ Found user: {user.email}")
        
        # Get credentials using CredentialProvider
        credentials = CredentialProvider.get_credentials(
            user_id=user_id,
            db_session=db,
            auto_refresh=True
        )
        
        if not credentials:
            print(f"❌ No Google credentials found for user {user_id}")
            return
        
        print(f"✓ Loaded credentials (valid={credentials.valid})")
    
    # 2. Initialize Drive service
    from src.integrations.google_drive.service import GoogleDriveService
    drive_service = GoogleDriveService(config=config, credentials=credentials)
    print("✓ Drive service initialized")
    
    # 3. Initialize RAG engine for drive-files collection
    from src.ai.rag import RAGEngine
    rag_engine = RAGEngine(config=config, collection_name="drive-files")
    print("✓ RAG engine initialized (collection: drive-files)")
    
    # 4. Initialize Graph manager (optional, can be None)
    from src.services.indexing.graph import KnowledgeGraphManager
    try:
        graph_manager = KnowledgeGraphManager(config=config)
        print("✓ Graph manager initialized")
    except Exception as e:
        print(f"⚠ Graph manager not available: {e}")
        graph_manager = None
    
    # 5. Initialize DriveCrawler
    from src.services.indexing.crawlers.drive import DriveCrawler
    crawler = DriveCrawler(
        config=config,
        user_id=user_id,
        rag_engine=rag_engine,
        graph_manager=graph_manager,
        drive_service=drive_service
    )
    print("✓ Drive crawler initialized")
    
    # 6. Fetch files
    print(f"\n📂 Fetching files (starred + recent last 30 days)...")
    files = await crawler.fetch_delta()
    print(f"✓ Found {len(files)} files to index")
    
    if not files:
        print("⚠ No files found. Make sure you have starred or recent files in Drive.")
        return
    
    # 7. Index files
    print(f"\n📥 Indexing files into Qdrant...")
    indexed_count = 0
    failed_count = 0
    
    for i, file_data in enumerate(files[:limit]):
        try:
            # Transform to ParsedNode
            node = await crawler.transform_item(file_data)
            
            if node:
                # Index into RAG
                file_id = file_data.get('id')
                file_name = file_data.get('name', 'Unknown')
                mime_type = file_data.get('mimeType', '')
                
                # Index with metadata
                rag_engine.index_document(
                    doc_id=f"drive_{file_id}",
                    content=node.properties.get('content', file_name),
                    metadata={
                        'file_id': file_id,
                        'file_name': file_name,
                        'name': file_name,  # Duplicate for compatibility
                        'mime_type': mime_type,
                        'mimeType': mime_type,  # Duplicate for compatibility
                        'user_id': user_id,
                        'source': 'google_drive',
                        'node_type': 'drive_file'
                    }
                )
                indexed_count += 1
                print(f"  [{i+1}/{min(len(files), limit)}] ✓ {file_name[:50]}")
            else:
                print(f"  [{i+1}/{min(len(files), limit)}] ⚠ Skipped (no content): {file_data.get('name', 'Unknown')[:50]}")
                
        except Exception as e:
            failed_count += 1
            print(f"  [{i+1}/{min(len(files), limit)}] ❌ Failed: {file_data.get('name', 'Unknown')[:30]} - {e}")
    
    # 8. Summary
    print(f"\n{'='*60}")
    print(f"📊 INDEXING COMPLETE")
    print(f"{'='*60}")
    print(f"  ✓ Indexed: {indexed_count}")
    print(f"  ❌ Failed: {failed_count}")
    print(f"  ⚠ Skipped: {len(files[:limit]) - indexed_count - failed_count}")
    print(f"\n🎉 Drive files are now searchable via RAG!")
    print(f"   Try: 'get work items from Fall Senior Committee Meeting'")


def main():
    parser = argparse.ArgumentParser(description="Index Google Drive files into Qdrant")
    parser.add_argument("--user-id", type=int, required=True, help="User ID to index for")
    parser.add_argument("--limit", type=int, default=100, help="Maximum files to index")
    args = parser.parse_args()
    
    asyncio.run(index_drive_files(args.user_id, args.limit))


if __name__ == "__main__":
    main()
