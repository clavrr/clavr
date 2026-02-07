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
from ..ai.llm_factory import LLMFactory # Added LLMFactory import
import json

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
        user_id: Optional[int] = None, # Made optional
        rag_engine: Optional[RAGEngine] = None,
        graph_manager: Optional[KnowledgeGraphManager] = None
    ):
        """
        Initialize graph search service
        
        Args:
            config: Application configuration
            user_id: Default User ID (deprecated, pass to methods instead)
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
            graph_manager = KnowledgeGraphManager(config=config)
        
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
        llm_client = LLMFactory.get_llm_for_provider(config)
        self.analyzer = GraphRAGAnalyzer(
            graph_manager=self.graph,
            llm_client=llm_client,
            config=config
        )
        
        logger.info(f"GraphSearchService initialized (default_user={user_id})")
    
    async def search(
        self,
        query: str,
        user_id: Optional[int] = None, # New argument
        use_graph: bool = True,
        use_vector: bool = True,
        max_results: int = 10
    ) -> Dict[str, Any]:
        """
        Intelligent search combining graph and vector
        
        Args:
            query: Natural language query
            user_id: User ID for filtering (overrides request-level user_id)
            use_graph: Whether to use graph traversal
            use_vector: Whether to use vector search
            max_results: Maximum number of results
            
        Returns:
            Combined search results with sources
        """
        # Resolve user_id: Method arg > Instance attr
        effective_user_id = user_id if user_id is not None else self.user_id
        if effective_user_id is None:
             raise ValueError("user_id must be provided to search()")
             
        logger.info(f"Graph search: '{query}' (user={effective_user_id})")
        
        try:
            # Add user filter
            filters = {'user_id': str(effective_user_id)}
            
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
            stats = await self.graph.get_stats()
            
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
        max_nodes: int = 150
    ) -> Dict[str, Any]:
        """
        Get graph data for visualization with intelligent clustering.
        """
        logger.info(f"Generating graph visualization (depth={depth}, max_nodes={max_nodes})")
        
        try:
            nodes_dict = {}
            edges = []
            seen_edges = set()

            if center_node:
                # Get subgraph around center node
                context = await self.hybrid.get_node_with_context(
                    node_id=center_node,
                    depth=depth,
                    include_relationships=True
                )
                
                if context:
                    root_node = context['node']
                    # Use ArangoDB _id as the canonical ID for visualization to match edges
                    root_id = root_node.get('_id')
                    if root_id:
                        root_node['id'] = root_id
                        root_node['display_label'] = self._get_display_label(root_node)
                        nodes_dict[root_id] = root_node
                        
                        for neighbor in context.get('neighbors', []):
                            # Fix: hybrid.get_node_with_context returns {'node_id': ..., 'relationship': ...}
                            # It does NOT verify the node exists in the 'node' key unless we fetch it.
                            # But our updated manager puts the node in relationship['_neighbor_node']
                            rel_data = neighbor.get('relationship', {})
                            nb_node = rel_data.get('_neighbor_node')
                            
                            # Fallback if not in relationship (e.g. NetworkX backend)
                            if not nb_node:
                                # Try simple fetch
                                nb_id = neighbor.get('node_id')
                                if nb_id:
                                    nb_node = await self.graph.get_node(nb_id)

                            if nb_node:
                                # Use ArangoDB _id as canonical ID
                                nb_internal_id = nb_node.get('_id')
                                if not nb_internal_id:
                                    continue
                                
                                # Filtering system nodes
                                exclude_types = {'Identity', 'EmailAddress', 'Alias', 'System', 
                                                 'TimeBlock', 'Session', 'GraphPattern', 'Hypothesis'}
                                if nb_node.get('node_type') not in exclude_types:
                                    nb_node['id'] = nb_internal_id
                                    nb_node['display_label'] = self._get_display_label(nb_node)
                                    nodes_dict[nb_internal_id] = nb_node
                                    
                                    rel_type = rel_data.get('type')
                                    edge_key = tuple(sorted([root_id, nb_internal_id])) + (rel_type,)
                                    if edge_key not in seen_edges:
                                        seen_edges.add(edge_key)
                                        edges.append({
                                            'source': root_id,
                                            'target': nb_internal_id,
                                            'type': rel_type,
                                            'label': self._get_edge_label(rel_type)
                                        })
            else:
                # DISCOVERY STRATEGY: Find "Hubs" and expand clusters
                # 1. ALWAYS start with User node as central hub for connectivity
                user_nodes = await self.graph.get_nodes_by_type('User', limit=1, user_id=self.user_id)
                user_hub_id = None
                
                if user_nodes:
                    user_node = user_nodes[0]
                    user_hub_id = user_node.get('_id')
                    if user_hub_id:
                        user_node['id'] = user_hub_id
                        user_node['display_label'] = self._get_display_label(user_node)
                        nodes_dict[user_hub_id] = user_node
                
                # 2. Identify high-priority starting points (prioritize clear entities)
                discovery_types = [
                    'Project', 'Goal', 'Person', 'ActionItem', 
                    'GoogleTask', 'LinearIssue', # Task-like things are good
                    'CalendarEvent' # Events are good
                    # Removed 'Email', 'Message', 'Topic' from top-level discovery to reduce noise
                ]
                seed_hubs = []
                
                # Fetch a sampling of potential hubs (fewer per type to reduce clutter)
                for ntype in discovery_types:
                    limit = 8 if ntype in ['Project', 'Person', 'Goal'] else 5
                    type_nodes = await self.graph.get_nodes_by_type(ntype, limit=limit, user_id=self.user_id)
                    seed_hubs.extend(type_nodes)
                
                # Sort hubs by updated_at if available to show recent context
                seed_hubs.sort(key=lambda x: x.get('updated_at') or x.get('created_at') or '', reverse=True)
                
                # Process hubs
                for hub in seed_hubs:
                    if len(nodes_dict) >= max_nodes:
                        break
                        
                    hub_id = hub.get('_id')
                    if not hub_id:
                        continue
                        
                    # Use ArangoDB _id as canonical ID
                    hub['id'] = hub_id
                    hub['display_label'] = self._get_display_label(hub)
                    # Only add if not already present (preserve existing if any)
                    if hub_id not in nodes_dict:
                        nodes_dict[hub_id] = hub
                    
                    # Expand from this hub to find neighbors
                    neighbors = await self.graph.get_neighbors(hub_id, direction='both')
                    
                    # Take top neighbors (fewer neighbors to keep it clean)
                    neighbor_limit = 8 # Reduced from 15
                    for nb_id, rel_data in neighbors[:neighbor_limit]:
                        if len(nodes_dict) >= max_nodes:
                            break
                        
                        # nb_id is already the canonical _id from manager
                        
                        # Check availability of neighbor node data
                        nb_node = rel_data.get('_neighbor_node')
                        if not nb_node:
                            # Fetch if missing
                            nb_node = await self.graph.get_node(nb_id)
                            
                        if nb_node:
                            nb_internal_id = nb_node.get('_id')
                            if not nb_internal_id:
                                continue 
                                
                            # Stricter filtering of system/noise nodes
                            exclude_types = {
                                'Identity', 'EmailAddress', 'Alias', 'System', 
                                'TimeBlock', 'Session', 'GraphPattern', 'Hypothesis',
                                'WeatherContext', 'Skill' # Context nodes can be noisy
                            }
                            node_type = nb_node.get('node_type')
                            
                            # Filter out generic Topics
                            if node_type == 'Topic':
                                name = nb_node.get('properties', {}).get('name', nb_node.get('name', ''))
                                if len(name) < 4: # Filter short/generic topics
                                     continue
                            
                            if node_type not in exclude_types:
                                # CANONICAL ID ENFORCEMENT
                                nb_node['id'] = nb_internal_id
                                nb_node['display_label'] = self._get_display_label(nb_node)
                                
                                if nb_internal_id not in nodes_dict:
                                    nodes_dict[nb_internal_id] = nb_node
                                
                                # Add Edge
                                rel_type = rel_data.get('type')
                                # Ensure we use the exact IDs that are keys in nodes_dict
                                edge_key = tuple(sorted([hub_id, nb_internal_id])) + (rel_type,)
                                
                                if edge_key not in seen_edges:
                                    seen_edges.add(edge_key)
                                    edges.append({
                                        'source': hub_id,
                                        'target': nb_internal_id,
                                        'type': rel_type,
                                        'label': self._get_edge_label(rel_type)
                                    })

                # 3. Fill in gaps/edges between all selected nodes
                # This ensures we don't miss connections within the clusters we just formed
                # We iterate over a static list of keys to avoid runtime modification issues
                current_node_ids = list(nodes_dict.keys())
                for n_id in current_node_ids:
                    node_neighbors = await self.graph.get_neighbors(n_id, direction='both')
                    for nb_id, rel_data in node_neighbors:
                        if nb_id in nodes_dict:
                            # Both nodes are in our graph, add the edge
                            rel_type = rel_data.get('type')
                            edge_key = tuple(sorted([n_id, nb_id])) + (rel_type,)
                            if edge_key not in seen_edges:
                                seen_edges.add(edge_key)
                                edges.append({
                                    'source': n_id,
                                    'target': nb_id,
                                    'type': rel_type,
                                    'label': self._get_edge_label(rel_type)
                                })
                
                # 4. Ensure connectivity to User hub (ONLY for key entities to separate clusters)
                # We don't want everything connecting to User if it makes a hairball.
                # Only connect orphans that are important.
                if user_hub_id:
                    for n_id in nodes_dict:
                        if n_id != user_hub_id:
                            # Check if this node has ANY edges
                            is_connected = any(
                                e['source'] == n_id or e['target'] == n_id
                                for e in edges
                            )
                            
                            # If orphan, connect to User ONLY if it's a primary entity
                            # Default logic: Connect everything to user to ensure graph is one component?
                            # User asked for "minimal". A Disconnected graph of clusters is cleaner than a hairball.
                            # But standard visualization tools handle components poorly.
                            # Compromise: Connect 'Project', 'Goal', 'Person' to User. Leave others attached to their hubs.
                            
                            node_type = nodes_dict[n_id].get('node_type')
                            is_primary = node_type in ['Project', 'Goal', 'Person', 'Company']
                            
                            if not is_connected or (is_primary and not any(e['target'] == user_hub_id or e['source'] == user_hub_id for e in edges if e['source'] == n_id or e['target'] == n_id)):
                                edge_key = tuple(sorted([n_id, user_hub_id])) + ('BELONGS_TO',)
                                if edge_key not in seen_edges:
                                    seen_edges.add(edge_key)
                                    edges.append({
                                        'source': n_id,
                                        'target': user_hub_id,
                                        'type': 'BELONGS_TO',
                                        'label': 'belongs to'
                                    })

            nodes = list(nodes_dict.values())
            
            # Polyfill label/name for frontend compatibility
            for node in nodes:
                if 'display_label' in node:
                    node['label'] = node['display_label']
                    node['name'] = node['display_label']
            
            # Runtime LLM Polishing (Intelligent Labels)
            # We batch process visible nodes to make labels "sleek" and "natural"
            if len(nodes) > 0 and len(nodes) < 150: # Limit to avoid massive context cost
                 try:
                     nodes = await self._polish_labels_with_llm(nodes)
                 except Exception as e:
                     logger.warning(f"LLM label polishing failed: {e}")
            
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

    def _get_display_label(self, node: Dict[str, Any]) -> str:
        """
        Generate a user-friendly display label for an node based on its type.
        Returns the most meaningful identifier for the node.
        """
        node_type = node.get('node_type', node.get('type', ''))
        props = node.get('properties', node) # Handle both node-style or flattened dict
        
        # Composite Label Logic for Descriptive Names
        
        # 1. Emails: "Email: {Subject} (from {Sender})"
        if node_type == 'Email':
            subject = props.get('subject', 'No Subject')
            sender = props.get('sender', '')
            # Extract name from "Name <email>"
            sender_name = sender.split('<')[0].strip().replace('"', '') if '<' in sender else sender
            if sender_name:
                return f"Email from {sender_name}: {subject}"[:50] + "..." if len(subject) > 30 else f"Email from {sender_name}: {subject}"
            return f"Email: {subject}"[:50]

        # 2. Calendar: "Meeting: {Title}"
        if node_type == 'CalendarEvent':
            title = props.get('title') or props.get('summary', 'Untitled Event')
            if 'meeting' not in title.lower():
                return f"Meeting: {title}"
            return title

        # 3. ActionItem / Google Task: "Task: {Title}"
        if node_type in ['ActionItem', 'GoogleTask']:
            raw_title = props.get('title') or props.get('description', '')
            # Clean up raw titles if they are IDs
            if not raw_title or raw_title.startswith('action:') or raw_title.startswith('gtask_'):
                # Try to get a better description? 
                # If we updated the graph correctly, title should be good.
                raw_title = props.get('description') or "Untitled Task"
            
            # Remove "Action_" prefix if present in description
            if raw_title.startswith('Action_'):
                 raw_title = "Untitled Task"
                 
            return f"Task: {raw_title}"[:60]

        # 4. Receipt: "{Merchant} (${Total})"
        if node_type == 'Receipt':
            merchant = props.get('merchant', 'Unknown Vendor')
            total = props.get('total')
            if total:
                 return f"{merchant} (${total})"
            return f"Receipt: {merchant}"

        # 5. Person: Just Name
        if node_type in ['Person', 'Contact']:
            name = props.get('name') or props.get('full_name') or props.get('email', 'Unknown Person')
            return name

        # 6. Default Property Fallback (Priority List)
        # Priority order of fields to check for display label
        label_fields = {
            'Project': ['name', 'title'],
            'Topic': ['name', 'title'],
            'Goal': ['name', 'title'],
            'Document': ['filename', 'title'],
            'KeyResult': ['description'],
            'Company': ['name'],
            'Vendor': ['name'],
            'User': ['name', 'email'],
            'LinearIssue': ['title', 'identifier'],
            'Location': ['name', 'address'],
            'Skill': ['name']
        }
        
        # Get fields to check for this node type
        fields_to_check = label_fields.get(node_type, ['name', 'title', 'subject', 'description', 'label', 'text', 'content'])
        
        for field in fields_to_check:
            value = props.get(field)
            if value and isinstance(value, str) and len(value) > 0:
                # SAFETY: Mask potential tokens
                if value.startswith('gAAAA'):
                    continue
                
                # Truncate long labels
                if len(value) > 50:
                    return value[:47] + '...'
                return value
        
        # If no label properties found, look for ANY string property that isn't an ID
        for key, value in props.items():
            if key not in ['id', 'node_id', 'node_type', 'type', 'user_id', '_id', '_key', '_rev'] and isinstance(value, str):
                if 3 < len(value) < 50: # Reasonable length
                    # SAFETY: Mask potential tokens
                    if value.startswith('gAAAA'):
                        continue
                        
                    # Exclude obvious IDs or dates
                    if not any(x in value for x in ['://']) and not value.replace('-','').replace(':','').isdigit():
                         return f"{node_type}: {value}"

        # Fallback to formatted node ID
        node_id = node.get('id', node.get('node_id', 'unknown'))
        if isinstance(node_id, str):
            if '_' in node_id:
                # Extract more readable part (e.g., "person_abc123" -> "person (abc...)")
                short_id = node_id.split('_')[-1][:6]
                return f"{node_type} ({short_id})"
            elif ':' in node_id:
                parts = node_id.split(':')
                short_hash = parts[1][:6] if len(parts) > 1 else '?'
                return f"{node_type} ({short_hash})"
        return str(node_id)


    def _get_edge_label(self, edge_type: str) -> str:
        """
        Generate a user-friendly label for an edge/relationship type.
        """
        if not edge_type:
            return 'related'
        
        # Map internal relationship types to friendly labels
        edge_labels = {
            'FROM': 'from',
            'TO': 'to',
            'CC': 'cc',
            'BCC': 'bcc',
            'SENT': 'sent',
            'RECEIVED': 'received',
            'ATTENDED_BY': 'attended by',
            'ASSIGNED_TO': 'assigned to',
            'WORKS_ON': 'works on',
            'MENTIONS': 'mentions',
            'DISCUSSES': 'discusses',
            'ABOUT': 'about',
            'CONTAINS': 'contains',
            'RELATED_TO': 'related to',
            'CREATED_BY': 'created by',
            'HAS_IDENTITY': 'has contact',
            'SAME_AS': 'same as',
            'KNOWS': 'knows',
            'BELONGS_TO': 'belongs to',
            'CREATED': 'created',
            'MODIFIED': 'modified',
            'PART_OF': 'part of',
            'TAGGED': 'tagged',
            'OWNS': 'owns',
            'MANAGES': 'manages',
            'REPORTS_TO': 'reports to',
            'INVITED': 'invited',
            'ATTENDING': 'attending',
            'ORGANIZED': 'organized',
            'OCCURRED_DURING': 'during',
            'FOLLOWS': 'follows',
            'PRECEDED': 'preceded',
            'ATTACHED_TO': 'attached to'
        }
        
        return edge_labels.get(edge_type, edge_type.lower().replace('_', ' '))

    async def _polish_labels_with_llm(self, nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Use LLM to rewrite node labels to be more natural, concise, and intelligent.
        Processed in a single batch for low latency.
        """
        # Prepare batch input
        # We only send ID, Type, and Current Label to save tokens
        batch_input = []
        for n in nodes:
            batch_input.append({
                "id": n.get('id'),
                "type": n.get('node_type'),
                "current_label": n.get('display_label') or n.get('label')
            })
            
        prompt = f"""
        You are an intelligent interface designer. Rewrite these Knowledge Graph node labels to be sleek, natural, and concise (max 6-8 words).
        
        Rules:
        1. Remove robotic prefixes like "Task:", "Email from:", "Meeting:", "Receipt:".
        2. Make it sound like a smart summary. 
           - "Task: Review Doc" -> "Review Doc"
           - "Email from Sophie: Funding" -> "Funding chat with Sophie"
           - "Meeting: Team Sync" -> "Team Sync"
           - "Receipt: Uber ($15)" -> "Uber ($15)"
        3. Prioritize the content/action over the type.
        4. Return ONLY a JSON list of objects: {{"id": "...", "new_label": "..."}}.
        
        Nodes:
        {json.dumps(batch_input)}
        """
        
        try:
            # Use streaming generator to get full response
            response_text = ""
            async for chunk in LLMFactory.stream_llm_response(self.config, prompt, temperature=0.3):
                response_text += chunk
                
            # Parse JSON response
            # Clean potential markdown blocks
            clean_text = response_text.replace('```json', '').replace('```', '').strip()
            
            try:
                rewrites = json.loads(clean_text)
                
                # Create a map for fast lookup
                rewrite_map = {item['id']: item['new_label'] for item in rewrites if 'id' in item and 'new_label' in item}
                
                # Apply updates
                updated_count = 0
                for node in nodes:
                    node_id = node.get('id')
                    if node_id in rewrite_map:
                        new_label = rewrite_map[node_id]
                        # Verify it's not empty or junk
                        if new_label and len(new_label) > 2:
                            node['label'] = new_label
                            node['name'] = new_label
                            node['display_label'] = new_label # Update source correctness too
                            updated_count += 1
                            
                logger.info(f"Polished {updated_count} labels with LLM")
                
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse LLM label response: {clean_text[:100]}...")
                
        except Exception as e:
            logger.error(f"Error calling LLM for labels: {e}")
            
        return nodes
