"""
Vector Store Interface and Implementations

Unified vector store module with:
- Abstract VectorStore interface
- PineconeVectorStore (Primary - cloud-native, fully managed)
- PostgresVectorStore (Fallback - self-hosted with pgvector)

ChromaDB has been removed - use Pinecone for production or PostgreSQL for self-hosted.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Set, cast
from datetime import datetime
import os
import uuid
import time

from langchain_core.documents import Document

from ....utils.config import Config, RAGConfig
from ....utils.logger import setup_logger
from .embedding_provider import EmbeddingProvider

logger = setup_logger(__name__)


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
            from langchain_postgres import PGVector
            from langchain_core.embeddings import Embeddings
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
        from langchain_core.embeddings import Embeddings
        
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
        doc = Document(
            page_content=content,
            metadata=metadata or {},
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
        
        Note: PGVector's similarity_search_with_score expects a query string,
        not an embedding. This method is not directly supported for PostgreSQL.
        Use search_by_text() instead, or let RAGEngine handle the conversion.
        """
        # PGVector uses query text and embeds it internally
        # This method signature is for compatibility with the abstract interface
        # RAGEngine will call search_by_text() for PostgreSQL stores
        logger.debug("Direct embedding search not supported by PGVector, use search_by_text instead")
        return []
    
    def search_by_text(self, query_text: str, k: int = 5, 
                      filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Search using query text (PGVector's native method)."""
        results = self.store.similarity_search_with_score(query_text, k=k, filter=filters)
        
        formatted_results = []
        for doc, score in results:
            formatted_results.append({
                'content': doc.page_content,
                'metadata': doc.metadata,
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
        except:
            return False
    
    def batch_document_exists(self, doc_ids: List[str]) -> Set[str]:
        """
        Check which documents exist in batch.
        
        Much more efficient than checking one-by-one.
        
        Args:
            doc_ids: List of document IDs to check
            
        Returns:
            Set of document IDs that exist in the vector store
        """
        if not doc_ids:
            return set()
        
        try:
            from sqlalchemy import create_engine, text
            
            engine = create_engine(self.db_url)
            with engine.connect() as conn:
                # Query for existing document IDs in batch
                # Using ANY for efficient PostgreSQL array containment
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
            from sqlalchemy import create_engine, text
            
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
            from sqlalchemy import create_engine, text
            
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


class PineconeVectorStore(VectorStore):
    """
    Pinecone vector store implementation (PRIMARY).
    
    Cloud-native, fully managed vector database with:
    - Auto-scaling for high performance
    - Built-in replication and backups  
    - Advanced metadata filtering
    - High availability (99.9% uptime SLA)
    - Native hybrid search support
    
    Best for: Production deployments with large-scale data (100K+ vectors)
    """
    
    def __init__(
        self,
        index_name: str,
        embedding_provider: EmbeddingProvider,
        api_key: Optional[str] = None,
        environment: Optional[str] = None,
        namespace: Optional[str] = None,
        metric: str = "cosine"
    ):
        """
        Initialize Pinecone vector store.
        
        Args:
            index_name: Name of the Pinecone index
            embedding_provider: Embedding provider instance
            api_key: Pinecone API key (defaults to PINECONE_API_KEY env var)
            environment: Pinecone environment (defaults to PINECONE_ENVIRONMENT env var)
            namespace: Optional namespace for data isolation (multi-tenancy)
            metric: Distance metric ("cosine", "euclidean", or "dotproduct")
        """
        try:
            from pinecone import Pinecone, ServerlessSpec
        except ImportError:
            raise ImportError(
                "pinecone package is required. Install with: pip install pinecone"
            )
        
        self.index_name = index_name
        self.embedding_provider = embedding_provider
        self.namespace = namespace or "default"
        self.metric = metric
        
        # Initialize Pinecone
        api_key = api_key or os.getenv("PINECONE_API_KEY")
        if not api_key:
            raise ValueError("Pinecone API key is required (set PINECONE_API_KEY env var)")
        
        self.pc = Pinecone(api_key=api_key)
        
        # Get embedding dimension
        embedding_dim = embedding_provider.get_dimension()
        
        # Create or connect to index
        try:
            # Check if index exists
            existing_indexes = self.pc.list_indexes()
            index_exists = any(idx['name'] == index_name for idx in existing_indexes)
            
            if not index_exists:
                logger.info(f"Creating Pinecone index: {index_name} (dimension={embedding_dim})")
                
                # Create serverless index (recommended for most use cases)
                self.pc.create_index(
                    name=index_name,
                    dimension=embedding_dim,
                    metric=metric,
                    spec=ServerlessSpec(
                        cloud='aws',  # Can be 'aws', 'gcp', or 'azure'
                        region=os.getenv('PINECONE_REGION', 'us-east-1')
                    )
                )
                
                # Wait for index to be ready
                logger.info("Waiting for index to be ready...")
                time.sleep(10)  # Initial wait
                
            self.index = self.pc.Index(index_name)
            logger.info(f"Connected to Pinecone index: {index_name} (namespace={self.namespace})")
            
        except Exception as e:
            logger.error(f"Failed to initialize Pinecone index: {e}")
            raise
    
    def add_document(self, doc_id: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Add a single document to the vector store."""
        # Generate embedding
        embedding = self.embedding_provider.encode(content)
        if hasattr(embedding, 'tolist'):
            embedding = embedding.tolist()
        
        # Prepare metadata (Pinecone supports nested metadata)
        meta = (metadata or {}).copy()
        
        # Truncate content if it's too large (max 10KB for metadata)
        max_content_bytes = 10000
        content_str = content
        if len(content_str.encode('utf-8')) > max_content_bytes:
            # Truncate at word boundary
            truncated = content_str[:max_content_bytes - 100]
            last_space = truncated.rfind(' ')
            if last_space > max_content_bytes // 2:
                content_str = truncated[:last_space] + '...'
            else:
                content_str = truncated + '...'
            logger.warning(f"Truncated content in metadata for {doc_id} to {max_content_bytes} bytes")
        
        meta['content'] = content_str  # Store content in metadata for retrieval
        meta['indexed_at'] = datetime.utcnow().isoformat()
        
        # Validate and truncate metadata to stay under Pinecone's 40KB limit
        meta = self._truncate_metadata(meta, max_bytes=40000)
        
        # Upsert to Pinecone
        self.index.upsert(
            vectors=[(doc_id, embedding, meta)],
            namespace=self.namespace
        )
        
        logger.debug(f"Added document to Pinecone: {doc_id}")
    
    def _truncate_metadata(self, metadata: Dict[str, Any], max_bytes: int = 40000) -> Dict[str, Any]:
        """
        Truncate metadata to stay under Pinecone's size limit (40KB).
        
        Args:
            metadata: Metadata dictionary to truncate
            max_bytes: Maximum size in bytes (default 40KB for Pinecone)
            
        Returns:
            Truncated metadata dictionary
        """
        import json
        
        # Calculate current size
        try:
            current_size = len(json.dumps(metadata, ensure_ascii=False).encode('utf-8'))
        except Exception:
            # Fallback: estimate size
            current_size = sum(len(str(v).encode('utf-8')) for v in metadata.values())
        
        if current_size <= max_bytes:
            return metadata
        
        # Metadata is too large - need to truncate
        logger.warning(f"Metadata size ({current_size} bytes) exceeds limit ({max_bytes} bytes), truncating...")
        
        # Make a copy to avoid modifying original
        truncated_meta = metadata.copy()
        
        # First, remove or truncate the largest fields immediately
        # Priority order for truncation (truncate less important fields first)
        truncation_order = [
            'body',  # Full email body (if present) - least important in metadata
            'content',  # Content field (already truncated, but may still be large)
            'searchable_text',  # Searchable text (if present)
            'text',  # Text content
            'html',  # HTML content
            'raw_body',  # Raw body content
        ]
        
        # Remove large fields first
        for field in truncation_order:
            if field in truncated_meta:
                del truncated_meta[field]
                logger.debug(f"Removed large metadata field '{field}'")
        
        # Recalculate size after removal
        try:
            current_size = len(json.dumps(truncated_meta, ensure_ascii=False).encode('utf-8'))
        except Exception:
            current_size = sum(len(str(v).encode('utf-8')) for v in truncated_meta.values())
        
        # If still too large, truncate remaining string fields
        if current_size > max_bytes:
            # Truncate string fields in order of importance
            string_fields_to_truncate = [
                'subject',  # Subject line (truncate if very long)
                'sender',  # Sender (usually small, but truncate if needed)
                'to',  # Recipient
                'recipient',  # Recipient
                'cc',  # CC
                'bcc',  # BCC
            ]
            
            for field in string_fields_to_truncate:
                if field not in truncated_meta:
                    continue
                
                value = truncated_meta[field]
                if isinstance(value, str):
                    # Truncate string fields to max 2KB each
                    max_field_bytes = 2000
                    if len(value.encode('utf-8')) > max_field_bytes:
                        truncated = value[:max_field_bytes - 100]
                        last_space = truncated.rfind(' ')
                        if last_space > max_field_bytes // 2:
                            truncated_meta[field] = truncated[:last_space] + '...'
                        else:
                            truncated_meta[field] = truncated + '...'
                        logger.debug(f"Truncated metadata field '{field}' to {max_field_bytes} bytes")
                
                # Recalculate size
                try:
                    current_size = len(json.dumps(truncated_meta, ensure_ascii=False).encode('utf-8'))
                except Exception:
                    current_size = sum(len(str(v).encode('utf-8')) for v in truncated_meta.values())
                
                if current_size <= max_bytes:
                    break
        
        # If still too large, truncate ALL string fields aggressively
        if current_size > max_bytes:
            logger.warning(f"Metadata still too large ({current_size} bytes), applying aggressive truncation to all fields")
            for key, value in list(truncated_meta.items()):
                if isinstance(value, str):
                    # Truncate to 500 bytes max per field
                    if len(value.encode('utf-8')) > 500:
                        truncated_meta[key] = value[:500] + '...'
                elif isinstance(value, (list, dict)):
                    # Truncate lists/dicts by converting to string and truncating
                    str_value = json.dumps(value, ensure_ascii=False)
                    if len(str_value.encode('utf-8')) > 500:
                        truncated_meta[key] = json.loads(str_value[:500] + '...')
            
            # Recalculate final size
            try:
                current_size = len(json.dumps(truncated_meta, ensure_ascii=False).encode('utf-8'))
            except Exception:
                current_size = sum(len(str(v).encode('utf-8')) for v in truncated_meta.values())
        
        # Final safety check - if STILL too large, keep only essential fields
        if current_size > max_bytes:
            logger.error(f"Metadata still exceeds limit ({current_size} bytes), keeping only essential fields")
            essential_fields = ['id', 'chunk_type', 'chunk_index', 'parent_doc_id', 'indexed_at']
            essential_meta = {k: v for k, v in truncated_meta.items() if k in essential_fields}
            # Add truncated content if needed
            if 'content' in truncated_meta:
                content = truncated_meta['content']
                if isinstance(content, str):
                    # Keep only first 5000 bytes of content
                    essential_meta['content'] = content[:5000] + '...' if len(content.encode('utf-8')) > 5000 else content
            truncated_meta = essential_meta
            current_size = len(json.dumps(truncated_meta, ensure_ascii=False).encode('utf-8'))
        
        try:
            original_size = len(json.dumps(metadata, ensure_ascii=False).encode('utf-8'))
        except Exception:
            original_size = sum(len(str(v).encode('utf-8')) for v in metadata.values())
        
        logger.info(f"Metadata truncated from {original_size} to {current_size} bytes")
        return truncated_meta
    
    def add_documents(self, documents: List[Dict[str, Any]]) -> None:
        """Add multiple documents to the vector store (batch operation)."""
        if not documents:
            return
        
        # Extract contents and filter out empty content
        # Extract text content - handle both Chunk objects and strings
        contents = []
        valid_doc_indices = []  # Track which documents have non-empty content
        
        for i, doc in enumerate(documents):
            content = doc['content']
            # If it's a Chunk object, extract the text property
            if hasattr(content, 'text'):
                content_str = content.text
            elif isinstance(content, str):
                content_str = content
            else:
                # Fallback: convert to string
                content_str = str(content)
            
            # Filter out empty or whitespace-only content
            if content_str and content_str.strip():
                contents.append(content_str)
                valid_doc_indices.append(i)
            else:
                doc_id = doc.get('id', f"doc_{i}")
                logger.warning(f"Skipping document {doc_id} with empty content (chunk_index={doc.get('metadata', {}).get('chunk_index', 'unknown')})")
        
        if not contents:
            logger.warning("All documents had empty content, nothing to index")
            return
        
        # Batch encode embeddings only for non-empty content
        embeddings = self.embedding_provider.encode_batch(contents)
        embeddings = [
            emb.tolist() if hasattr(emb, 'tolist') else list(emb)
            for emb in embeddings
        ]
        
        # Prepare vectors for upsert (only for documents with valid content)
        vectors = []
        for emb_idx, doc_idx in enumerate(valid_doc_indices):
            doc = documents[doc_idx]
            doc_id = doc.get('id', f"doc_{doc_idx}_{int(time.time())}")
            meta = doc.get('metadata', {}).copy()  # Make a copy to avoid modifying original
            
            # Store content in metadata (needed for retrieval), but truncate if too large
            content_value = doc['content']
            if hasattr(content_value, 'text'):
                content_str = content_value.text
            elif isinstance(content_value, str):
                content_str = content_value
            else:
                content_str = str(content_value)
            
            # Truncate content if it's too large (max 10KB for metadata)
            max_content_bytes = 10000
            if len(content_str.encode('utf-8')) > max_content_bytes:
                # Truncate at word boundary
                truncated = content_str[:max_content_bytes - 100]
                last_space = truncated.rfind(' ')
                if last_space > max_content_bytes // 2:
                    content_str = truncated[:last_space] + '...'
                else:
                    content_str = truncated + '...'
                logger.warning(f"Truncated content in metadata for {doc_id} from {len(content_str.encode('utf-8'))} to {max_content_bytes} bytes")
            
            meta['content'] = content_str
            meta['indexed_at'] = datetime.utcnow().isoformat()
            
            # Validate and truncate metadata to stay under Pinecone's 40KB limit
            meta = self._truncate_metadata(meta, max_bytes=40000)
            
            # Final safety check - verify metadata size before adding to batch
            import json
            try:
                final_size = len(json.dumps(meta, ensure_ascii=False).encode('utf-8'))
                if final_size > 40000:
                    logger.error(f"Metadata still too large ({final_size} bytes) after truncation for {doc_id}, applying emergency truncation")
                    # Emergency: keep only absolute essentials
                    meta = {
                        'id': meta.get('id', doc_id),
                        'chunk_type': meta.get('chunk_type', 'unknown'),
                        'indexed_at': meta.get('indexed_at', datetime.utcnow().isoformat())
                    }
                    # Add minimal content if needed (max 5KB)
                    if 'content' in doc.get('metadata', {}):
                        content = str(doc.get('metadata', {}).get('content', ''))[:5000]
                        meta['content'] = content
            except Exception as e:
                logger.warning(f"Error validating metadata size for {doc_id}: {e}")
            
            vectors.append((doc_id, embeddings[emb_idx], meta))
        
        # Batch upsert (Pinecone recommends batches of 100-200)
        batch_size = 100
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            try:
                self.index.upsert(vectors=batch, namespace=self.namespace)
            except Exception as e:
                # If batch fails due to metadata size, try individual upserts with emergency truncation
                if 'Metadata size' in str(e) or 'exceeds the limit' in str(e):
                    logger.error(f"Batch upsert failed due to metadata size, retrying with emergency truncation")
                    for vec_id, vec_emb, vec_meta in batch:
                        try:
                            # Emergency truncation for this vector
                            emergency_meta = {
                                'id': vec_meta.get('id', vec_id),
                                'chunk_type': vec_meta.get('chunk_type', 'unknown'),
                                'indexed_at': vec_meta.get('indexed_at', datetime.utcnow().isoformat())
                            }
                            # Add minimal content (max 5KB)
                            if 'content' in vec_meta:
                                content = str(vec_meta['content'])[:5000]
                                emergency_meta['content'] = content
                            self.index.upsert(vectors=[(vec_id, vec_emb, emergency_meta)], namespace=self.namespace)
                        except Exception as vec_error:
                            logger.error(f"Failed to upsert vector {vec_id}: {vec_error}")
                else:
                    raise
        
        indexed_count = len(vectors)
        if indexed_count < len(documents):
            logger.info(f"Added {indexed_count}/{len(documents)} documents to Pinecone (namespace={self.namespace}) - {len(documents) - indexed_count} empty chunks filtered out")
        else:
            logger.info(f"Added {indexed_count} documents to Pinecone (namespace={self.namespace})")
    
    def search(
        self,
        query_embedding: List[float],
        k: int = 5,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar documents using query embedding.
        
        Args:
            query_embedding: Query vector
            k: Number of results to return
            filters: Metadata filters (Pinecone supports complex filtering)
                     Example: {"user_id": "123", "created_at": {"$gte": "2024-01-01"}}
        
        Returns:
            List of search results with content, metadata, and scores
        """
        # Query Pinecone
        results = self.index.query(
            vector=query_embedding,
            top_k=k,
            namespace=self.namespace,
            filter=filters,
            include_metadata=True
        )
        
        # Format results
        formatted_results = []
        matches = getattr(results, 'matches', []) or []
        
        for match in matches:
            # Extract data - handle both response object and dict formats
            if hasattr(match, 'metadata'):
                # Response object format (Pinecone v3+)
                metadata = dict(match.metadata) if match.metadata else {}
                score = float(match.score)
                match_id = str(getattr(match, 'id'))
            else:
                # Dict format (legacy)
                metadata = dict(match.get('metadata', {})) if hasattr(match, 'get') else {}
                score = float(match.get('score', 0))
                match_id = str(match.get('id', ''))
            
            content = metadata.pop('content', '')
            
            formatted_results.append({
                'content': content,
                'metadata': metadata,
                'distance': 1 - score,  # Convert similarity to distance
                'score': score,  # Similarity score (0-1)
                'id': match_id
            })
        
        return formatted_results
    
    def delete_document(self, doc_id: str) -> None:
        """Delete a document from the vector store."""
        self.index.delete(ids=[doc_id], namespace=self.namespace)
        logger.debug(f"Deleted document from Pinecone: {doc_id}")
    
    def delete_documents(self, doc_ids: List[str]) -> None:
        """Delete multiple documents (batch operation)."""
        self.index.delete(ids=doc_ids, namespace=self.namespace)
        logger.info(f"Deleted {len(doc_ids)} documents from Pinecone")
    
    def document_exists(self, doc_id: str) -> bool:
        """Check if a document exists."""
        try:
            result = self.index.fetch(ids=[doc_id], namespace=self.namespace)
            vectors = result.vectors if hasattr(result, 'vectors') else result.get('vectors', {})
            return doc_id in vectors
        except Exception as e:
            logger.error(f"Error checking document existence: {e}")
            return False
    
    def batch_document_exists(self, doc_ids: List[str]) -> Set[str]:
        """
        Check which documents exist in the vector store (batch operation).
        
        Much more efficient than calling document_exists() individually.
        Pinecone's fetch API supports up to 1000 IDs at once.
        
        Args:
            doc_ids: List of document IDs to check
            
        Returns:
            Set of document IDs that exist in the vector store
        """
        if not doc_ids:
            return set()
        
        existing_ids = set()
        
        try:
            # Pinecone fetch supports up to 1000 IDs per request
            batch_size = 1000
            
            for i in range(0, len(doc_ids), batch_size):
                batch = doc_ids[i:i + batch_size]
                
                try:
                    result = self.index.fetch(ids=batch, namespace=self.namespace)
                    
                    # Extract existing IDs from result
                    vectors = result.vectors if hasattr(result, 'vectors') else result.get('vectors', {})
                    existing_ids.update(vectors.keys())
                    
                except Exception as e:
                    logger.error(f"Error in batch fetch (batch {i//batch_size + 1}): {e}")
                    # Continue with next batch instead of failing completely
                    continue
            
            logger.debug(f"Batch check: {len(existing_ids)}/{len(doc_ids)} documents exist")
            return existing_ids
            
        except Exception as e:
            logger.error(f"Error in batch_document_exists: {e}")
            # Fallback to individual checks
            logger.warning("Falling back to individual document checks")
            for doc_id in doc_ids:
                if self.document_exists(doc_id):
                    existing_ids.add(doc_id)
            return existing_ids
    
    def get_stats(self) -> Dict[str, Any]:
        """Get vector store statistics."""
        try:
            stats = self.index.describe_index_stats()
            
            # Handle both response object and dict formats
            if hasattr(stats, 'namespaces'):
                namespaces = stats.namespaces or {}
                namespace_stats = namespaces.get(self.namespace, None)
                
                return {
                    'backend': 'pinecone',
                    'index_name': self.index_name,
                    'namespace': self.namespace,
                    'total_documents': namespace_stats.vector_count if namespace_stats else 0,
                    'embedding_dimension': stats.dimension if hasattr(stats, 'dimension') else self.embedding_provider.get_dimension(),
                    'index_fullness': stats.index_fullness if hasattr(stats, 'index_fullness') else 0,
                    'total_vector_count': stats.total_vector_count if hasattr(stats, 'total_vector_count') else 0
                }
            else:
                # Dict format (older versions)
                namespace_stats = stats.get('namespaces', {}).get(self.namespace, {})
                
                return {
                    'backend': 'pinecone',
                    'index_name': self.index_name,
                    'namespace': self.namespace,
                    'total_documents': namespace_stats.get('vector_count', 0),
                    'embedding_dimension': stats.get('dimension', self.embedding_provider.get_dimension()),
                    'index_fullness': stats.get('index_fullness', 0),
                    'total_vector_count': stats.get('total_vector_count', 0)
                }
        except Exception as e:
            logger.error(f"Failed to get Pinecone stats: {e}")
            return {
                'backend': 'pinecone',
                'index_name': self.index_name,
                'namespace': self.namespace,
                'total_documents': 0,
                'error': str(e)
            }
    
    def get_all_documents(self, batch_size: int = 100, max_docs: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieve all documents from Pinecone vector store.
        
        Note: Pinecone doesn't support direct pagination/scanning.
        This uses a dummy query to retrieve top-k documents.
        
        Args:
            batch_size: Not used for Pinecone
            max_docs: Maximum number of documents to retrieve (None for all, max 10000)
            
        Returns:
            List of documents with 'id', 'content', and 'metadata' fields
        """
        try:
            # Create a dummy vector for querying
            dummy_vector = [0.0] * self.embedding_provider.get_dimension()
            
            # Query to get results (top_k limited to 10000 in Pinecone)
            top_k = min(max_docs if max_docs else 10000, 10000)
            
            results = self.index.query(
                vector=dummy_vector,
                top_k=top_k,
                namespace=self.namespace,
                include_metadata=True
            )
            
            documents = []
            # Handle both response object and dict formats
            matches_list: List[Any] = []
            if hasattr(results, 'matches'):
                matches_list = results.matches or []
            elif isinstance(results, dict):
                # Dict format (legacy) - explicitly cast for type safety
                results_dict = cast(Dict[str, Any], results)
                matches_list = results_dict.get('matches', [])
            
            for match in matches_list:
                # Extract ID and metadata from match
                if hasattr(match, 'id'):
                    # Response object format
                    doc_id = str(getattr(match, 'id'))
                    metadata = dict(match.metadata) if hasattr(match, 'metadata') and match.metadata else {}
                elif hasattr(match, 'get'):
                    # Dict format
                    doc_id = str(match.get('id', ''))
                    metadata = dict(match.get('metadata', {}))
                else:
                    continue
                
                content = metadata.pop('content', '')
                
                documents.append({
                    'id': doc_id,
                    'content': content,
                    'metadata': metadata
                })
            
            logger.info(f"Retrieved {len(documents)} documents from Pinecone (limited to top {top_k})")
            return documents
            
        except Exception as e:
            logger.error(f"Failed to retrieve documents from Pinecone: {e}")
            return []


def create_vector_store(config: Config, rag_config: Optional[RAGConfig], 
                       embedding_provider: EmbeddingProvider, 
                       collection_name: Optional[str] = None) -> VectorStore:
    """
    Factory function to create appropriate vector store.
    
    Priority: Pinecone (primary) → PostgreSQL (fallback)
    
    Args:
        config: Application configuration
        rag_config: RAG configuration
        embedding_provider: Embedding provider instance
        collection_name: Optional collection name override
        
    Returns:
        VectorStore instance (PineconeVectorStore or PostgresVectorStore)
        
    Raises:
        ValueError: If neither Pinecone nor PostgreSQL is configured
    """
    if rag_config is None:
        rag_config = RAGConfig()
    
    collection = collection_name or rag_config.collection_name
    backend = rag_config.vector_store_backend.lower()
    
    # Determine backend
    if backend == "auto":
        # Priority: Pinecone (primary) > PostgreSQL (fallback)
        if os.getenv('PINECONE_API_KEY'):
            backend = "pinecone"
            logger.info("Auto-detected Pinecone (PINECONE_API_KEY found)")
        else:
            db_url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL') or (config.database.url if hasattr(config, 'database') else None)
            if db_url and 'postgresql' in db_url:
                backend = "postgres"
                logger.info("Auto-detected PostgreSQL (DATABASE_URL found)")
            else:
                logger.error("No vector store configured! Please set PINECONE_API_KEY or DATABASE_URL")
                raise ValueError("No vector store configured. Pinecone or PostgreSQL required.")
    
    # Create Pinecone (PRIMARY)
    if backend == "pinecone":
        try:
            index_name = os.getenv('PINECONE_INDEX_NAME', collection)
            namespace = os.getenv('PINECONE_NAMESPACE', 'default')
            logger.info(f"Using Pinecone vector store (index={index_name}, namespace={namespace})")
            return PineconeVectorStore(
                index_name=index_name,
                embedding_provider=embedding_provider,
                namespace=namespace
            )
        except Exception as e:
            logger.warning(f"Pinecone initialization failed: {e}, falling back to PostgreSQL")
            # Fallback to PostgreSQL
            db_url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL') or (config.database.url if hasattr(config, 'database') else None)
            if db_url and 'postgresql' in db_url:
                try:
                    logger.info(f"Using PostgreSQL vector store as fallback (collection={collection})")
                    return PostgresVectorStore(db_url, collection, embedding_provider)
                except Exception as pg_error:
                    logger.error(f"PostgreSQL fallback also failed: {pg_error}")
                    raise ValueError("Both Pinecone and PostgreSQL initialization failed")
            else:
                logger.error("PostgreSQL fallback not available (DATABASE_URL not configured)")
                raise ValueError("Pinecone failed and PostgreSQL not configured")
    
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
        logger.error(f"Invalid vector store backend: {backend}. Use 'auto', 'pinecone', or 'postgres'")
        raise ValueError(f"Invalid vector store backend: {backend}. Supported: 'auto', 'pinecone', 'postgres'")

