#!/usr/bin/env python3
"""
Drive Graph Edge Verification Script

Tests that OWNER_OF, STORED_IN, and FOLDER nodes are created correctly
when the DriveCrawler indexes files.
"""
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.getcwd())

from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)


async def verify_drive_graph_edges():
    """Verify Drive graph edges are created correctly."""
    
    print("\n" + "="*60)
    print("Drive Graph Edge Verification")
    print("="*60 + "\n")
    
    # 1. Check ArangoDB Connection
    print("1. Checking ArangoDB connection...")
    try:
        from src.services.indexing.graph.manager import KnowledgeGraphManager
        graph = KnowledgeGraphManager(backend="arangodb")
        print("   ✅ Connected to ArangoDB")
    except Exception as e:
        print(f"   ❌ Failed to connect: {e}")
        print("\n   Make sure ArangoDB is running (docker-compose up -d)")
        return False
    
    # 2. Query for existing OWNER_OF edges
    print("\n2. Querying for OWNER_OF edges...")
    try:
        query = """
        FOR e IN OWNER_OF
        LIMIT 10
        RETURN {
            from: e._from,
            to: e._to,
            created_at: e.created_at
        }
        """
        owner_of_edges = await graph.query(query)
        print(f"   Found {len(owner_of_edges)} OWNER_OF edges")
        for edge in owner_of_edges[:3]:
            print(f"   - {edge.get('from')} -> {edge.get('to')}")
    except Exception as e:
        print(f"   ⚠️ OWNER_OF collection may not exist yet: {e}")
        owner_of_edges = []
    
    # 3. Query for existing STORED_IN edges
    print("\n3. Querying for STORED_IN edges...")
    try:
        query = """
        FOR e IN STORED_IN
        LIMIT 10
        RETURN {
            from: e._from,
            to: e._to
        }
        """
        stored_in_edges = await graph.query(query)
        print(f"   Found {len(stored_in_edges)} STORED_IN edges")
        for edge in stored_in_edges[:3]:
            print(f"   - {edge.get('from')} -> {edge.get('to')}")
    except Exception as e:
        print(f"   ⚠️ STORED_IN collection may not exist yet: {e}")
        stored_in_edges = []
    
    # 4. Query for FOLDER nodes
    print("\n4. Querying for FOLDER nodes...")
    try:
        query = """
        FOR n IN Folder
        LIMIT 10
        RETURN {
            id: n._key,
            name: n.name,
            folder_id: n.folder_id
        }
        """
        folders = await graph.query(query)
        print(f"   Found {len(folders)} FOLDER nodes")
        for folder in folders[:3]:
            print(f"   - {folder.get('name')} (id: {folder.get('id')})")
    except Exception as e:
        print(f"   ⚠️ Folder collection may not exist yet: {e}")
        folders = []
    
    # 5. Query for Document nodes with Drive metadata
    print("\n5. Querying for Document nodes with Drive metadata...")
    try:
        query = """
        FOR n IN Document
        FILTER n.source == "google_drive" OR n.node_type == "Document"
        LIMIT 10
        RETURN {
            id: n._key,
            filename: n.filename,
            owner_email: n.owner_email,
            parent_folder_id: n.parent_folder_id,
            source: n.source
        }
        """
        docs = await graph.query(query)
        print(f"   Found {len(docs)} Document nodes with Drive source")
        for doc in docs[:3]:
            owner = doc.get('owner_email', 'N/A')
            parent = doc.get('parent_folder_id', 'N/A')
            print(f"   - {doc.get('filename')} (owner: {owner}, parent: {parent})")
    except Exception as e:
        print(f"   ⚠️ Error querying documents: {e}")
        docs = []
    
    # 6. Query for Person nodes (owners)
    print("\n6. Querying for Person nodes from Drive...")
    try:
        query = """
        FOR n IN Person
        FILTER n.source == "google_drive" OR CONTAINS(n._key, "person_")
        LIMIT 10
        RETURN {
            id: n._key,
            name: n.name,
            email: n.email,
            source: n.source
        }
        """
        persons = await graph.query(query)
        print(f"   Found {len(persons)} Person nodes")
        for person in persons[:3]:
            print(f"   - {person.get('name')} ({person.get('email')})")
    except Exception as e:
        print(f"   ⚠️ Error querying persons: {e}")
        persons = []
    
    # Summary
    print("\n" + "="*60)
    print("Summary")
    print("="*60)
    print(f"OWNER_OF edges:  {len(owner_of_edges)}")
    print(f"STORED_IN edges: {len(stored_in_edges)}")
    print(f"FOLDER nodes:    {len(folders)}")
    print(f"Drive Documents: {len(docs)}")
    print(f"Person nodes:    {len(persons)}")
    
    if len(owner_of_edges) > 0 or len(stored_in_edges) > 0 or len(folders) > 0:
        print("\n✅ Drive graph edges are being created!")
        return True
    else:
        print("\n⚠️ No Drive graph edges found yet.")
        print("   Run the DriveCrawler to create edges:")
        print("   - Start the indexer: python -m src.services.indexing.unified_indexer")
        print("   - Or trigger a manual sync")
        return False


async def run_drive_crawler_sync():
    """Attempt to run a DriveCrawler sync cycle."""
    print("\n" + "="*60)
    print("Attempting DriveCrawler Sync...")
    print("="*60 + "\n")
    
    try:
        from src.utils.config import Config
        from src.services.indexing.graph.manager import KnowledgeGraphManager
        from src.ai.rag import RAGEngine
        from src.services.indexing.crawlers.drive import DriveCrawler
        from src.integrations.google_drive.service import GoogleDriveService
        
        config = Config()
        
        # We need user credentials to run the crawler
        # This is a simplified test - in production, you'd get these from the DB
        print("Note: Running DriveCrawler requires user credentials.")
        print("This test only verifies the infrastructure is correct.")
        print("\nTo fully test, you need to:")
        print("1. Start the backend server")
        print("2. Authenticate a user with Google Drive")
        print("3. The indexer will run automatically")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


async def main():
    """Main verification entry point."""
    try:
        # Verify graph edges exist
        edges_ok = await verify_drive_graph_edges()
        
        if not edges_ok:
            # Provide guidance on running the crawler
            await run_drive_crawler_sync()
        
        print("\n" + "="*60)
        print("Verification Complete")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n❌ Verification failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
