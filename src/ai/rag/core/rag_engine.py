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
import os
import concurrent.futures
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime

from ....utils.config import Config, RAGConfig
from ....utils.logger import setup_logger
from .embedding_provider import EmbeddingProvider, create_embedding_provider
from .vector_store import VectorStore, create_vector_store, PostgresVectorStore
from .semantic_cache import SemanticCache
from .cache import TTLCache
from ..chunking import RecursiveTextChunker
from ..query import QueryEnhancer, ResultReranker, HybridSearchEngine
from ..query import apply_diversity, maximal_marginal_relevance
from ..query import AdaptiveRerankingWeights, create_adaptive_reranker
from ..chunking import EmailChunker
from ..utils.utils import deduplicate_results, calculate_semantic_score
from ..utils.performance import CircuitBreaker
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
        self.email_chunker = EmailChunker(chunk_size=int(rag_config.chunk_size * 0.75))
        
        # Initialize hybrid search if enabled
        self.use_hybrid_search = getattr(rag_config, 'use_hybrid_search', False)
        if self.use_hybrid_search:
            # Determine backend type (Qdrant or PostgreSQL only)
            backend_type = rag_config.vector_store_backend.lower()
            if backend_type == "auto":
                # Detect based on vector store instance
                if "Qdrant" in self.vector_store.__class__.__name__:
                    backend_type = "qdrant"
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
        
        # Initialize semantic cache (vector-based)
        self.semantic_cache = SemanticCache(
            embedding_provider=self.embedding_provider,
            threshold=getattr(rag_config, 'semantic_cache_threshold', 0.96),
            max_size=getattr(rag_config, 'query_cache_size', 1000),
            ttl_seconds=getattr(rag_config, 'query_cache_ttl_seconds', 3600)
        )
        
        # Initialize circuit breaker
        from ..utils.performance import CircuitBreaker
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=rag_config.circuit_breaker_threshold,
            recovery_timeout=rag_config.circuit_breaker_timeout
        )
        
        # Shared ThreadPoolExecutor for parallel operations
        # Use config or default to 10 workers
        max_workers = int(os.getenv('RAG_PARALLEL_WORKERS', '10'))
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        
        # Initialize reranker for recent queries (avoid creating new instance each time)
        # Use recency-optimized weights for "recent" queries (higher recency_weight)
        self.recent_query_reranker = ResultReranker(
            semantic_weight=rag_config.rerank_semantic_weight * 0.625,  # Lower for recency focus
            keyword_weight=rag_config.rerank_keyword_weight * 0.75,
            metadata_weight=rag_config.rerank_metadata_weight * 0.75,
            recency_weight=rag_config.rerank_recency_weight * 2.25  # Higher for recent queries
        )
        
        # Document version tracking for smart cache invalidation
        self._document_version = 0  # Incremented on any document change
        self._last_cache_clear = datetime.utcnow()
        
        # Initialize monitoring
        self.monitor = get_monitor()
        
        logger.info(f"[OK] RAG Engine initialized (backend: {self.vector_store.__class__.__name__}, "
                   f"collection: {rag_config.collection_name}, "
                   f"embedding_dim: {self.embedding_provider.get_dimension()}, "
                   f"cache_size: {self.semantic_cache.max_size}, cache_ttl: {self.semantic_cache.ttl_seconds}s)")
    
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
    
    def index_bulk_documents(self, documents: List[Dict[str, Any]], batch_size: Optional[int] = None) -> Dict[str, Any]:
        """
        Bulk index documents with optimized batch processing.
        
        Args:
            documents: List of dicts with keys: id, content, metadata
            batch_size: Optional batch size override
            
        Returns:
            Dict containing:
            - success_count: Number of successfully indexed documents
            - failed_count: Number of failed documents
            - errors: List of dicts with 'batch_index' and 'error' message
        """
        if not documents:
            return {'success_count': 0, 'failed_count': 0, 'errors': []}
        
        batch_size = batch_size or self.rag_config.batch_size
        total_indexed = 0
        failed_count = 0
        errors = []
        
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
                batch_error = f"Failed to index batch {i//batch_size + 1}: {str(e)}"
                logger.error(batch_error, exc_info=True)
                failed_count += len(batch)
                errors.append({
                    'batch_index': i//batch_size + 1,
                    'error': str(e),
                    'document_ids': [d.get('id') for d in batch]
                })
                # Continue with next batch
        
        logger.info(f"Bulk indexing complete: {total_indexed}/{len(documents)} indexed, {failed_count} failed")
        
        # Invalidate cache after bulk indexing
        if total_indexed > 0:
            self._invalidate_cache_on_change()
            
        return {
            'success_count': total_indexed,
            'failed_count': failed_count,
            'errors': errors
        }
    
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
    
    def build_bm25_index_from_vector_store(self, max_docs: int = 10000, rebuild: bool = False):
        """
        Build BM25 index for hybrid search from existing vector store.
        
        Only needed for PostgreSQL backend.
        Qdrant uses native sparse-dense hybrid search.
        
        Args:
            max_docs: Maximum number of documents to index (to avoid memory issues)
            rebuild: Force rebuild index even if persistent file exists
        """
        if not self.hybrid_engine:
            logger.warning("Hybrid search not enabled, skipping BM25 index build")
            return
        
        if self.hybrid_engine.supports_native_hybrid():
            logger.info("Qdrant supports native hybrid search, skipping BM25 index")
            return
            
        # Check for persistent index
        index_path = os.path.join(os.path.dirname(self.vector_store.__class__.__module__.replace('.', '/')), 
                                "data", "bm25_index.pkl")
        # Ensure data directory exists relative to project root instead
        index_path = os.path.abspath(os.path.join(os.getcwd(), "data", "bm25_index.pkl"))
        
        if not rebuild and os.path.exists(index_path):
            if self.hybrid_engine.load_index(index_path):
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
        
        # Save index
        self.hybrid_engine.save_index(index_path)
        
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
        
        # Check semantic cache (conceptual hits)
        if use_cache:
            cached_results = self.semantic_cache.get(query)
            if cached_results is not None:
                cache_hit = True
                logger.debug(f"Semantic Cache HIT for query: {query[:50]}...")
                # Log metrics for cached result
                search_duration = (time.time() - search_start) * 1000
                logger.info(
                    f"RAG_METRICS|query_len={len(query)}|results={len(cached_results)}|"
                    f"duration_ms={search_duration:.1f}|cache_hit=True|semantic=True|rerank={rerank}"
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
            # Use shared executor instead of creating new one
            future = self.executor.submit(
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
                    # avg_score = sum(r.get('confidence', 0) for r in results) / len(results)
                    # self.monitor.record_relevance_score(avg_score)
                    pass
                
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
    
    async def asearch(self, query: str, k: int = 5, filters: Optional[Dict[str, Any]] = None,
                      rerank: bool = True, min_confidence: float = 0.5,
                      use_multi_query: bool = True, use_cache: bool = True,
                      timeout: int = 10) -> List[Dict[str, Any]]:
        """
        Search for documents (Async).
        
        This method uses async query enhancement (allowing non-blocking LLM calls)
        and then offloads the blocking vector search to a thread pool.
        """
        search_start = time.time()
        
        # Check semantic cache (conceptual hits)
        if use_cache:
            cached_results = self.semantic_cache.get(query)
            if cached_results is not None:
                # Log success and return
                self.monitor.record_search((time.time() - search_start) * 1000, len(cached_results), cache_hit=True)
                return cached_results

        try:
            # 1. Enhance query asynchronously (non-blocking LLM)
            enhanced = await self.query_enhancer.enhance(query)
            
            # 2. Run the rest of the search in the thread pool
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                self.executor,
                self._search_execution,
                query, k, filters, rerank, min_confidence, use_multi_query, enhanced, use_cache
            )
            
            # Record metrics
            duration = (time.time() - search_start) * 1000
            self.monitor.record_search(duration, len(results), cache_hit=False)
            
            return results
            
        except Exception as e:
            logger.error(f"Async search failed: {e}", exc_info=True)
            return []

    def _search_impl(self, query: str, k: int, filters: Optional[Dict[str, Any]],
                     rerank: bool, min_confidence: float, use_multi_query: bool,
                     use_cache: bool) -> List[Dict[str, Any]]:
        """Internal search implementation (Synchronous wrapper)."""
        # Enhance query using SYNC method to avoid event loop issues
        enhanced = self.query_enhancer.enhance_sync(query)
        
        # Delegate to execution logic
        return self._search_execution(
            query, k, filters, rerank, min_confidence, use_multi_query, enhanced, use_cache
        )

    def _search_execution(self, query: str, k: int, filters: Optional[Dict[str, Any]],
                         rerank: bool, min_confidence: float, use_multi_query: bool,
                         enhanced: Dict[str, Any], use_cache: bool = True) -> List[Dict[str, Any]]:
        """Core search execution logic (Blocking/CPU-bound)."""
        # If cache was missed, we use the results from this run to populate it
        results = self._search_execution_impl(
            query, k, filters, rerank, min_confidence, use_multi_query, enhanced
        )
        
        if use_cache and results:
            self.semantic_cache.set(query, results)
            
        return results

    def _search_execution_impl(self, query: str, k: int, filters: Optional[Dict[str, Any]],
                              rerank: bool, min_confidence: float, use_multi_query: bool,
                              enhanced: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Internal search core logic."""
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
        logger.debug(f"_search_parallel returned {len(all_results)} results")
        
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
                    all_results,
                    query,
                    k=k * 3  # Rerank more for recent queries
                )
            else:
                # Use adaptive reranking for other query types
                adaptive_reranker = create_adaptive_reranker(intent)
                all_results = adaptive_reranker.rerank(
                    all_results,
                    query,
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
        
        # Use shared executor for parallel query processing
        future_to_query = {}
        
        for search_query in queries:
            future = self.executor.submit(self._search_single_query, search_query, fetch_k, filters)
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
        # Perform semantic search using the unified search_by_text interface
        # This handles both Postgres (native text search) and Qdrant (encodes text to vector)
        return self.vector_store.search_by_text(search_query, fetch_k, filters)
    
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
            'query_cache': self.semantic_cache.get_stats(),
            'circuit_breaker': self.circuit_breaker.get_state()
        })
        return stats
    
    def clear_cache(self):
        """
        Manually clear the query result cache.
        
        Useful for forcing fresh results or after bulk document operations.
        """
        self.semantic_cache.clear()
        self._last_cache_clear = datetime.utcnow()
        logger.info("Query cache manually cleared")
    
    def reset_circuit_breaker(self) -> None:
        """Manually reset circuit breaker."""
        self.circuit_breaker.reset()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        stats = self.semantic_cache.get_stats()
        stats.update({
            'document_version': self._document_version,
            'last_cache_clear': self._last_cache_clear.isoformat()
        })
        return stats
    
    def fast_search(self, query: str, k: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Fast direct vector search bypassing the full enhancement/reranking pipeline.
        
        Ideal for caching and low-latency entity lookups.
        """
        try:
            # Check cache first
            cached = self.semantic_cache.get(query)
            if cached:
                return cached[:k]
                
            # Direct vector search
            results = self.vector_store.search_by_text(query, k, filters)
            
            # Simple confidence calculation
            for r in results:
                r['confidence'] = calculate_semantic_score(r.get('distance', 1.0))
            
            # Update cache
            if results:
                self.semantic_cache.set(query, results)
                
            return results
        except Exception as e:
            logger.error(f"Fast search failed: {e}")
            return []
    
    def _invalidate_cache_on_change(self):
        """
        Invalidate query cache when documents change.
        
        This ensures search results stay fresh after indexing/deleting documents.
        """
        self._document_version += 1
        self._last_cache_clear = datetime.utcnow()
        
        # Clear the entire cache when documents change
        self.semantic_cache.clear()
        
        # Track cache invalidation in monitoring
        self.monitor.record_cache_invalidation()
        
        logger.debug(f"Cache invalidated (document version: {self._document_version})")

    async def self_rag_search(
        self,
        query: str,
        k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        max_expansion_attempts: int = 2,
        relevance_threshold: float = 0.4
    ) -> Dict[str, Any]:
        """
        Self-RAG enhanced search with automatic query expansion.
        
        Implements the Self-RAG pattern:
        1. Search with initial query
        2. Grade relevance of retrieved chunks
        3. If relevance too low, expand query and retry
        4. Return results with relevance metadata
        
        Args:
            query: User's search query
            k: Number of results to return
            filters: Optional metadata filters
            max_expansion_attempts: Max times to expand query (default: 2)
            relevance_threshold: Minimum relevance score (default: 0.4)
            
        Returns:
            Dict with results, relevance info, and expansion history
        """
        from ..query.relevance_grader import RelevanceGrader, RelevanceLevel
        
        grader = RelevanceGrader(
            expansion_threshold=relevance_threshold,
            min_relevant_chunks=2
        )
        
        expansion_history = []
        current_query = query
        best_results = []
        best_relevance = None
        
        for attempt in range(max_expansion_attempts + 1):
            # Search with current query
            results = await self.asearch(
                current_query,
                k=k * 2,  # Fetch more for relevance filtering
                filters=filters,
                rerank=True,
                use_cache=attempt == 0  # Only cache first attempt
            )
            
            # Grade relevance
            enhanced = self.query_enhancer.enhance_sync(current_query)
            intent = enhanced.get('intent', 'search')
            
            relevance = grader.grade(current_query, results, query_intent=intent)
            
            logger.info(
                f"Self-RAG attempt {attempt + 1}: relevance={relevance.score:.2f}, "
                f"level={relevance.level.value}, expand={relevance.should_expand_query}"
            )
            
            expansion_history.append({
                'attempt': attempt + 1,
                'query': current_query,
                'relevance_score': relevance.score,
                'relevance_level': relevance.level.value,
                'num_results': len(results),
                'reasoning': relevance.reasoning
            })
            
            # Track best results
            if best_relevance is None or relevance.score > best_relevance.score:
                best_results = results
                best_relevance = relevance
            
            # Check if we should stop
            if not relevance.should_expand_query:
                logger.info(f"Self-RAG: Sufficient relevance achieved ({relevance.score:.2f})")
                break
            
            # Check if we've exhausted attempts
            if attempt >= max_expansion_attempts:
                logger.warning(
                    f"Self-RAG: Max expansion attempts reached. "
                    f"Best relevance: {best_relevance.score:.2f}"
                )
                break
            
            # Expand query for next attempt
            expanded = await self.query_enhancer.enhance(current_query)
            
            # Try reformulations first, then LLM expansion
            if expanded.get('reformulated'):
                # Use first reformulation that's different from current
                for reform in expanded['reformulated']:
                    if reform.lower() != current_query.lower():
                        current_query = reform
                        break
            elif expanded.get('expanded') and expanded['expanded'] != current_query:
                current_query = expanded['expanded']
            else:
                # Generate new query variant using synonyms
                current_query = f"{query} {' '.join(enhanced.get('keywords', [])[:3])}"
            
            logger.info(f"Self-RAG: Expanding query to: '{current_query}'")
        
        # Return best results with metadata
        return {
            'results': best_results[:k],
            'relevance': {
                'score': best_relevance.score,
                'level': best_relevance.level.value,
                'reasoning': best_relevance.reasoning
            },
            'expansion_history': expansion_history,
            'final_query': current_query,
            'original_query': query,
            'attempts': len(expansion_history)
        }

    def shutdown(self):
        """Shutdown the RAG engine and release resources."""
        self.executor.shutdown(wait=True)
        logger.info("RAG Engine shutdown complete")

    async def intelligent_search(
        self,
        query: str,
        k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        use_self_rag: bool = True,
        use_decomposition: bool = True,
        use_cross_encoder: bool = True,
        relevance_threshold: float = 0.4
    ) -> Dict[str, Any]:
        """
        Intelligent search combining all RAG improvements for maximum accuracy.
        
        Combines:
        1. Query decomposition for complex multi-part queries
        2. Self-RAG with relevance grading and query expansion
        3. Cross-encoder reranking for precision
        
        Args:
            query: User's search query
            k: Number of results to return
            filters: Optional metadata filters
            use_self_rag: Enable Self-RAG relevance grading
            use_decomposition: Enable query decomposition
            use_cross_encoder: Enable cross-encoder reranking
            relevance_threshold: Minimum relevance score
            
        Returns:
            Dict with 'results', 'metadata', and pipeline info
        """
        from ..query.query_decomposer import QueryDecomposer, QueryComplexity, DecomposedRAGExecutor
        from ..query.cross_encoder_reranker import CrossEncoderReranker
        from ..query.relevance_grader import RelevanceGrader
        
        pipeline_info = {
            'original_query': query,
            'decomposed': False,
            'self_rag_expanded': False,
            'cross_encoder_applied': False
        }
        
        # Step 1: Check if query needs decomposition
        if use_decomposition:
            decomposer = QueryDecomposer()
            decomposition = decomposer.decompose(query)
            
            if decomposition.complexity != QueryComplexity.SIMPLE:
                logger.info(f"Decomposing complex query ({decomposition.complexity.value})")
                pipeline_info['decomposed'] = True
                pipeline_info['sub_queries'] = [sq.query for sq in decomposition.sub_queries]
                
                # Execute decomposed queries
                executor = DecomposedRAGExecutor(self, decomposer)
                decomposed_result = await executor.execute(query, k * 2, filters)
                
                all_results = decomposed_result.get('aggregated_results', [])
                pipeline_info['decomposition_results'] = len(all_results)
            else:
                # Simple query - proceed normally
                all_results = await self.asearch(query, k=k * 2, filters=filters)
        else:
            all_results = await self.asearch(query, k=k * 2, filters=filters)
        
        # Step 2: Self-RAG relevance grading
        if use_self_rag and all_results:
            grader = RelevanceGrader(expansion_threshold=relevance_threshold)
            enhanced_query = await self.query_enhancer.enhance(query)
            
            relevance = grader.grade_chunks(all_results[:k], enhanced_query)
            pipeline_info['relevance_score'] = relevance.score
            pipeline_info['relevance_level'] = relevance.level.value
            
            # Expand if relevance is low
            if relevance.should_expand_query:
                logger.info(f"Self-RAG: Low relevance ({relevance.score:.2f}), expanding query")
                pipeline_info['self_rag_expanded'] = True
                
                # Try reformulated queries
                for reform in enhanced_query.get('reformulated', [])[:2]:
                    if reform.lower() != query.lower():
                        extra_results = await self.asearch(reform, k=k, filters=filters)
                        all_results = self._merge_results(all_results, extra_results)
                        break
        
        # Step 3: Cross-encoder reranking
        if use_cross_encoder and all_results:
            try:
                cross_encoder = CrossEncoderReranker()
                all_results = await cross_encoder.arerank(query, all_results, k=k * 2)
                pipeline_info['cross_encoder_applied'] = True
            except Exception as e:
                logger.debug(f"Cross-encoder skipped: {e}")
        
        # Final slice
        final_results = all_results[:k]
        
        return {
            'results': final_results,
            'metadata': {
                'result_count': len(final_results),
                'pipeline': pipeline_info
            }
        }
    
    def _merge_results(
        self,
        primary: List[Dict[str, Any]],
        secondary: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Merge and deduplicate results from multiple searches."""
        seen_ids = set()
        merged = []
        
        for result in primary + secondary:
            result_id = result.get('id') or result.get('doc_id')
            if result_id and result_id not in seen_ids:
                seen_ids.add(result_id)
                merged.append(result)
            elif not result_id:
                merged.append(result)
        
        # Sort by score
        merged.sort(key=lambda x: x.get('score', x.get('rerank_score', 0)), reverse=True)
        return merged


