
import asyncio
import os
import sys
from typing import Dict, Any

# Add project root to path
sys.path.append(os.getcwd())

from src.utils.config import load_config
from src.database import get_db_context
from src.database.models import User, Session as DBSession
from src.ai.rag import RAGEngine
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.integrations.google_drive.service import GoogleDriveService
from src.services.indexing.crawlers.drive import DriveCrawler
from src.auth.token_refresh import get_valid_credentials
from google.oauth2.credentials import Credentials

async def reindex_meeting_doc():
    config = load_config()
    user_id = 3
    file_id = "17wmHYyLgeOvYrs-751QyiQKEAWIR7U9GpYs5HkisXtg"
    
    with get_db_context() as db:
        user = db.query(User).filter(User.id == user_id).first()
        user_session = db.query(DBSession).filter(
            DBSession.user_id == user_id,
            DBSession.gmail_access_token.isnot(None)
        ).order_by(DBSession.id.desc()).first()
        
        if not user_session:
            print("No session found")
            return

        creds_obj = get_valid_credentials(db, user_session, auto_refresh=True)
        google_creds = Credentials(
            token=creds_obj.token,
            refresh_token=creds_obj.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv('GOOGLE_CLIENT_ID'),
            client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
            scopes=creds_obj.scopes
        )

        rag_engine = RAGEngine(config=config, collection_name='drive-files')
        graph_manager = KnowledgeGraphManager(config=config)
        drive_service = GoogleDriveService(config=config, credentials=google_creds)
        
        crawler = DriveCrawler(
            config=config,
            user_id=user_id,
            rag_engine=rag_engine,
            graph_manager=graph_manager,
            drive_service=drive_service
        )

        print(f"📥 Fetching file data for: {file_id}")
        file_data = drive_service.client.get_file(file_id)
        
        print(f"🔄 Transforming item (will use Docling and chunking via HybridIndex)...")
        node = await crawler.transform_item(file_data)
        
        if node:
            # Use the proper indexing method that includes chunking
            print(f"🚀 Indexing node via HybridIndex (Graph + Vector with Chunking)")
            success = await crawler.hybrid_index.index_node(node)
            if success:
                print(f"✅ Successfully re-indexed {file_data.get('name')} with chunking")
            else:
                print(f"❌ Failed to index node")
        else:
            print(f"❌ Transformation failed")

if __name__ == "__main__":
    asyncio.run(reindex_meeting_doc())
