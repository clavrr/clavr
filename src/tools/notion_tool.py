"""
Notion Tool - Integration Layer

Provides natural language interface for Notion operations through the Notion integration layer.

Architecture:
    NotionTool → NotionGraphRAGIntegration/NotionAutonomousExecution → NotionClient → Notion API

The integration layer provides:
- Graph-grounded search (Notion + Neo4j)
- Cross-platform synthesis
- Autonomous workflow execution
- Database and page management
"""
from typing import Optional, Any, List, Dict
from datetime import datetime
from pydantic import BaseModel, Field, PrivateAttr

from .base_tool import ClavrBaseTool
from ..integrations.notion.service import NotionService
from ..integrations.notion.exceptions import (
    NotionServiceException,
    NotionPageNotFoundException,
    NotionDatabaseNotFoundException,
    ServiceUnavailableException
)
from ..utils.logger import setup_logger
from ..utils.config import Config

# Import modular components (for advanced features)
from .notion import (
    NotionSearch,
    NotionActions,
    NotionAutoManagement
)

logger = setup_logger(__name__)


class NotionActionInput(BaseModel):
    """Input schema for Notion operations"""
    action: str = Field(
        description="Action to perform: 'search', 'create_page', 'update_page', 'get_page', 'query_database', 'create_database_entry', 'update_database_entry', 'cross_platform_synthesis', 'auto_manage_database'"
    )
    query: Optional[str] = Field(default=None, description="Search query or page content")
    database_id: Optional[str] = Field(default=None, description="Notion database ID")
    page_id: Optional[str] = Field(default=None, description="Notion page ID")
    title: Optional[str] = Field(default=None, description="Page title")
    properties: Optional[Dict[str, Any]] = Field(default=None, description="Page properties (for create/update)")
    content: Optional[List[Dict[str, Any]]] = Field(default=None, description="Page content blocks")
    num_results: Optional[int] = Field(default=5, description="Number of search results to return")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Database query filters")
    sorts: Optional[List[Dict[str, Any]]] = Field(default=None, description="Database query sort order")
    action_type: Optional[str] = Field(default=None, description="Action type for auto_manage_database")
    source_system: Optional[str] = Field(default=None, description="Source system for auto_manage_database")
    action_data: Optional[Dict[str, Any]] = Field(default=None, description="Action data for auto_manage_database")
    databases: Optional[List[str]] = Field(default=None, description="List of database IDs for cross-platform synthesis")
    external_contexts: Optional[Dict[str, Any]] = Field(default=None, description="External contexts for cross-platform synthesis")


