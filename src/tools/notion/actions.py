"""
Notion Actions Operations

Provides CRUD operations for Notion pages and databases.
"""
from typing import Optional, Dict, Any, List

from ...integrations.notion.service import NotionService
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class NotionActions:
    """
    CRUD operations for Notion pages and databases.
    
    Provides:
    - Page creation and updates
    - Database queries
    - Page retrieval
    """
    
    def __init__(
        self,
        notion_service: Optional[NotionService] = None,
        notion_client: Optional[Any] = None  # For backward compatibility
    ):
        """
        Initialize Notion actions.
        
        Args:
            notion_service: NotionService instance (preferred)
            notion_client: NotionClient instance (for backward compatibility)
        """
        self.notion_service = notion_service
        # Fallback to client if service not provided (for backward compatibility)
        if not self.notion_service and notion_client:
            # Create a minimal service wrapper if only client is provided
            # This is a temporary fallback - prefer using NotionService
            self._notion_client = notion_client
        logger.info("[NOTION_ACTIONS] Initialized")
    
    def create_page(
        self,
        database_id: str,
        title: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        content: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new Notion page.
        
        Args:
            database_id: Database ID where page will be created
            title: Page title (will be converted to properties if properties not provided)
            properties: Page properties
            content: Optional page content blocks
            
        Returns:
            Created page object or None if failed
        """
        if self.notion_service:
            try:
                return self.notion_service.create_page(
                    database_id=database_id,
                    title=title,
                    properties=properties,
                    content=content
                )
            except Exception as e:
                logger.error(f"[NOTION_ACTIONS] Error creating page: {e}")
                return None
        
        # Fallback to direct client (backward compatibility)
        if hasattr(self, '_notion_client') and self._notion_client:
            if not properties:
                if title:
                    properties = {'title': {'title': [{'text': {'content': title}}]}}
                else:
                    logger.error("[NOTION_ACTIONS] Either title or properties required")
                    return None
            
            page = self._notion_client.create_page(
                database_id=database_id,
                properties=properties,
                content=content
            )
            
            if page:
                logger.info(f"[NOTION_ACTIONS] Created page: {page.get('id', 'unknown')}")
            
            return page
        
        logger.error("[NOTION_ACTIONS] NotionService or NotionClient not available")
        return None
    
    def update_page(
        self,
        page_id: str,
        properties: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update a Notion page.
        
        Args:
            page_id: Page ID to update
            properties: New property values
            
        Returns:
            Updated page object or None if failed
        """
        if self.notion_service:
            try:
                return self.notion_service.update_page(
                    page_id=page_id,
                    properties=properties
                )
            except Exception as e:
                logger.error(f"[NOTION_ACTIONS] Error updating page: {e}")
                return None
        
        # Fallback to direct client
        if hasattr(self, '_notion_client') and self._notion_client:
            page = self._notion_client.update_page(
                page_id=page_id,
                properties=properties
            )
            if page:
                logger.info(f"[NOTION_ACTIONS] Updated page: {page_id}")
            return page
        
        logger.error("[NOTION_ACTIONS] NotionService or NotionClient not available")
        return None
    
    def get_page(self, page_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a Notion page.
        
        Args:
            page_id: Page ID to retrieve
            
        Returns:
            Page object or None if not found
        """
        if self.notion_service:
            try:
                return self.notion_service.get_page(page_id)
            except Exception as e:
                logger.error(f"[NOTION_ACTIONS] Error getting page: {e}")
                return None
        
        # Fallback to direct client
        if hasattr(self, '_notion_client') and self._notion_client:
            return self._notion_client.get_page(page_id)
        
        logger.error("[NOTION_ACTIONS] NotionService or NotionClient not available")
        return None
    
    def query_database(
        self,
        database_id: str,
        filters: Optional[Dict[str, Any]] = None,
        sorts: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Query a Notion database.
        
        Args:
            database_id: Database ID to query
            filters: Optional filter criteria
            sorts: Optional sort order
            
        Returns:
            Query results with pages
        """
        if self.notion_service:
            try:
                return self.notion_service.query_database(
                    database_id=database_id,
                    filters=filters,
                    sorts=sorts
                )
            except Exception as e:
                logger.error(f"[NOTION_ACTIONS] Error querying database: {e}")
                return {'results': []}
        
        # Fallback to direct client
        if hasattr(self, '_notion_client') and self._notion_client:
            return self._notion_client.query_database(
                database_id=database_id,
                filters=filters,
                sorts=sorts
            )
        
        logger.error("[NOTION_ACTIONS] NotionService or NotionClient not available")
        return {'results': []}
    
    def format_database_results(self, result: Dict[str, Any]) -> str:
        """
        Format database query results for display.
        
        Args:
            result: Database query result dictionary
            
        Returns:
            Formatted string
        """
        pages = result.get('results', [])
        if not pages:
            return "No pages found in database."
        
        formatted_pages = []
        for page in pages:
            page_id = page.get('id', '')
            page_url = page.get('url', '')
            # Extract title from properties
            title_prop = page.get('properties', {}).get('title', {})
            if isinstance(title_prop, dict):
                title = title_prop.get('title', [{}])[0].get('plain_text', 'Untitled')
            else:
                title = 'Untitled'
            
            formatted_pages.append(f"**{title}**\nURL: {page_url}")
        
        return f"Found {len(pages)} pages:\n\n" + "\n\n".join(formatted_pages)

