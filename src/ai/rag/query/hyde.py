"""
Hypothetical Document Embeddings (HyDE)

Improves retrieval on vague or abstract queries by generating a hypothetical
answer first, then using that answer to search for similar documents.

This technique helps bridge the semantic gap between user queries and
document content, particularly effective for:
- Conceptual questions
- How-to queries
- Vague or underspecified queries

Expected impact: +15% recall on vague queries
"""
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import asyncio

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class HyDEConfig:
    """Configuration for HyDE generation."""
    model_name: str = "gemini-2.0-flash"
    max_tokens: int = 300
    temperature: float = 0.3
    num_hypotheticals: int = 1  # Number of hypothetical docs to generate
    combine_with_original: bool = True  # Also search with original query


class HyDEGenerator:
    """
    Hypothetical Document Embeddings (HyDE) Generator.
    
    Creates a hypothetical document that would answer the user's query,
    then uses that document for semantic search instead of the query itself.
    
    Research shows this can significantly improve retrieval for:
    - Abstract questions ("What is the best approach to...")
    - Conceptual queries ("How does X relate to Y")
    - Vague queries that don't contain the exact document terminology
    
    Usage:
        hyde = HyDEGenerator(llm_client)
        # Generate hypothetical and search
        results = await hyde.search_with_hyde(query, rag_engine, k=5)
        
        # Or just get the hypothetical document
        hypothetical = await hyde.generate_hypothetical(query)
    """
    
    # Query patterns that benefit from HyDE
    HYDE_BENEFICIAL_PATTERNS = [
        "how to", "how do", "what is the best", "what are",
        "explain", "describe", "why does", "when should",
        "approach to", "strategy for", "way to"
    ]
    
    def __init__(
        self, 
        llm_client: Optional[Any] = None,
        config: Optional[HyDEConfig] = None
    ):
        """
        Initialize HyDE generator.
        
        Args:
            llm_client: Gemini or compatible LLM client
            config: Optional configuration
        """
        self.llm_client = llm_client
        self.config = config or HyDEConfig()
        
        logger.info("HyDEGenerator initialized")
    
    def should_use_hyde(self, query: str) -> bool:
        """
        Determine if HyDE would benefit this query.
        
        HyDE is most effective for abstract/conceptual queries
        and less useful for specific entity queries.
        
        Args:
            query: User's search query
            
        Returns:
            True if HyDE would likely help
        """
        query_lower = query.lower()
        
        # Check for beneficial patterns
        has_beneficial_pattern = any(
            pattern in query_lower 
            for pattern in self.HYDE_BENEFICIAL_PATTERNS
        )
        
        # Short entity queries don't benefit from HyDE
        word_count = len(query.split())
        is_short_entity_query = word_count <= 3 and not has_beneficial_pattern
        
        # Questions typically benefit more
        is_question = query_lower.startswith(('what', 'how', 'why', 'when', 'where', 'who'))
        
        return (has_beneficial_pattern or is_question) and not is_short_entity_query
    
    async def generate_hypothetical(
        self, 
        query: str,
        context: Optional[str] = None
    ) -> str:
        """
        Generate a hypothetical document that would answer the query.
        
        Args:
            query: User's search query
            context: Optional additional context
            
        Returns:
            Hypothetical document text
        """
        if not self.llm_client:
            logger.warning("No LLM client available for HyDE generation")
            return query  # Fallback to original query
        
        try:
            prompt = self._build_prompt(query, context)
            
            from google import genai
            
            response = await self.llm_client.models.generate_content_async(
                model=self.config.model_name,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=self.config.temperature,
                    max_output_tokens=self.config.max_tokens
                )
            )
            
            hypothetical = response.text.strip()
            logger.debug(f"HyDE generated: {hypothetical[:100]}...")
            
            return hypothetical
            
        except Exception as e:
            logger.error(f"HyDE generation failed: {e}")
            return query  # Fallback to original query
    
    def _build_prompt(self, query: str, context: Optional[str] = None) -> str:
        """Build the prompt for hypothetical document generation."""
        base_prompt = f"""Write a short, factual paragraph that directly answers this question or addresses this topic. Write as if you are an expert providing information from a document. Do not include phrases like "According to" or "Based on". Just write the answer content directly.

Question/Topic: {query}"""

        if context:
            base_prompt += f"\n\nAdditional context: {context}"
        
        return base_prompt
    
    async def generate_multiple_hypotheticals(
        self,
        query: str,
        num_hypotheticals: int = 3
    ) -> List[str]:
        """
        Generate multiple hypothetical documents for better coverage.
        
        Useful for complex queries where multiple perspectives might help.
        
        Args:
            query: User's search query
            num_hypotheticals: Number of hypotheticals to generate
            
        Returns:
            List of hypothetical documents
        """
        if not self.llm_client:
            return [query]
        
        # Generate concurrently for speed
        tasks = [
            self.generate_hypothetical(query)
            for _ in range(num_hypotheticals)
        ]
        
        hypotheticals = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out failures
        valid = [h for h in hypotheticals if isinstance(h, str) and h != query]
        
        if not valid:
            return [query]
        
        return valid
    
    async def search_with_hyde(
        self,
        query: str,
        rag_engine: Any,
        k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        combine_results: bool = True
    ) -> Dict[str, Any]:
        """
        Perform search using HyDE.
        
        Process:
        1. Generate hypothetical document
        2. Search using hypothetical as query
        3. Optionally combine with original query results
        
        Args:
            query: Original user query
            rag_engine: RAG engine instance
            k: Number of results
            filters: Optional metadata filters
            combine_results: Whether to combine with original query results
            
        Returns:
            Dict with results and metadata
        """
        metadata = {
            'original_query': query,
            'hyde_used': False,
            'hypothetical': None
        }
        
        # Check if HyDE would benefit this query
        if not self.should_use_hyde(query):
            logger.debug(f"HyDE skipped for query: {query[:50]}...")
            results = await rag_engine.asearch(query, k=k, filters=filters)
            metadata['hyde_used'] = False
            return {'results': results, 'metadata': metadata}
        
        # Generate hypothetical
        hypothetical = await self.generate_hypothetical(query)
        metadata['hypothetical'] = hypothetical
        metadata['hyde_used'] = True
        
        # Search with hypothetical
        hyde_results = await rag_engine.asearch(hypothetical, k=k, filters=filters)
        
        if combine_results and self.config.combine_with_original:
            # Also search with original query
            original_results = await rag_engine.asearch(query, k=k, filters=filters)
            
            # Merge and deduplicate
            all_results = self._merge_results(hyde_results, original_results)
            metadata['combined_count'] = len(all_results)
            
            return {'results': all_results[:k], 'metadata': metadata}
        
        return {'results': hyde_results, 'metadata': metadata}
    
    def _merge_results(
        self,
        primary: List[Dict[str, Any]],
        secondary: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Merge and deduplicate results, keeping best scores."""
        seen_ids = {}
        
        for result in primary + secondary:
            result_id = result.get('id') or result.get('doc_id')
            if result_id:
                if result_id not in seen_ids:
                    seen_ids[result_id] = result
                else:
                    # Keep the one with higher score
                    existing_score = seen_ids[result_id].get('score', 0)
                    new_score = result.get('score', 0)
                    if new_score > existing_score:
                        seen_ids[result_id] = result
            else:
                # No ID, add with hash of content
                content = result.get('content', '')
                content_hash = hash(content[:200])
                if content_hash not in seen_ids:
                    seen_ids[content_hash] = result
        
        # Sort by score
        merged = list(seen_ids.values())
        merged.sort(key=lambda x: x.get('score', x.get('rerank_score', 0)), reverse=True)
        
        return merged


# Convenience function for one-off usage
async def hyde_search(
    query: str,
    rag_engine: Any,
    llm_client: Any,
    k: int = 5,
    filters: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Convenience function for HyDE search.
    
    Args:
        query: Search query
        rag_engine: RAG engine instance
        llm_client: LLM client for generation
        k: Number of results
        filters: Optional filters
        
    Returns:
        Search results
    """
    hyde = HyDEGenerator(llm_client)
    result = await hyde.search_with_hyde(query, rag_engine, k, filters)
    return result['results']
