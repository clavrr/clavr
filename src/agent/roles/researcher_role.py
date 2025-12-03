"""
Researcher Role: Query knowledge bases and retrieve context

Responsible for:
- Querying Pinecone (vector store) for semantic matches
- Querying Neo4j (graph database) for relationship traversal
- Combining vector and graph results for comprehensive context
- Providing contextual information to other roles
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from ...utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class ResearchResult:
    """Result from research query"""
    query: str
    vector_results: List[Dict[str, Any]] = field(default_factory=list)
    graph_results: List[Dict[str, Any]] = field(default_factory=list)
    combined_results: List[Dict[str, Any]] = field(default_factory=list)
    success: bool = True
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    
    def get_top_results(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get top N results from combined results"""
        return self.combined_results[:limit]


class ResearcherRole:
    """
    Researcher Role: Queries knowledge bases for contextual information
    
    The Researcher is responsible for:
    - Querying Pinecone (vector store) for semantic document matches
    - Querying Neo4j (graph database) for relationship traversal
    - Combining results from both sources
    - Providing rich context to other roles
    
    This implements the "Researcher" role from the multi-role architecture.
    """
    
    def __init__(
        self,
        rag_engine: Optional[Any] = None,
        graph_manager: Optional[Any] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize ResearcherRole
        
        Args:
            rag_engine: Optional RAGEngine for Pinecone queries
            graph_manager: Optional KnowledgeGraphManager for Neo4j queries
            config: Optional configuration dictionary
        """
        self.rag_engine = rag_engine
        self.graph_manager = graph_manager
        self.config = config or {}
        
        self.stats = {
            'queries_performed': 0,
            'vector_queries': 0,
            'graph_queries': 0,
            'combined_queries': 0,
            'avg_results_per_query': 0.0,
            'errors': 0
        }
        
        logger.info("ResearcherRole initialized")
    
    async def research(
        self,
        query: str,
        limit: int = 10,
        use_vector: bool = True,
        use_graph: bool = True,
        filters: Optional[Dict[str, Any]] = None
    ) -> ResearchResult:
        """
        Perform research query across knowledge bases
        
        Args:
            query: Research query string
            limit: Maximum number of results to return
            use_vector: Whether to query Pinecone vector store
            use_graph: Whether to query Neo4j graph database
            filters: Optional filters (dates, domains, etc.)
            
        Returns:
            ResearchResult with combined results
        """
        start_time = datetime.now()
        result = ResearchResult(query=query)
        
        try:
            self.stats['queries_performed'] += 1
            
            # Query vector store (Pinecone)
            if use_vector and self.rag_engine:
                try:
                    vector_results = await self._query_vector_store(query, limit, filters)
                    result.vector_results = vector_results
                    self.stats['vector_queries'] += 1
                    logger.debug(f"[RESEARCHER] Vector query returned {len(vector_results)} results")
                except Exception as e:
                    logger.warning(f"[RESEARCHER] Vector query failed: {e}")
            
            # Query graph database (Neo4j)
            if use_graph and self.graph_manager:
                try:
                    graph_results = await self._query_graph_database(query, limit, filters)
                    result.graph_results = graph_results
                    self.stats['graph_queries'] += 1
                    logger.debug(f"[RESEARCHER] Graph query returned {len(graph_results)} results")
                except Exception as e:
                    logger.warning(f"[RESEARCHER] Graph query failed: {e}")
            
            # Combine results intelligently
            result.combined_results = self._combine_results(
                result.vector_results,
                result.graph_results,
                limit
            )
            
            if use_vector and use_graph:
                self.stats['combined_queries'] += 1
            
            # Update statistics
            total_results = len(result.combined_results)
            if self.stats['queries_performed'] > 0:
                self.stats['avg_results_per_query'] = (
                    (self.stats['avg_results_per_query'] * (self.stats['queries_performed'] - 1) + total_results) /
                    self.stats['queries_performed']
                )
            
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            result.execution_time_ms = execution_time
            
            logger.info(f"[RESEARCHER] Research completed: {total_results} results in {execution_time:.1f}ms")
            
        except Exception as e:
            result.success = False
            result.error = str(e)
            self.stats['errors'] += 1
            logger.error(f"[RESEARCHER] Research failed: {e}", exc_info=True)
        
        return result
    
    async def _query_vector_store(
        self,
        query: str,
        limit: int,
        filters: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Query Pinecone vector store"""
        try:
            # Use RAG engine's search method (RAGEngine.search is sync, so wrap in thread)
            import asyncio
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self.rag_engine.search(
                    query=query,
                    k=limit,  # RAGEngine uses 'k' not 'top_k'
                    filters=filters
                )
            )
            
            # Format results consistently
            # RAGEngine returns results with 'content' key, but some may use 'text'
            formatted_results = []
            for result in results:
                # Handle both 'content' and 'text' keys
                text_content = result.get('content') or result.get('text', '')
                # Handle both 'confidence' and 'score' keys
                score = result.get('confidence') or result.get('score', 0.0)
                # If distance is provided, convert to score (lower distance = higher score)
                if 'distance' in result and score == 0.0:
                    distance = result.get('distance', 1.0)
                    score = max(0.0, 1.0 - distance)  # Convert distance to score
                
                formatted_results.append({
                    'id': result.get('id', ''),
                    'text': text_content,
                    'content': text_content,  # Include both for compatibility
                    'metadata': result.get('metadata', {}),
                    'score': score,
                    'confidence': result.get('confidence', score),
                    'source': 'vector'
                })
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"[RESEARCHER] Vector store query error: {e}")
            return []
    
    async def _query_graph_database(
        self,
        query: str,
        limit: int,
        filters: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Query Neo4j graph database"""
        try:
            # Build Cypher query based on query text
            # This is a simplified version - in production, you'd use query parsing
            cypher_query = """
            MATCH (n)
            WHERE toLower(n.text) CONTAINS toLower($search_query)
               OR toLower(n.subject) CONTAINS toLower($search_query)
               OR toLower(n.name) CONTAINS toLower($search_query)
            """
            
            # Use 'search_query' instead of 'query' to avoid conflict with method parameter name
            params = {'search_query': query, 'limit': limit}
            
            # Apply filters if provided
            filter_conditions = []
            if filters:
                # Filter by domain if specified
                if 'domain' in filters:
                    filter_conditions.append("n.domain = $domain")
                    params['domain'] = filters['domain']
                
                # Filter by date range if specified
                if 'from_date' in filters:
                    filter_conditions.append("n.created_at >= $from_date")
                    params['from_date'] = filters['from_date']
                if 'to_date' in filters:
                    filter_conditions.append("n.created_at <= $to_date")
                    params['to_date'] = filters['to_date']
                
                # Filter by type if specified
                if 'type' in filters:
                    filter_conditions.append("n.type = $type")
                    params['type'] = filters['type']
                
                # Add filter conditions to WHERE clause
                if filter_conditions:
                    cypher_query += " AND " + " AND ".join(filter_conditions)
            
            # Complete the query
            cypher_query += "\nRETURN n\nLIMIT $limit"
            
            # Execute query (may be sync or async)
            import asyncio
            if asyncio.iscoroutinefunction(self.graph_manager.query):
                results = await self.graph_manager.query(cypher_query, params)
            else:
                # Run sync method in thread pool
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(
                    None,
                    lambda: self.graph_manager.query(cypher_query, params)
                )
            
            # Format results consistently
            formatted_results = []
            for record in results:
                node = record.get('n', {})
                formatted_results.append({
                    'id': node.get('id', ''),
                    'text': node.get('text', node.get('subject', node.get('name', ''))),
                    'metadata': {k: v for k, v in node.items() if k not in ['id', 'text', 'subject', 'name']},
                    'score': 1.0,  # Graph queries don't have scores
                    'source': 'graph'
                })
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"[RESEARCHER] Graph database query error: {e}")
            return []
    
    def _combine_results(
        self,
        vector_results: List[Dict[str, Any]],
        graph_results: List[Dict[str, Any]],
        limit: int
    ) -> List[Dict[str, Any]]:
        """
        Combine vector and graph results intelligently
        
        Strategy:
        1. Prioritize high-scoring vector results
        2. Add graph results that aren't duplicates
        3. Sort by relevance score
        """
        combined = []
        seen_ids = set()
        
        # Add vector results first (they have scores)
        for result in vector_results:
            result_id = result.get('id', '')
            if result_id and result_id not in seen_ids:
                combined.append(result)
                seen_ids.add(result_id)
        
        # Add graph results that aren't duplicates
        for result in graph_results:
            result_id = result.get('id', '')
            if result_id and result_id not in seen_ids:
                combined.append(result)
                seen_ids.add(result_id)
        
        # Sort by score (vector results have scores, graph results have score=1.0)
        combined.sort(key=lambda x: x.get('score', 0.0), reverse=True)
        
        return combined[:limit]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get researcher statistics"""
        return self.stats.copy()