class NotionTool(ClavrBaseTool):
    """
    Notion operations tool with GraphRAG integration
    
    Capabilities:
    - Search Notion pages with graph-grounded search (Notion + Neo4j)
    - Create and update Notion pages
    - Query Notion databases
    - Cross-platform synthesis (combine Notion with Slack, Calendar, etc.)
    - Autonomous database management (auto-create/update based on external actions)
    
    Architecture:
        NotionTool → NotionGraphRAGIntegration/NotionAutonomousExecution → NotionClient → Notion API
    
    Examples:
        "Search my Notion pages for Q3 budget decisions"
        "Create a Notion page about the meeting notes"
        "Update the project tracker with today's progress"
        "Query the tasks database for overdue items"
        "Synthesize information from Notion and Slack about the project"
    """
    
    name: str = "notion"
    description: str = (
        "Manage Notion pages and databases with advanced GraphRAG capabilities. "
        "Can search pages with graph-grounded search (combines Notion + Neo4j), "
        "create and update pages, query databases, perform cross-platform synthesis, "
        "and autonomously manage databases based on external actions. "
        "Use this tool for comprehensive Notion knowledge management."
    )
    args_schema: type[BaseModel] = NotionActionInput
    
    # Config and credentials
    config: Optional[Config] = None
    _user_id: Optional[str] = PrivateAttr(default=None)
    _api_key: Optional[str] = PrivateAttr(default=None)
    
    # Notion service (business logic layer)
    _notion_service: Optional[NotionService] = PrivateAttr(default=None)
    
    # Graph manager and RAG engine for GraphRAG features
    _graph_manager: Optional[Any] = PrivateAttr(default=None)
    _rag_engine: Optional[Any] = PrivateAttr(default=None)
    
    # Modular components (lazy-loaded) - for advanced features
    _search: Optional[NotionSearch] = PrivateAttr(default=None)
    _actions: Optional[NotionActions] = PrivateAttr(default=None)
    _auto_management: Optional[NotionAutoManagement] = PrivateAttr(default=None)
    
    # Parser for intelligent query understanding
    _parser: Optional[Any] = PrivateAttr(default=None)
    
    def __init__(
        self,
        config: Optional[Config] = None,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
        graph_manager: Optional[Any] = None,
        rag_engine: Optional[Any] = None,
        **kwargs
    ):
        """
        Initialize Notion tool
        
        Args:
            config: Configuration object
            user_id: User ID (for future multi-user support)
            api_key: Notion API key (defaults to NOTION_API_KEY env var)
            graph_manager: Optional KnowledgeGraphManager for Neo4j
            rag_engine: Optional RAGEngine for Pinecone vectorization
        """
        super().__init__(config=config, **kwargs)
        self.config = config
        self._user_id = user_id
        self._api_key = api_key
        self._graph_manager = graph_manager
        self._rag_engine = rag_engine
        
        logger.info(f"[OK] {self.name} tool initialized")
    
    @property
    def notion_service(self) -> NotionService:
        """Get or create Notion service with user credentials"""
        if self._notion_service is None:
            logger.info(f"[NOTION] Initializing NotionService - user_id={self._user_id}")
            
            self._notion_service = NotionService(
                config=self.config,
                api_key=self._api_key,
                graph_manager=self._graph_manager,
                rag_engine=self._rag_engine
            )
            
            logger.info(f"[OK] NotionService initialized (user_id={self._user_id})")
        
        return self._notion_service
    
    @property
    def search(self) -> NotionSearch:
        """Get or create NotionSearch modular component"""
        if self._search is None:
            self._search = NotionSearch(notion_service=self.notion_service)
        return self._search
    
    @property
    def actions(self) -> NotionActions:
        """Get or create NotionActions modular component"""
        if self._actions is None:
            self._actions = NotionActions(notion_service=self.notion_service)
        return self._actions
    
    @property
    def auto_management(self) -> NotionAutoManagement:
        """Get or create NotionAutoManagement modular component"""
        if self._auto_management is None:
            self._auto_management = NotionAutoManagement(notion_service=self.notion_service)
        return self._auto_management
    
    @property
    def parser(self) -> Any:
        """Get or create NotionParser for intelligent query understanding"""
        if self._parser is None and self.config:
            try:
                from ..agent.parsers.notion_parser import NotionParser
                parser_instance = NotionParser(
                    rag_service=self._rag_engine,
                    config=self.config
                )
                self._parser = parser_instance
                logger.info("[NOTION] NotionParser initialized for query understanding")
            except Exception as e:
                logger.warning(f"[NOTION] NotionParser initialization failed: {e}")
                self._parser = None
        return self._parser
    
    def _run(
        self,
        action: str,
        query: Optional[str] = None,
        database_id: Optional[str] = None,
        page_id: Optional[str] = None,
        title: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        content: Optional[List[Dict[str, Any]]] = None,
        num_results: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        sorts: Optional[List[Dict[str, Any]]] = None,
        action_type: Optional[str] = None,
        source_system: Optional[str] = None,
        action_data: Optional[Dict[str, Any]] = None,
        databases: Optional[List[str]] = None,
        external_contexts: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """
        Execute Notion operation
        
        Args:
            action: Action to perform
            query: Search query or content
            database_id: Notion database ID
            page_id: Notion page ID
            title: Page title
            properties: Page properties
            content: Page content blocks
            num_results: Number of search results
            filters: Database query filters
            sorts: Database query sort order
            action_type: Action type for auto_manage_database
            source_system: Source system for auto_manage_database
            action_data: Action data for auto_manage_database
            databases: List of database IDs for cross-platform synthesis
            external_contexts: External contexts for cross-platform synthesis
            
        Returns:
            Result string
        """
        # === PARSER INTEGRATION ===
        # Use parser to enhance parameter extraction if query is provided
        if query and self.parser:
            try:
                parsed = self.parser.parse_query_to_params(
                    query=query,
                    user_id=int(self._user_id) if self._user_id else None,
                    session_id=None
                )
                
                logger.info(f"[NOTION] Parser result: action={parsed['action']}, confidence={parsed['confidence']:.2f}")
                
                # Use parsed action if confidence is high enough
                parsed_action = parsed.get('action')
                parsed_entities = parsed.get('entities', {})
                parsed_confidence = parsed.get('confidence', 0.0)
                
                # Critical actions should always override
                critical_actions = ['create_page', 'update_page', 'create_database_entry', 'update_database_entry']
                is_critical_action = parsed_action in critical_actions
                
                # Use parsed action if it's critical or confidence is high
                if is_critical_action or parsed_confidence >= 0.7:
                    if not action or action == 'search' or parsed_confidence >= 0.85:
                        action = parsed_action
                        logger.info(f"[NOTION] Using parser-detected action: {action} (confidence: {parsed_confidence:.2f})")
                
                # Enhance parameters with parsed entities (only if not already provided)
                if not title and parsed_entities.get('title'):
                    title = parsed_entities['title']
                    logger.info(f"[NOTION] Using parser-extracted title: {title}")
                if not database_id and parsed_entities.get('database_id'):
                    database_id = parsed_entities['database_id']
                    logger.info(f"[NOTION] Using parser-extracted database_id: {database_id}")
                if not page_id and parsed_entities.get('page_id'):
                    page_id = parsed_entities['page_id']
                    logger.info(f"[NOTION] Using parser-extracted page_id: {page_id}")
                if not query and parsed_entities.get('query'):
                    query = parsed_entities['query']
                    logger.info(f"[NOTION] Using parser-extracted query: {query}")
                if parsed_entities.get('num_results') and num_results == 5:  # Only override default
                    num_results = parsed_entities['num_results']
                    logger.info(f"[NOTION] Using parser-extracted num_results: {num_results}")
                    
            except Exception as e:
                logger.debug(f"[NOTION] Parser integration failed (non-critical): {e}")
        
        try:
            # Handle async operations synchronously
            import asyncio
            import concurrent.futures
            
            # Prepare kwargs for async call
            async_kwargs = {
                'action': action,
                'query': query,
                'database_id': database_id,
                'page_id': page_id,
                'title': title,
                'properties': properties,
                'content': content,
                'num_results': num_results,
                'filters': filters,
                'sorts': sorts,
                'action_type': action_type,
                'source_system': source_system,
                'action_data': action_data,
                'databases': databases,
                'external_contexts': external_contexts,
                **kwargs
            }
            
            # Check if we're in an async context
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're in an async context, run in thread pool
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, self._run_async(**async_kwargs))
                        return future.result()
                else:
                    return loop.run_until_complete(self._run_async(**async_kwargs))
            except RuntimeError:
                # No event loop, create one
                return asyncio.run(self._run_async(**async_kwargs))
                
        except Exception as e:
            logger.error(f"[NOTION] Error executing action '{action}': {e}", exc_info=True)
            return f"Error: {str(e)}"
    
    async def _run_async(
        self,
        action: str,
        query: Optional[str] = None,
        database_id: Optional[str] = None,
        page_id: Optional[str] = None,
        title: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        content: Optional[List[Dict[str, Any]]] = None,
        num_results: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        sorts: Optional[List[Dict[str, Any]]] = None,
        action_type: Optional[str] = None,
        source_system: Optional[str] = None,
        action_data: Optional[Dict[str, Any]] = None,
        databases: Optional[List[str]] = None,
        external_contexts: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """Async implementation of Notion operations"""
        
        if action == "search":
            if not query or not database_id:
                return "Error: 'search' action requires 'query' and 'database_id'"
            
            result = await self.search.graph_grounded_search(
                query=query,
                database_id=database_id,
                num_results=num_results
            )
            
            if result.get('success'):
                results = result.get('results', [])
                return self.search.format_search_results(results)
            else:
                return f"Search failed: {result.get('error', 'Unknown error')}"
        
        elif action == "create_page":
            if not database_id:
                return "Error: 'create_page' action requires 'database_id'"
            
            page = self.actions.create_page(
                database_id=database_id,
                title=title,
                properties=properties,
                content=content
            )
            
            if page:
                page_id = page.get('id', 'unknown')
                page_url = page.get('url', '')
                return f"Successfully created Notion page: {page_url} (ID: {page_id})"
            else:
                return "Error: Failed to create Notion page"
        
        elif action == "update_page":
            if not page_id:
                return "Error: 'update_page' action requires 'page_id'"
            
            if not properties:
                return "Error: 'update_page' requires 'properties'"
            
            page = self.actions.update_page(
                page_id=page_id,
                properties=properties
            )
            
            if page:
                page_url = page.get('url', '')
                return f"Successfully updated Notion page: {page_url}"
            else:
                return "Error: Failed to update Notion page"
        
        elif action == "get_page":
            if not page_id:
                return "Error: 'get_page' action requires 'page_id'"
            
            page = self.actions.get_page(page_id)
            
            if page:
                from .notion.utils import extract_page_title
                page_title = extract_page_title(page)
                page_url = page.get('url', '')
                return f"**{page_title}**\nURL: {page_url}"
            else:
                return f"Error: Page {page_id} not found"
        
        elif action == "query_database":
            if not database_id:
                return "Error: 'query_database' action requires 'database_id'"
            
            result = self.actions.query_database(
                database_id=database_id,
                filters=filters,
                sorts=sorts
            )
            
            return self.actions.format_database_results(result)
        
        elif action == "cross_platform_synthesis":
            if not query or not databases:
                return "Error: 'cross_platform_synthesis' requires 'query' and 'databases'"
            
            result = await self.search.cross_platform_synthesis(
                query=query,
                databases=databases,
                external_contexts=external_contexts
            )
            
            if result.get('success'):
                synthesized = result.get('synthesized_result', '')
                sources = result.get('sources', {})
                return f"Synthesized result:\n\n{synthesized}\n\nSources: {len(sources)} systems queried"
            else:
                return f"Synthesis failed: {result.get('error', 'Unknown error')}"
        
        elif action == "auto_manage_database":
            if not action_type or not source_system or not action_data or not database_id:
                return "Error: 'auto_manage_database' requires 'action_type', 'source_system', 'action_data', and 'database_id'"
            
            result = await self.auto_management.manage_database(
                action_type=action_type,
                source_system=source_system,
                action_data=action_data,
                target_database_id=database_id
            )
            
            return self.auto_management.format_management_result(result)
        
        else:
            return f"Error: Unknown action '{action}'. Supported actions: search, create_page, update_page, get_page, query_database, cross_platform_synthesis, auto_manage_database"

