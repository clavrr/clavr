#!/usr/bin/env python3
"""
Diagnostic Script: Email Search Issue
Run with: /Users/maniko/Documents/clavr/email_agent/bin/python -m src.scripts.diagnose_email_search
"""
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

async def diagnose():
    print("\n" + "="*60)
    print("EMAIL SEARCH DIAGNOSTIC")
    print("="*60)
    
    # ============================================================
    # 1. Check Qdrant Collection Status
    # ============================================================
    print("\n[1/4] QDRANT COLLECTION STATUS")
    print("-" * 40)
    
    try:
        from qdrant_client import QdrantClient
        
        qdrant_url = os.getenv("QDRANT_ENDPOINT") or os.getenv("QDRANT_URL")
        qdrant_key = os.getenv("QDRANT_API_KEY")
        
        if qdrant_url and qdrant_key:
            client = QdrantClient(url=qdrant_url, api_key=qdrant_key)
            
            # Get collection info
            collections = client.get_collections().collections
            print(f"   Collections found: {[c.name for c in collections]}")
            
            # Check email-knowledge specifically
            try:
                info = client.get_collection("email-knowledge")
                print(f"   ✓ email-knowledge: {info.points_count} points")
                
                # Sample some points
                if info.points_count > 0:
                    sample = client.scroll(
                        collection_name="email-knowledge",
                        limit=5,
                        with_payload=True,
                        with_vectors=False
                    )
                    print(f"   Sample documents:")
                    for point in sample[0]:
                        payload = point.payload
                        doc_type = payload.get('type', 'unknown')
                        subject = payload.get('subject', payload.get('content', ''))[:50]
                        print(f"      - [{doc_type}] {subject}...")
                else:
                    print("   ✗ COLLECTION IS EMPTY - NO DATA INDEXED!")
                    
            except Exception as e:
                print(f"   ✗ email-knowledge collection error: {e}")
        else:
            print("   ✗ QDRANT_ENDPOINT or QDRANT_API_KEY not set")
            
    except Exception as e:
        print(f"   ✗ Qdrant check failed: {e}")
    
    # ============================================================
    # 2. Check Gmail API directly for ElevenLabs email
    # ============================================================
    print("\n[2/4] GMAIL API DIRECT CHECK")
    print("-" * 40)
    
    try:
        from sqlalchemy import select
        from src.database.database import SessionLocal
        from src.database.models import User, UserIntegration
        from src.core.credential_provider import CredentialProvider
        from src.integrations.gmail.client import GoogleGmailClient
        
        db = SessionLocal()
        
        # Get user 7's Gmail credentials
        integration = db.query(UserIntegration).filter(
            UserIntegration.user_id == 7,
            UserIntegration.provider == 'gmail'
        ).first()
        
        if integration:
            print(f"   ✓ Gmail integration found for user 7")
            
            # Get credentials
            cred_provider = CredentialProvider(config, integration.user_id)
            creds = cred_provider.get_gmail_credentials()
            
            if creds:
                # Initialize Gmail client
                gmail_client = GoogleGmailClient(credentials=creds)
                
                # Search for ElevenLabs emails
                search_queries = [
                    "from:elevenlabs",
                    "from:eleven-labs", 
                    "from:@elevenlabs.io",
                    "eleven labs",
                    "elevenlabs subscription",
                    "elevenlabs receipt"
                ]
                
                for q in search_queries:
                    try:
                        results = gmail_client.service.users().messages().list(
                            userId='me', 
                            q=q,
                            maxResults=5
                        ).execute()
                        
                        messages = results.get('messages', [])
                        if messages:
                            print(f"   ✓ Query '{q}': {len(messages)} messages found")
                            # Get first message details
                            msg = gmail_client.service.users().messages().get(
                                userId='me',
                                id=messages[0]['id'],
                                format='metadata',
                                metadataHeaders=['Subject', 'From', 'Date']
                            ).execute()
                            headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
                            print(f"      First: {headers.get('Subject', 'N/A')[:60]}")
                            print(f"             From: {headers.get('From', 'N/A')}")
                        else:
                            print(f"   ✗ Query '{q}': 0 messages")
                    except Exception as e:
                        print(f"   ✗ Query '{q}' failed: {e}")
            else:
                print("   ✗ Could not get Gmail credentials")
        else:
            print("   ✗ No Gmail integration for user 7")
            
        db.close()
        
    except Exception as e:
        print(f"   ✗ Gmail check failed: {e}")
        import traceback
        traceback.print_exc()
    
    # ============================================================
    # 3. Check ArangoDB Graph for Email nodes
    # ============================================================
    print("\n[3/4] ARANGODB GRAPH CHECK")
    print("-" * 40)
    
    try:
        from arango import ArangoClient
        
        arango_host = os.getenv("ARANGO_HOST", "localhost")
        arango_port = os.getenv("ARANGO_PORT", "8529")
        arango_user = os.getenv("ARANGO_USER", "root")
        arango_pass = os.getenv("ARANGO_PASSWORD", "")
        arango_db = os.getenv("ARANGO_DB", "clavr")
        
        client = ArangoClient(hosts=f"http://{arango_host}:{arango_port}")
        db = client.db(arango_db, username=arango_user, password=arango_pass)
        
        # Count Email nodes
        if db.has_collection("Email"):
            email_count = db.collection("Email").count()
            print(f"   ✓ Email nodes: {email_count}")
            
            # Sample some
            if email_count > 0:
                cursor = db.aql.execute("FOR e IN Email LIMIT 3 RETURN {subject: e.subject, sender: e.sender, date: e.timestamp}")
                print("   Sample emails:")
                for doc in cursor:
                    print(f"      - {doc.get('subject', 'N/A')[:50]}...")
                    
                # Search for ElevenLabs specifically
                cursor = db.aql.execute(
                    "FOR e IN Email FILTER CONTAINS(LOWER(e.subject), 'eleven') OR CONTAINS(LOWER(e.sender), 'eleven') RETURN e",
                )
                elevenlabs_emails = list(cursor)
                if elevenlabs_emails:
                    print(f"   ✓ Found {len(elevenlabs_emails)} ElevenLabs emails in graph!")
                else:
                    print("   ✗ No ElevenLabs emails found in graph")
        else:
            print("   ✗ Email collection does not exist")
            
    except Exception as e:
        print(f"   ✗ ArangoDB check failed: {e}")
    
    # ============================================================
    # 4. Check Index State in Postgres
    # ============================================================
    print("\n[4/4] POSTGRES INDEX STATE")
    print("-" * 40)
    
    try:
        from src.database.database import SessionLocal
        from src.database.models import IndexState
        
        db = SessionLocal()
        
        states = db.query(IndexState).filter(IndexState.user_id == 7).all()
        for state in states:
            print(f"   {state.provider}: last_sync={state.last_sync_at}, cursor={state.cursor_value}")
            
        db.close()
        
    except Exception as e:
        print(f"   ✗ Postgres check failed: {e}")
    
    print("\n" + "="*60)
    print("DIAGNOSIS COMPLETE")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(diagnose())
