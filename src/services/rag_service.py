"""
RAG Service - High-level service layer for RAG operations

Provides a simplified interface for RAG operations with caching and LLM enhancement.
This is a thin service layer that wraps RAGEngine with additional features like
context caching and LLM-based context extraction.
"""
import json
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from ..ai.rag import RAGEngine
from ..utils.config import Config, RAGConfig
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class RAGService:
    """
    High-level RAG service with caching and LLM enhancement.
    
    This service layer provides:
    - Context caching with TTL
    - LLM-based context extraction
    - Query enhancement
    - Simplified API for common RAG operations
    
    For direct RAG operations, use RAGEngine directly.
    """
    
    def __init__(self, config: Config, collection_name: str = "email-knowledge"):
        """
        Initialize RAG service.
        
        Args:
            config: Application configuration
            collection_name: RAG collection name
        """
        self.config = config
        
        # Get RAG config for cache TTL
        rag_config = config.rag if hasattr(config, 'rag') and config.rag else RAGConfig()
        self.cache_ttl = timedelta(hours=rag_config.cache_ttl_hours)
        
        # Initialize RAG engine
        self.rag_engine = RAGEngine(config, collection_name=collection_name, rag_config=rag_config)
        
        # Context cache
        self._context_cache: Dict[str, Dict[str, Any]] = {}
        
        # Initialize NLP utilities (optional)
        self.classifier = None
        self.llm_client = None
        self._init_nlp()
        
        logger.info("[OK] RAG Service initialized")
    
    def _init_nlp(self):
        """Initialize optional NLP utilities for query understanding."""
        try:
            from ..ai.query_classifier import QueryClassifier
            from ..ai.llm_factory import LLMFactory
            
            self.classifier = QueryClassifier(self.config)
            self.llm_client = LLMFactory.get_llm_for_provider(self.config, temperature=0.1)
            logger.debug("NLP capabilities initialized for RAG service")
        except Exception as e:
            logger.debug(f"NLP initialization skipped: {e}")
    
    def get_context(self, query: str, max_results: int = 3, use_llm: bool = True) -> Dict[str, Any]:
        """
        Get context for a query using semantic search with optional LLM enhancement.
        
        Args:
            query: User query
            max_results: Maximum number of context results
            use_llm: Whether to use LLM for context extraction
            
        Returns:
            Context dictionary with relevant information
        """
        # Check cache first
        cache_key = f"{query}_{max_results}_{use_llm}"
        if cache_key in self._context_cache:
            cached_entry = self._context_cache[cache_key]
            if datetime.now() - cached_entry['timestamp'] < self.cache_ttl:
                logger.debug(f"Using cached context for: {query}")
                return cached_entry['context']
        
        try:
            # Perform semantic search
            results = self.rag_engine.search(query, k=max_results, rerank=True)
            
            if not results:
                context = {'summary': '', 'results': [], 'confidence': 0.0}
            else:
                # Extract context using LLM if available
                if use_llm and self.llm_client:
                    context = self._extract_context_with_llm(query, results)
                else:
                    context = self._extract_context_simple(results)
            
            # Cache the result
            self._context_cache[cache_key] = {
                'context': context,
                'timestamp': datetime.now()
            }
            
            return context
            
        except Exception as e:
            logger.error(f"Failed to get context: {e}")
            return {'summary': '', 'results': [], 'confidence': 0.0, 'error': str(e)}
    
    def _extract_context_with_llm(self, query: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract context using LLM for better understanding."""
        try:
            # Build results summary for LLM
            results_text = ""
            for i, result in enumerate(results[:5], 1):
                metadata = result.get('metadata', {})
                content = result.get('content', '')[:500]
                results_text += f"\n{i}. Subject: {metadata.get('subject', 'N/A')}\n"
                results_text += f"   From: {metadata.get('sender', 'N/A')}\n"
                results_text += f"   Content: {content}\n"
            
            prompt = f"""Extract key context from the following search results for the query: "{query}"

Results:
{results_text}

Please provide:
1. A concise summary of the key information
2. Main topics or themes
3. Any important dates, people, or entities mentioned
4. The overall relevance to the query

Format as JSON with keys: summary, topics, entities, relevance_score"""
            
            response = self.llm_client.invoke(prompt)
            llm_context = self._parse_llm_response(response)
            
            return {
                'summary': llm_context.get('summary', ''),
                'topics': llm_context.get('topics', []),
                'entities': llm_context.get('entities', []),
                'results': results,
                'confidence': llm_context.get('relevance_score', self._calculate_confidence(results)),
                'timestamp': datetime.now().isoformat(),
                'llm_enhanced': True
            }
        except Exception as e:
            logger.warning(f"LLM context extraction failed: {e}")
            return self._extract_context_simple(results)
    
    def _extract_context_simple(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Simple context extraction without LLM."""
        summary_parts = []
        for result in results:
            metadata = result.get('metadata', {})
            subject = metadata.get('subject', 'No Subject')
            sender = metadata.get('sender', 'Unknown')
            summary_parts.append(f"{subject} from {sender}")
        
        summary = f"Related emails: {'; '.join(summary_parts)}"
        
        return {
            'summary': summary,
            'results': results,
            'confidence': self._calculate_confidence(results),
            'timestamp': datetime.now().isoformat(),
            'llm_enhanced': False
        }
    
    def _parse_llm_response(self, response) -> Dict[str, Any]:
        """Parse LLM JSON response."""
        try:
            if hasattr(response, 'content'):
                text = response.content
            else:
                text = str(response)
            
            # Remove markdown code blocks if present
            json_match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
            if json_match:
                text = json_match.group(1)
            
            return json.loads(text)
        except Exception as e:
            logger.debug(f"Failed to parse LLM response: {e}")
            return {'summary': '', 'topics': [], 'entities': [], 'relevance_score': 0.5}
    
    def get_email_context(self, query: str) -> Dict[str, Any]:
        """
        Get email-specific context for a query.
        
        Args:
            query: User query
            
        Returns:
            Email context dictionary
        """
        try:
            results = self.rag_engine.search(query, k=5, rerank=True)
            
            if not results:
                return {'emails': [], 'senders': [], 'subjects': []}
            
            # Extract email information
            emails = []
            senders = []
            subjects = []
            
            for result in results:
                metadata = result.get('metadata', {})
                emails.append({
                    'subject': metadata.get('subject', 'No Subject'),
                    'sender': metadata.get('sender', 'Unknown'),
                    'timestamp': metadata.get('timestamp', ''),
                    'content': result.get('content', '')[:200] + '...'
                })
                senders.append(metadata.get('sender', 'Unknown'))
                subjects.append(metadata.get('subject', 'No Subject'))
            
            return {
                'emails': emails,
                'senders': list(set(senders)),
                'subjects': list(set(subjects)),
                'total_found': len(results)
            }
            
        except Exception as e:
            logger.error(f"Failed to get email context: {e}")
            return {'emails': [], 'senders': [], 'subjects': [], 'error': str(e)}
    
    def search_with_filters(self, query: str, filters: Optional[Dict[str, Any]] = None, k: int = 5) -> List[Dict[str, Any]]:
        """
        Search with metadata filters.
        
        Args:
            query: Search query
            filters: Metadata filters
            k: Number of results
            
        Returns:
            List of filtered results
        """
        try:
            return self.rag_engine.search(query, k=k, filters=filters, rerank=True)
        except Exception as e:
            logger.error(f"Filtered search failed: {e}")
            return []
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """Get RAG collection statistics."""
        return self.rag_engine.get_stats()
    
    def _calculate_confidence(self, results: List[Dict[str, Any]]) -> float:
        """Calculate confidence score for search results."""
        if not results:
            return 0.0
        
        distances = [result.get('distance', 1.0) for result in results]
        avg_distance = sum(distances) / len(distances)
        confidence = max(0.0, 1.0 - avg_distance)
        
        return round(confidence, 2)
    
    def clear_cache(self):
        """Clear the context cache."""
        self._context_cache.clear()
        logger.info("RAG service cache cleared")
    
    def get_service_info(self) -> Dict[str, Any]:
        """Get RAG service information."""
        stats = self.get_collection_stats()
        return {
            'service_name': 'RAGService',
            'collection_stats': stats,
            'cache_size': len(self._context_cache),
            'has_rag_engine': self.rag_engine is not None
        }
    
    # Delegate common operations to RAG engine
    def index_document(self, doc_id: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Index a single document."""
        if metadata is None:
            metadata = {}
        # Ensure neo4j_node_id exists for hybrid GraphRAG integration (THE BRIDGE)
        if 'neo4j_node_id' not in metadata:
            metadata['neo4j_node_id'] = doc_id
        if 'node_id' not in metadata:
            metadata['node_id'] = doc_id  # Also keep for backward compatibility
        self.rag_engine.index_document(doc_id, content, metadata)
    
    def index_email(self, email_id: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Index an email (convenience method)."""
        if metadata is None:
            metadata = {}
        metadata['doc_type'] = 'email'
        # Ensure neo4j_node_id exists for hybrid GraphRAG integration (THE BRIDGE)
        if 'neo4j_node_id' not in metadata:
            metadata['neo4j_node_id'] = email_id
        if 'node_id' not in metadata:
            metadata['node_id'] = email_id  # Also keep for backward compatibility
        self.rag_engine.index_document(email_id, content, metadata)
    
    def search(self, query: str, k: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Search for similar documents."""
        return self.rag_engine.search(query, k=k, filters=filters, rerank=True)
