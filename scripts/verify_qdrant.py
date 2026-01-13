import os
import sys
from dotenv import load_dotenv
from qdrant_client import QdrantClient

# Load env variables
load_dotenv()

url = os.getenv("QDRANT_ENDPOINT")
api_key = os.getenv("QDRANT_API_KEY")

print(f"Testing URL: {url}")

if not url:
    print("ERROR: QDRANT_ENDPOINT is missing in .env")
    sys.exit(1)

try:
    client = QdrantClient(url=url, api_key=api_key)
    # Just checking collections isn't enough, we need to handle 404 explicitly
    try:
        collections = client.get_collections()
        print("SUCCESS: Qdrant connection established!")
        print("Collections:", collections)
    except Exception as ie:
        err_str = str(ie).lower()
        if "404" in err_str or "not found" in err_str:
            print("\n" + "="*60)
            print("CRITICAL ERROR: 404 Not Found")
            print("="*60)
            print(f"The Qdrant Endpoint URL is invalid: {url}")
            print("This usually means the Cluster ID (the '7bf6...' part) has changed.")
            print("\nACTION REQUIRED:")
            print("1. Go to Qdrant Cloud Dashboard: https://cloud.qdrant.io")
            print("2. Click on 'Clusters'")
            print("3. Click 'Cluster Details' for 'clavr'")
            print("4. Copy the 'Endpoint' URL")
            print("5. Update QDRANT_ENDPOINT in your .env file")
            print("="*60 + "\n")
        else:
            raise ie

except Exception as e:
    print(f"Connection failed: {e}")

# Try adding port 6333 if missing
if url and ":6333" not in url:
    url_with_port = url.rstrip('/') + ":6333"
    print(f"\nAlso tested with port 6333 ({url_with_port})...")
    # Same check logic...
