"""
Embedding Provider Interface and Implementations

Abstract interface for embedding generation with concrete implementations
for Gemini and Sentence Transformers.
"""
import hashlib
import math
import re
import time
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
import concurrent.futures

from ....utils.config import Config, RAGConfig
from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class EmbeddingProvider(ABC):
    """Abstract interface for embedding generation."""
    
    @abstractmethod
    def encode(self, text: str) -> List[float]:
        """Encode a single text into an embedding vector."""
        pass
    
    @abstractmethod
    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """Encode multiple texts into embedding vectors."""
        pass
    
    @abstractmethod
    def encode_query(self, text: str) -> List[float]:
        """Encode a query text (may use different task type)."""
        pass
    
    @abstractmethod
    def get_dimension(self) -> int:
        """Get the dimension of embeddings produced by this provider."""
        pass


class GeminiEmbeddingProvider(EmbeddingProvider):
    """
    Google Gemini embedding provider with caching and retry logic.
    
    Features:
    - LRU cache for frequently accessed embeddings
    - Batch API calls for efficiency
    - Exponential backoff retry logic
    - Separate task types for documents and queries
    """
    
    def __init__(self, api_key: str, model_name: str = "models/text-embedding-004", 
                 cache_size: int = 1000, cache_ttl_hours: int = 24,
                 max_retries: int = 3, retry_base_delay: float = 1.0):
        """
        Initialize Gemini embedding provider.
        
        Args:
            api_key: Google API key
            model_name: Gemini embedding model name
            cache_size: Size of LRU cache for embeddings
            cache_ttl_hours: Cache TTL in hours
            max_retries: Maximum retry attempts
            retry_base_delay: Base delay for exponential backoff
        """
        try:
            import google.generativeai as genai
            import os
            
            # Configure API key - use getattr to avoid type checking issues
            configure_func = getattr(genai, 'configure', None)
            if configure_func:
                configure_func(api_key=api_key)
            else:
                # Fallback: set as environment variable
                os.environ['GOOGLE_API_KEY'] = api_key
            
            self.genai = genai
        except ImportError:
            raise ImportError("google-generativeai package is required for Gemini embeddings")
        
        self.model_name = self._normalize_model_name(model_name)
        
        # Use shared TTLCache
        from .cache import TTLCache
        self._embedding_cache = TTLCache(max_size=cache_size, ttl_seconds=cache_ttl_hours * 3600)
        
        self._max_retries = max_retries
        self._base_delay = retry_base_delay
        self._dimension = 768  # Gemini embeddings are 768D
        
        # Shared ThreadPoolExecutor for batch processing
        max_workers = int(os.environ.get('EMBEDDING_PARALLEL_WORKERS', '10'))
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)

    @staticmethod
    def _normalize_model_name(model_name: str) -> str:
        """Normalize known legacy aliases and ensure Gemini API model format."""
        normalized = model_name.strip()

        legacy_aliases = {
            "embedding-001": "models/text-embedding-004",
            "models/embedding-001": "models/text-embedding-004",
            "gemini-embedding-001": "models/text-embedding-004",
            "models/gemini-embedding-001": "models/text-embedding-004",
        }

        normalized = legacy_aliases.get(normalized, normalized)
        if not normalized.startswith("models/"):
            normalized = f"models/{normalized}"

        return normalized
    
    def get_dimension(self) -> int:
        """Get embedding dimension."""
        return self._dimension
    
    def _get_cache_key(self, text: str, task_type: str) -> str:
        """Generate cache key for text and task type."""
        content = f"{text}:{task_type}"
        return hashlib.md5(content.encode()).hexdigest()

    @staticmethod
    def _is_model_unavailable_error(error_message: str) -> bool:
        """Detect non-retriable model availability errors from Gemini API."""
        lowered = error_message.lower()
        return (
            "not found" in lowered
            or "not supported for embedcontent" in lowered
            or "is not supported for embedcontent" in lowered
            or "unsupported model" in lowered
            or "404 models/" in lowered
        )

    def _build_local_fallback_embedding(self, text: str) -> List[float]:
        """Build deterministic fallback embedding when remote model is unavailable."""
        vector = [0.0] * self._dimension
        tokens = re.findall(r"\w+", text.lower())

        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector

        return [v / norm for v in vector]
    
    def _get_cached(self, cache_key: str) -> Optional[List[float]]:
        """Get cached embedding if valid."""
        return self._embedding_cache.get(cache_key)
    
    def _set_cached(self, cache_key: str, embedding: List[float]):
        """Cache an embedding with LRU eviction."""
        self._embedding_cache.set(cache_key, embedding)
    
    def _embed_with_retry(self, text: str, task_type: str) -> List[float]:
        """Embed text with exponential backoff retry logic."""
        # Safety check: ensure text is not too large before attempting embedding
        text_bytes = len(text.encode('utf-8'))
        max_bytes = 30000  # 30KB limit with buffer
        
        if text_bytes > max_bytes:
            # Force truncation if somehow text is still too large
            logger.warning(f"Text still exceeds {max_bytes} bytes ({text_bytes} bytes) in _embed_with_retry, forcing truncation")
            # Truncate at character boundary if no word boundary found
            truncated = text[:max_bytes - 100]
            # Try to find last space for cleaner truncation
            last_space = truncated.rfind(' ')
            if last_space > max_bytes // 2:  # Only use space if it's reasonably far into the text
                text = truncated[:last_space]
            else:
                text = truncated
            logger.warning(f"Truncated text from {text_bytes} to {len(text.encode('utf-8'))} bytes")
        
        cache_key = self._get_cache_key(text, task_type)
        
        # Check cache first
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        
        # Retry logic with exponential backoff
        last_error = None
        for attempt in range(self._max_retries):
            try:
                # Use getattr to avoid type checking issues with embed_content
                embed_func = getattr(self.genai, 'embed_content', None)
                if not embed_func:
                    raise AttributeError("embed_content method not found")
                
                result = embed_func(
                    model=self.model_name,
                    content=text,
                    task_type=task_type,
                    output_dimensionality=self._dimension
                )
                embedding = result['embedding']
                
                # Cache the result
                self._set_cached(cache_key, embedding)
                return embedding
                
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                
                # Don't retry on quota/authentication errors
                if 'quota' in error_str or '429' in error_str or 'authentication' in error_str:
                    raise
                
                # Exponential backoff
                if attempt < self._max_retries - 1:
                    delay = self._base_delay * (2 ** attempt)
                    time.sleep(delay)
                    # Use debug level for retries - they're expected behavior for transient failures
                    # Only log final failure as warning, retries are debug level to reduce noise
                    logger.debug(f"Retry {attempt + 1}/{self._max_retries} for embedding after {delay}s (error: {type(e).__name__})")
        
        # Log final failure as warning with full error details
        error_msg = str(last_error)
        if 'rate' in error_msg.lower() or 'limit' in error_msg.lower():
            logger.warning(f"Failed to generate embedding after {self._max_retries} attempts: Rate limit exceeded")
        elif '500' in error_msg or '503' in error_msg:
            logger.warning(f"Failed to generate embedding after {self._max_retries} attempts: Server error ({error_msg[:100]})")
        else:
            logger.warning(f"Failed to generate embedding after {self._max_retries} attempts: {error_msg[:200]}")

        # If the configured Gemini embedding model is unavailable for this API key/version,
        # use a deterministic local fallback vector instead of hard-failing indexing.
        if self._is_model_unavailable_error(error_msg):
            logger.warning(
                "Gemini embedding model unavailable; using deterministic local fallback embedding "
                "for degraded-but-functional semantic indexing."
            )
            fallback_embedding = self._build_local_fallback_embedding(text)
            self._set_cached(cache_key, fallback_embedding)
            return fallback_embedding
        
        raise Exception(f"Failed to generate embedding after {self._max_retries} attempts: {last_error}")
    
    def _truncate_or_split_oversized_text(self, text: str, max_bytes: int = 30000) -> List[str]:
        """
        Split or truncate text that exceeds Gemini's payload size limit.
        
        Args:
            text: Text to process
            max_bytes: Maximum byte size (default 30KB, leaving buffer for API overhead)
            
        Returns:
            List of text chunks (may be single item if within limit)
        """
        text_bytes = len(text.encode('utf-8'))
        
        if text_bytes <= max_bytes:
            return [text]
        
        # Text is too large - try to split intelligently
        logger.warning(f"Text chunk exceeds {max_bytes} bytes ({text_bytes} bytes), splitting...")
        
        # Try to split by paragraphs first
        chunks = []
        paragraphs = text.split('\n\n')
        current_chunk = []
        current_size = 0
        
        for para in paragraphs:
            para_bytes = len(para.encode('utf-8'))
            
            # If single paragraph exceeds limit, truncate it
            if para_bytes > max_bytes:
                # Truncate to max_bytes (leaving some buffer)
                truncated_chars = para[:max_bytes - 100]
                # Try to find last space for cleaner truncation
                last_space = truncated_chars.rfind(' ')
                if last_space > max_bytes // 2:  # Only use space if it's reasonably far into the text
                    truncated = truncated_chars[:last_space]
                else:
                    truncated = truncated_chars  # Use character boundary if no good space found
                chunks.append(truncated)
                logger.warning(f"Truncated oversized paragraph from {para_bytes} to {len(truncated.encode('utf-8'))} bytes")
                continue
            
            # Check if adding this paragraph would exceed limit
            if current_size + para_bytes + 2 > max_bytes and current_chunk:  # +2 for '\n\n'
                # Finalize current chunk
                chunks.append('\n\n'.join(current_chunk))
                current_chunk = [para]
                current_size = para_bytes
            else:
                current_chunk.append(para)
                current_size += para_bytes + 2
        
        # Add final chunk
        if current_chunk:
            chunks.append('\n\n'.join(current_chunk))
        
        logger.info(f"Split oversized text into {len(chunks)} chunks")
        return chunks
    
    def encode(self, text: str) -> List[float]:
        """Encode a single text into an embedding vector."""
        # Check size and split if needed
        text_chunks = self._truncate_or_split_oversized_text(text)
        
        if len(text_chunks) == 1:
            return self._embed_with_retry(text, "RETRIEVAL_DOCUMENT")
        
        # If split into multiple chunks, encode first chunk (most important)
        # and return its embedding
        logger.warning(f"Text was split into {len(text_chunks)} chunks, encoding first chunk only")
        return self._embed_with_retry(text_chunks[0], "RETRIEVAL_DOCUMENT")
    
    def encode_batch(self, texts: List[str], batch_size: int = 50) -> List[List[float]]:
        """
        Encode multiple texts with optimized batch processing.
        
        Args:
            texts: List of text strings
            batch_size: Number of texts to process per batch
            
        Returns:
            List of embedding vectors
        """
        # Check cache first for all texts
        cached_results = {}
        uncached_texts = []
        uncached_indices = []
        uncached_embeddings = []  # Initialize here so it's always defined
        
        for idx, text in enumerate(texts):
            cache_key = self._get_cache_key(text, "RETRIEVAL_DOCUMENT")
            cached = self._get_cached(cache_key)
            if cached is not None:
                cached_results[idx] = cached
            else:
                uncached_texts.append(text)
                uncached_indices.append(idx)
        
        # Process uncached texts in parallel batches
        if uncached_texts:
            # Pre-process texts to handle oversized chunks
            processed_texts = []
            processed_indices = []
            
            for idx, text in enumerate(uncached_texts):
                text_chunks = self._truncate_or_split_oversized_text(text)
                # For batch processing, use first chunk if split (most important content)
                if len(text_chunks) > 1:
                    logger.warning(f"Text at index {idx} was split into {len(text_chunks)} chunks, using first chunk for batch")
                processed_texts.append(text_chunks[0])
                processed_indices.append(idx)
            
            for i in range(0, len(processed_texts), batch_size):
                batch = processed_texts[i:i + batch_size]
                batch_indices = processed_indices[i:i + batch_size]
                
                batch_results = list(self.executor.map(
                    lambda t: self._embed_with_retry(t, "RETRIEVAL_DOCUMENT"),
                    batch
                ))
                
                # Cache results
                for text, embedding in zip(batch, batch_results):
                    cache_key = self._get_cache_key(text, "RETRIEVAL_DOCUMENT")
                    self._set_cached(cache_key, embedding)
                
                uncached_embeddings.extend(batch_results)
        
        # Combine cached and uncached results in correct order
        all_embeddings = [None] * len(texts)
        for idx, embedding in cached_results.items():
            all_embeddings[idx] = embedding
        # Only iterate if there are uncached embeddings
        if uncached_indices and uncached_embeddings:
            for idx, embedding in zip(uncached_indices, uncached_embeddings):
                all_embeddings[idx] = embedding
        
        return all_embeddings
    
    def encode_query(self, text: str) -> List[float]:
        """Encode a query text (uses RETRIEVAL_QUERY task type)."""
        return self._embed_with_retry(text, "RETRIEVAL_QUERY")
    
    def clear_cache(self):
        """Clear the embedding cache."""
        self._embedding_cache.clear()
        logger.info("Embedding cache cleared")
        
    def shutdown(self):
        """Shutdown the embedding provider and release resources."""
        self.executor.shutdown(wait=True)
        logger.info("Gemini Embedding Provider shutdown complete")


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """
    Sentence Transformers embedding provider.
    
    Supports multiple models with automatic dimension detection.
    """
    
    def __init__(self, model_name: str = "sentence-transformers/all-mpnet-base-v2"):
        """
        Initialize Sentence Transformer embedding provider.
        
        Args:
            model_name: Sentence transformer model name
        """
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(model_name)
        except ImportError:
            raise ImportError("sentence-transformers package is required")
        
        # Detect dimension from model
        test_embedding = self.model.encode("test")
        self._dimension = len(test_embedding)
        logger.info(f"Initialized SentenceTransformer '{model_name}' with dimension {self._dimension}")
    
    def get_dimension(self) -> int:
        """Get embedding dimension."""
        return self._dimension
    
    def encode(self, text: str) -> List[float]:
        """Encode a single text into an embedding vector."""
        embedding = self.model.encode(text)
        if hasattr(embedding, 'tolist'):
            return embedding.tolist()
        return list(embedding)
    
    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """Encode multiple texts (sentence-transformers handles batches natively)."""
        embeddings = self.model.encode(texts)
        
        # Convert to list format
        if hasattr(embeddings, 'tolist'):
            return embeddings.tolist()
        
        # Handle numpy array
        return [emb.tolist() if hasattr(emb, 'tolist') else list(emb) for emb in embeddings]
    
    def encode_query(self, text: str) -> List[float]:
        """Encode a query text (same as document encoding for sentence-transformers)."""
        return self.encode(text)


