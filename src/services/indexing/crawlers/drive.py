"""
Google Drive Crawler

Indexes files from Google Drive into the Memory Graph.
Focuses on "Starred" and "Recent" files to provide high-signal context.
"""
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
import asyncio

from src.services.indexing.base_indexer import BaseIndexer
from src.services.indexing.parsers.base import ParsedNode
from src.integrations.google_drive.service import GoogleDriveService
from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.schema import NodeType, RelationType
from pathlib import Path
import tempfile
import os

logger = setup_logger(__name__)

# Import Docling components (optional)
try:
    from docling.document_converter import DocumentConverter
    from docling.datamodel.base_models import InputFormat
    DOCLING_AVAILABLE = True
except ImportError:
    DocumentConverter = None
    InputFormat = None
    DOCLING_AVAILABLE = False
    logger.warning("Docling not available. Pdf/Office parsing will be skipped.")

class DriveCrawler(BaseIndexer):
    """
    Crawler for Google Drive files.
    
    Strategy:
    1. Fetch Starred files (High importance)
    2. Fetch Recent files (Last 30 days)
    3. Convert to Document nodes (using Docling for complex formats)
    """
    
    def __init__(
        self,
        config: Config,
        user_id: int,
        rag_engine: Any,
        graph_manager: Any,
        drive_service: GoogleDriveService,
        topic_extractor: Any = None,
        temporal_indexer: Any = None,
        relationship_manager: Any = None,
        entity_resolver: Any = None,
        observer_service: Any = None
    ):
        super().__init__(
            config=config,
            user_id=user_id,
            rag_engine=rag_engine,
            graph_manager=graph_manager,
            topic_extractor=topic_extractor,
            temporal_indexer=temporal_indexer,
            relationship_manager=relationship_manager,
            entity_resolver=entity_resolver,
            observer_service=observer_service
        )
        self.drive_service = drive_service
        
        # Drive-specific settings from ServiceConstants
        from src.services.service_constants import ServiceConstants
        self.sync_interval = ServiceConstants.DRIVE_SYNC_INTERVAL
        self._name = "google_drive"
        
        # Initialize Docling
        if DOCLING_AVAILABLE:
            try:
                self.converter = DocumentConverter()
                logger.info("[DriveCrawler] Docling converter initialized")
            except Exception as e:
                logger.warning(f"[DriveCrawler] Failed to init Docling: {e}")
                self.converter = None
        else:
            self.converter = None

        self.sync_token = None

    @property
    def name(self) -> str:
        return self._name

    async def fetch_delta(self) -> List[Any]:
        """
        Fetch files to process.
        Uses incremental sync (changes API) if token is available.
        Otherwise performs full sync (Starred + Recent) and gets token.
        """
        try:
            logger.info(f"[DriveCrawler] Fetching files for user {self.user_id}")
            
            all_files = []
            
            # Incremental Sync
            if self.sync_token:
                logger.info(f"[DriveCrawler] Using sync token: {self.sync_token}")
                changes_data = self.drive_service.fetch_changes(self.sync_token)
                
                # Get new token
                new_token = changes_data.get('newStartPageToken') or changes_data.get('nextPageToken')
                if new_token:
                    self.sync_token = new_token
                
                # Process changes
                changes = changes_data.get('changes', [])
                for change in changes:
                    file_data = change.get('file')
                    removed = change.get('removed', False)
                    file_id = change.get('fileId')
                    
                    if not removed and file_data:
                        # Ensure ID is present (sometimes 'file' dict might miss it if 'fileId' is at top level)
                        if 'id' not in file_data:
                            file_data['id'] = file_id
                        all_files.append(file_data)
                    elif removed:
                        logger.info(f"[DriveCrawler] File removed: {file_id} (handling deletion not implemented yet)")
                        
                logger.info(f"[DriveCrawler] Found {len(all_files)} changes")
                
            else:
                # Full Sync (First Run)
                logger.info("[DriveCrawler] Performing full sync (Starred + Recent + Folders)")
                
                # 1. Get Token for specific future changes
                self.sync_token = self.drive_service.get_sync_token()
                logger.info(f"[DriveCrawler] Initialized sync token: {self.sync_token}")
                
                # 2. Fetch High Signal Files
                starred_files = self.drive_service.list_starred_files(limit=100)
                recent_files = self.drive_service.list_recent_files(days=30, limit=100)
                
                # Deduplicate by ID
                all_files_map = {f['id']: f for f in starred_files + recent_files}
                
                # 3. Expand folders - recursively fetch files inside folders (2 levels deep)
                folders_to_expand = [
                    f for f in all_files_map.values() 
                    if f.get('mimeType') == 'application/vnd.google-apps.folder'
                ]
                
                for folder in folders_to_expand:
                    folder_id = folder['id']
                    folder_name = folder.get('name', 'Unknown Folder')
                    logger.info(f"[DriveCrawler] Expanding folder: {folder_name}")
                    
                    try:
                        # List files inside this folder
                        folder_contents = self.drive_service.list_folder_contents(folder_id, limit=50)
                        for file_data in folder_contents:
                            if file_data['id'] not in all_files_map:
                                all_files_map[file_data['id']] = file_data
                                
                                # Level 2 - expand subfolders
                                if file_data.get('mimeType') == 'application/vnd.google-apps.folder':
                                    subfolder_contents = self.drive_service.list_folder_contents(file_data['id'], limit=30)
                                    for subfile in subfolder_contents:
                                        if subfile['id'] not in all_files_map:
                                            all_files_map[subfile['id']] = subfile
                    except Exception as e:
                        logger.warning(f"[DriveCrawler] Failed to expand folder {folder_name}: {e}")
                
                all_files = list(all_files_map.values())
                
                logger.info(f"[DriveCrawler] Found {len(all_files)} total files (incl. folder contents)")

            return all_files
            
        except Exception as e:
            logger.error(f"[DriveCrawler] Failed to fetch files: {e}")
            # If token invalid, reset it
            if "StartPageToken" in str(e) or "Invalid" in str(e):
                self.sync_token = None
            return []

    async def transform_item(self, item: Dict[str, Any]) -> Optional[ParsedNode]:
        """
        Convert Drive file dict to ParsedNode.
        
        Enhanced to capture:
        - Owner information (for OWNER_OF edges)
        - Parent folder (for STORED_IN edges)
        - Shared status
        """
        try:
            file_id = item['id']
            name = item.get('name', 'Untitled')
            mime_type = item.get('mimeType', '')
            
            # Extract owner info from API response
            owners = item.get('owners', [])
            owner_email = owners[0].get('emailAddress') if owners else None
            owner_name = owners[0].get('displayName') if owners else None
            
            # Extract parent folder info
            parents = item.get('parents', [])
            parent_folder_id = parents[0] if parents else None
            
            # Handle folders - create Folder nodes instead of skipping
            if mime_type == 'application/vnd.google-apps.folder':
                return self._create_folder_node(item, owner_email, parent_folder_id)
            
            # Binary files (images, videos, audio) - index metadata only, no content download
            binary_mime_prefixes = ['image/', 'video/', 'audio/']
            binary_extensions = ['.cr2', '.raw', '.nef', '.arw', '.dng', '.mp4', '.mov', '.avi', '.mp3', '.wav']
            is_binary = (
                any(mime_type.startswith(prefix) for prefix in binary_mime_prefixes) or
                any(name.lower().endswith(ext) for ext in binary_extensions)
            )
            
            if is_binary:
                # For binary files, just index the filename as searchable content
                content_text = f"File: {name}"
                properties = {
                    "filename": name,
                    "content": content_text,
                    "doc_type": mime_type,
                    "file_size": int(item.get('size', 0)) if item.get('size') else 0,
                    "created_at": item.get('createdTime', '').replace('Z', '+00:00') if item.get('createdTime') else None,
                    "updated_at": item.get('modifiedTime'),
                    "docling_metadata": {"source": "google_drive", "mime_type": mime_type, "binary": True},
                    "timestamp": item.get('modifiedTime'),
                    "web_link": item.get('webViewLink'),
                    # NEW: Owner and folder metadata
                    "owner_email": owner_email,
                    "owners": [o.get('emailAddress') for o in owners],
                    "parent_folder_id": parent_folder_id,
                }
                
                node = ParsedNode(
                    node_id=f"drive_{file_id}",
                    node_type=NodeType.DOCUMENT,
                    properties=properties,
                    searchable_text=content_text
                )
                
                # Schedule relationship creation after node is indexed
                node._pending_relationships = self._build_pending_relationships(
                    file_id, owner_email, owner_name, parent_folder_id
                )
                
                return node

            # 1. Get Content for non-binary files
            content_bytes = self.drive_service.get_file_content(file_id, mime_type)
            if not content_bytes:
                # Some files might be 0 bytes or skipped (e.g. apps scripts)
                if not self.drive_service._is_google_doc(mime_type): # Check if it's not a G-Doc which export might fix
                     logger.debug(f"[DriveCrawler] No content for {name} ({file_id})")
                return None
            
            content_text = ""
            docling_metadata = {"source": "google_drive", "mime_type": mime_type}
            
            # 2. Extract with Docling if supported and available
            if self.converter and self._is_docling_supported(mime_type, name):
                try:
                    logger.debug(f"[DriveCrawler] Processing {name} with Docling")
                    extracted = await self._extract_with_docling(content_bytes, name)
                    content_text = extracted.get('text', '')
                    if extracted.get('metadata'):
                        docling_metadata.update(extracted['metadata'])
                except Exception as e:
                    logger.warning(f"[DriveCrawler] Docling failed for {name}: {e}. Fallback to text.")
                    content_text = self._fallback_text_decode(content_bytes)
            else:
                # Fallback to simple extract
                content_text = self._fallback_text_decode(content_bytes)
            
            if not content_text:
                return None
                
            # 3. Create ParsedNode
            # Drive API timestamps are like '2023-12-01T10:00:00.000Z'
            created_at = item.get('createdTime')
            if created_at:
                 created_at = created_at.replace('Z', '+00:00')

            # Limit content stored in payload to 100KB to avoid Qdrant payload limits
            # Full content is still used for searchable_text (embeddings)
            MAX_PAYLOAD_CONTENT = 100000  # 100KB limit for stored content
            stored_content = content_text[:MAX_PAYLOAD_CONTENT] if len(content_text) > MAX_PAYLOAD_CONTENT else content_text
            
            properties = {
                "filename": name,
                "content": stored_content,  # Limited for payload storage
                "doc_type": mime_type,
                "file_size": int(item.get('size', 0)) if item.get('size') else len(content_bytes),
                "created_at": created_at,
                "updated_at": item.get('modifiedTime'),
                "docling_metadata": docling_metadata,
                # For temporal linking
                "timestamp": item.get('modifiedTime'),
                "web_link": item.get('webViewLink'),
                # NEW: Owner and folder metadata for graph edges
                "owner_email": owner_email,
                "owners": [o.get('emailAddress') for o in owners],
                "parent_folder_id": parent_folder_id,
            }
            
            node = ParsedNode(
                node_id=f"drive_{file_id}",
                node_type=NodeType.DOCUMENT,
                properties=properties,
                searchable_text=content_text  # Full content for embeddings
            )
            
            # Schedule relationship creation after node is indexed
            node._pending_relationships = self._build_pending_relationships(
                file_id, owner_email, owner_name, parent_folder_id
            )
            
            return node
            
        except Exception as e:
            logger.error(f"[DriveCrawler] Transformation failed for {item.get('id')}: {e}")
            return None

    def _create_folder_node(self, item: Dict[str, Any], owner_email: Optional[str], parent_folder_id: Optional[str]) -> ParsedNode:
        """Create a Folder node for Drive folder hierarchy."""
        folder_id = item['id']
        name = item.get('name', 'Untitled Folder')
        
        properties = {
            "name": name,
            "folder_id": folder_id,
            "parent_folder_id": parent_folder_id,
            "web_link": item.get('webViewLink'),
            "owner_email": owner_email,
            "created_at": item.get('createdTime', '').replace('Z', '+00:00') if item.get('createdTime') else None,
            "updated_at": item.get('modifiedTime'),
        }
        
        node = ParsedNode(
            node_id=f"folder_{folder_id}",
            node_type=NodeType.FOLDER,
            properties=properties,
            searchable_text=f"Folder: {name}"  # Minimal searchable text for folders
        )
        
        # Schedule STORED_IN relationship if folder has parent
        if parent_folder_id:
            node._pending_relationships = [
                {
                    "from_id": f"folder_{folder_id}",
                    "to_id": f"folder_{parent_folder_id}",
                    "rel_type": RelationType.STORED_IN,
                    "properties": {"source": "google_drive"}
                }
            ]
        
        return node

    def _build_pending_relationships(
        self, 
        file_id: str, 
        owner_email: Optional[str], 
        owner_name: Optional[str],
        parent_folder_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """
        Build a list of relationships to create after the node is indexed.
        
        This enables:
        - Person -[OWNER_OF]-> Document
        - Document -[STORED_IN]-> Folder
        """
        relationships = []
        
        # STORED_IN relationship (Document -> Folder)
        if parent_folder_id:
            relationships.append({
                "from_id": f"drive_{file_id}",
                "to_id": f"folder_{parent_folder_id}",
                "rel_type": RelationType.STORED_IN,
                "properties": {"source": "google_drive"}
            })
        
        # OWNER_OF relationship (Person -> Document)
        # We need a stable Person node ID based on email
        if owner_email:
            from src.services.indexing.node_id_utils import generate_person_id
            person_node_id = generate_person_id(email=owner_email)
            relationships.append({
                "from_id": person_node_id,
                "to_id": f"drive_{file_id}",
                "rel_type": RelationType.OWNER_OF,
                "properties": {"source": "google_drive"},
                # Include Person node data for creation if needed
                "_create_from_node": {
                    "node_id": person_node_id,
                    "node_type": NodeType.PERSON,
                    "properties": {
                        "name": owner_name or owner_email.split('@')[0],
                        "email": owner_email,
                        "user_id": self.user_id
                    }
                }
            })
        
        return relationships

    def _is_docling_supported(self, mime_type: str, filename: str) -> bool:
        """Check if file type is supported by Docling"""
        supported_mimes = [
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document', # docx
            'application/vnd.openxmlformats-officedocument.presentationml.presentation', # pptx
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' # xlsx
        ]
        supported_exts = ['.pdf', '.docx', '.pptx', '.xlsx', '.md', '.html']
        
        if mime_type in supported_mimes:
            return True
        return any(filename.lower().endswith(ext) for ext in supported_exts)

    def _fallback_text_decode(self, content_bytes: bytes) -> str:
        """Simple fallback decoding"""
        try:
            return content_bytes.decode('utf-8', errors='ignore')
        except Exception as e:
            logger.debug(f"Fallback text decode failed: {e}")
            return "[Binary Content]"

    async def _extract_with_docling(self, data: bytes, filename: str) -> Dict[str, Any]:
        """Extract content using Docling via temp file"""
        # Run in thread executor to avoid blocking asyncio loop (Docling is CPU bound)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._docling_sync_process, data, filename)

    def _docling_sync_process(self, data: bytes, filename: str) -> Dict[str, Any]:
        """Synchronous Docling processing (to be run in executor)"""
        temp_path = None
        try:
            # Create temporary file with appropriate extension
            # Docling relies on extension to detect format
            ext = Path(filename).suffix or '.pdf' # Default to PDF if unknown?
            if not ext:
                 ext = '.tmp'
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
                temp_file.write(data)
                temp_path = temp_file.name
            
            # Convert
            result = self.converter.convert(temp_path, raises_on_error=False)
            
            # Extract
            text = result.document.export_to_markdown()
            metadata = {
                'title': getattr(result.document, 'title', ''),
                'num_pages': getattr(result.document, 'num_pages', 0)
            }
            
            return {'text': text, 'metadata': metadata}
            
        except Exception as e:
            logger.error(f"Docling internal error for {filename}: {e}")
            raise e
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception as e:
                    logger.debug(f"Failed to cleanup temp file {temp_path}: {e}")
