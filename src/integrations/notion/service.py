"""
Notion Service - Business logic layer for Notion operations

Provides a clean interface for Notion operations, abstracting away the complexity
of Notion API, error handling, and GraphRAG integration.

This service is used by:
- NotionTool (LangChain tool)
- Notion background workers (Celery tasks - future)
- API endpoints

Architecture:
    NotionService → NotionClient → Notion API
    NotionService → NotionGraphRAGIntegration (for GraphRAG features)
    NotionService → NotionAutonomousExecution (for autonomous features)
"""
from typing import Optional, List, Dict, Any
from datetime import datetime

from .client import NotionClient
from .rag_integration import NotionGraphRAGIntegration
from .autonomous_execution import NotionAutonomousExecution
from .exceptions import (
    NotionServiceException,
    NotionPageNotFoundException,
    NotionDatabaseNotFoundException,
    NotionAuthenticationException,
    ServiceUnavailableException
)
from ...utils.logger import setup_logger
from ...utils.config import Config

logger = setup_logger(__name__)


class NotionService:
    """
    Notion service providing business logic for Notion operations
    
    Features:
    - Page CRUD operations (create, read, update, delete)
    - Database queries with filtering and sorting
    - Graph-grounded search (Notion + ArangoDB)
    - Cross-platform synthesis
    - Autonomous database management
    - Error handling and retries
    """
    
    def __init__(
        self,
        config: Config,
        api_key: Optional[str] = None,
        graph_manager: Optional[Any] = None,
        rag_engine: Optional[Any] = None
    ):
        """
        Initialize Notion service
        
        Args:
            config: Application configuration
            api_key: Notion API key (defaults to NOTION_API_KEY env var)
            graph_manager: Optional KnowledgeGraphManager for ArangoDB
            rag_engine: Optional RAGEngine for Qdrant vectorization
        """
        self.config = config
        self.api_key = api_key
        
        # Initialize Notion client
        try:
            self.notion_client = NotionClient(api_key=api_key)
            logger.info("[NOTION_SERVICE] NotionClient initialized")
        except Exception as e:
            logger.error(f"[NOTION_SERVICE] Failed to initialize NotionClient: {e}")
            raise ServiceUnavailableException(
                f"Notion service is not available: {str(e)}",
                service_name="notion"
            )
        
        # Initialize GraphRAG integration (optional)
        self.rag_integration = None
        if graph_manager or rag_engine:
            try:
                self.rag_integration = NotionGraphRAGIntegration(
                    notion_client=self.notion_client,
                    graph_manager=graph_manager,
                    rag_engine=rag_engine,
                    config=config
                )
                logger.info("[NOTION_SERVICE] NotionGraphRAGIntegration initialized")
            except Exception as e:
                logger.warning(f"[NOTION_SERVICE] Could not initialize GraphRAG integration: {e}")
        
        # Initialize autonomous execution (optional)
        self.autonomous_execution = None
        if rag_engine:
            try:
                self.autonomous_execution = NotionAutonomousExecution(
                    notion_client=self.notion_client,
                    rag_engine=rag_engine,
                    config=config
                )
                logger.info("[NOTION_SERVICE] NotionAutonomousExecution initialized")
            except Exception as e:
                logger.warning(f"[NOTION_SERVICE] Could not initialize autonomous execution: {e}")
    
    def _ensure_available(self):
        """Ensure Notion client is available"""
        if not self.notion_client:
            raise ServiceUnavailableException(
                "Notion service is not available. Please check your API key.",
                service_name="notion"
            )
    
    # ===================================================================
    # PAGE OPERATIONS
    # ===================================================================
    
    def create_page(
        self,
        database_id: str,
        title: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        content: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Create a new Notion page
        
        Args:
            database_id: Database ID where page will be created
            title: Page title (will be converted to properties if properties not provided)
            properties: Page properties
            content: Optional page content blocks
            
        Returns:
            Created page object
            
        Raises:
            NotionServiceException: If page creation fails
        """
        self._ensure_available()
        
        try:
            if not properties:
                # Create basic properties from title
                if title:
                    properties = {'title': {'title': [{'text': {'content': title}}]}}
                else:
                    raise NotionServiceException(
                        "Either 'title' or 'properties' is required for page creation",
                        service_name="notion"
                    )
            
            page = self.notion_client.create_page(
                database_id=database_id,
                properties=properties,
                content=content
            )
            
            if not page:
                raise NotionServiceException(
                    f"Failed to create page in database {database_id}",
                    service_name="notion"
                )
            
            logger.info(f"[NOTION_SERVICE] Created page: {page.get('id', 'unknown')}")
            return page
            
        except NotionServiceException:
            raise
        except Exception as e:
            logger.error(f"[NOTION_SERVICE] Error creating page: {e}", exc_info=True)
            raise NotionServiceException(
                f"Failed to create Notion page: {str(e)}",
                service_name="notion",
                cause=e
            )
    
    def update_page(
        self,
        page_id: str,
        properties: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update a Notion page
        
        Args:
            page_id: Page ID to update
            properties: New property values
            
        Returns:
            Updated page object
            
        Raises:
            NotionPageNotFoundException: If page not found
            NotionServiceException: If update fails
        """
        self._ensure_available()
        
        try:
            page = self.notion_client.update_page(
                page_id=page_id,
                properties=properties
            )
            
            if not page:
                raise NotionPageNotFoundException(
                    f"Page {page_id} not found or could not be updated",
                    service_name="notion"
                )
            
            logger.info(f"[NOTION_SERVICE] Updated page: {page_id}")
            return page
            
        except NotionPageNotFoundException:
            raise
        except Exception as e:
            logger.error(f"[NOTION_SERVICE] Error updating page {page_id}: {e}", exc_info=True)
            raise NotionServiceException(
                f"Failed to update Notion page: {str(e)}",
                service_name="notion",
                cause=e
            )
    
    def get_page(self, page_id: str) -> Dict[str, Any]:
        """
        Get a Notion page
        
        Args:
            page_id: Page ID to retrieve
            
        Returns:
            Page object
            
        Raises:
            NotionPageNotFoundException: If page not found
        """
        self._ensure_available()
        
        try:
            page = self.notion_client.get_page(page_id)
            
            if not page:
                raise NotionPageNotFoundException(
                    f"Page {page_id} not found",
                    service_name="notion"
                )
            
            return page
            
        except NotionPageNotFoundException:
            raise
        except Exception as e:
            logger.error(f"[NOTION_SERVICE] Error getting page {page_id}: {e}", exc_info=True)
            raise NotionServiceException(
                f"Failed to get Notion page: {str(e)}",
                service_name="notion",
                cause=e
            )
    
    # ===================================================================
    # DATABASE OPERATIONS
    # ===================================================================
    
    def query_database(
        self,
        database_id: str,
        filters: Optional[Dict[str, Any]] = None,
        sorts: Optional[List[Dict[str, Any]]] = None,
        start_cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Query a Notion database
        
        Args:
            database_id: Database ID to query
            filters: Optional filter criteria
            sorts: Optional sort order
            start_cursor: For pagination
            
        Returns:
            Query results with pages
            
        Raises:
            NotionDatabaseNotFoundException: If database not found
        """
        self._ensure_available()
        
        try:
            result = self.notion_client.query_database(
                database_id=database_id,
                filters=filters,
                sorts=sorts,
                start_cursor=start_cursor
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[NOTION_SERVICE] Error querying database {database_id}: {e}", exc_info=True)
            raise NotionDatabaseNotFoundException(
                f"Database {database_id} not found or query failed: {str(e)}",
                service_name="notion",
                cause=e
            )
    
    # ===================================================================
    # SEARCH OPERATIONS (GraphRAG)
    # ===================================================================
    
    async def graph_grounded_search(
        self,
        query: str,
        database_id: str,
        num_results: int = 5
    ) -> Dict[str, Any]:
        """
        Perform graph-grounded search combining Notion + ArangoDB
        
        Args:
            query: Search query
            database_id: Notion database ID
            num_results: Maximum results to return
            
        Returns:
            Search results with citations
            
        Raises:
            ServiceUnavailableException: If GraphRAG integration not available
        """
        if not self.rag_integration:
            raise ServiceUnavailableException(
                "GraphRAG integration not available. Please provide graph_manager and rag_engine.",
                service_name="notion"
            )
        
        return await self.rag_integration.graph_grounded_search(
            query=query,
            database_id=database_id,
            num_results=num_results
        )
    
    async def cross_platform_synthesis(
        self,
        query: str,
        databases: List[str],
        external_contexts: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Perform cross-platform synthesis combining Notion with external systems
        
        Args:
            query: User query
            databases: List of Notion database IDs
            external_contexts: Optional context from Slack, Calendar, etc.
            
        Returns:
            Synthesized results
            
        Raises:
            ServiceUnavailableException: If GraphRAG integration not available
        """
        if not self.rag_integration:
            raise ServiceUnavailableException(
                "GraphRAG integration not available. Please provide graph_manager and rag_engine.",
                service_name="notion"
            )
        
        return await self.rag_integration.cross_platform_synthesis(
            query=query,
            databases=databases,
            external_contexts=external_contexts
        )
    
    # ===================================================================
    # AUTONOMOUS MANAGEMENT OPERATIONS
    # ===================================================================
    
    async def auto_manage_database(
        self,
        action_type: str,
        source_system: str,
        action_data: Dict[str, Any],
        target_database_id: str
    ) -> Dict[str, Any]:
        """
        Automatically manage Notion database based on external action
        
        Args:
            action_type: Type of action ('meeting_held', 'email_sent', etc.)
            source_system: Source system ('calendar', 'slack', 'email', etc.)
            action_data: Data from the action
            target_database_id: Notion database to update
            
        Returns:
            Result of database management operation
            
        Raises:
            ServiceUnavailableException: If autonomous execution not available
        """
        if not self.autonomous_execution:
            raise ServiceUnavailableException(
                "Autonomous execution not available. Please provide rag_engine.",
                service_name="notion"
            )
        
        return await self.autonomous_execution.database_management_at_scale(
            action_type=action_type,
            source_system=source_system,
            action_data=action_data,
            target_database_id=target_database_id
        )

