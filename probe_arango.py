import asyncio
from arango import ArangoClient
import os

async def probe():
    uri = 'http://localhost:8529'
    passwords = ['', 'password', 'root', 'arangodb']
    user = 'root'
    db_name = 'clavr'
    
    print(f"Probing ArangoDB at {uri}...")
    client = ArangoClient(hosts=uri)
    
    for pwd in passwords:
        try:
            print(f"Trying user={user}, password='{pwd}'...")
            sys_db = client.db('_system', username=user, password=pwd)
            # Try to list databases to verify auth
            dbs = sys_db.databases()
            print(f"✅ Success with password: '{pwd}'")
            print(f"Databases: {dbs}")
            return
        except Exception as e:
            print(f"❌ Failed with password '{pwd}': {e}")

if __name__ == "__main__":
    asyncio.run(probe())
