"""
Hybrid Search Module - Semantic + Keyword Search with RRF Fusion

Supports:
1. Qdrant native hybrid search (sparse-dense vectors) - PRIMARY
2. BM25 + semantic fusion for PostgreSQL backend - FALLBACK

ChromaDB is not supported.
"""
import re
import pickle
import os
import spacy
from typing import List, Dict, Any, Optional

from ....utils.logger import setup_logger
from .rules import SEARCH_STOPWORDS

logger = setup_logger(__name__)


class HybridSearchEngine:
    """
    Hybrid search combining semantic (dense) and keyword (sparse) search.
    
    For Qdrant: Uses native sparse-dense vector support
    For other backends: Uses BM25 + RRF fusion
    """
    
    def __init__(self, backend_type: str = "qdrant"):
        """
        Initialize hybrid search engine.
        
        Args:
            backend_type: "qdrant" or "postgres" 
        """
        self.backend_type = backend_type.lower()
        
        if self.backend_type not in ["qdrant", "postgres"]:
            # Handle special case for 'none' or empty
            if not backend_type or backend_type == 'none':
                 self.backend_type = 'qdrant'
            else:
                logger.warning(f"Unsupported hybrid backend: {backend_type}. Defaulting to 'qdrant'.")
                self.backend_type = 'qdrant'
        
        self.bm25_index = None
        self.indexed_docs = []
        self.doc_id_map = {}
        self.nlp = None
        
        logger.info(f"Hybrid search initialized for backend: {self.backend_type}")

    def _load_spacy(self):
        """Lazy load spaCy model."""
        if self.nlp is None:
            try:
                self.nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"]) # Disable unused pipes for speed
            except OSError:
                logger.warning("spaCy model not found. Using simple regex tokenization.")
                self.nlp = False # Flag that we tried and failed

    def supports_native_hybrid(self) -> bool:
        """Check if current backend supports native sparse-dense hybrid search."""
        return self.backend_type == "qdrant"
    
    def build_bm25_index(self, documents: List[Dict[str, Any]]):
        """Build BM25 index for non-native hybrid backends."""
        if self.supports_native_hybrid():
            logger.debug("Qdrant uses native hybrid search, skipping BM25 index")
            return
        
        if not documents:
            logger.warning("No documents provided for BM25 indexing")
            return
            
        if len(documents) > 1000:
            logger.warning(
                f"Building BM25 index for {len(documents)} documents in-memory. "
                "This may be slow and memory intensive. Consider using a persistent index."
            )
        
        try:
            from rank_bm25 import BM25Plus
        except ImportError:
            logger.error("rank-bm25 not installed. Run: pip install rank-bm25")
            return
        
        try:
            # Tokenize documents
            tokenized_docs = []
            self.doc_id_map = {}
            
            for idx, doc in enumerate(documents):
                content = doc.get('content', '')
                tokens = self._tokenize(content)
                tokenized_docs.append(tokens)
                
                # Map index to doc_id for later lookup
                doc_id = doc.get('id', f"doc_{idx}")
                self.doc_id_map[idx] = doc_id
                self.indexed_docs.append(doc)
            
            # Build BM25 index
            self.bm25_index = BM25Plus(tokenized_docs)
            logger.info(f"Built BM25 index with {len(documents)} documents (corpus size: {self.bm25_index.corpus_size})")

        except Exception as e:
            logger.error(f"Error building index: {e}")

    def save_index(self, path: str):
        """Save BM25 index to disk (Atomic)."""
        if not self.bm25_index:
            logger.warning("No BM25 index to save")
            return
            
        try:
            # Ensure directory exists
            dir_path = os.path.dirname(os.path.abspath(path))
            os.makedirs(dir_path, exist_ok=True)
            
            data = {
                'bm25_index': self.bm25_index,
                'indexed_docs': self.indexed_docs,
                'doc_id_map': self.doc_id_map
            }
            
            # Atomic write: write to temp file then rename
            temp_path = f"{path}.tmp"
            with open(temp_path, 'wb') as f:
                pickle.dump(data, f)
                
            os.replace(temp_path, path)
            logger.info(f"Saved BM25 index to {path}")
                
        except Exception as e:
            logger.error(f"Failed to save BM25 index: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def load_index(self, path: str) -> bool:
        """Load BM25 index from disk."""
        if not os.path.exists(path):
            return False
            
        try:
            with open(path, 'rb') as f:
                data = pickle.load(f)
            
            self.bm25_index = data.get('bm25_index')
            self.indexed_docs = data.get('indexed_docs', [])
            self.doc_id_map = data.get('doc_id_map', {})
            
            logger.info(f"Loaded BM25 index from {path} with {len(self.indexed_docs)} documents")
            return True
        except Exception as e:
            logger.error(f"Failed to load BM25 index: {e}")
            return False
    
    def search_bm25(self, query: str, k: int = 10) -> List[Dict[str, Any]]:
        """
        Keyword search using BM25 (for non-native hybrid backends).
        
        Args:
            query: Search query
            k: Number of results
            
        Returns:
            Top-k results by BM25 score
        """
        if self.supports_native_hybrid():
            logger.debug("Native hybrid backend detected, skipping BM25-only search")
            return []
        
        if not self.bm25_index:
            logger.warning("BM25 index not built, returning empty results")
            return []
        
        try:
            # Tokenize query
            query_tokens = self._tokenize(query)
            
            # Get BM25 scores
            scores = self.bm25_index.get_scores(query_tokens)
            
            # Get top-k indices
            top_k_indices = sorted(
                range(len(scores)), 
                key=lambda i: scores[i], 
                reverse=True
            )[:k]
            
            # Format results
            results = []
            for idx in top_k_indices:
                if scores[idx] > 0:  # Only include non-zero scores
                    if idx in self.doc_id_map:
                        doc_id = self.doc_id_map[idx]
                        doc = next((d for d in self.indexed_docs if d.get('id') == doc_id), {})
                        
                        results.append({
                            'id': doc_id,
                            'content': doc.get('content', ''),
                            'metadata': doc.get('metadata', {}),
                            'bm25_score': float(scores[idx]),
                            'source': 'bm25'
                        })
            
            return results
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def fusion_search(
        self,
        semantic_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        semantic_weight: float = 0.7,
        bm25_weight: float = 0.3,
        k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Fuse semantic and BM25 results using Reciprocal Rank Fusion (RRF).
        """
        RRF_K = 60  # Standard RRF constant
        
        # Calculate RRF scores
        rrf_scores = {}
        result_map = {}  # Store full result objects
        
        # Process semantic results
        for rank, result in enumerate(semantic_results, start=1):
            doc_id = result.get('id')
            if doc_id:
                rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + semantic_weight / (rank + RRF_K)
                if doc_id not in result_map:
                    result_map[doc_id] = result
        
        # Process BM25 results
        for rank, result in enumerate(bm25_results, start=1):
            doc_id = result.get('id')
            if doc_id:
                rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + bm25_weight / (rank + RRF_K)
                if doc_id not in result_map:
                    result_map[doc_id] = result
        
        # Sort by RRF score
        sorted_doc_ids = sorted(
            rrf_scores.keys(),
            key=lambda doc_id: rrf_scores[doc_id],
            reverse=True
        )[:k]
        
        # Build final results
        fused_results = []
        for doc_id in sorted_doc_ids:
            result = result_map[doc_id].copy()
            result['rrf_score'] = rrf_scores[doc_id]
            result['fusion_method'] = 'rrf'
            fused_results.append(result)
        
        logger.debug(
            f"Fused {len(semantic_results)} semantic + {len(bm25_results)} BM25 "
            f"results → {len(fused_results)} final results"
        )
        
        return fused_results
    
    def extract_keywords_for_sparse(self, text: str, max_keywords: int = 10) -> Dict[str, float]:
        """
        Extract keywords with TF-IDF-like scores for vector store sparse vectors.
        Uses POS filtering if spaCy is available.
        """
        self._load_spacy()
        
        if self.nlp:
            doc = self.nlp(text)
            # Filter by POS (Noun, Proper Noun, Verb, Adjective)
            tokens = [
                token.lemma_.lower() for token in doc 
                if not token.is_stop and not token.is_punct and len(token.text) > 2
                and token.pos_ in {'NOUN', 'PROPN', 'VERB', 'ADJ'}
            ]
        else:
            # Fallback to simple tokenization
            tokens = self._tokenize(text)
        
        # Calculate term frequencies
        tf = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
        
        # Simple scoring based on frequency
        max_freq = max(tf.values()) if tf else 1
        keyword_scores = {
            token: freq / max_freq 
            for token, freq in tf.items()
        }
        
        # Return top keywords
        sorted_keywords = sorted(
            keyword_scores.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:max_keywords]
        
        return dict(sorted_keywords)
    
    def _tokenize(self, text: str) -> List[str]:
        """
        Tokenize text for BM25 indexing or keyword extraction.
        Uses spaCy lemmatization if available.
        """
        self._load_spacy()
        
        if self.nlp:
            doc = self.nlp(text)
            return [
                token.lemma_.lower() for token in doc 
                if not token.is_stop and not token.is_punct and len(token.text) > 2
                and not token.is_space
            ]
        
        # Fallback to simple regex
        tokens = re.findall(r'\b\w+\b', text.lower())
        return [t for t in tokens if t not in SEARCH_STOPWORDS and len(t) > 2]
    
    def adaptive_fusion_weights(self, query: str) -> tuple:
        """
        Compute adaptive RRF weights based on query characteristics.
        
        Short queries with specific entities benefit from BM25.
        Long conceptual queries benefit from semantic search.
        
        Args:
            query: Search query
            
        Returns:
            Tuple of (semantic_weight, bm25_weight)
        """
        words = query.split()
        word_count = len(words)
        
        # Check for named entities (capitalized words, excluding first word)
        has_named_entity = any(
            word[0].isupper() and i > 0 
            for i, word in enumerate(words) 
            if word
        )
        
        # Check for quoted phrases (exact match intent)
        has_quotes = '"' in query or "'" in query
        
        # Check for question words (conceptual queries)
        question_words = {'what', 'why', 'how', 'when', 'where', 'who', 'which'}
        is_question = any(w.lower() in question_words for w in words[:2])
        
        # Determine weights based on query type
        if has_quotes:
            # Quoted phrases → exact match → higher BM25
            return 0.4, 0.6
        elif word_count <= 3 and has_named_entity:
            # Short entity queries → equal weights
            return 0.5, 0.5
        elif word_count <= 2:
            # Very short queries → higher BM25 for precision
            return 0.5, 0.5
        elif word_count > 10 or is_question:
            # Long/conceptual queries → higher semantic
            return 0.8, 0.2
        else:
            # Default balanced
            return 0.7, 0.3
    
    def fusion_search_adaptive(
        self,
        semantic_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]],
        query: str,
        k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Fuse results using adaptive weights based on query type.
        
        Args:
            semantic_results: Results from semantic search
            bm25_results: Results from BM25 search
            query: Original query for weight calculation
            k: Number of results to return
            
        Returns:
            Fused results with adaptive weighting
        """
        semantic_weight, bm25_weight = self.adaptive_fusion_weights(query)
        logger.debug(f"Adaptive fusion weights: semantic={semantic_weight:.2f}, bm25={bm25_weight:.2f}")
        
        return self.fusion_search(
            semantic_results=semantic_results,
            bm25_results=bm25_results,
            semantic_weight=semantic_weight,
            bm25_weight=bm25_weight,
            k=k
        )

