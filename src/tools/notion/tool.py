"""
Notion Tool - Notion integration capabilities
"""
import asyncio
from typing import Optional, Any, Type
from langchain.tools import BaseTool
from pydantic import Field, BaseModel

from ...utils.logger import setup_logger
from ...utils.config import Config

logger = setup_logger(__name__)


class NotionInput(BaseModel):
    """Input for NotionTool."""
    action: str = Field(description="Action to perform (query, create, update, list_databases, search)")
    query: Optional[str] = Field(default="", description="Query or details for the action.")
    database_id: Optional[str] = Field(default=None, description="Notion database ID")
    properties: Optional[dict] = Field(default=None, description="Notion page properties")


class NotionTool(BaseTool):
    """Notion integration tool with per-user OAuth support"""
    name: str = "notion"
    description: str = "Notion database management (query, create, update, search). Use this for Notion-related queries."
    args_schema: Type[BaseModel] = NotionInput
    
    config: Optional[Config] = Field(default=None)
    user_id: Optional[int] = Field(default=None)
    access_token: Optional[str] = Field(default=None)
    graph_manager: Optional[Any] = Field(default=None)
    rag_engine: Optional[Any] = Field(default=None)
    _client: Optional[Any] = None
    _parser: Optional[Any] = None
    
    def __init__(
        self, 
        config: Optional[Config] = None, 
        user_id: Optional[int] = None,
        access_token: Optional[str] = None,
        graph_manager: Optional[Any] = None,
        rag_engine: Optional[Any] = None, 
        **kwargs
    ):
        super().__init__(**kwargs)
        self.config = config
        self.user_id = user_id
        self.access_token = access_token
        self.graph_manager = graph_manager
        self.rag_engine = rag_engine
        self._client = None
        self._parser = None
        
        if access_token:
            logger.info(f"[NotionTool] Initialized with provided access token")
        elif user_id:
            logger.info(f"[NotionTool] Initialized for user {user_id}, will fetch credentials on use")
        else:
            logger.warning("[NotionTool] Initialized without user context, will use env API key")
    
    def _get_access_token(self) -> Optional[str]:
        """Get access token for the current user from database."""
        # If token was provided directly, use it
        if self.access_token:
            return self.access_token
        
        # If no user_id, can't fetch from DB
        if not self.user_id:
            return None
        
        try:
            from ...database import get_db_context
            from ...database.models import UserIntegration
            
            with get_db_context() as db:
                integration = db.query(UserIntegration).filter(
                    UserIntegration.user_id == self.user_id,
                    UserIntegration.provider == "notion"
                ).first()
                
                if integration:
                    logger.debug(f"[NotionTool] Found Notion credentials for user {self.user_id}")
                    return integration.access_token
                else:
                    logger.debug(f"[NotionTool] No Notion integration found for user {self.user_id}")
        except Exception as e:
            logger.warning(f"[NotionTool] Failed to get Notion credentials for user {self.user_id}: {e}")
        
        return None
    
    def _initialize_client(self):
        """Lazy initialization of Notion client with user credentials."""
        if self._client is None:
            try:
                from ...integrations.notion.client import NotionClient
                
                # Get access token (OAuth) or fall back to env API key
                token = self._get_access_token()
                
                self._client = NotionClient(access_token=token)
                logger.debug("[NotionTool] NotionClient initialized")
            except ValueError as e:
                logger.warning(f"[NotionTool] Notion not configured: {e}")
                self._client = None
            except Exception as e:
                logger.error(f"[NotionTool] Failed to initialize NotionClient: {e}")
                self._client = None
        return self._client
    
    def _run(self, action: str = "search", query: str = "", **kwargs) -> str:
        """Execute Notion tool action"""
        client = self._initialize_client()
        
        if not client:
            return "[INTEGRATION_REQUIRED] Notion permission not granted. Please enable Notion integration in Settings."
        
        try:
            if action == "search":
                results = client.search(query)
                if not results:
                    return f"No results found for '{query}' in Notion."
                
                # Format results
                lines = [f"Found {len(results)} results in Notion:\n"]
                for i, page in enumerate(results[:10], 1):
                    title = self._extract_page_title(page)
                    url = page.get('url', '')
                    lines.append(f"{i}. **{title}**")
                    if url:
                        lines.append(f"   {url}")
                return "\n".join(lines)
            
            elif action == "query":
                database_id = kwargs.get('database_id')
                if not database_id:
                    return "Error: database_id is required for query action."
                
                result = client.query_database(database_id)
                pages = result.get('results', [])
                
                if not pages:
                    return "No pages found in this database."
                
                lines = [f"Found {len(pages)} pages:\n"]
                for page in pages[:10]:
                    title = self._extract_page_title(page)
                    lines.append(f"• {title}")
                return "\n".join(lines)
            
            elif action == "create":
                database_id = kwargs.get('database_id')
                properties = kwargs.get('properties')
                
                if not database_id:
                    return "Error: database_id is required for create action."
                
                page = client.create_page(database_id, properties or {})
                if page:
                    title = self._extract_page_title(page)
                    return f"Created new page: {title}"
                return "Failed to create page."
            
            elif action == "update":
                page_id = kwargs.get('page_id')
                properties = kwargs.get('properties')
                
                if not page_id:
                    return "Error: page_id is required for update action."
                
                page = client.update_page(page_id, properties or {})
                if page:
                    return "Page updated successfully."
                return "Failed to update page."
            
            else:
                return f"Unknown action: {action}. Supported: search, query, create, update"
                
        except Exception as e:
            logger.error(f"[NotionTool] Error: {e}", exc_info=True)
            return f"Error: {str(e)}"
    
    def _extract_page_title(self, page: dict) -> str:
        """Extract title from a Notion page object."""
        properties = page.get('properties', {})
        
        # Try common title property names
        for prop_name in ['Name', 'Title', 'name', 'title']:
            prop = properties.get(prop_name, {})
            if prop.get('type') == 'title':
                title_arr = prop.get('title', [])
                if title_arr:
                    return ''.join([t.get('plain_text', '') for t in title_arr])
        
        # Fallback: look for any title type property
        for prop in properties.values():
            if isinstance(prop, dict) and prop.get('type') == 'title':
                title_arr = prop.get('title', [])
                if title_arr:
                    return ''.join([t.get('plain_text', '') for t in title_arr])
        
        return "Untitled"
    
    async def _arun(self, action: str = "search", query: str = "", **kwargs) -> str:
        """Async execution - runs blocking _run in thread pool to avoid blocking event loop"""
        return await asyncio.to_thread(self._run, action=action, query=query, **kwargs)

