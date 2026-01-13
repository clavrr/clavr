import os
import json
import glob
from dotenv import load_dotenv

load_dotenv()

# 1. Find the credentials file
cred_files = glob.glob("credentials/*.json")
if not cred_files:
    print("WARNING: No JSON file found in credentials/ directory.")
    exit(0)

cred_file = cred_files[0]
print(f"Checking file: {cred_file}")

# 2. Read the file
try:
    with open(cred_file, 'r') as f:
        data = json.load(f)
        installed = data.get('installed') or data.get('web')
        if not installed:
            print("ERROR: Invalid JSON structure (missing 'installed' or 'web' key)")
            exit(1)
            
        file_client_id = installed.get('client_id')
        file_client_secret = installed.get('client_secret')
        
except Exception as e:
    print(f"ERROR reading file: {e}")
    exit(1)

# 3. Read Env Vars
env_client_id = os.getenv('GOOGLE_CLIENT_ID')
env_client_secret = os.getenv('GOOGLE_CLIENT_SECRET')

# 4. Compare
print("\n--- Comparison Results ---")
match = True

if file_client_id == env_client_id:
    print("✅ Client ID matches.")
else:
    print("❌ Client ID MISMATCH!")
    print(f"  File: {file_client_id[:10]}...")
    print(f"  Env:  {env_client_id[:10]}...")
    match = False

if file_client_secret == env_client_secret:
    print("✅ Client Secret matches.")
else:
    print("❌ Client Secret MISMATCH!")
    print(f"  File: {file_client_secret[:5]}...")
    print(f"  Env:  {env_client_secret[:5]}...")
    match = False

if match:
    print("\nSUCCESS: The credentials file CONTENT matches your active Environment Variables.")
    print("Note: The application uses the Environment Variables, not this file directly.")
else:
    print("\nWARNING: The credentials file content DOES NOT match your Environment Variables.")
    print("The application is using the Environment Variables. If the file is the source of truth, update your .env.")
