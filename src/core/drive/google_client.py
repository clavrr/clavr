"""
Google Drive API Client
Provides methods to interact with Google Drive API with automatic retry logic
"""
from typing import List, Dict, Any, Optional
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

from ...utils.logger import setup_logger
from ...utils.config import Config
from ..base import BaseGoogleAPIClient

logger = setup_logger(__name__)

# Constants
DEFAULT_PAGE_SIZE = 100
DEFAULT_FIELDS = "nextPageToken, files(id, name, mimeType, modifiedTime, size, webViewLink, iconLink, starred, description, owners, parents)"


class GoogleDriveClient(BaseGoogleAPIClient):
    """
    Google Drive API client
    
    Provides methods to interact with Google Drive:
    - List files
    - Search files
    - Get file metadata
    - Export Google Docs/Sheets/Slides
    - Download file content
    - Track changes
    
    Inherits retry logic and credential management from BaseGoogleAPIClient.
    """
    
    def _build_service(self) -> Any:
        """Build Google Drive API service"""
        return build('drive', 'v3', credentials=self.credentials)
    
    def _get_required_scopes(self) -> List[str]:
        """Get required Google Drive scopes"""
        return ['https://www.googleapis.com/auth/drive.readonly']
    
    def _get_service_name(self) -> str:
        """Get service name"""
        return "Google Drive"
    
    # =========================================================================
    # File Listing
    # =========================================================================
    
    def list_files(
        self,
        q: Optional[str] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        order_by: Optional[str] = None,
        fields: str = DEFAULT_FIELDS,
        include_shared_drives: bool = True
    ) -> Dict[str, Any]:
        """
        List files from Google Drive
        
        Args:
            q: Query string (Drive search syntax)
            page_size: Number of files to return per page
            order_by: Sort order (e.g., 'modifiedTime desc', 'name')
            fields: Fields to include in response
            include_shared_drives: Include items from shared drives
            
        Returns:
            Dict containing 'files' list and 'nextPageToken'
        """
        if not self.is_available():
            logger.warning("[GoogleDriveClient] Service not available")
            return {'files': []}
        
        try:
            request_params = {
                'pageSize': page_size,
                'fields': fields,
                'supportsAllDrives': include_shared_drives,
                'includeItemsFromAllDrives': include_shared_drives
            }
            
            if q:
                request_params['q'] = q
            if order_by:
                request_params['orderBy'] = order_by
            
            results = self.service.files().list(**request_params).execute()
            
            logger.debug(f"[GoogleDriveClient] Listed {len(results.get('files', []))} files")
            return results
            
        except Exception as e:
            logger.error(f"[GoogleDriveClient] Failed to list files: {e}")
            return {'files': []}
    
    def search_files(
        self,
        query: str,
        file_type: Optional[str] = None,
        max_results: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Search files in Google Drive
        
        Args:
            query: Search query
            file_type: Optional file type filter ('document', 'spreadsheet', 'presentation', 'pdf')
            max_results: Maximum results to return
            
        Returns:
            List of matching files
        """
        # Build Drive query
        q_parts = [f"fullText contains '{query}'", "trashed = false"]
        
        # Add file type filter
        if file_type:
            mime_type_map = {
                'document': 'application/vnd.google-apps.document',
                'spreadsheet': 'application/vnd.google-apps.spreadsheet',
                'presentation': 'application/vnd.google-apps.presentation',
                'pdf': 'application/pdf',
                'folder': 'application/vnd.google-apps.folder'
            }
            if file_type.lower() in mime_type_map:
                q_parts.append(f"mimeType = '{mime_type_map[file_type.lower()]}'")
        
        q = ' and '.join(q_parts)
        
        result = self.list_files(q=q, page_size=max_results, order_by='modifiedTime desc')
        return result.get('files', [])
    
    def list_recent_files(self, days: int = 7, max_results: int = 20) -> List[Dict[str, Any]]:
        """
        List recently modified files
        
        Args:
            days: Number of days to look back
            max_results: Maximum results
            
        Returns:
            List of recently modified files
        """
        from datetime import datetime, timedelta
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        cutoff_str = cutoff.strftime('%Y-%m-%dT%H:%M:%S')
        
        q = f"modifiedTime > '{cutoff_str}' and trashed = false"
        
        result = self.list_files(q=q, page_size=max_results, order_by='modifiedTime desc')
        return result.get('files', [])
    
    # =========================================================================
    # File Operations
    # =========================================================================
    
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
            logger.error(f"[GoogleDriveClient] Failed to get file {file_id}: {e}")
            raise
    
    def export_file(self, file_id: str, mime_type: str = 'text/plain') -> bytes:
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
            logger.error(f"[GoogleDriveClient] Failed to export file {file_id}: {e}")
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
            
            # Use streaming download for large files
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    logger.debug(f"[GoogleDriveClient] Download progress: {int(status.progress() * 100)}%")
            
            return fh.getvalue()
        except Exception as e:
            logger.error(f"[GoogleDriveClient] Failed to download content for {file_id}: {e}")
            raise
    
    # =========================================================================
    # Change Tracking
    # =========================================================================
    
    def get_start_page_token(self) -> str:
        """
        Get the starting page token for future changes
        
        Returns:
            Start page token for change tracking
        """
        if not self.is_available():
            raise Exception("Drive service not available")
        
        try:
            response = self.service.changes().getStartPageToken(
                supportsAllDrives=True
            ).execute()
            return response.get('startPageToken')
        except Exception as e:
            logger.error(f"[GoogleDriveClient] Failed to get start page token: {e}")
            raise
    
    def list_changes(self, page_token: str, page_size: int = 100) -> Dict[str, Any]:
        """
        List changes since the given page token
        
        Args:
            page_token: The token from get_start_page_token or previous list_changes
            page_size: Maximum changes to return
            
        Returns:
            Dict with 'changes', 'newStartPageToken', and 'nextPageToken'
        """
        if not self.is_available():
            raise Exception("Drive service not available")
        
        try:
            fields = "nextPageToken, newStartPageToken, changes(fileId, removed, file(id, name, mimeType, modifiedTime, size, webViewLink, starred, owners, trashed, parents))"
            
            return self.service.changes().list(
                pageToken=page_token,
                pageSize=page_size,
                fields=fields,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
        except Exception as e:
            logger.error(f"[GoogleDriveClient] Failed to list changes: {e}")
            raise
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def get_starred_files(self, max_results: int = 50) -> List[Dict[str, Any]]:
        """
        Get starred/favorite files
        
        Args:
            max_results: Maximum results
            
        Returns:
            List of starred files
        """
        q = "starred = true and trashed = false"
        result = self.list_files(q=q, page_size=max_results)
        return result.get('files', [])
    
    def get_service_info(self) -> dict:
        """Get drive service info including storage quota"""
        info = super().get_service_info()
        
        if self.is_available():
            try:
                about = self.service.about().get(fields="storageQuota, user").execute()
                quota = about.get('storageQuota', {})
                info['storage'] = {
                    'limit': int(quota.get('limit', 0)),
                    'usage': int(quota.get('usage', 0)),
                    'usage_in_drive': int(quota.get('usageInDrive', 0)),
                    'usage_in_trash': int(quota.get('usageInDriveTrash', 0))
                }
                info['user'] = about.get('user', {}).get('emailAddress')
            except Exception as e:
                logger.debug(f"[GoogleDriveClient] Could not fetch about info: {e}")
        
        return info
