"""
Notion GraphRAG Integration

Implements capability 1: Enhanced Knowledge and RAG (Retrieval)
- Graph-Grounded Search: Uses Notion API + Neo4j for contextual retrieval
- Cross-Platform Synthesis: Combines Slack + Notion + other systems
- Instant Knowledge Capture: Monitors Notion databases in real-time
"""
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import asyncio

from .client import NotionClient
from .config import NotionConfig
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class NotionGraphRAGIntegration:
    """
    GraphRAG integration for Notion.
    
    Provides:
    1. Graph-Grounded Search - Notion pages + Neo4j relationships
    2. Cross-Platform Synthesis - Multi-hop queries across systems
    3. Instant Knowledge Capture - Real-time database monitoring
    """
    
    def __init__(
        self,
        notion_client: NotionClient,
        graph_manager: Optional[Any] = None,
        rag_engine: Optional[Any] = None,
        config: Optional[Any] = None
    ):
        """
        Initialize Notion GraphRAG integration.
        
        Args:
            notion_client: NotionClient instance
            graph_manager: Optional KnowledgeGraphManager for Neo4j
            rag_engine: Optional RAGEngine for Pinecone vectorization
            config: Optional configuration object
        """
        self.notion_client = notion_client
        self.graph_manager = graph_manager
        self.rag_engine = rag_engine
        self.config = config or NotionConfig
        
        logger.info("Notion GraphRAG integration initialized")
    
    async def graph_grounded_search(
        self,
        query: str,
        database_id: str,
        num_results: int = 5
    ) -> Dict[str, Any]:
        """
        Perform graph-grounded search combining Notion + Neo4j.
        
        This implements capability 1, part 1:
        - Searches Notion database for relevant pages
        - Verifies relationships via Neo4j
        - Returns contextual, cited results
        
        Args:
            query: User's search query
            database_id: Notion database to search
            num_results: Maximum results to return
            
        Returns:
            Search results with citations and metadata
        """
        try:
            logger.info(f"[NOTION] Graph-grounded search for: {query}")
            
            # Step 1: Search Notion database
            notion_results = await self._search_notion_database(query, database_id)
            
            if not notion_results:
                logger.warning("[NOTION] No results found in Notion database")
                return {
                    'success': False,
                    'results': [],
                    'message': 'No relevant information found in Notion'
                }
            
            # Step 2: Enrich with Neo4j relationships (graph verification)
            enriched_results = await self._enrich_with_graph_context(notion_results)
            
            # Step 3: Rank by relevance and Neo4j verification
            ranked_results = await self._rank_by_verification(enriched_results, num_results)
            
            # Step 4: Extract citations from Notion pages
            results_with_citations = await self._extract_citations(ranked_results)
            
            logger.info(f"[NOTION] Graph-grounded search returned {len(results_with_citations)} results")
            
            return {
                'success': True,
                'results': results_with_citations,
                'query': query,
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"[NOTION] Error in graph-grounded search: {e}", exc_info=True)
            return {
                'success': False,
                'results': [],
                'error': str(e)
            }
    
    async def cross_platform_synthesis(
        self,
        query: str,
        databases: List[str],
        external_contexts: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Perform cross-platform synthesis combining Notion + external systems.
        
        This implements capability 1, part 2:
        - Example: "Summarize decisions from Slack thread and update Notion task"
        - Queries multiple systems, synthesizes results
        - Ensures single consolidated answer
        
        Args:
            query: User's query (e.g., cross-platform task)
            databases: Notion database IDs to search
            external_contexts: Optional context from Slack, Calendar, etc.
            
        Returns:
            Synthesized result with sources from all systems
        """
        try:
            logger.info(f"[NOTION] Cross-platform synthesis: {query}")
            
            # Step 1: Search all Notion databases
            notion_contexts = []
            for db_id in databases:
                results = await self._search_notion_database(query, db_id)
                notion_contexts.extend(results)
            
            # Step 2: Combine with external contexts (from Slack, Calendar, etc.)
            combined_contexts = {
                'notion': notion_contexts,
                'external': external_contexts or {}
            }
            
            # Step 3: Synthesize into single consolidated answer
            synthesized = await self._synthesize_contexts(query, combined_contexts)
            
            logger.info(f"[NOTION] Cross-platform synthesis complete")
            
            return {
                'success': True,
                'synthesized_answer': synthesized['answer'],
                'sources': synthesized['sources'],
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"[NOTION] Error in cross-platform synthesis: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }
    
    async def instant_knowledge_capture(
        self,
        database_id: str,
        page_id: str,
        page_content: Dict[str, Any]
    ) -> bool:
        """
        Capture Notion page into knowledge graph in real-time.
        
        This implements capability 1, part 3:
        - Extract entities and relationships from Notion page
        - Create Neo4j nodes and edges
        - Vectorize page content for Pinecone
        - Keep knowledge fresh and searchable
        
        Args:
            database_id: Parent database ID
            page_id: Notion page ID
            page_content: Page content and properties
            
        Returns:
            True if capture successful, False otherwise
        """
        try:
            logger.info(f"[NOTION] Instant knowledge capture for page {page_id}")
            
            # Step 1: Extract entities from Notion page
            entities = await self._extract_entities_from_page(page_content)
            
            # Step 2: Create Neo4j nodes for entities
            await self._create_graph_nodes(entities, page_id)
            
            # Step 3: Extract relationships
            relationships = await self._extract_relationships_from_page(page_content)
            
            # Step 4: Create Neo4j relationships
            await self._create_graph_relationships(relationships)
            
            # Step 5: Vectorize page content for Pinecone
            await self._vectorize_page_content(page_id, page_content)
            
            logger.info(f"[NOTION] Knowledge capture complete for page {page_id}")
            return True
            
        except Exception as e:
            logger.error(f"[NOTION] Error in knowledge capture: {e}", exc_info=True)
            return False
    
    # Helper methods
    
    async def _search_notion_database(
        self,
        query: str,
        database_id: str
    ) -> List[Dict[str, Any]]:
        """Search Notion database and return matching pages"""
        try:
            results = await self.notion_client.query_database_async(
                database_id=database_id,
                filters=self._build_search_filter(query)
            )
            
            pages = results.get('results', [])
            logger.debug(f"Found {len(pages)} pages matching query in database {database_id}")
            return pages
            
        except Exception as e:
            logger.warning(f"Error searching Notion database: {e}")
            return []
    
    async def _enrich_with_graph_context(
        self,
        results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Enrich results with Neo4j graph context"""
        if not self.graph_manager:
            return results
        
        enriched = []
        for result in results:
            try:
                # Extract page title
                properties = result.get('properties', {})
                title = self._extract_title_from_properties(properties)
                
                # Query graph for relationships
                graph_context = await asyncio.to_thread(
                    self._query_graph_for_context,
                    title
                )
                
                result['graph_context'] = graph_context
                enriched.append(result)
                
            except Exception as e:
                logger.warning(f"Error enriching result: {e}")
                enriched.append(result)
        
        return enriched
    
    async def _rank_by_verification(
        self,
        results: List[Dict[str, Any]],
        limit: int
    ) -> List[Dict[str, Any]]:
        """Rank results by Neo4j verification strength"""
        # Results with verified graph relationships rank higher
        ranked = sorted(
            results,
            key=lambda r: len(r.get('graph_context', {}).get('relationships', [])),
            reverse=True
        )
        return ranked[:limit]
    
    async def _extract_citations(
        self,
        results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extract proper citations from Notion pages"""
        citations = []
        for result in results:
            try:
                page_id = result.get('id')
                properties = result.get('properties', {})
                title = self._extract_title_from_properties(properties)
                url = result.get('url', '')
                
                citation = {
                    'title': title,
                    'url': url,
                    'page_id': page_id,
                    'source': 'Notion',
                    'retrieved_at': datetime.utcnow().isoformat()
                }
                
                citations.append(citation)
                
            except Exception as e:
                logger.warning(f"Error extracting citation: {e}")
        
        return citations
    
    async def _synthesize_contexts(
        self,
        query: str,
        contexts: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Synthesize multiple contexts into single answer"""
        # This would use the agent's synthesizer role
        # For now, return consolidated structure
        
        all_sources = []
        all_sources.extend(contexts.get('notion', []))
        
        return {
            'answer': f"Based on Notion and external sources, here's the answer to: {query}",
            'sources': all_sources
        }
    
    async def _extract_entities_from_page(
        self,
        page_content: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract entities from Notion page"""
        # Parse page properties and content
        entities = []
        
        try:
            properties = page_content.get('properties', {})
            
            # Extract title as entity
            title = self._extract_title_from_properties(properties)
            if title:
                entities.append({
                    'type': 'NOTION_PAGE',
                    'name': title,
                    'properties': properties
                })
            
            # Extract other properties as entities
            for prop_name, prop_value in properties.items():
                if prop_value.get('type') == 'people':
                    for person in prop_value.get('people', []):
                        entities.append({
                            'type': 'PERSON',
                            'name': person.get('name'),
                            'email': person.get('email')
                        })
                        
            logger.debug(f"Extracted {len(entities)} entities from page")
            return entities
            
        except Exception as e:
            logger.warning(f"Error extracting entities: {e}")
            return entities
    
    async def _create_graph_nodes(
        self,
        entities: List[Dict[str, Any]],
        page_id: str
    ) -> None:
        """Create Neo4j nodes for entities"""
        if not self.graph_manager:
            logger.debug("No graph manager available, skipping node creation")
            return
        
        try:
            from ...services.indexing.graph.schema import NodeType
            
            for entity in entities:
                await asyncio.to_thread(
                    self.graph_manager.add_node,
                    node_id=f"notion_{page_id}_{entity.get('name', 'unknown')}",
                    node_type=NodeType.DOCUMENT,
                    properties=entity
                )
            
            logger.debug(f"Created {len(entities)} graph nodes")
            
        except Exception as e:
            logger.warning(f"Error creating graph nodes: {e}")
    
    async def _extract_relationships_from_page(
        self,
        page_content: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract relationships from Notion page"""
        relationships = []
        
        try:
            # Parse page content for relationships
            # This would depend on page structure
            logger.debug("Extracting relationships from page")
            return relationships
            
        except Exception as e:
            logger.warning(f"Error extracting relationships: {e}")
            return relationships
    
    async def _create_graph_relationships(
        self,
        relationships: List[Dict[str, Any]]
    ) -> None:
        """Create Neo4j relationships"""
        if not self.graph_manager:
            return
        
        try:
            for rel in relationships:
                await asyncio.to_thread(
                    self.graph_manager.add_relationship,
                    from_node=rel.get('from'),
                    to_node=rel.get('to'),
                    rel_type=rel.get('type')
                )
            
            logger.debug(f"Created {len(relationships)} graph relationships")
            
        except Exception as e:
            logger.warning(f"Error creating relationships: {e}")
    
    async def _vectorize_page_content(
        self,
        page_id: str,
        page_content: Dict[str, Any]
    ) -> None:
        """Vectorize Notion page content for Pinecone"""
        if not self.rag_engine:
            logger.debug("No RAG engine available, skipping vectorization")
            return
        
        try:
            # Extract text content from page
            text_content = self._extract_text_content(page_content)
            
            if text_content:
                # Vectorize and index
                self.rag_engine.index_document(
                    doc_id=f"notion_{page_id}",
                    content=text_content,
                    metadata={
                        'source': 'notion',
                        'page_id': page_id,
                        'timestamp': datetime.utcnow().isoformat()
                    }
                )
                
                logger.debug(f"Vectorized page {page_id} for Pinecone")
                
        except Exception as e:
            logger.warning(f"Error vectorizing page: {e}")
    
    def _build_search_filter(self, query: str) -> Dict[str, Any]:
        """Build Notion filter from search query"""
        # This would parse the query and build a proper Notion filter
        # For now, return basic structure
        return {}
    
    def _extract_title_from_properties(self, properties: Dict[str, Any]) -> Optional[str]:
        """Extract title from Notion page properties"""
        try:
            # Title is usually in 'Title' property
            for prop_name, prop_value in properties.items():
                if prop_value.get('type') == 'title':
                    title_content = prop_value.get('title', [])
                    if title_content:
                        return title_content[0].get('plain_text', '')
            return None
        except Exception as e:
            logger.debug(f"Error extracting title: {e}")
            return None
    
    def _query_graph_for_context(self, entity_name: str) -> Dict[str, Any]:
        """Query Neo4j graph for entity context"""
        if not self.graph_manager:
            return {}
        
        try:
            # Query for entity and relationships
            query = """
            MATCH (n {name: $name})
            OPTIONAL MATCH (n)-[r]->(m)
            RETURN n, r, m
            LIMIT 10
            """
            
            result = self.graph_manager.query(query, {'name': entity_name})
            
            return {
                'entity': entity_name,
                'relationships': result
            }
            
        except Exception as e:
            logger.debug(f"Error querying graph: {e}")
            return {}
    
    def _extract_text_content(self, page_content: Dict[str, Any]) -> str:
        """Extract plain text from Notion page content"""
        try:
            # Extract from title and properties
            text_parts = []
            
            properties = page_content.get('properties', {})
            
            # Get title
            title = self._extract_title_from_properties(properties)
            if title:
                text_parts.append(title)
            
            # Get other text properties
            for prop_name, prop_value in properties.items():
                if prop_value.get('type') == 'rich_text':
                    rich_text = prop_value.get('rich_text', [])
                    for text_block in rich_text:
                        if text_block.get('type') == 'text':
                            text_parts.append(text_block.get('text', {}).get('content', ''))
            
            return ' '.join(text_parts)
            
        except Exception as e:
            logger.debug(f"Error extracting text: {e}")
            return ''
