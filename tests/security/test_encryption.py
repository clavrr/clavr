"""
Security Verification Tests - Encryption at Rest
Verifies that sensitive data is correctly encrypted in SQL, Vector DB, Knowledge Graph, and Filesystem.
"""
import pytest
import os
import json
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import User, Session as DBSession
from src.database.types import EncryptedString
from src.utils.encryption import get_encryption
from src.utils.file_encryption import save_encrypted_json, load_encrypted_json
from src.ai.rag.core.vector_store import VectorStore
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import GraphSchema

@pytest.mark.asyncio
async def test_sql_encryption(db_session: AsyncSession):
    """Verify that sensitive SQL fields are encrypted in the database."""
    # 1. Create a user with sensitive data
    test_email = "sensitive@example.com"
    test_name = "Sensitive User"
    user = User(email=test_email, name=test_name)
    db_session.add(user)
    await db_session.commit()
    
    # 2. Check the raw value in the database (bypass SQLAlchemy type)
    # We use a raw SQL query to see the actual stored string
    from sqlalchemy import text
    result = await db_session.execute(text(f"SELECT email, name FROM users WHERE id = {user.id}"))
    raw_row = result.fetchone()
    
    # 3. Verify that the values are encrypted (should start with Fernet prefix or not be the plaintext)
    # Note: Depending on how the DB driver works, we might see the decrypted value if we use SQLAlchemy models.
    # Raw SQL should show the encrypted string if the underlying column type is String/Text.
    raw_email = raw_row[0]
    raw_name = raw_row[1]
    
    assert raw_email != test_email
    assert raw_name != test_name
    assert raw_email.startswith("gAAAA") # Fernet token prefix
    
    # 4. Verify that SQLAlchemy handles decryption transparently
    stmt = select(User).where(User.id == user.id)
    result = await db_session.execute(stmt)
    loaded_user = result.scalar_one()
    
    assert loaded_user.email == test_email
    assert loaded_user.name == test_name


@pytest.mark.asyncio
async def test_vector_payload_encryption():
    """Verify that vector document content is encrypted."""
    # This test requires a running ChromaDB or a mock
    # For now, we'll verify the encryption logic within VectorStore
    store = VectorStore(collection_name="test_encryption")
    
    original_content = "This is a very sensitive document about project X."
    metadata = {"source": "internal", "author": "secret"}
    
    # 1. Add document (this should encrypt content)
    await store.add_documents(
        texts=[original_content],
        metadatas=[metadata],
        ids=["test_1"]
    )
    
    # 2. Access the underlying collection directly to see "raw" data
    # Chroma stores data in its own format. We'll use get() to retrieve it.
    results = store.collection.get(ids=["test_1"], include=["documents", "metadatas"])
    
    stored_content = results["documents"][0]
    
    # 3. Verify content is encrypted
    assert stored_content != original_content
    assert stored_content.startswith("gAAAA")
    
    # 4. Search and retrieve (should be transparently decrypted)
    retrieved = await store.similarity_search("project X", k=1)
    assert retrieved[0].page_content == original_content


@pytest.mark.asyncio
async def test_graph_property_encryption():
    """Verify that sensitive graph properties are encrypted."""
    # Requires ArangoDB access
    manager = KnowledgeGraphManager()
    schema = GraphSchema()
    
    test_node_id = "test_node_1"
    sensitive_props = {
        "content": "Secret graph data",
        "email_body": "Top secret email content",
        "non_sensitive": "Public info"
    }
    
    # 1. Upsert node (should encrypt sensitive props)
    await manager.upsert_node("TestNode", test_node_id, sensitive_props)
    
    # 2. Get node directly from DB (bypassing decryption)
    # We'll use a raw AQL query
    query = "FOR doc IN TestNode FILTER doc._key == @key RETURN doc"
    cursor = await manager.db.aql.execute(query, bind_vars={"key": test_node_id})
    raw_node = cursor.next()
    
    # 3. Verify sensitive properties are encrypted
    assert raw_node["content"] != sensitive_props["content"]
    assert raw_node["email_body"] != sensitive_props["email_body"]
    assert raw_node["content"].startswith("gAAAA")
    
    # 4. Verify non-sensitive properties are NOT encrypted
    assert raw_node["non_sensitive"] == sensitive_props["non_sensitive"]
    
    # 5. Retrieve via manager (should be decrypted)
    node = await manager.get_node("TestNode", test_node_id)
    assert node["content"] == sensitive_props["content"]
    assert node["email_body"] == sensitive_props["email_body"]


def test_filesystem_encryption(tmp_path):
    """Verify that sensitive JSON files are encrypted on disk."""
    file_path = tmp_path / "sensitive.json"
    data = {"secret_key": "secret_value", "nested": {"data": 123}}
    
    # 1. Save encrypted
    save_encrypted_json(file_path, data)
    
    # 2. Read raw file content
    with open(file_path, 'r') as f:
        raw_content = f.read()
    
    # 3. Verify it's not JSON and is a Fernet token
    assert "secret_key" not in raw_content
    assert raw_content.startswith("gAAAA")
    
    # 4. Load via utility (should be decrypted)
    loaded_data = load_encrypted_json(file_path)
    assert loaded_data == data
