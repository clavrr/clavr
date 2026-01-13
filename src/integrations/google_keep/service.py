"""
Keep Service - Business logic layer for note operations

Provides a clean interface for note operations using Google Keep API.

IMPORTANT: Google Keep API requires Google Workspace Enterprise.
Regular Gmail accounts cannot use this API.

This service is used by:
- KeepTool (LangChain tool)
- API endpoints
- Voice assistant

Architecture:
    KeepService → GoogleKeepClient (required)
"""
from typing import Optional, List, Dict, Any

from src.core.keep.google_client import GoogleKeepClient
from src.utils.logger import setup_logger
from src.utils.config import Config
from .exceptions import (
    KeepServiceException,
    NoteNotFoundException,
    NoteValidationException,
    KeepAuthenticationException,
    KeepUnavailableException
)

logger = setup_logger(__name__)


class KeepService:
    """
    Keep service providing business logic for note operations
    
    IMPORTANT: Requires Google Workspace Enterprise account.
    
    Features:
    - Create text notes
    - Create checklist notes
    - List notes
    - Search notes
    - Delete notes
    """
    
    def __init__(
        self,
        config: Config,
        credentials: Any
    ):
        """
        Initialize Keep service with Google Keep
        
        Args:
            config: Application configuration
            credentials: Google OAuth credentials (REQUIRED)
            
        Raises:
            KeepAuthenticationException: If credentials not provided
            KeepUnavailableException: If Google Keep API unavailable
        """
        if not credentials:
            raise KeepAuthenticationException(
                message="Google Keep credentials required. "
                        "Please authenticate with Google OAuth. "
                        "Note: Requires Google Workspace Enterprise account."
            )
        
        self.config = config
        self.credentials = credentials
        
        try:
            self.keep_client = GoogleKeepClient(config, credentials=credentials)
            
            if not self.keep_client.is_available():
                raise KeepUnavailableException(
                    message="Google Keep API is not available. "
                            "This may mean your account is not a Workspace Enterprise account."
                )
            
            logger.info("[KEEP_SERVICE] Google Keep client initialized successfully")
            
        except KeepUnavailableException:
            raise
        except Exception as e:
            logger.error(f"[KEEP_SERVICE] Failed to initialize Google Keep: {e}")
            raise KeepUnavailableException(
                message=f"Failed to initialize Google Keep: {str(e)}",
                cause=e
            )
    
    # ===================================================================
    # CORE NOTE OPERATIONS
    # ===================================================================
    
    def create_note(
        self,
        title: str = "",
        body: str = "",
        list_items: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Create a new note
        
        Args:
            title: Note title
            body: Note body text (for text notes)
            list_items: List of items (for checklist notes)
            
        Returns:
            Created note details
            
        Raises:
            NoteValidationException: If note data is invalid
            KeepServiceException: If creation fails
        """
        try:
            if not title and not body and not list_items:
                raise NoteValidationException(
                    "Note must have a title, body, or list items",
                    field="content"
                )
            
            logger.info(f"[KEEP_SERVICE] Creating note: {title or '(untitled)'}")
            
            note = self.keep_client.create_note(
                title=title,
                body=body,
                list_items=list_items
            )
            
            if not note:
                raise KeepServiceException(
                    "Failed to create note: Google Keep API returned None",
                    details={'title': title}
                )
            
            logger.info(f"[KEEP_SERVICE] Note created: {note.get('id')}")
            return note
            
        except NoteValidationException:
            raise
        except KeepServiceException:
            raise
        except Exception as e:
            logger.error(f"[KEEP_SERVICE] Failed to create note: {e}")
            raise KeepServiceException(
                f"Failed to create note: {str(e)}",
                details={'title': title}
            )
    
    def get_note(self, note_id: str) -> Dict[str, Any]:
        """
        Get a single note by ID
        
        Args:
            note_id: Note ID
            
        Returns:
            Note details
            
        Raises:
            NoteNotFoundException: If note not found
        """
        try:
            note = self.keep_client.get_note(note_id)
            
            if not note:
                raise NoteNotFoundException(note_id)
            
            return note
            
        except NoteNotFoundException:
            raise
        except Exception as e:
            logger.error(f"[KEEP_SERVICE] Failed to get note: {e}")
            raise KeepServiceException(
                f"Failed to get note: {str(e)}",
                details={'note_id': note_id}
            )
    
    def list_notes(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        List notes
        
        Args:
            limit: Maximum results
            
        Returns:
            List of notes
        """
        try:
            logger.info(f"[KEEP_SERVICE] Listing notes (limit={limit})")
            
            notes = self.keep_client.list_notes(page_size=limit)
            
            logger.info(f"[KEEP_SERVICE] Found {len(notes)} notes")
            return notes
            
        except Exception as e:
            logger.error(f"[KEEP_SERVICE] Failed to list notes: {e}")
            raise KeepServiceException(f"Failed to list notes: {str(e)}")
    
    def search_notes(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Search notes by content
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of matching notes
        """
        try:
            logger.info(f"[KEEP_SERVICE] Searching notes: '{query}'")
            
            notes = self.keep_client.search_notes(query, limit=limit)
            
            logger.info(f"[KEEP_SERVICE] Found {len(notes)} matching notes")
            return notes
            
        except Exception as e:
            logger.error(f"[KEEP_SERVICE] Failed to search notes: {e}")
            raise KeepServiceException(f"Failed to search notes: {str(e)}")
    
    def delete_note(self, note_id: str) -> Dict[str, Any]:
        """
        Delete a note
        
        Args:
            note_id: Note ID
            
        Returns:
            Success confirmation
        """
        try:
            logger.info(f"[KEEP_SERVICE] Deleting note: {note_id}")
            
            success = self.keep_client.delete_note(note_id)
            
            if not success:
                raise KeepServiceException(
                    f"Failed to delete note {note_id}",
                    details={'note_id': note_id}
                )
            
            logger.info(f"[KEEP_SERVICE] Note deleted: {note_id}")
            return {'note_id': note_id, 'status': 'deleted'}
            
        except KeepServiceException:
            raise
        except Exception as e:
            logger.error(f"[KEEP_SERVICE] Failed to delete note: {e}")
            raise KeepServiceException(
                f"Failed to delete note: {str(e)}",
                details={'note_id': note_id}
            )
    
    # ===================================================================
    # CONVENIENCE METHODS
    # ===================================================================
    
    def quick_note(self, content: str) -> Dict[str, Any]:
        """
        Create a quick note from a single string
        
        Automatically determines if content is a list (comma or newline separated)
        
        Args:
            content: Note content
            
        Returns:
            Created note
        """
        # Check if content looks like a list
        if '\n' in content or ', ' in content:
            # Parse as list items
            if '\n' in content:
                items = [item.strip() for item in content.split('\n') if item.strip()]
            else:
                items = [item.strip() for item in content.split(', ') if item.strip()]
            
            if len(items) > 1:
                return self.create_note(list_items=items)
        
        # Create as text note
        return self.create_note(body=content)
    
    def create_grocery_list(self, items: List[str], title: str = "Groceries") -> Dict[str, Any]:
        """
        Create a grocery list note
        
        Args:
            items: List of grocery items
            title: List title (default: "Groceries")
            
        Returns:
            Created note
        """
        return self.create_note(title=title, list_items=items)
