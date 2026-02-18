"""
Vector Store Interface and Implementations

# Unified vector store module with:
# - Abstract VectorStore interface
# - QdrantVectorStore (Primary - high-performance, scalable)
# - PostgresVectorStore (Fallback - self-hosted with pgvector)

"""
import os
import uuid
import time
import json
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Set, cast
from datetime import datetime

# Third-party imports (try/except for optional dependencies)
try:
    from langchain_core.documents import Document
    from langchain_core.embeddings import Embeddings
except ImportError:
    pass  # Handled in specific classes

try:
    from langchain_postgres import PGVector
except ImportError:
    pass

try:
    from sqlalchemy import create_engine, text
except ImportError:
    pass



try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qdrant_models
except ImportError:
    pass

from ....utils.config import Config, RAGConfig
from ....utils.logger import setup_logger
from .embedding_provider import EmbeddingProvider
from ....utils.encryption import encrypt_token, decrypt_token

logger = setup_logger(__name__)

# Sensitive metadata keys that should be encrypted in the vector store payload
SENSITIVE_METADATA_KEYS = {
    'title', 'subject', 'sender', 'sender_email', 'recipients', 
    'snippet', 'body', 'name', 'email', 'description', 'summary',
    'text', 'file_name', 'topic', 'reason'
}

def _encrypt_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Encrypt sensitive fields in a document payload."""
    if not payload:
        return payload
    
    new_payload = payload.copy()
    
    # Encrypt content if present
    if 'content' in new_payload and isinstance(new_payload['content'], str):
        new_payload['content'] = encrypt_token(new_payload['content'])
    
    # Encrypt sensitive metadata
    for key in SENSITIVE_METADATA_KEYS:
        if key in new_payload and isinstance(new_payload[key], str):
            new_payload[key] = encrypt_token(new_payload[key])
            
    return new_payload

def _decrypt_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Decrypt sensitive fields in a document payload."""
    if not payload:
        return payload
    
    new_payload = payload.copy()
    
    # Decrypt content
    if 'content' in new_payload and isinstance(new_payload['content'], str):
        new_payload['content'] = decrypt_token(new_payload['content'])
        
    # Decrypt sensitive metadata
    for key in SENSITIVE_METADATA_KEYS:
        if key in new_payload and isinstance(new_payload[key], str):
            new_payload[key] = decrypt_token(new_payload[key])
            
    return new_payload