def create_embedding_provider(config: Config, rag_config: Optional[RAGConfig] = None) -> EmbeddingProvider:
    """
    Factory function to create appropriate embedding provider based on configuration.
    
    Args:
        config: Application configuration
        rag_config: Optional RAG-specific configuration
        
    Returns:
        EmbeddingProvider instance
    """
    if rag_config is None:
        # Use defaults
        rag_config = RAGConfig()
    
    provider_name = rag_config.embedding_provider.lower()

    def _sentence_transformer_fallback_model() -> str:
        """Choose a safe sentence-transformer fallback when Gemini init fails."""
        candidate = (rag_config.embedding_model or "").strip()
        if candidate.startswith("models/") or "embedding-" in candidate:
            return "sentence-transformers/all-mpnet-base-v2"
        return candidate or "sentence-transformers/all-mpnet-base-v2"
    
    if provider_name == "gemini":
        if not config.ai.api_key:
            logger.warning("Gemini API key not found, falling back to sentence-transformers")
            return SentenceTransformerEmbeddingProvider(_sentence_transformer_fallback_model())
        
        try:
            return GeminiEmbeddingProvider(
                api_key=config.ai.api_key,
                model_name=rag_config.embedding_model,
                cache_size=rag_config.embedding_cache_size,
                cache_ttl_hours=rag_config.embedding_cache_ttl_hours,
                max_retries=rag_config.max_retries,
                retry_base_delay=rag_config.retry_base_delay
            )
        except Exception as e:
            logger.warning(f"Failed to initialize Gemini embeddings: {e}, falling back to sentence-transformers")
            return SentenceTransformerEmbeddingProvider(_sentence_transformer_fallback_model())
    else:
        # Default to sentence-transformers
        return SentenceTransformerEmbeddingProvider(_sentence_transformer_fallback_model())

