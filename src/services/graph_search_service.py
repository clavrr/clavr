"""
Graph-Enhanced Search Service

Combines knowledge graph reasoning with vector search for intelligent querying.
Bridges the gap between graph system and user-facing queries.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..utils.logger import setup_logger
from ..utils.config import Config
from ..ai.rag import RAGEngine
from .indexing.graph import KnowledgeGraphManager, GraphRAGAnalyzer, NodeType, RelationType
from .indexing.hybrid_index import HybridIndexCoordinator
from .indexing.rag_graph_bridge import GraphRAGIntegrationService

logger = setup_logger(__name__)


class GraphSearchService:
    """
    Graph-enhanced search service combining vector and graph queries
    
    Usage:
        service = GraphSearchService(config, user_id)
        results = await service.search("find all receipts from Amazon")
    """
    
    def __init__(
        self,
        config: Config,
        user_id: int,
        rag_engine: Optional[RAGEngine] = None,
        graph_manager: Optional[KnowledgeGraphManager] = None
    ):
        """
        Initialize graph search service
        
        Args:
            config: Application configuration
            user_id: User ID for filtering
            rag_engine: Optional RAG engine instance
            graph_manager: Optional graph manager instance
        """
        self.config = config
        self.user_id = user_id
        
        # Initialize components
        if not rag_engine:
            rag_engine = RAGEngine(config)
        self.rag = rag_engine
        
        if not graph_manager:
            # Initialize graph manager with config
            graph_config = config.__dict__.get('indexing', {})
            graph_backend = graph_config.get('graph_backend', 'networkx')
            
            if graph_backend == 'neo4j':
                from ..indexing.graph.graph_constants import NEO4J_DEFAULT_URI
                neo4j_uri = graph_config.get('neo4j_uri', NEO4J_DEFAULT_URI)
                neo4j_user = graph_config.get('neo4j_user', 'neo4j')
                neo4j_password = graph_config.get('neo4j_password', 'password')
                graph_manager = KnowledgeGraphManager(
                    backend='neo4j',
                    neo4j_uri=neo4j_uri,
                    neo4j_user=neo4j_user,
                    neo4j_password=neo4j_password
                )
            else:
                graph_manager = KnowledgeGraphManager(backend='networkx')
        
        self.graph = graph_manager
        
        # Initialize hybrid coordinator
        self.hybrid = HybridIndexCoordinator(
            graph_manager=self.graph,
            rag_engine=self.rag,  # Changed from vector_store to rag_engine
            enable_graph=True,
            enable_vector=True
        )
        
        # Get integration service from hybrid coordinator
        self.integration = self.hybrid.integration
        
        # Initialize GraphRAG analyzer
        from ..ai.llm_factory import LLMFactory
        llm_client = LLMFactory.create_llm(config)
        self.analyzer = GraphRAGAnalyzer(
            graph_manager=self.graph,
            llm_client=llm_client,
            config=config
        )
        
        logger.info(f"GraphSearchService initialized for user {user_id} with RAG-Graph integration")
    
    async def search(
        self,
        query: str,
        use_graph: bool = True,
        use_vector: bool = True,
        max_results: int = 10
    ) -> Dict[str, Any]:
        """
        Intelligent search combining graph and vector
        
        Args:
            query: Natural language query
            use_graph: Whether to use graph traversal
            use_vector: Whether to use vector search
            max_results: Maximum number of results
            
        Returns:
            Combined search results with sources
        """
        logger.info(f"Graph search: '{query}' (user={self.user_id})")
        
        try:
            # Add user filter
            filters = {'user_id': str(self.user_id)}
            
            # Execute hybrid query
            results = await self.hybrid.query(
                text_query=query,
                use_graph=use_graph,
                use_vector=use_vector,
                graph_depth=2,
                vector_limit=max_results,
                filters=filters
            )
            
            # Enhance with GraphRAG analysis if appropriate
            if use_graph and self._should_analyze(query):
                analysis = await self._run_graphrag_analysis(query, results)
                results['graphrag_analysis'] = analysis
            
            logger.info(
                f"Found {len(results.get('vector_results', []))} vector results, "
                f"{len(results.get('graph_results', []))} graph results"
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Graph search failed: {e}", exc_info=True)
            # Fallback to vector-only search
            if use_vector:
                logger.info("Falling back to vector-only search")
                vector_results = self.rag.search(query, k=max_results, filters=filters)
                return {
                    'vector_results': vector_results,
                    'graph_results': [],
                    'fallback': True,
                    'error': str(e)
                }
            raise
    
    async def enhanced_search(
        self,
        query: str,
        max_results: int = 10,
        include_context: bool = True
    ) -> Dict[str, Any]:
        """
        Enhanced search using the integration service for better results.
        
        This method provides:
        - Automatic graph context enrichment
        - Better consistency between graph and vector stores
        - Unified result format
        
        Args:
            query: Natural language query
            max_results: Maximum number of results
            include_context: Whether to include graph context
            
        Returns:
            Enhanced search results with graph context
        """
        logger.info(f"Enhanced search: '{query}' (user={self.user_id})")
        
        try:
            # Use integration service if available
            if self.integration:
                filters = {'user_id': str(self.user_id)}
                results = await self.integration.search_with_context(
                    query=query,
                    max_results=max_results,
                    graph_depth=2,
                    include_graph_context=include_context,
                    filters=filters
                )
                
                # Add GraphRAG analysis if appropriate
                if self._should_analyze(query):
                    analysis = await self._run_graphrag_analysis(query, results)
                    results['graphrag_analysis'] = analysis
                
                return results
            else:
                # Fallback to standard search
                return await self.search(
                    query,
                    use_graph=include_context,
                    max_results=max_results
                )
                
        except Exception as e:
            logger.error(f"Enhanced search failed: {e}", exc_info=True)
            # Fallback to basic search
            return await self.search(query, max_results=max_results)
    
    async def ensure_node_consistency(self, node_id: str) -> bool:
        """
        Ensure a node is consistent between graph and vector stores.
        
        Args:
            node_id: Node ID to check
            
        Returns:
            True if consistent or successfully synchronized
        """
        if not self.integration:
            logger.warning("Integration service not available")
            return False
        
        try:
            return await self.integration.ensure_consistency(node_id)
        except Exception as e:
            logger.error(f"Consistency check failed: {e}")
            return False
    
    async def find_by_entity(
        self,
        entity_type: str,
        entity_name: str,
        relationship_type: Optional[str] = None,
        max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Find all items related to a specific entity
        
        Examples:
            - find_by_entity("PERSON", "John Doe")
            - find_by_entity("VENDOR", "Amazon", "HAS_RECEIPT")
        
        Args:
            entity_type: Type of entity (PERSON, VENDOR, etc.)
            entity_name: Name of the entity
            relationship_type: Optional relationship type filter
            max_results: Maximum results
            
        Returns:
            List of related nodes
        """
        logger.info(f"Finding by entity: {entity_type}/{entity_name}")
        
        try:
            # Find the entity node
            entity_node = await self.graph.find_node_by_property(
                node_type=NodeType[entity_type],
                property_name='name',
                property_value=entity_name
            )
            
            if not entity_node:
                logger.warning(f"Entity not found: {entity_type}/{entity_name}")
                return []
            
            # Get related nodes
            if relationship_type:
                rel_type = RelationType[relationship_type]
                related = await self.hybrid.find_related_nodes(
                    node_id=entity_node['id'],
                    rel_type=rel_type,
                    max_results=max_results
                )
            else:
                # Get all neighbors
                neighbors = await self.graph.get_neighbors(
                    node_id=entity_node['id'],
                    direction='both'
                )
                related = neighbors[:max_results]
            
            logger.info(f"Found {len(related)} related nodes")
            return related
            
        except Exception as e:
            logger.error(f"Find by entity failed: {e}", exc_info=True)
            return []
    
    async def analyze_spending(
        self,
        time_period: Optional[str] = None,
        vendor_filter: Optional[str] = None,
        category_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze spending patterns using GraphRAG
        
        Args:
            time_period: Optional time period filter (e.g., "30" for 30 days)
            vendor_filter: Optional vendor name filter
            category_filter: Optional category filter
            
        Returns:
            Spending analysis with insights
        """
        logger.info(f"Analyzing spending (user={self.user_id})")
        
        try:
            # Parse time period
            time_range_days = int(time_period) if time_period else 30
            
            # Use GraphRAG analyzer's analyze_spending method
            analysis = await self.analyzer.analyze_spending(
                user_id=str(self.user_id),
                category=category_filter,
                vendor=vendor_filter,
                time_range_days=time_range_days,
                generate_advice=True
            )
            
            return analysis
            
        except Exception as e:
            logger.error(f"Spending analysis failed: {e}", exc_info=True)
            return {'error': str(e), 'success': False}
    
    async def get_insights(
        self,
        insight_type: str = 'general'
    ) -> Dict[str, Any]:
        """
        Get AI-generated insights from knowledge graph
        
        Args:
            insight_type: Type of insights ('general', 'spending', 'vendor', etc.)
            
        Returns:
            Insights and recommendations
        """
        logger.info(f"Generating {insight_type} insights")
        
        try:
            # Get graph statistics
            stats = await self.graph.get_statistics()
            
            # Generate insights based on type
            if insight_type == 'spending':
                insights = await self.analyzer.analyze_spending(
                    user_id=str(self.user_id),
                    generate_advice=True
                )
            elif insight_type == 'vendor':
                insights = await self.analyzer.analyze_vendor_spending(
                    user_id=str(self.user_id),
                    generate_advice=True
                )
            else:
                # For general insights, use spending analysis
                insights = await self.analyzer.analyze_spending(
                    user_id=str(self.user_id),
                    generate_advice=True
                )
            
            return {
                'stats': stats,
                'insights': insights,
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Insights generation failed: {e}", exc_info=True)
            return {'error': str(e)}
    
    async def visualize_graph(
        self,
        center_node: Optional[str] = None,
        depth: int = 2,
        max_nodes: int = 50
    ) -> Dict[str, Any]:
        """
        Get graph data for visualization
        
        Args:
            center_node: Optional center node ID
            depth: Traversal depth
            max_nodes: Maximum nodes to return
            
        Returns:
            Graph data in visualization format
        """
        logger.info(f"Generating graph visualization (depth={depth})")
        
        try:
            if center_node:
                # Get subgraph around center node
                context = await self.hybrid.get_node_with_context(
                    node_id=center_node,
                    depth=depth,
                    include_relationships=True
                )
                
                if context:
                    nodes = [context['node']] + [n.get('node', {}) for n in context.get('neighbors', [])]
                    edges = [
                        {
                            'source': context['node']['id'],
                            'target': n.get('node_id', ''),
                            'type': n.get('relationship', {}).get('type')
                        }
                        for n in context.get('neighbors', [])
                        if n.get('node_id')
                    ]
                else:
                    nodes = []
                    edges = []
            else:
                # Get overview of user's graph
                stats = await self.graph.get_statistics()
                
                # Get sample nodes (limited)
                all_nodes = await self.graph.get_nodes_by_type(
                    node_type=None,  # All types
                    limit=max_nodes
                )
                
                nodes = all_nodes[:max_nodes]
                edges = []
                
                # Get relationships for these nodes
                for node in nodes[:20]:  # Limit edges for performance
                    neighbors = await self.graph.get_neighbors(node['id'], direction='outgoing')
                    for neighbor_id, rel_data in neighbors[:5]:
                        if neighbor_id in [n['id'] for n in nodes]:
                            edges.append({
                                'source': node['id'],
                                'target': neighbor_id,
                                'type': rel_data.get('type')
                            })
            
            return {
                'nodes': nodes,
                'edges': edges,
                'center': center_node,
                'depth': depth
            }
            
        except Exception as e:
            logger.error(f"Graph visualization failed: {e}", exc_info=True)
            return {'error': str(e), 'nodes': [], 'edges': []}
    
    def _should_analyze(self, query: str) -> bool:
        """Determine if query warrants GraphRAG analysis"""
        analysis_keywords = [
            'spend', 'spending', 'cost', 'price', 'total',
            'pattern', 'trend', 'insight', 'analyze', 'summary',
            'vendor', 'merchant', 'from', 'all',
            'relationship', 'connection', 'related'
        ]
        
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in analysis_keywords)
    
    async def _run_graphrag_analysis(
        self,
        query: str,
        search_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run GraphRAG analysis on search results"""
        try:
            # Determine analysis type from query
            query_lower = query.lower()
            
            if any(word in query_lower for word in ['spend', 'cost', 'price']):
                return await self.analyzer.analyze_spending(
                    user_id=str(self.user_id),
                    generate_advice=True
                )
            elif any(word in query_lower for word in ['vendor', 'merchant']):
                return await self.analyzer.analyze_vendor_spending(
                    user_id=str(self.user_id),
                    generate_advice=True
                )
            else:
                return {'type': 'none', 'reason': 'No specific analysis triggered'}
                
        except Exception as e:
            logger.error(f"GraphRAG analysis failed: {e}")
            return {'error': str(e)}
            return {'error': str(e)}
