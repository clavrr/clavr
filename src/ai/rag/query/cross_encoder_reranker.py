"""
Cross-Encoder Reranker

High-accuracy reranking using cross-encoder models that jointly encode
query and document for more precise relevance scoring.

This is a significant improvement over bi-encoder (embedding-based) scoring
as cross-encoders can capture fine-grained query-document interactions.

Expected impact: +15-25% precision on retrieval tasks.
"""
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import asyncio

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class CrossEncoderConfig:
    """Configuration for cross-encoder reranking."""
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"
    batch_size: int = 32
    max_length: int = 512  # Max tokens for query + document
    score_threshold: float = 0.0  # Minimum score to keep
    use_gpu: bool = False


class CrossEncoderReranker:
    """
    Reranks search results using a cross-encoder model for higher accuracy.
    
    Cross-encoders jointly process query and document, enabling them to
    capture fine-grained semantic relationships that bi-encoders miss.
    
    Recommended models:
    - ms-marco-MiniLM-L-12-v2: Fast, good quality (default)
    - ms-marco-MiniLM-L-6-v2: Faster, slightly lower quality
    - cross-encoder/nli-deberta-v3-base: Higher quality, slower
    
    Usage:
        reranker = CrossEncoderReranker()
        reranked = reranker.rerank(query, results, k=10)
    """
    
    def __init__(self, config: Optional[CrossEncoderConfig] = None):
        """
        Initialize cross-encoder reranker.
        
        Args:
            config: Optional configuration
        """
        self.config = config or CrossEncoderConfig()
        self._model = None
        self._initialized = False
        
        logger.info(f"CrossEncoderReranker initialized (model={self.config.model_name})")
    
    def _load_model(self):
        """Lazy load the cross-encoder model."""
        if self._model is not None:
            return
        
        try:
            from sentence_transformers import CrossEncoder
            
            device = "cuda" if self.config.use_gpu else "cpu"
            self._model = CrossEncoder(
                self.config.model_name,
                max_length=self.config.max_length,
                device=device
            )
            self._initialized = True
            logger.info(f"CrossEncoder model loaded: {self.config.model_name}")
            
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )
            self._initialized = False
        except Exception as e:
            logger.error(f"Failed to load cross-encoder model: {e}")
            self._initialized = False
    
    def rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        k: int = 10,
        content_key: str = "content",
        preserve_original_score: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Rerank search results using cross-encoder.
        
        Args:
            query: The search query
            results: List of search results with 'content' field
            k: Number of results to return
            content_key: Key for document content
            preserve_original_score: Keep original score as 'original_score'
            
        Returns:
            Reranked results with 'cross_encoder_score' field
        """
        if not results:
            return []
        
        # Load model if needed
        self._load_model()
        
        if not self._initialized:
            # Fallback: return original results if model unavailable
            logger.warning("Cross-encoder not available, returning original results")
            return results[:k]
        
        try:
            # Prepare query-document pairs
            pairs = []
            for result in results:
                content = result.get(content_key, "")
                if not content:
                    content = result.get("text", "")
                
                # Truncate if needed
                if len(content) > 2000:
                    content = content[:2000]
                
                pairs.append((query, content))
            
            # Score all pairs
            scores = self._model.predict(
                pairs,
                batch_size=self.config.batch_size,
                show_progress_bar=False
            )
            
            # Add scores to results
            reranked = []
            for result, score in zip(results, scores):
                result_copy = result.copy()
                
                if preserve_original_score and "score" in result:
                    result_copy["original_score"] = result["score"]
                
                result_copy["cross_encoder_score"] = float(score)
                result_copy["score"] = float(score)  # Update main score
                
                if score >= self.config.score_threshold:
                    reranked.append(result_copy)
            
            # Sort by cross-encoder score
            reranked.sort(key=lambda x: x["cross_encoder_score"], reverse=True)
            
            return reranked[:k]
            
        except Exception as e:
            logger.error(f"Cross-encoder reranking failed: {e}")
            return results[:k]
    
    async def arerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        k: int = 10,
        content_key: str = "content"
    ) -> List[Dict[str, Any]]:
        """
        Async version of rerank (runs in thread pool).
        
        Cross-encoder inference is CPU/GPU bound, so we run it
        in a thread pool to avoid blocking the event loop.
        """
        return await asyncio.to_thread(
            self.rerank, query, results, k, content_key
        )
    
    def combine_with_heuristic(
        self,
        query: str,
        results: List[Dict[str, Any]],
        heuristic_scores: List[float],
        k: int = 10,
        cross_encoder_weight: float = 0.7,
        heuristic_weight: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Combine cross-encoder scores with heuristic scores.
        
        Useful for blending cross-encoder precision with other signals
        like recency, metadata importance, etc.
        
        Args:
            query: Search query
            results: Search results
            heuristic_scores: Pre-computed heuristic scores
            k: Number of results
            cross_encoder_weight: Weight for cross-encoder score
            heuristic_weight: Weight for heuristic score
            
        Returns:
            Results sorted by combined score
        """
        # Get cross-encoder scores
        reranked = self.rerank(query, results, k=len(results))
        
        # Combine scores
        for i, result in enumerate(reranked):
            ce_score = result.get("cross_encoder_score", 0)
            heuristic = heuristic_scores[i] if i < len(heuristic_scores) else 0
            
            # Normalize cross-encoder score to 0-1 if needed
            # (ms-marco models output roughly -10 to 10)
            ce_normalized = (ce_score + 10) / 20
            ce_normalized = max(0, min(1, ce_normalized))
            
            combined = (
                ce_normalized * cross_encoder_weight +
                heuristic * heuristic_weight
            )
            result["combined_score"] = combined
            result["score"] = combined
        
        # Re-sort by combined score
        reranked.sort(key=lambda x: x["combined_score"], reverse=True)
        
        return reranked[:k]


class LightweightCrossEncoder:
    """
    Lightweight alternative using Gemini for cross-encoding.
    
    Uses LLM to score query-document relevance when sentence-transformers
    isn't available. Slower but doesn't require additional dependencies.
    """
    
    def __init__(self, llm_client: Optional[Any] = None):
        """
        Initialize with LLM client.
        
        Args:
            llm_client: Gemini or other LLM client
        """
        self.llm_client = llm_client
    
    async def rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Rerank using LLM for scoring.
        
        Note: This is slower and uses API calls, use sparingly.
        """
        if not self.llm_client:
            return results[:k]
        
        # Only score top N to save API calls
        candidates = results[:min(k * 2, 20)]
        
        scored = []
        for result in candidates:
            content = result.get("content", "")[:500]
            score = await self._score_relevance(query, content)
            result_copy = result.copy()
            result_copy["llm_relevance_score"] = score
            result_copy["score"] = score
            scored.append(result_copy)
        
        scored.sort(key=lambda x: x["llm_relevance_score"], reverse=True)
        return scored[:k]
    
    async def _score_relevance(self, query: str, content: str) -> float:
        """Score relevance of content to query using LLM."""
        try:
            prompt = f"""Rate the relevance of this document to the query on a scale of 0-10.

Query: {query}

Document: {content}

Output only a number from 0 to 10."""
            
            from google import genai
            
            response = await self.llm_client.models.generate_content_async(
                model="gemini-2.0-flash",
                contents=prompt
            )
            
            # Parse score from response
            text = response.text.strip()
            score = float(text.split()[0]) / 10.0
            return max(0, min(1, score))
            
        except Exception as e:
            logger.debug(f"LLM scoring failed: {e}")
            return 0.5  # Neutral score on failure
