"""
RAG Engine - Main orchestrator for Retrieval-Augmented Generation

Combines embedding generation, vector storage, and intelligent retrieval.

Performance Features:
- Query result caching for faster repeated queries
- Circuit breaker for resilient operations
- Parallel query processing for multi-query searches
- Optimized reranking with early termination
- Connection pooling and resource management
"""
import uuid
import time
import concurrent.futures
from typing import List, Dict, Any, Optional
from datetime import datetime

from ....utils.config import Config, RAGConfig
from ....utils.logger import setup_logger
from .embedding_provider import EmbeddingProvider, create_embedding_provider
from .vector_store import VectorStore, create_vector_store, PostgresVectorStore
from ..chunking import RecursiveTextChunker
from ..query import QueryEnhancer, ResultReranker, HybridSearchEngine
from ..query import apply_diversity, maximal_marginal_relevance
from ..query import AdaptiveRerankingWeights, create_adaptive_reranker
from ..chunking import EmailChunker
from ..utils.utils import deduplicate_results, calculate_semantic_score
from ..utils.performance import QueryResultCache, CircuitBreaker
from ..utils.monitoring import get_monitor, RAGMonitor

logger = setup_logger(__name__)


class RAGEngine:
    """
    Main RAG engine orchestrating embeddings, vector storage, and retrieval.
    
    Features:
    - Unified interface for RAG operations
    - Hybrid search (semantic + keyword)
    - Result reranking for accuracy
    - Intelligent chunking
    - Batch processing
    - Error handling with graceful fallbacks
    """
    
    def __init__(self, config: Config, collection_name: Optional[str] = None, 
                 rag_config: Optional[RAGConfig] = None):
        """
        Initialize RAG engine.
        
        Args:
            config: Application configuration
            collection_name: Optional collection name override
            rag_config: Optional RAG-specific configuration
        """
        self.config = config
        
        # Get RAG configuration
        if rag_config is None:
            rag_config = config.rag if hasattr(config, 'rag') and config.rag else RAGConfig()
        self.rag_config = rag_config
        
        # Override collection name if provided
        if collection_name:
            rag_config.collection_name = collection_name
        
        # Initialize components
        logger.info("Initializing RAG engine components...")
        self.embedding_provider = create_embedding_provider(config, rag_config)
        self.vector_store = create_vector_store(config, rag_config, self.embedding_provider, 
                                               rag_config.collection_name)
        
        # Initialize advanced recursive text chunker with parent-child support
        self.chunker = RecursiveTextChunker(
            chunk_size=int(rag_config.chunk_size * 0.75),  # Convert words to tokens
            child_chunk_size=int(rag_config.chunk_size * 0.75 // 2),  # Half of parent
            overlap_tokens=int(rag_config.chunk_overlap * 0.75),  # Convert words to tokens
            use_parent_child=rag_config.use_semantic_chunking  # Enable for semantic mode
        )
        
        # Initialize email-aware chunker for better email search
        self.email_chunker = EmailChunker(max_chunk_words=300)
        
        # Initialize hybrid search if enabled
        self.use_hybrid_search = getattr(rag_config, 'use_hybrid_search', False)
        if self.use_hybrid_search:
            # Determine backend type (Pinecone or PostgreSQL only)
            backend_type = rag_config.vector_store_backend.lower()
            if backend_type == "auto":
                # Detect based on vector store instance
                if "Pinecone" in self.vector_store.__class__.__name__:
                    backend_type = "pinecone"
                else:
                    backend_type = "postgres"
            
            self.hybrid_engine = HybridSearchEngine(backend_type=backend_type)
            logger.info(f"Hybrid search enabled (backend: {backend_type})")
        else:
            self.hybrid_engine = None
        
        # Initialize query enhancement and reranking with configurable weights
        self.query_enhancer = QueryEnhancer(
            use_llm_expansion=rag_config.use_llm_expansion if hasattr(rag_config, 'use_llm_expansion') else False
        )
        self.reranker = ResultReranker(
            semantic_weight=rag_config.rerank_semantic_weight if hasattr(rag_config, 'rerank_semantic_weight') else 0.4,
            keyword_weight=rag_config.rerank_keyword_weight if hasattr(rag_config, 'rerank_keyword_weight') else 0.2,
            metadata_weight=rag_config.rerank_metadata_weight if hasattr(rag_config, 'rerank_metadata_weight') else 0.2,
            recency_weight=rag_config.rerank_recency_weight if hasattr(rag_config, 'rerank_recency_weight') else 0.2
        )
        
        # Performance optimizations
        cache_ttl = getattr(rag_config, 'query_cache_ttl_seconds', 300)  # 5 minutes default
        cache_size = getattr(rag_config, 'query_cache_size', 1000)
        self.query_cache = QueryResultCache(max_size=cache_size, ttl_seconds=cache_ttl)
        
        # Circuit breaker for resilient operations
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=getattr(rag_config, 'circuit_breaker_threshold', 5),
            recovery_timeout=getattr(rag_config, 'circuit_breaker_timeout', 60)
        )
        
        # Pre-create reranker for recent queries (avoid creating new instance each time)
        self.recent_query_reranker = ResultReranker(
            semantic_weight=0.25,
            keyword_weight=0.15,
            metadata_weight=0.15,
            recency_weight=0.45
        )
        
        # Document version tracking for smart cache invalidation
        self._document_version = 0  # Incremented on any document change
        self._last_cache_clear = datetime.utcnow()
        
        # Initialize monitoring
        self.monitor = get_monitor()
        
        logger.info(f"[OK] RAG Engine initialized (backend: {self.vector_store.__class__.__name__}, "
                   f"collection: {rag_config.collection_name}, "
                   f"embedding_dim: {self.embedding_provider.get_dimension()}, "
                   f"cache_size: {cache_size}, cache_ttl: {cache_ttl}s)")
    
    def index_document(self, doc_id: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Index a single document.
        
        Args:
            doc_id: Unique document identifier
            content: Document content
            metadata: Optional metadata
        """
        start_time = time.time()
        try:
            # Ensure doc_type is set
            if metadata is None:
                metadata = {}
            metadata['doc_type'] = metadata.get('doc_type', 'document')
            metadata['indexed_at'] = datetime.utcnow().isoformat()
            
            self.vector_store.add_document(doc_id, content, metadata)
            logger.debug(f"Indexed document {doc_id}")
            
            # Invalidate cache when document is added
            self._invalidate_cache_on_change()
            
            # Record metrics
            latency = (time.time() - start_time) * 1000
            self.monitor.record_index(latency)
            
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            self.monitor.record_index(latency, error=str(e))
            logger.error(f"Failed to index document {doc_id}: {e}", exc_info=True)
            raise
    
    def index_document_chunked(self, doc_id: str, content: str, 
                              metadata: Optional[Dict[str, Any]] = None) -> List[str]:
        """
        Index a document with chunking for better retrieval of long content.
        
        Args:
            doc_id: Base document identifier
            content: Document content to chunk and index
            metadata: Optional metadata to attach to all chunks
            
        Returns:
            List of chunk document IDs
        """
        # Chunk the content
        chunks = self.chunker.chunk(content)
        
        if not chunks:
            return []
        
        chunk_ids = []
        documents = []
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{i}"
            chunk_ids.append(chunk_id)
            
            # Extract text from chunk (handle both Chunk objects and strings)
            if hasattr(chunk, 'text'):
                # Chunk object - extract text property
                chunk_text = chunk.text
            elif isinstance(chunk, dict):
                # Dictionary format - extract 'text' or 'content' key
                chunk_text = chunk.get('text') or chunk.get('content', '')
            else:
                # Assume it's already a string
                chunk_text = str(chunk)
            
            # Add chunk metadata
            chunk_metadata = {
                **(metadata or {}),
                'chunk_index': i,
                'total_chunks': len(chunks),
                'parent_doc_id': doc_id
            }
            
            documents.append({
                'id': chunk_id,
                'content': chunk_text,  # Use extracted text, not chunk object
                'metadata': chunk_metadata
            })
        
        # Batch add chunks
        self.vector_store.add_documents(documents)
        logger.info(f"Indexed document {doc_id} with {len(chunks)} chunks")
        
        # Invalidate cache when documents are added
        self._invalidate_cache_on_change()
        
        return chunk_ids
    
    def index_bulk_documents(self, documents: List[Dict[str, Any]], batch_size: Optional[int] = None) -> None:
        """
        Bulk index documents with optimized batch processing.
        
        Args:
            documents: List of dicts with keys: id, content, metadata
            batch_size: Optional batch size override
        """
        if not documents:
            return
        
        batch_size = batch_size or self.rag_config.batch_size
        total_indexed = 0
        
        # Process in batches
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            
            try:
                # Ensure metadata is properly formatted
                formatted_batch = []
                for doc in batch:
                    # Create a copy of metadata to avoid modifying the original
                    metadata = dict(doc.get('metadata', {}))
                    metadata['doc_type'] = metadata.get('doc_type', 'document')
                    metadata['indexed_at'] = datetime.utcnow().isoformat()
                    
                    # Ensure content is a string (not a Chunk object)
                    content_value = doc.get('content', '')
                    if hasattr(content_value, 'text'):
                        # It's a Chunk object - extract text
                        content_str = content_value.text
                    elif isinstance(content_value, str):
                        content_str = content_value
                    else:
                        # Fallback: convert to string
                        content_str = str(content_value)
                    
                    formatted_batch.append({
                        'id': doc.get('id', str(uuid.uuid4())),
                        'content': content_str,
                        'metadata': metadata
                    })
                
                self.vector_store.add_documents(formatted_batch)
                total_indexed += len(batch)
                logger.debug(f"Indexed batch {i//batch_size + 1}: {len(batch)} documents")
                
            except Exception as e:
                logger.error(f"Failed to index batch {i//batch_size + 1}: {e}", exc_info=True)
                # Continue with next batch
        
        logger.info(f"Bulk indexing complete: {total_indexed}/{len(documents)} documents indexed")
        
        # Invalidate cache after bulk indexing
        if total_indexed > 0:
            self._invalidate_cache_on_change()
    
    def index_email(self, email_id: str, email_data: Dict[str, Any]) -> List[str]:
        """
        Index an email using email-aware chunking.
        
        This method uses EmailChunker to create better chunks that preserve
        email structure (metadata, body, etc.) for improved search accuracy.
        
        Args:
            email_id: Unique email identifier
            email_data: Email data dict with 'subject', 'sender', 'body', etc.
            
        Returns:
            List of chunk document IDs
        """
        try:
            # Use email-aware chunking
            chunks = self.email_chunker.chunk_email(email_data)
            
            if not chunks:
                logger.warning(f"No chunks created for email {email_id}")
                return []
            
            # Add email_id to metadata for all chunks
            for chunk in chunks:
                if 'metadata' not in chunk:
                    chunk['metadata'] = {}
                chunk['metadata']['email_id'] = email_id
                chunk['metadata']['indexed_at'] = datetime.utcnow().isoformat()
            
            # Assign chunk IDs
            for i, chunk in enumerate(chunks):
                chunk['id'] = f"{email_id}_chunk_{i}"
            
            # Batch add chunks
            self.vector_store.add_documents(chunks)
            
            chunk_ids = [chunk['id'] for chunk in chunks]
            logger.debug(f"Indexed email {email_id} with {len(chunks)} chunks (email-aware)")
            
            # Invalidate cache when email is indexed
            self._invalidate_cache_on_change()
            
            return chunk_ids
            
        except Exception as e:
            logger.error(f"Failed to index email {email_id}: {e}", exc_info=True)
            raise
    
    def build_bm25_index_from_vector_store(self, max_docs: int = 10000):
        """
        Build BM25 index for hybrid search from existing vector store.
        
        Only needed for PostgreSQL backend.
        Pinecone uses native sparse-dense hybrid search.
        
        Args:
            max_docs: Maximum number of documents to index (to avoid memory issues)
        """
        if not self.hybrid_engine:
            logger.warning("Hybrid search not enabled, skipping BM25 index build")
            return
        
        if self.hybrid_engine.supports_native_hybrid():
            logger.info("Pinecone supports native hybrid search, skipping BM25 index")
            return
        
        logger.info("Building BM25 index for hybrid search...")
        
        # Get statistics first
        stats = self.vector_store.get_stats()
        total_docs = stats.get('total_documents', 0)
        
        if total_docs == 0:
            logger.warning("No documents in vector store to build BM25 index")
            return
        
        logger.info(f"Retrieving up to {min(total_docs, max_docs)} documents from vector store...")
        
        # Retrieve all documents from vector store
        documents = self.vector_store.get_all_documents(
            batch_size=100,
            max_docs=max_docs
        )
        
        if not documents:
            logger.warning("Failed to retrieve documents from vector store")
            return
        
        # Build BM25 index
        logger.info(f"Building BM25 index with {len(documents)} documents...")
        self.hybrid_engine.build_bm25_index(documents)
        logger.info(f"BM25 index built successfully with {len(documents)} documents")
    
    def search(self, query: str, k: Optional[int] = None, 
               filters: Optional[Dict[str, Any]] = None,
               rerank: Optional[bool] = None,
               min_confidence: float = 0.3,
               use_multi_query: bool = True,
               use_cache: bool = True,
               timeout: float = 5.0) -> List[Dict[str, Any]]:
        """
        Search for similar documents using enhanced semantic search.
        
        Args:
            query: Search query text
            k: Number of results (defaults to config value)
            filters: Optional metadata filters
            rerank: Enable advanced reranking (defaults to config value). 
                   When enabled, hybrid scoring (semantic + keyword + metadata) is applied automatically.
            min_confidence: Minimum confidence threshold (0-1)
            use_multi_query: Use multiple query variants for better recall
            use_cache: Use query result cache (default: True)
            
        Returns:
            List of relevant documents with content, metadata, distance, and confidence
        """
        k = k or self.rag_config.default_search_k
        rerank = rerank if rerank is not None else self.rag_config.rerank_results
        
        # Track search start time for metrics
        search_start = time.time()
        
        # Check cache first
        cache_hit = False
        if use_cache:
            cached_results = self.query_cache.get(query, k, filters)
            if cached_results is not None:
                cache_hit = True
                logger.debug(f"Cache HIT for query: {query[:50]}...")
                # Log metrics for cached result
                search_duration = (time.time() - search_start) * 1000
                logger.info(
                    f"RAG_METRICS|query_len={len(query)}|results={len(cached_results)}|"
                    f"duration_ms={search_duration:.1f}|cache_hit=True|rerank={rerank}"
                )
                # Record monitoring metrics
                self.monitor.record_search(
                    latency=search_duration,
                    num_results=len(cached_results),
                    cache_hit=True
                )
                return cached_results
        
        try:
            # Use circuit breaker with timeout for resilient search
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    self.circuit_breaker.call,
                    self._search_impl,
                    query, k, filters, rerank, min_confidence, use_multi_query, use_cache
                )
                try:
                    results = future.result(timeout=timeout)
                    
                    # Log metrics for successful search
                    search_duration = (time.time() - search_start) * 1000
                    logger.info(
                        f"RAG_METRICS|query_len={len(query)}|results={len(results)}|"
                        f"duration_ms={search_duration:.1f}|cache_hit=False|rerank={rerank}"
                    )
                    
                    # Record monitoring metrics
                    self.monitor.record_search(
                        latency=search_duration,
                        num_results=len(results),
                        cache_hit=False
                    )
                    if results:
                        avg_score = sum(r.get('confidence', 0) for r in results) / len(results)
                        self.monitor.record_relevance_score(avg_score)
                    
                    return results
                except concurrent.futures.TimeoutError:
                    search_duration = (time.time() - search_start) * 1000
                    logger.error(f"Search timed out after {timeout}s for query: {query[:50]}")
                    self.monitor.record_search(search_duration, 0, error="timeout")
                    return []
        except Exception as e:
            search_duration = (time.time() - search_start) * 1000
            logger.error(f"Search failed: {e}", exc_info=True)
            self.monitor.record_search(search_duration, 0, error=str(type(e).__name__))
            # Return empty results instead of raising to maintain stability
            return []
    
    def _search_impl(self, query: str, k: int, filters: Optional[Dict[str, Any]],
                     rerank: bool, min_confidence: float, use_multi_query: bool,
                     use_cache: bool) -> List[Dict[str, Any]]:
        """Internal search implementation."""
        # Enhance query
        enhanced = self.query_enhancer.enhance(query)
        primary_query = enhanced['expanded']
        
        # Check if this is a "recent" query
        is_recent_query = enhanced['intent'] == 'recent' or any(
            term in query.lower() for term in ['recent', 'new', 'latest', 'today', 'yesterday']
        )
        
        # Fetch more results if reranking is enabled
        # For recent queries, fetch even more to ensure we have truly recent emails
        if is_recent_query:
            fetch_k = k * 10 if rerank else k * 5  # Fetch more for recent queries
        else:
            fetch_k = k * 5 if rerank else k * 2
        
        # Multi-query retrieval: try multiple query variants in parallel for speed
        queries_to_try = [primary_query]
        if use_multi_query and enhanced['reformulated']:
            queries_to_try.extend(enhanced['reformulated'][:2])  # Add top 2 variants
        
        # Process queries in parallel for better performance
        all_results = self._search_parallel(queries_to_try, fetch_k, filters)
        
        # Deduplicate results across query variants
        all_results = deduplicate_results(all_results)
        
        # Apply advanced reranking if enabled with adaptive weights
        if rerank and all_results:
            # Track reranking usage
            self.monitor.record_reranking()
            
            # Get adaptive weights based on query intent
            intent = enhanced.get('intent', 'search')
            
            # For recent queries, use pre-created reranker (faster)
            if is_recent_query or intent == 'recent':
                all_results = self.recent_query_reranker.rerank(
                    query, 
                    all_results, 
                    query_keywords=enhanced['keywords'],
                    k=k * 3  # Rerank more for recent queries
                )
            else:
                # Use adaptive reranking for other query types
                adaptive_reranker = create_adaptive_reranker(intent)
                all_results = adaptive_reranker.rerank(
                    query, 
                    all_results, 
                    query_keywords=enhanced['keywords'],
                    k=k * 2  # Rerank more, then filter by confidence
                )
                
                logger.debug(f"Applied adaptive reranking with intent: {intent}")
        
        # Filter by confidence threshold and calculate confidence scores
        filtered_results = []
        for result in all_results:
            # Calculate confidence from rerank_score or distance
            if 'rerank_score' in result:
                confidence = result['rerank_score']
            else:
                distance = result.get('distance', 1.0)
                confidence = calculate_semantic_score(distance)
            
            result['confidence'] = confidence
            
            if confidence >= min_confidence:
                filtered_results.append(result)
        
        # Sort by confidence (if not already sorted by rerank_score)
        if not rerank:
            filtered_results.sort(key=lambda x: x.get('confidence', 0), reverse=True)
        
        # Apply diversity enhancement if enabled (reduces near-duplicates)
        enable_diversity = getattr(self.rag_config, 'enable_search_diversity', True)
        if enable_diversity and len(filtered_results) > k:
            logger.debug(f"Applying diversity enhancement to {len(filtered_results)} results")
            self.monitor.record_diversity()  # Track diversity usage
            filtered_results = apply_diversity(
                results=filtered_results,
                k=k * 2,  # Keep more for final filtering
                diversity_mode='mmr',  # Use MMR algorithm
                lambda_param=0.6  # Slightly favor relevance over diversity
            )
        
        final_results = filtered_results[:k]
        
        # Cache results for future queries
        if use_cache:
            self.query_cache.set(query, k, final_results, filters)
        
        return final_results
    
    def _search_parallel(self, queries: List[str], fetch_k: int, 
                        filters: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Search multiple query variants in parallel for better performance.
        
        Args:
            queries: List of query variants to search
            fetch_k: Number of results to fetch per query
            filters: Optional metadata filters
            
        Returns:
            Combined results from all queries
        """
        all_results = []
        
        # Use ThreadPoolExecutor for parallel query processing
        # Increased from 3 to 10 workers for better parallelism
        import os
        max_workers = int(os.getenv('RAG_PARALLEL_WORKERS', '10'))
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(queries), max_workers)) as executor:
            future_to_query = {}
            
            for search_query in queries:
                future = executor.submit(self._search_single_query, search_query, fetch_k, filters)
                future_to_query[future] = search_query
            
            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_query):
                search_query = future_to_query[future]
                try:
                    results = future.result()
                    # Add query context to results
                    for result in results:
                        result['query_variant'] = search_query
                    all_results.extend(results)
                except Exception as e:
                    logger.debug(f"Query variant '{search_query}' failed: {e}")
                    continue
        
        return all_results
    
    def _search_single_query(self, search_query: str, fetch_k: int,
                            filters: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Search a single query variant.
        
        Args:
            search_query: Query text
            fetch_k: Number of results to fetch
            filters: Optional metadata filters
            
        Returns:
            Search results
        """
        # Perform semantic search
        if isinstance(self.vector_store, PostgresVectorStore):
            # PostgreSQL handles embedding internally
            return self.vector_store.search_by_text(search_query, fetch_k, filters)
        else:
            # Other stores need explicit embedding
            query_embedding = self.embedding_provider.encode_query(search_query)
            return self.vector_store.search(query_embedding, fetch_k, filters)
    
    
    def delete_document(self, doc_id: str) -> None:
        """Delete a document from the vector store."""
        self.vector_store.delete_document(doc_id)
        logger.info(f"Deleted document {doc_id}")
        
        # Invalidate cache when document is deleted
        self._invalidate_cache_on_change()
    
    def document_exists(self, doc_id: str) -> bool:
        """Check if a document exists in the vector store."""
        return self.vector_store.document_exists(doc_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get RAG engine statistics."""
        stats = self.vector_store.get_stats()
        stats.update({
            'embedding_provider': self.embedding_provider.__class__.__name__,
            'embedding_dimension': self.embedding_provider.get_dimension(),
            'chunk_size': self.rag_config.chunk_size,
            'chunk_overlap': self.rag_config.chunk_overlap,
            'query_cache': self.query_cache.get_stats(),
            'circuit_breaker': self.circuit_breaker.get_state()
        })
        return stats
    
    def clear_cache(self):
        """
        Manually clear the query result cache.
        
        Useful for forcing fresh results or after bulk document operations.
        """
        self.query_cache.clear()
        self._last_cache_clear = datetime.utcnow()
        logger.info("Query cache manually cleared")
    
    def reset_circuit_breaker(self) -> None:
        """Manually reset circuit breaker."""
        self.circuit_breaker.reset()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache stats (size, hit rate, version)
        """
        return {
            'cache_size': len(self.query_cache.cache),
            'max_cache_size': self.query_cache.max_size,
            'document_version': self._document_version,
            'last_cache_clear': self._last_cache_clear.isoformat(),
            'ttl_seconds': self.query_cache.ttl_seconds
        }
    
    def _invalidate_cache_on_change(self):
        """
        Invalidate query cache when documents change.
        
        This ensures search results stay fresh after indexing/deleting documents.
        """
        self._document_version += 1
        self._last_cache_clear = datetime.utcnow()
        
        # Clear the entire cache when documents change
        # Alternative: could track which queries might be affected
        self.query_cache.clear()
        
        # Track cache invalidation in monitoring
        self.monitor.record_cache_invalidation()
        
        logger.debug(f"Cache invalidated (document version: {self._document_version})")

