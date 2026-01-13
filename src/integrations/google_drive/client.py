"""
Google Drive Client Module

Wrapper around the Google Drive API.
"""
from typing import Optional, Dict, Any, List
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from ...utils.logger import setup_logger
from ...utils.config import Config

logger = setup_logger(__name__)

class GoogleDriveClient:
    """
    Client for interacting with Google Drive API v3
    """
    
    def __init__(self, config: Config, credentials: Optional[Credentials] = None, token_update_callback: Optional[Any] = None):
        """
        Initialize Google Drive client
        
        Args:
            config: Application configuration
            credentials: Valid Google OAuth credentials
            token_update_callback: Optional callback(credentials) to persist refreshed tokens
        """
        self.config = config
        self.service = None
        self.token_update_callback = token_update_callback
        
        if credentials:
            # Wrap credentials.refresh to trigger persistence callback on auto-refresh
            if token_update_callback:
                self._wrap_credentials_refresh(credentials)
            self.service = build('drive', 'v3', credentials=credentials)

    def _wrap_credentials_refresh(self, credentials: Credentials):
        """Monkey-patch credentials.refresh to call our callback after success"""
        original_refresh = credentials.refresh
        callback = self.token_update_callback
        
        def wrapped_refresh(request):
            logger.info("[DRIVE_CLIENT] Auto-refreshing credentials...")
            original_refresh(request)
            logger.info("[DRIVE_CLIENT] Credentials refreshed successfully. Invoking persistence callback.")
            try:
                callback(credentials)
            except Exception as e:
                logger.error(f"[DRIVE_CLIENT] Failed to persist refreshed tokens: {e}")
        
        credentials.refresh = wrapped_refresh

    def is_available(self) -> bool:
        """Check if client is authenticated and available"""
        return self.service is not None

    def list_files(
        self,
        q: Optional[str] = None,
        page_size: int = 100,
        order_by: Optional[str] = None,
        fields: str = "nextPageToken, files(id, name, mimeType, modifiedTime, modifiedByMeTime, size, webViewLink, iconLink, thumbnailLink, starred, description, owners, lastModifyingUser, parents)"
    ) -> Dict[str, Any]:
        """
        List files from Google Drive
        
        Args:
            q: Query string
            page_size: Number of files to return per page
            order_by: Sort order
            fields: Fields to include
            
        Returns:
            Dict containing 'files' list and 'nextPageToken'
        """
        if not self.is_available():
            logger.warning("[DRIVE_CLIENT] Service not available")
            return {'files': []}
            
        try:
            results = self.service.files().list(
                pageSize=page_size,
                fields=fields,
                q=q,
                orderBy=order_by,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            
            return results
            
        except Exception as e:
            logger.error(f"[DRIVE_CLIENT] Failed to list files: {e}")
            raise

    def get_file(self, file_id: str, fields: str = "*") -> Dict[str, Any]:
        """
        Get file metadata
        
        Args:
            file_id: File ID
            fields: Fields to return
            
        Returns:
            File metadata dictionary
        """
        if not self.is_available():
            raise Exception("Drive service not available")
            
        try:
            return self.service.files().get(
                fileId=file_id,
                fields=fields,
                supportsAllDrives=True
            ).execute()
        except Exception as e:
            logger.error(f"[DRIVE_CLIENT] Failed to get file {file_id}: {e}")
            raise

    def export_file(self, file_id: str, mime_type: str) -> bytes:
        """
        Export a Google Doc/Sheet/Slide to a specific MIME type
        
        Args:
            file_id: File ID
            mime_type: Target MIME type (e.g., 'application/pdf', 'text/plain')
            
        Returns:
            File content as bytes
        """
        if not self.is_available():
            raise Exception("Drive service not available")

        try:
            request = self.service.files().export_media(
                fileId=file_id,
                mimeType=mime_type
            )
            return request.execute()
        except Exception as e:
            logger.error(f"[DRIVE_CLIENT] Failed to export file {file_id}: {e}")
            raise

    def get_file_content(self, file_id: str) -> bytes:
        """
        Download binary content of a stored file (PDF, Image, etc.)
        
        Args:
            file_id: File ID
            
        Returns:
            File content as bytes
        """
        if not self.is_available():
            raise Exception("Drive service not available")

        try:
            request = self.service.files().get_media(fileId=file_id)
            return request.execute()
        except Exception as e:
            logger.error(f"[DRIVE_CLIENT] Failed to download content for {file_id}: {e}")
            raise
    def get_start_page_token(self) -> str:
        """
        Get the starting page token for future changes
        """
        if not self.is_available():
            raise Exception("Drive service not available")
            
        try:
            response = self.service.changes().getStartPageToken(
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            return response.get('startPageToken')
        except Exception as e:
            logger.error(f"[DRIVE_CLIENT] Failed to get start page token: {e}")
            raise

    def list_changes(self, page_token: str, page_size: int = 100) -> Dict[str, Any]:
        """
        List changes since the given page token
        
        Args:
            page_token: The token from get_start_page_token or previous list_changes
            page_size: limit
            
        Returns:
            Dict with 'changes', 'newStartPageToken', and 'nextPageToken'
        """
        if not self.is_available():
            raise Exception("Drive service not available")
            
        try:
            # We need to fetch 'file' resource to get properties for the changed file
            # changes(file(id, name, mimeType, modifiedTime, trashed, webViewLink))
            fields = "nextPageToken, newStartPageToken, changes(fileId, removed, file(id, name, mimeType, modifiedTime, size, webViewLink, starred, owners, trashed, parents))"
            
            return self.service.changes().list(
                pageToken=page_token,
                pageSize=page_size,
                fields=fields,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
        except Exception as e:
            logger.error(f"[DRIVE_CLIENT] Failed to list changes: {e}")
            raise
