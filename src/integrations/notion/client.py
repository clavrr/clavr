"""
Notion Client Wrapper

Wraps Notion SDK for API communication.
Handles database queries, page creation, and updates.
"""
from typing import Optional, Dict, Any, List
import asyncio
import httpx
from datetime import datetime

try:
    from notion_client import Client
    from notion_client.helpers import get_id
    NOTION_SDK_AVAILABLE = True
except ImportError:
    NOTION_SDK_AVAILABLE = False
    Client = None

from .config import NotionConfig
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class NotionClient:
    """
    Notion client wrapper for API communication.
    
    Handles:
    - Database queries and filtering
    - Page creation and updates
    - Property management
    - Error handling and retries
    """
    
    def __init__(self, api_key: Optional[str] = None, access_token: Optional[str] = None):
        """
        Initialize Notion client.
        
        Args:
            api_key: Notion API key (internal integration token) - defaults to NOTION_API_KEY env var
            access_token: OAuth access token (from public integration) - takes precedence over api_key
        """
        if not NOTION_SDK_AVAILABLE:
            raise ImportError(
                "notion-client is not installed. Install it with: pip install notion-client"
            )
        
        # OAuth token takes precedence over API key for multi-user support
        self.api_key = access_token or api_key or NotionConfig.NOTION_API_KEY
        
        if not self.api_key:
            raise ValueError("Notion access token or API key is required")
        
        # Initialize Notion client
        self.client = Client(auth=self.api_key)  # type: ignore
        
        logger.info("Notion client initialized")
    
    def query_database(
        self,
        database_id: str,
        filters: Optional[Dict[str, Any]] = None,
        sorts: Optional[List[Dict[str, Any]]] = None,
        start_cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Query a Notion database with filters and sorting.
        
        Args:
            database_id: Database ID to query
            filters: Optional filter criteria
            sorts: Optional sort order
            start_cursor: For pagination
            
        Returns:
            Query results with pages
        """
        try:
            response = self.client.databases.query(
                database_id=database_id,
                filter=filters,
                sorts=sorts,
                start_cursor=start_cursor
            )
            
            logger.debug(f"Queried database {database_id}: {len(response.get('results', []))} pages")
            return response
            
        except Exception as e:
            logger.error(f"Error querying database {database_id}: {e}", exc_info=True)
            raise
    
    def get_page(self, page_id: str) -> Optional[Dict[str, Any]]:
        """
        Get page details from Notion.
        
        Args:
            page_id: Page ID to retrieve
            
        Returns:
            Page object or None if not found
        """
        try:
            page = self.client.pages.retrieve(page_id=page_id)
            logger.debug(f"Retrieved page {page_id}")
            return page
            
        except Exception as e:
            logger.warning(f"Error retrieving page {page_id}: {e}")
            return None
    
    def create_page(
        self,
        database_id: str,
        properties: Dict[str, Any],
        content: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new page in a Notion database.
        
        Args:
            database_id: Database ID where page will be created
            properties: Page properties (title, fields, etc.)
            content: Optional page content blocks
            
        Returns:
            Created page object or None if failed
        """
        try:
            page_data = {
                'parent': {'database_id': database_id},
                'properties': properties
            }
            
            if content:
                page_data['children'] = content
            
            page = self.client.pages.create(**page_data)
            logger.info(f"Created page in database {database_id}")
            return page
            
        except Exception as e:
            logger.error(f"Error creating page in database {database_id}: {e}", exc_info=True)
            return None
    
    def update_page(
        self,
        page_id: str,
        properties: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update page properties.
        
        Args:
            page_id: Page ID to update
            properties: New property values
            
        Returns:
            Updated page object or None if failed
        """
        try:
            page = self.client.pages.update(
                page_id=page_id,
                properties=properties
            )
            logger.debug(f"Updated page {page_id}")
            return page
            
        except Exception as e:
            logger.error(f"Error updating page {page_id}: {e}", exc_info=True)
            return None
    
    def append_block_children(
        self,
        page_id: str,
        children: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Append blocks (content) to a page.
        
        Args:
            page_id: Page ID to append to
            children: List of block content to append
            
        Returns:
            Append result or None if failed
        """
        try:
            result = self.client.blocks.children.append(
                block_id=page_id,
                children=children
            )
            logger.debug(f"Appended {len(children)} blocks to page {page_id}")
            return result
            
        except Exception as e:
            logger.error(f"Error appending blocks to page {page_id}: {e}", exc_info=True)
            return None
    
    def get_block_children(
        self,
        block_id: str,
        page_size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get children blocks of a page or block.
        
        Args:
            block_id: Block ID to get children from
            page_size: Number of children to retrieve per request
            
        Returns:
            List of child blocks
        """
        try:
            children = []
            has_more = True
            start_cursor = None
            
            while has_more:
                response = self.client.blocks.children.list(
                    block_id=block_id,
                    page_size=page_size,
                    start_cursor=start_cursor
                )
                
                children.extend(response.get('results', []))
                has_more = response.get('has_more', False)
                start_cursor = response.get('next_cursor')
            
            logger.debug(f"Retrieved {len(children)} child blocks from {block_id}")
            return children
            
        except Exception as e:
            logger.warning(f"Error getting block children for {block_id}: {e}")
            return []
    
    def search(self, query: str, filter_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search Notion workspace.
        
        Args:
            query: Search query text
            filter_type: Optional filter ('page', 'database', etc.)
            
        Returns:
            List of search results
        """
        try:
            search_params = {
                'query': query,
            }
            
            if filter_type:
                search_params['filter'] = {'value': filter_type, 'property': 'object'}
            
            response = self.client.search(**search_params)
            results = response.get('results', [])
            
            logger.debug(f"Search for '{query}': {len(results)} results")
            return results
            
        except Exception as e:
            logger.warning(f"Error searching Notion: {e}")
            return []
    
    async def query_database_async(
        self,
        database_id: str,
        filters: Optional[Dict[str, Any]] = None,
        sorts: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Async version of query_database"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.query_database,
            database_id,
            filters,
            sorts,
            None
        )
    
    async def create_page_async(
        self,
        database_id: str,
        properties: Dict[str, Any],
        content: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[Dict[str, Any]]:
        """Async version of create_page"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.create_page,
            database_id,
            properties,
            content
        )
    
    async def update_page_async(
        self,
        page_id: str,
        properties: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Async version of update_page"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.update_page,
            page_id,
            properties
        )