class VectorStore(ABC):
    """Abstract interface for vector storage and retrieval."""
    
    @abstractmethod
    def add_document(self, doc_id: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Add a single document to the vector store."""
        pass
    
    @abstractmethod
    def add_documents(self, documents: List[Dict[str, Any]]) -> None:
        """Add multiple documents to the vector store."""
        pass
    
    @abstractmethod
    def search(self, query_embedding: List[float], k: int = 5, 
              filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Search for similar documents using query embedding."""
        pass
    
    @abstractmethod
    def search_by_text(self, query_text: str, k: int = 5, 
                      filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Search for similar documents using query text."""
        pass
    
    @abstractmethod
    def delete_document(self, doc_id: str) -> None:
        """Delete a document from the vector store."""
        pass
    
    @abstractmethod
    def document_exists(self, doc_id: str) -> bool:
        """Check if a document exists in the vector store."""
        pass
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get vector store statistics."""
        pass
    
    @abstractmethod
    def get_all_documents(self, batch_size: int = 100, max_docs: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieve all documents from the vector store in batches.
        
        Args:
            batch_size: Number of documents per batch
            max_docs: Maximum number of documents to retrieve (None for all)
            
        Returns:
            List of documents with 'id', 'content', and 'metadata' fields
        """
        pass


class PostgresVectorStore(VectorStore):
    """
    PostgreSQL vector store using pgvector via langchain-postgres.
    
    Production-ready with connection pooling and async support.
    """
    
    def __init__(self, db_url: str, collection_name: str, embedding_provider: EmbeddingProvider):
        """
        Initialize PostgreSQL vector store.
        
        Args:
            db_url: PostgreSQL connection URL
            collection_name: Collection/table name
            embedding_provider: Embedding provider instance
        """
        try:
            import langchain_postgres
        except ImportError:
            raise ImportError("langchain-postgres package is required for PostgreSQL vector store")
        
        self.db_url = db_url
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider
        
        # Create LangChain embeddings wrapper
        embeddings = self._create_langchain_embeddings(embedding_provider)
        
        # Initialize PGVector
        self.store = PGVector(
            embeddings=embeddings,
            connection=db_url,
            collection_name=collection_name,
            use_jsonb=True  # Use JSONB for metadata (faster queries)
        )
        
        logger.info(f"PostgreSQL vector store initialized (collection: {collection_name})")
    
    def _create_langchain_embeddings(self, provider: EmbeddingProvider):
        """Create LangChain embeddings wrapper from embedding provider."""
        
        class ProviderEmbeddings(Embeddings):
            def __init__(self, provider: EmbeddingProvider):
                self.provider = provider
            
            def embed_documents(self, texts: List[str]) -> List[List[float]]:
                return self.provider.encode_batch(texts)
            
            def embed_query(self, text: str) -> List[float]:
                return self.provider.encode_query(text)
        
        return ProviderEmbeddings(provider)
    
    def add_document(self, doc_id: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Add a single document to the vector store."""
        # Prepare encrypted document
        doc = Document(
            page_content=encrypt_token(content) if content else "",
            metadata=_encrypt_payload(metadata or {}),
            id=doc_id
        )
        self.store.add_documents([doc])
    
    def add_documents(self, documents: List[Dict[str, Any]]) -> None:
        """Add multiple documents to the vector store."""
        docs = [
            Document(
                page_content=doc['content'],
                metadata=doc.get('metadata', {}),
                id=doc.get('id', str(uuid.uuid4()))
            )
            for doc in documents
        ]
        self.store.add_documents(docs)
    
    def search(self, query_embedding: List[float], k: int = 5, 
              filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Search for similar documents using query embedding.
        
        Note: PGVector's similarity_search_with_score expects a query string.
        Since we can't reverse an embedding to text, this method is limited.
        Ideally, use search_by_text.
        """
        logger.warning("PostgresVectorStore.search called with embedding. This is inefficient/unsupported directly by PGVector wrapper. Use search_by_text if possible.")
        # We can't easily search by embedding with the high-level PGVector wrapper if it doesn't expose it directly
        # But we can try to use the underlying store if available, or just return empty/error
        # For now, we'll log a warning.
        return []
    
    def search_by_text(self, query_text: str, k: int = 5, 
                      filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Search using query text (PGVector's native method)."""
        results = self.store.similarity_search_with_score(query_text, k=k, filter=filters)
        
        formatted_results = []
        for doc, score in results:
            # Decrypt payload
            decrypted_metadata = _decrypt_payload(doc.metadata)
            decrypted_content = decrypt_token(doc.page_content)
            
            formatted_results.append({
                'content': decrypted_content,
                'metadata': decrypted_metadata,
                'distance': float(score),
                'id': doc.id if hasattr(doc, 'id') else None
            })
        
        return formatted_results
    
    def delete_document(self, doc_id: str) -> None:
        """Delete a document from the vector store."""
        self.store.delete([doc_id])
    
    def document_exists(self, doc_id: str) -> bool:
        """Check if a document exists."""
        try:
            # Try to get the document
            results = self.store.similarity_search(f"id:{doc_id}", k=1)
            return len(results) > 0
        except Exception:
            # Document search failed, assume doesn't exist
            return False
    
    def batch_document_exists(self, doc_ids: List[str]) -> Set[str]:
        """
        Check which documents exist in batch.
        
        Much more efficient than checking one-by-one.
        """
        if not doc_ids:
            return set()
        
        try:
            engine = create_engine(self.db_url)
            with engine.connect() as conn:
                # Query for existing document IDs in batch
                query = text("""
                    SELECT DISTINCT e.id
                    FROM langchain_pg_embedding e
                    JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                    WHERE c.name = :collection_name
                    AND e.id = ANY(:doc_ids)
                """)
                
                result = conn.execute(
                    query,
                    {
                        "collection_name": self.collection_name,
                        "doc_ids": doc_ids
                    }
                )
                
                existing_ids = {row[0] for row in result}
                
            logger.debug(f"Batch check: {len(existing_ids)}/{len(doc_ids)} documents exist")
            return existing_ids
            
        except Exception as e:
            logger.error(f"Error in batch_document_exists: {e}")
            # Fallback: check individually
            existing = set()
            for doc_id in doc_ids:
                if self.document_exists(doc_id):
                    existing.add(doc_id)
            return existing
    
    def get_stats(self) -> Dict[str, Any]:
        """Get vector store statistics."""
        try:
            engine = create_engine(self.db_url)
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT COUNT(*) 
                    FROM langchain_pg_embedding e
                    JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                    WHERE c.name = :collection_name
                """), {"collection_name": self.collection_name})
                count = result.scalar() or 0
            
            return {
                'backend': 'postgres',
                'collection_name': self.collection_name,
                'total_documents': count,
                'embedding_dimension': self.embedding_provider.get_dimension()
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {
                'backend': 'postgres',
                'collection_name': self.collection_name,
                'total_documents': 0
            }
    
    def get_all_documents(self, batch_size: int = 100, max_docs: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve all documents from PostgreSQL vector store in batches."""
        try:
            documents = []
            engine = create_engine(self.db_url)
            
            with engine.connect() as conn:
                # Get collection UUID first
                collection_result = conn.execute(
                    text("SELECT uuid FROM langchain_pg_collection WHERE name = :collection_name"),
                    {"collection_name": self.collection_name}
                )
                collection_row = collection_result.fetchone()
                if not collection_row:
                    logger.warning(f"Collection {self.collection_name} not found")
                    return []
                
                collection_uuid = collection_row[0]
                
                # Fetch documents in batches
                offset = 0
                while True:
                    limit = min(batch_size, max_docs - offset) if max_docs else batch_size
                    
                    result = conn.execute(text("""
                        SELECT id, document, cmetadata
                        FROM langchain_pg_embedding
                        WHERE collection_id = :collection_id
                        ORDER BY id
                        LIMIT :limit OFFSET :offset
                    """), {
                        "collection_id": collection_uuid,
                        "limit": limit,
                        "offset": offset
                    })
                    
                    batch = result.fetchall()
                    if not batch:
                        break
                    
                    for row in batch:
                        documents.append({
                            'id': row[0],
                            'content': row[1],
                            'metadata': row[2] if row[2] else {}
                        })
                    
                    offset += len(batch)
                    
                    if max_docs and offset >= max_docs:
                        break
                    
                    if len(batch) < batch_size:
                        break
            
            logger.info(f"Retrieved {len(documents)} documents from PostgreSQL vector store")
            return documents
            
        except Exception as e:
            logger.error(f"Failed to retrieve documents: {e}")
            return []




class QdrantVectorStore(VectorStore):
    """
    Qdrant vector store implementation.
    
    High-performance vector database with:
    - Advanced filtering
    - Scalable storage
    - Cloud and self-hosted options
    """
    
    def __init__(
        self,
        collection_name: str,
        embedding_provider: EmbeddingProvider,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        prefer_grpc: bool = False  # Qdrant Cloud free tier only supports REST, not gRPC
    ):
        """
        Initialize Qdrant vector store.
        
        Args:
            collection_name: Name of the collection
            embedding_provider: Embedding provider instance
            url: Qdrant URL (defaults to QDRANT_ENDPOINT env var)
            api_key: Qdrant API key (defaults to QDRANT_API_KEY env var)
            prefer_grpc: Whether to use gRPC (faster)
        """
        try:
            import qdrant_client
            from qdrant_client.http import models
        except ImportError:
            raise ImportError(
                "qdrant-client package is required. Install with: pip install qdrant-client"
            )
        
        self.collection_name = collection_name or "default"
        self.embedding_provider = embedding_provider
        self.models = models
        
        # Initialize client
        url = url or os.getenv("QDRANT_ENDPOINT")
        api_key = api_key or os.getenv("QDRANT_API_KEY")
        
        # If no URL, check if we should use local memory (for testing)
        if not url and not api_key:
            logger.warning("No Qdrant credentials found, using in-memory storage (not persistent!)")
            self.client = qdrant_client.QdrantClient(":memory:")
        else:
            self.client = qdrant_client.QdrantClient(
                url=url, 
                api_key=api_key,
                prefer_grpc=prefer_grpc
            )
        
        # Get embedding dimension
        self.embedding_dim = embedding_provider.get_dimension()
        
        # Ensure collection exists
        self._ensure_collection()
        
        logger.info(f"Connected to Qdrant collection: {self.collection_name}")
    
    def _ensure_collection(self):
        """Ensure collection exists with correct configuration."""
        try:
            collections = self.client.get_collections().collections
            exists = any(c.name == self.collection_name for c in collections)
            
            if not exists:
                logger.info(f"Creating Qdrant collection: {self.collection_name} (dim={self.embedding_dim})")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=self.models.VectorParams(
                        size=self.embedding_dim,
                        distance=self.models.Distance.COSINE
                    )
                )
        except Exception as e:
            logger.error(f"Failed to ensure Qdrant collection: {e}")
            raise

    def add_document(self, doc_id: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Add a single document to the vector store."""
        # Generate embedding using full content
        embedding = self.embedding_provider.encode(content)
        if hasattr(embedding, 'tolist'):
            embedding = embedding.tolist()
        
        # Limit content stored in payload to 100KB to avoid Qdrant 32MB payload limit
        # Full content is used for embedding generation above
        MAX_PAYLOAD_CONTENT = 100000  # 100KB
        stored_content = content[:MAX_PAYLOAD_CONTENT] if len(content) > MAX_PAYLOAD_CONTENT else content
        
        # Prepare payload
        payload = (metadata or {}).copy()
        payload['content'] = stored_content  # Limited content for payload storage
        payload['original_id'] = doc_id  # Store original ID for retrieval
        payload['indexed_at'] = datetime.utcnow().isoformat()
        
        # Encrypt payload before storage
        encrypted_payload = _encrypt_payload(payload)
        
        # Upsert
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                self.models.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id)) if not self._is_valid_uuid(doc_id) else doc_id,
                    vector=embedding,
                    payload=encrypted_payload
                )
            ]
        )
        logger.debug(f"Added document to Qdrant: {doc_id}")

    def add_documents(self, documents: List[Dict[str, Any]]) -> None:
        """Add multiple documents to the vector store."""
        if not documents:
            return
            
        points = []
        for doc in documents:
            content = doc.get('content', '')
            if not content:
                continue
                
            # Handle different content types
            if hasattr(content, 'text'):
                content_str = content.text
            else:
                content_str = str(content)
                
            doc_id = doc.get('id', str(uuid.uuid4()))
            
            # Generate embedding (if not already provided? usually provider handles batch)
            # Here we need batch encoding.
            # But wait, we iterate documents. 
            # Ideally we batch encode first.
            pass 
        
        # Efficient batch implementation
        contents = []
        valid_docs = []
        
        for doc in documents:
            content = doc.get('content', '')
            if hasattr(content, 'text'):
                content = content.text
            else:
                content = str(content)
                
            if content and content.strip():
                contents.append(content)
                valid_docs.append(doc)
                
        if not contents:
            return
            
        # Batch encode
        embeddings = self.embedding_provider.encode_batch(contents)
        embeddings = [emb.tolist() if hasattr(emb, 'tolist') else list(emb) for emb in embeddings]
        
        points = []
        for i, doc in enumerate(valid_docs):
            doc_id = doc.get('id', str(uuid.uuid4()))
            # Qdrant prefers UUIDs or integers. We'll use UUIDs.
            # If doc_id is not a valid UUID, we hash it to one.
            point_id = doc_id if self._is_valid_uuid(doc_id) else str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id))
            
            # Limit content stored in payload to 100KB to avoid Qdrant 32MB payload limit
            MAX_PAYLOAD_CONTENT = 100000  # 100KB
            stored_content = contents[i][:MAX_PAYLOAD_CONTENT] if len(contents[i]) > MAX_PAYLOAD_CONTENT else contents[i]
            
            payload = doc.get('metadata', {}).copy()
            payload['content'] = stored_content  # Limited content for payload storage
            payload['original_id'] = doc_id # Store original ID if we hashed it
            payload['indexed_at'] = datetime.utcnow().isoformat()
            
            # Encrypt payload
            encrypted_payload = _encrypt_payload(payload)
            
            points.append(self.models.PointStruct(
                id=point_id,
                vector=embeddings[i],
                payload=encrypted_payload
            ))
            
        # Batch upsert
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            try:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=batch
                )
            except Exception as e:
                logger.error(f"Batch upsert failed: {e}")
                
        logger.info(f"Added {len(points)} documents to Qdrant")

    def search(self, query_embedding: List[float], k: int = 5, 
               filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Search for similar documents using query embedding."""
        
        try:
            # Convert filters to Qdrant filter
            q_filter = self._build_qdrant_filter(filters) if filters else None
            
            # Use query_points instead of search (more robust/newer API)
            results = self.client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                limit=k,
                query_filter=q_filter,
                with_payload=True
            ).points
            
            formatted_results = []
            for res in results:
                payload = res.payload or {}
                # Decrypt payload
                decrypted_payload = _decrypt_payload(payload)
                decrypted_content = decrypted_payload.pop('content', '')
                original_id = decrypted_payload.pop('original_id', str(res.id))
                
                formatted_results.append({
                    'content': decrypted_content,
                    'metadata': decrypted_payload,
                    'distance': res.score, # Cosine similarity
                    'score': res.score,
                    'id': original_id
                })
                
            return formatted_results
            
        except Exception as e:
            # Handle empty collection or other API errors gracefully
            error_msg = str(e).lower()
            if '400' in error_msg or 'bad request' in error_msg or 'empty' in error_msg:
                logger.debug(f"Qdrant search returned no results (possibly empty collection): {e}")
            else:
                logger.warning(f"Qdrant search error: {e}")
            return []

    def search_by_text(self, query_text: str, k: int = 5, 
                      filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Search using query text."""
        query_embedding = self.embedding_provider.encode_query(query_text)
        return self.search(query_embedding, k, filters)

    def delete_document(self, doc_id: str) -> None:
        """Delete a document."""
        # We need to handle the ID conversion again
        point_id = doc_id if self._is_valid_uuid(doc_id) else str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id))
        
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=self.models.PointIdsList(
                points=[point_id]
            )
        )

    def document_exists(self, doc_id: str) -> bool:
        """Check if document exists."""
        point_id = doc_id if self._is_valid_uuid(doc_id) else str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id))
        
        points = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[point_id]
        )
        return len(points) > 0

    def get_stats(self) -> Dict[str, Any]:
        """Get stats."""
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                'backend': 'qdrant',
                'collection_name': self.collection_name,
                'total_documents': info.points_count,
                'status': str(info.status)
            }
        except Exception as e:
            return {'error': str(e)}

    def get_all_documents(self, batch_size: int = 100, max_docs: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve all documents via scroll."""
        documents = []
        next_offset = None
        current_count = 0
        
        while True:
            # Calculate limit
            limit = batch_size
            if max_docs and (current_count + limit > max_docs):
                limit = max_docs - current_count
                
            if limit <= 0:
                break
                
            points, next_offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=limit,
                offset=next_offset,
                with_payload=True
            )
            
            for point in points:
                payload = point.payload or {}
                documents.append({
                    'id': payload.get('original_id', str(point.id)),
                    'content': payload.get('content', ''),
                    'metadata': payload
                })
                
            current_count += len(points)
            
            if next_offset is None or (max_docs and current_count >= max_docs):
                break
                
        return documents

    def _is_valid_uuid(self, val: str) -> bool:
        try:
            uuid.UUID(str(val))
            return True
        except ValueError:
            return False

    def _build_qdrant_filter(self, filters: Dict[str, Any]):
        """Convert simple dict filters to Qdrant Filter."""
        if not filters:
            return None
            
        conditions = []
        for key, value in filters.items():
            # Handle simple direct matches
            if isinstance(value, (str, int, bool)):
                conditions.append(
                    self.models.FieldCondition(
                        key=key,
                        match=self.models.MatchValue(value=value)
                    )
                )
            elif isinstance(value, list):
                conditions.append(
                    self.models.FieldCondition(
                        key=key,
                        match=self.models.MatchAny(any=value)
                    )
                )
        
        return self.models.Filter(must=conditions)


def create_vector_store(config: Config, rag_config: Optional[RAGConfig], 
                       embedding_provider: EmbeddingProvider, 
                       collection_name: Optional[str] = None) -> VectorStore:
    """
    Factory function to create appropriate vector store.
    
    Priority: Qdrant (primary) → PostgreSQL (fallback)
    
    Args:
        config: Application configuration
        rag_config: RAG configuration
        embedding_provider: Embedding provider instance
        collection_name: Optional collection name override
        
    Returns:
        VectorStore instance
        
    Raises:
        ValueError: If no valid vector store is configured
    """
    if rag_config is None:
        rag_config = RAGConfig()
    
    collection = collection_name or rag_config.collection_name
    backend = rag_config.vector_store_backend.lower()
    
    # Determine backend
    if backend == "auto":
        # Priority: Qdrant > PostgreSQL
        if os.getenv('QDRANT_API_KEY') or os.getenv('QDRANT_ENDPOINT'):
            backend = "qdrant"
            logger.info("Auto-detected Qdrant (QDRANT_API_KEY/ENDPOINT found)")
        else:
            db_url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL') or (config.database.url if hasattr(config, 'database') else None)
            if db_url and 'postgresql' in db_url:
                backend = "postgres"
                logger.info("Auto-detected PostgreSQL (DATABASE_URL found)")
            else:
                logger.error("No vector store configured! Please set QDRANT_API_KEY or DATABASE_URL")
                raise ValueError("No vector store configured.")
    
    # Create Qdrant (PRIMARY)
    if backend == "qdrant":
        try:
            return QdrantVectorStore(
                collection_name=collection,
                embedding_provider=embedding_provider
            )
        except Exception as e:
            logger.warning(f"Qdrant initialization failed: {e}, falling back to PostgreSQL")
            # Fallback to PostgreSQL
            db_url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL') or (config.database.url if hasattr(config, 'database') else None)
            if db_url and 'postgresql' in db_url:
                try:
                    logger.info(f"Using PostgreSQL vector store as fallback (collection={collection})")
                    return PostgresVectorStore(db_url, collection, embedding_provider)
                except Exception as pg_error:
                    logger.error(f"PostgreSQL fallback also failed: {pg_error}")
                    raise ValueError("Both Qdrant and PostgreSQL initialization failed")
            else:
                logger.error("PostgreSQL fallback not available (DATABASE_URL not configured)")
                raise ValueError(f"Qdrant initialization failed: {e}")
    
    # Create PostgreSQL (FALLBACK)
    elif backend == "postgres":
        db_url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL') or (config.database.url if hasattr(config, 'database') else None)
        if not db_url or 'postgresql' not in db_url:
            logger.error("PostgreSQL requested but DATABASE_URL not configured")
            raise ValueError("PostgreSQL URL not found")
        
        try:
            logger.info(f"Using PostgreSQL vector store (collection={collection})")
            return PostgresVectorStore(db_url, collection, embedding_provider)
        except Exception as e:
            logger.error(f"PostgreSQL initialization failed: {e}")
            raise ValueError(f"PostgreSQL initialization failed: {e}")
            
    else:
        # Invalid backend specified
        logger.error(f"Invalid vector store backend: {backend}. Use 'auto', 'qdrant', or 'postgres'")
        raise ValueError(f"Invalid vector store backend: {backend}. Supported: 'auto', 'qdrant', 'postgres'")

