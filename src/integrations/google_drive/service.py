"""
Google Drive Service Module

Provides high-level business logic for Google Drive operations.
"""
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, timedelta

from ...utils.logger import setup_logger
from ...utils.config import Config
from .client import GoogleDriveClient

logger = setup_logger(__name__)

class GoogleDriveService:
    """
    Service for Google Drive High-Level Operations
    """
    
    def __init__(self, config: Config, credentials: Optional[Any] = None, token_update_callback: Optional[Any] = None):
        self.config = config
        self.client = GoogleDriveClient(config, credentials, token_update_callback=token_update_callback)

    def get_sync_token(self) -> Optional[str]:
        """Get the current sync token"""
        try:
            return self.client.get_start_page_token()
        except Exception as e:
            logger.error(f"[DRIVE_SERVICE] Failed to get sync token: {e}")
            return None

    def fetch_changes(self, sync_token: str) -> Dict[str, Any]:
        """Fetch changes since token"""
        try:
            return self.client.list_changes(sync_token)
        except Exception as e:
            logger.error(f"[DRIVE_SERVICE] Failed to fetch changes: {e}")
            return {}
        
    def _handle_api_error(self, e: Exception, operation: str) -> None:
        """Handle API errors, raising IntegrationRequired for auth issues"""
        error_str = str(e).lower()
        if any(x in error_str for x in ['401', '403', 'unauthorized', 'permission', 'forbidden', 'credentials', 'token']):
            logger.warning(f"[DRIVE_SERVICE] Auth error during {operation}: {e}")
            raise Exception("[INTEGRATION_REQUIRED] Drive permission not granted. Please enable Google integration in Settings.")
        logger.error(f"[DRIVE_SERVICE] Failed to {operation}: {e}")

    def list_recent_files(self, days: int = 30, limit: int = 50) -> List[Dict[str, Any]]:
        """
        List files modified in the last N days
        
        Args:
            days: Number of days to look back
            limit: Max results
            
        Returns:
            List of file metadata
        """
        # ISO format time
        start_time = (datetime.utcnow() - timedelta(days=days)).isoformat("T") + "Z"
        
        # Use modifiedTime instead of modifiedByMeTime - modifiedByMeTime can be null
        # for files the user didn't modify themselves, causing query errors
        query = f"modifiedTime > '{start_time}' and trashed = false"
        
        try:
            result = self.client.list_files(q=query, page_size=limit, order_by='modifiedTime desc')
            return result.get('files', [])
        except Exception as e:
            self._handle_api_error(e, "list recent files")
            return []

    def list_starred_files(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        List starred files (high signal)
        
        Args:
            limit: Max results
            
        Returns:
            List of file metadata
        """
        query = "starred = true and trashed = false"
        
        try:
            result = self.client.list_files(q=query, page_size=limit)
            return result.get('files', [])
        except Exception as e:
            self._handle_api_error(e, "list starred files")
            return []
    
    def list_folder_contents(self, folder_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        List files inside a specific folder
        
        Args:
            folder_id: The folder ID to list contents of
            limit: Max results
            
        Returns:
            List of file metadata
        """
        query = f"'{folder_id}' in parents and trashed = false"
        
        try:
            result = self.client.list_files(q=query, page_size=limit)
            return result.get('files', [])
        except Exception as e:
            self._handle_api_error(e, "list folder contents")
            return []
            
    def get_file_content(self, file_id: str, mime_type: str) -> Optional[bytes]:
        """
        Get content of a file, handling both Google Docs (export) and Binary files (download)
        
        Args:
            file_id: File ID
            mime_type: File MIME type
            
        Returns:
            File content in bytes, or None if failure
        """
        try:
            # Google Doc types need export
            if mime_type.startswith('application/vnd.google-apps.'):
                # Map to export format based on type
                if 'spreadsheet' in mime_type:
                    # Export spreadsheets as CSV (text/plain doesn't work for spreadsheets)
                    return self.client.export_file(file_id, 'text/csv')
                elif 'document' in mime_type:
                    # Export Google Docs as PDF for better Docling parsing
                    return self.client.export_file(file_id, 'application/pdf')
                elif 'presentation' in mime_type:
                    # Export presentations as PDF
                    return self.client.export_file(file_id, 'application/pdf')
                else:
                    # Fallback for other Google apps types (drawings, etc.)
                    return self.client.export_file(file_id, 'application/pdf')
            
            else:
                # Binary download
                return self.client.get_file_content(file_id)
                
        except Exception as e:
            logger.warning(f"[DRIVE_SERVICE] Failed to get content for {file_id} ({mime_type}): {e}")
            return None

    def _is_google_doc(self, mime_type: str) -> bool:
        """Check if mime type is a Google Doc"""
        return mime_type is not None and mime_type.startswith('application/vnd.google-apps.') and 'folder' not in mime_type
