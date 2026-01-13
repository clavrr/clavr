"""
Keep Tool - Note management capabilities

LangChain tool wrapper for Google Keep API operations.

IMPORTANT: Google Keep API requires Google Workspace Enterprise.
"""
import asyncio
from typing import Optional, Any, List
from langchain.tools import BaseTool
from pydantic import Field

from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)


class KeepTool(BaseTool):
    """
    Note management tool wrapping KeepService for Google Keep API
    
    Actions:
    - create: Create a new note (text or checklist)
    - list: List recent notes
    - search: Search notes by content
    - delete: Delete a note
    - quick: Create a quick note from text
    """
    
    name: str = "notes"
    description: str = "Note management (create, list, search). Use this for note-related queries."
    
    config: Optional[Config] = Field(default=None, exclude=True)
    user_id: int = Field(default=1, exclude=True)
    credentials: Optional[Any] = Field(default=None, exclude=True)
    _keep_service: Optional[Any] = None
    
    def __init__(
        self,
        config: Optional[Config] = None,
        user_id: int = 1,
        credentials: Optional[Any] = None,
        **kwargs
    ):
        super().__init__(
            config=config or Config(),
            user_id=user_id,
            credentials=credentials,
            **kwargs
        )
        if credentials:
            logger.info(f"[KeepTool] Initialized with credentials (valid={getattr(credentials, 'valid', 'unknown')})")
        else:
            logger.warning("[KeepTool] Initialized with NO credentials")
    
    @property
    def keep_service(self):
        """Lazy initialization of keep service for Google Keep API access"""
        if self._keep_service is None:
            try:
                from src.integrations.google_keep import KeepService
                self._keep_service = KeepService(self.config, self.credentials)
                logger.info("[KEEP_TOOL] KeepService initialized successfully")
            except Exception as e:
                logger.error(f"[KEEP_TOOL] Failed to initialize KeepService: {e}")
                self._keep_service = None
        return self._keep_service
    
    def _run(self, action: str = "list", query: str = "", **kwargs) -> str:
        """Execute keep tool action"""
        logger.info(f"[KEEP_TOOL] Executing action: {action}, query: {query[:50]}...")
        
        try:
            if action == "create":
                return self._handle_create(query, **kwargs)
            elif action == "list":
                return self._handle_list(**kwargs)
            elif action == "search":
                return self._handle_search(query, **kwargs)
            elif action == "delete":
                return self._handle_delete(query, **kwargs)
            elif action == "quick":
                return self._handle_quick(query)
            else:
                return f"Unknown action: {action}. Available: create, list, search, delete, quick"
                
        except Exception as e:
            logger.error(f"[KEEP_TOOL] Error executing {action}: {e}")
            return f"Error: {str(e)}"
    
    def _handle_create(self, query: str, **kwargs) -> str:
        """Handle note creation"""
        if not self.keep_service:
            return "Error: Google Keep service not available. Requires Google Workspace Enterprise."
        
        title = kwargs.get('title', '')
        body = kwargs.get('body', query)
        list_items = kwargs.get('list_items', kwargs.get('items', None))
        
        # Parse list_items from string if needed
        if isinstance(list_items, str):
            list_items = [item.strip() for item in list_items.split(',') if item.strip()]
        
        try:
            note = self.keep_service.create_note(
                title=title,
                body=body if not list_items else "",
                list_items=list_items
            )
            
            if list_items:
                return f"✅ Created checklist '{title or 'Note'}' with {len(list_items)} items"
            else:
                preview = body[:50] + "..." if len(body) > 50 else body
                return f"✅ Created note '{title or 'Note'}': {preview}"
                
        except Exception as e:
            return f"Failed to create note: {str(e)}"
    
    def _handle_list(self, **kwargs) -> str:
        """Handle listing notes"""
        if not self.keep_service:
            return "Error: Google Keep service not available. Requires Google Workspace Enterprise."
        
        limit = kwargs.get('limit', 10)
        
        try:
            notes = self.keep_service.list_notes(limit=limit)
            
            if not notes:
                return "📝 No notes found"
            
            result_lines = [f"📝 Found {len(notes)} notes:\n"]
            
            for i, note in enumerate(notes[:10], 1):
                title = note.get('title', '(Untitled)')
                if note.get('is_list'):
                    items = note.get('list_items', [])
                    checked = sum(1 for item in items if item.get('checked'))
                    result_lines.append(f"{i}. 📋 {title} ({checked}/{len(items)} done)")
                else:
                    body_preview = note.get('body', '')[:40]
                    if body_preview:
                        result_lines.append(f"{i}. 📝 {title}: {body_preview}...")
                    else:
                        result_lines.append(f"{i}. 📝 {title}")
            
            return "\n".join(result_lines)
            
        except Exception as e:
            return f"Failed to list notes: {str(e)}"
    
    def _handle_search(self, query: str, **kwargs) -> str:
        """Handle searching notes"""
        if not self.keep_service:
            return "Error: Google Keep service not available. Requires Google Workspace Enterprise."
        
        if not query:
            return "Please provide a search query"
        
        limit = kwargs.get('limit', 10)
        
        try:
            notes = self.keep_service.search_notes(query, limit=limit)
            
            if not notes:
                return f"🔍 No notes found matching '{query}'"
            
            result_lines = [f"🔍 Found {len(notes)} notes matching '{query}':\n"]
            
            for i, note in enumerate(notes[:10], 1):
                title = note.get('title', '(Untitled)')
                if note.get('is_list'):
                    result_lines.append(f"{i}. 📋 {title}")
                else:
                    result_lines.append(f"{i}. 📝 {title}")
            
            return "\n".join(result_lines)
            
        except Exception as e:
            return f"Failed to search notes: {str(e)}"
    
    def _handle_delete(self, query: str, **kwargs) -> str:
        """Handle deleting a note"""
        if not self.keep_service:
            return "Error: Google Keep service not available. Requires Google Workspace Enterprise."
        
        note_id = kwargs.get('note_id', query)
        
        if not note_id:
            return "Please provide a note ID to delete"
        
        try:
            result = self.keep_service.delete_note(note_id)
            return f"🗑️ Deleted note: {note_id}"
            
        except Exception as e:
            return f"Failed to delete note: {str(e)}"
    
    def _handle_quick(self, content: str) -> str:
        """Handle quick note creation"""
        if not self.keep_service:
            return "Error: Google Keep service not available. Requires Google Workspace Enterprise."
        
        if not content:
            return "Please provide note content"
        
        try:
            note = self.keep_service.quick_note(content)
            
            if note.get('is_list'):
                items_count = len(note.get('list_items', []))
                return f"✅ Created quick checklist with {items_count} items"
            else:
                preview = content[:40] + "..." if len(content) > 40 else content
                return f"✅ Created quick note: {preview}"
                
        except Exception as e:
            return f"Failed to create quick note: {str(e)}"
    
    async def _arun(self, action: str = "list", query: str = "", **kwargs) -> str:
        """Async execution - runs blocking _run in thread pool"""
        return await asyncio.to_thread(self._run, action, query, **kwargs)
