import os
import sys
from dotenv import load_dotenv
load_dotenv()
import json

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchText

qdrant_url = os.getenv('QDRANT_ENDPOINT') or os.getenv('QDRANT_URL')
qdrant_key = os.getenv('QDRANT_API_KEY')

target_user_id = 7
# Search for the specific receipt ID from the screenshot
search_term = "2376-4262-2855"

print(f"Connecting to Qdrant...")
client = QdrantClient(url=qdrant_url, api_key=qdrant_key)

# 1. Check user_id distribution in email-knowledge
collection_name = 'email-knowledge' # Define collection_name here
from qdrant_client import models # Import models for Filter, FieldCondition, MatchValue
print(f"\n[1] Checking documents for user_id={target_user_id} in '{collection_name}':")
try:
    response = client.scroll(
        collection_name=collection_name, 
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=target_user_id))]
        ),
        limit=50,
        with_payload=True
    )
    
    found_count = len(response[0])
    print(f"   Found {found_count} documents for user {target_user_id}.")

    if found_count > 0:
        print("   Sample Content:")
        for point in response[0][:10]:
            p = point.payload
            doc_type = p.get('doc_type', 'unknown')
            node_type = p.get('node_type', 'unknown')
            subj = p.get('subject', '[No Subject]')
            sender = p.get('sender', '[Unknown Sender]')
            print(f"     - Type: {doc_type}/{node_type} | Subj: {subj[:40]}... | From: {sender}")
except Exception as e:
    print(f"   Error during user_id check: {e}")

print(f"\n[2] Search for '{search_term}' for user {target_user_id}:")

# 2. Search for ElevenLabs specifically
print(f"\n[2] Search for '{search_term}' for user {target_user_id}:")
try:
    # Text match on content/subject/sender
    results = client.scroll(
        collection_name='email-knowledge',
        scroll_filter=Filter(
            must=[
                FieldCondition(key="user_id", match=MatchValue(value=7))
            ],
            should=[
                FieldCondition(key="sender", match=MatchText(text="elevenlabs")),
                FieldCondition(key="subject", match=MatchText(text="elevenlabs")),
                FieldCondition(key="content", match=MatchText(text="elevenlabs"))
            ]
        ),
        limit=5,
        with_payload=True
    )
    
    if results[0]:
        print(f"   ✓ Found {len(results[0])} ElevenLabs documents for user {target_user_id}!")
        for res in results[0]:
            payload = res.payload
            print(f"   - ID: {res.id}")
            print(f"   - Subject: {payload.get('subject')}")
            print(f"   - Sender: {payload.get('sender')}")
            print(f"   - Metadata/Properties: {json.dumps(payload, indent=2, default=str)}")
            print("-" * 50)
    else:
        print(f"   ✗ No ElevenLabs documents found for user {target_user_id}")

except Exception as e:
    print(f"   Error: {e}")
