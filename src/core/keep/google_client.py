"""
Google Keep Client
Integrates with Google Keep API to manage notes

Note: Google Keep API is only available to Google Workspace Enterprise accounts.
"""
from typing import List, Dict, Any, Optional
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.core.base import BaseGoogleAPIClient

logger = setup_logger(__name__)


def format_note_from_google(note: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format a Google Keep note to a standardized format
    
    Args:
        note: Raw note from Google Keep API
        
    Returns:
        Formatted note dictionary
    """
    # Extract list items if present
    list_items = []
    body = note.get('body', {})
    
    if 'listContent' in body:
        for item in body.get('listContent', []):
            text_content = item.get('text', {}).get('text', '')
            is_checked = item.get('checked', False)
            list_items.append({
                'text': text_content,
                'checked': is_checked
            })
    
    # Extract text content
    text_content = ''
    if 'text' in body:
        text_content = body.get('text', {}).get('text', '')
    
    return {
        'id': note.get('name', '').replace('notes/', ''),
        'name': note.get('name', ''),
        'title': note.get('title', ''),
        'body': text_content,
        'list_items': list_items,
        'is_list': len(list_items) > 0,
        'is_trashed': note.get('trashed', False),
        'create_time': note.get('createTime'),
        'update_time': note.get('updateTime'),
        'raw': note
    }


class GoogleKeepClient(BaseGoogleAPIClient):
    """
    Google Keep API client
    
    Provides methods to interact with Google Keep:
    - List notes
    - Create notes (text and list)
    - Get note by ID
    - Delete (trash) notes
    
    Note: Requires Google Workspace Enterprise account.
    """
    
    def __init__(self, config: Config, credentials: Optional[Credentials] = None):
        """
        Initialize Google Keep client
        
        Args:
            config: Configuration object
            credentials: OAuth2 credentials
        """
        self._account_restricted = False
        super().__init__(config, credentials)
    
    def _build_service(self) -> Any:
        """Build Google Keep API service"""
        return build('keep', 'v1', credentials=self.credentials, cache_discovery=False)
    
    def _get_required_scopes(self) -> List[str]:
        """Get required Google Keep scopes"""
        return ['https://www.googleapis.com/auth/keep']
    
    def _get_service_name(self) -> str:
        """Get service name"""
        return "Google Keep"
    
    def list_notes(self, page_size: int = 100, filter_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List notes from Google Keep
        
        Args:
            page_size: Maximum number of notes to return
            filter_str: Optional filter string (e.g., "trashed=false")
            
        Returns:
            List of note dictionaries
        """
        if not self.is_available():
            logger.warning("Google Keep service not available")
            return []
        
        try:
            all_notes: List[Dict[str, Any]] = []
            page_token: Optional[str] = None
            
            while True:
                request_params = {
                    'pageSize': min(page_size, 100)
                }
                
                if page_token:
                    request_params['pageToken'] = page_token
                
                if filter_str:
                    request_params['filter'] = filter_str
                
                results = self.service.notes().list(**request_params).execute()
                notes = results.get('notes', [])
                all_notes.extend(notes)
                
                page_token = results.get('nextPageToken')
                if not page_token or len(all_notes) >= page_size:
                    break
            
            # Format notes
            formatted_notes = [format_note_from_google(note) for note in all_notes]
            
            # Filter out trashed notes by default
            formatted_notes = [n for n in formatted_notes if not n.get('is_trashed', False)]
            
            logger.info(f"Retrieved {len(formatted_notes)} notes from Google Keep")
            return formatted_notes[:page_size]
            
        except HttpError as e:
            if e.resp.status == 403:
                logger.error(f"Google Keep API error (403): {e}")
                logger.error("Google Keep API requires Google Workspace Enterprise.")
                logger.error("Regular Gmail accounts cannot use this API.")
            else:
                logger.error(f"Google Keep API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to list Google Keep notes: {e}")
            return []
    
    def create_note(
        self,
        title: str = "",
        body: str = "",
        list_items: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new note in Google Keep
        
        Args:
            title: Note title
            body: Note body text (for text notes)
            list_items: List of items (for checklist notes)
            
        Returns:
            Created note dictionary or None if failed
        """
        if not self.is_available():
            logger.warning("Google Keep service not available")
            return None
        
        try:
            note_body: Dict[str, Any] = {}
            
            if title:
                note_body['title'] = title
            
            if list_items:
                # Create a checklist note
                note_body['body'] = {
                    'list': {
                        'listItems': [
                            {'text': {'text': item}, 'checked': False}
                            for item in list_items
                        ]
                    }
                }
            elif body:
                # Create a text note
                note_body['body'] = {
                    'text': {
                        'text': body
                    }
                }
            
            result = self.service.notes().create(body=note_body).execute()
            
            logger.info(f"Created Google Keep note: {title or '(untitled)'}")
            return format_note_from_google(result)
            
        except HttpError as e:
            error_str = str(e)
            if 'Account Restricted' in error_str or e.resp.status == 403:
                self._account_restricted = True
                logger.error("Google Keep API requires Google Workspace Enterprise.")
            else:
                logger.error(f"Google Keep API error creating note: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create Google Keep note: {e}")
            return None
    
    def get_note(self, note_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a note by ID
        
        Args:
            note_id: Note ID (with or without 'notes/' prefix)
            
        Returns:
            Note dictionary or None if not found
        """
        if not self.is_available():
            logger.warning("Google Keep service not available")
            return None
        
        try:
            # Ensure proper format
            name = note_id if note_id.startswith('notes/') else f'notes/{note_id}'
            
            result = self.service.notes().get(name=name).execute()
            
            logger.info(f"Retrieved Google Keep note: {result.get('title', note_id)}")
            return format_note_from_google(result)
            
        except HttpError as e:
            if e.resp.status == 404:
                logger.warning(f"Google Keep note not found: {note_id}")
            else:
                logger.error(f"Google Keep API error getting note: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to get Google Keep note: {e}")
            return None
    
    def delete_note(self, note_id: str) -> bool:
        """
        Delete (trash) a note
        
        Args:
            note_id: Note ID (with or without 'notes/' prefix)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available():
            logger.warning("Google Keep service not available")
            return False
        
        try:
            # Ensure proper format
            name = note_id if note_id.startswith('notes/') else f'notes/{note_id}'
            
            self.service.notes().delete(name=name).execute()
            
            logger.info(f"Deleted Google Keep note: {note_id}")
            return True
            
        except HttpError as e:
            logger.error(f"Google Keep API error deleting note: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete Google Keep note: {e}")
            return False
    
    def search_notes(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Search notes by content
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of matching notes
        """
        # Keep API doesn't have native search, so we filter client-side
        all_notes = self.list_notes(page_size=200)
        query_lower = query.lower()
        
        matching_notes = [
            note for note in all_notes
            if query_lower in note.get('title', '').lower() or
               query_lower in note.get('body', '').lower() or
               any(query_lower in item.get('text', '').lower() 
                   for item in note.get('list_items', []))
        ]
        
        logger.info(f"Found {len(matching_notes)} notes matching '{query}'")
        return matching_notes[:limit]
