"""
Notion Search Operations

Provides graph-grounded search capabilities for Notion pages.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime

from ...integrations.notion.service import NotionService
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class NotionSearch:
    """
    Search operations for Notion pages with GraphRAG integration.
    
    Provides:
    - Graph-grounded search (Notion + Neo4j)
    - Cross-platform synthesis
    - Result formatting and citation extraction
    """
    
    def __init__(
        self,
        notion_service: Optional[NotionService] = None,
        rag_integration: Optional[Any] = None  # For backward compatibility
    ):
        """
        Initialize Notion search.
        
        Args:
            notion_service: NotionService instance (preferred)
            rag_integration: NotionGraphRAGIntegration instance (for backward compatibility)
        """
        self.notion_service = notion_service
        # Fallback for backward compatibility
        if not self.notion_service and rag_integration:
            self._rag_integration = rag_integration
        logger.info("[NOTION_SEARCH] Initialized")
    
    async def graph_grounded_search(
        self,
        query: str,
        database_id: str,
        num_results: int = 5
    ) -> Dict[str, Any]:
        """
        Perform graph-grounded search combining Notion + Neo4j.
        
        Args:
            query: Search query
            database_id: Notion database ID
            num_results: Maximum results to return
            
        Returns:
            Search results with citations
        """
        if self.notion_service:
            try:
                return await self.notion_service.graph_grounded_search(
                    query=query,
                    database_id=database_id,
                    num_results=num_results
                )
            except Exception as e:
                logger.error(f"[NOTION_SEARCH] Error in graph-grounded search: {e}")
                return {
                    'success': False,
                    'results': [],
                    'error': str(e)
                }
        
        # Fallback for backward compatibility
        if hasattr(self, '_rag_integration') and self._rag_integration:
            return await self._rag_integration.graph_grounded_search(
                query=query,
                database_id=database_id,
                num_results=num_results
            )
        
        return {
            'success': False,
            'results': [],
            'error': 'GraphRAG integration not available'
        }
    
    async def cross_platform_synthesis(
        self,
        query: str,
        databases: List[str],
        external_contexts: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Perform cross-platform synthesis combining Notion with external systems.
        
        Args:
            query: User query
            databases: List of Notion database IDs
            external_contexts: Optional context from Slack, Calendar, etc.
            
        Returns:
            Synthesized results
        """
        if self.notion_service:
            try:
                return await self.notion_service.cross_platform_synthesis(
                    query=query,
                    databases=databases,
                    external_contexts=external_contexts
                )
            except Exception as e:
                logger.error(f"[NOTION_SEARCH] Error in cross-platform synthesis: {e}")
                return {
                    'success': False,
                    'error': str(e)
                }
        
        # Fallback for backward compatibility
        if hasattr(self, '_rag_integration') and self._rag_integration:
            return await self._rag_integration.cross_platform_synthesis(
                query=query,
                databases=databases,
                external_contexts=external_contexts
            )
        
        return {
            'success': False,
            'error': 'GraphRAG integration not available'
        }
    
    def format_search_results(self, results: List[Dict[str, Any]]) -> str:
        """
        Format search results for display.
        
        Args:
            results: List of search result dictionaries
            
        Returns:
            Formatted string
        """
        if not results:
            return "No relevant pages found in Notion."
        
        formatted_results = []
        for item in results:
            page_title = item.get('title', 'Untitled')
            page_url = item.get('url', '')
            citations = item.get('citations', [])
            summary = item.get('summary', '')
            
            formatted_results.append(
                f"**{page_title}**\n"
                f"URL: {page_url}\n"
                f"{summary}\n"
                f"Citations: {len(citations)} references"
            )
        
        return f"Found {len(results)} relevant pages:\n\n" + "\n\n---\n\n".join(formatted_results)

