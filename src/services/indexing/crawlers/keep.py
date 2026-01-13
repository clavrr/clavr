"""
Google Keep Crawler

Background indexer that crawls Google Keep notes for the knowledge graph.
Creates Document nodes for notes and extracts topics from content.

Note: Google Keep API requires Google Workspace Enterprise.

Features:
- Indexes Keep notes as Document nodes
- Supports both text notes and checklists
- Links to TimeBlocks for temporal queries
- Extracts topics from note content
"""
from typing import List, Any, Optional, Dict
from datetime import datetime, timedelta
import asyncio

from src.services.indexing.base_indexer import BaseIndexer
from src.services.indexing.parsers.base import ParsedNode
from src.services.indexing.graph.schema import NodeType
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class KeepCrawler(BaseIndexer):
    """
    Crawler that periodically indexes Google Keep notes.
    
    Processes:
    - Text notes
    - Checklist notes
    """
    
    def __init__(
        self,
        config,
        user_id: int,
        keep_service=None,
        **kwargs
    ):
        """
        Initialize Keep crawler.
        
        Args:
            config: Application configuration
            user_id: User ID to index for
            keep_service: KeepService instance
        """
        super().__init__(config, user_id, **kwargs)
        self.keep_service = keep_service
        self.last_sync_time = datetime.now() - timedelta(days=ServiceConstants.INITIAL_LOOKBACK_DAYS_NOTES)  # Notes need longer lookback
        self._note_cache = {}  # Track indexed notes
        
        # Keep-specific settings from ServiceConstants
        from src.services.service_constants import ServiceConstants
        self.sync_interval = ServiceConstants.KEEP_SYNC_INTERVAL
    
    @property
    def name(self) -> str:
        return "google_keep"
    
    async def fetch_delta(self) -> List[Any]:
        """
        Fetch Google Keep notes.
        """
        if not self.keep_service:
            logger.warning("[KeepCrawler] No Keep service available, skipping sync")
            return []
        
        new_items = []
        
        try:
            # Fetch all notes (Keep doesn't have great filtering)
            notes = await asyncio.to_thread(
                self.keep_service.list_notes,
                limit=200
            )
            
            for note in notes:
                note_id = note.get('name') or note.get('id')
                updated = note.get('update_time') or note.get('create_time')
                
                # Check if note is new or updated
                if note_id not in self._note_cache or self._note_cache.get(note_id) != updated:
                    new_items.append(note)
                    self._note_cache[note_id] = updated
            
            logger.info(f"[KeepCrawler] Found {len(new_items)} notes to index")
            return new_items
            
        except Exception as e:
            logger.error(f"[KeepCrawler] Fetch delta failed: {e}")
            return []
    
    async def transform_item(self, item: Any) -> Optional[List[ParsedNode]]:
        """
        Transform a Google Keep note into a graph node.
        """
        try:
            note_id = item.get('name') or item.get('id')
            if not note_id:
                return None
            
            # Extract note properties
            title = item.get('title', '')
            body = item.get('body', {})
            
            # Handle different note types
            if 'text' in body:
                # Text note
                content = body.get('text', {}).get('text', '')
            elif 'list' in body:
                # Checklist note
                list_items = body.get('list', {}).get('list_items', [])
                content_parts = []
                for list_item in list_items:
                    text = list_item.get('text', {}).get('text', '')
                    checked = list_item.get('checked', False)
                    status = '☑' if checked else '☐'
                    content_parts.append(f"{status} {text}")
                content = '\n'.join(content_parts)
            else:
                content = ''
            
            # Build searchable text
            searchable_text = f"{title} {content}".strip()
            
            if not searchable_text or len(searchable_text) < 5:
                return None
            
            # Extract timestamps
            create_time = item.get('create_time')
            update_time = item.get('update_time')
            
            # Clean note ID for node ID
            clean_id = note_id.replace('/', '_').replace('-', '_')
            node_id = f"keep_note_{clean_id}"
            
            note_node = ParsedNode(
                node_id=node_id,
                node_type=NodeType.DOCUMENT,
                properties={
                    'title': title or 'Untitled Note',
                    'filename': title or 'Untitled Note',  # Required for Document type
                    'content': content[:5000] if content else '',
                    'google_keep_id': note_id,
                    'source': 'google_keep',
                    'user_id': self.user_id,
                    'timestamp': update_time or create_time,
                    'created_at': create_time,
                    'updated_at': update_time,
                    'doc_type': 'keep_note',
                    'is_checklist': 'list' in (item.get('body') or {}),
                    'is_pinned': item.get('is_pinned', False),
                    'is_archived': item.get('is_trashed', False),
                },
                searchable_text=searchable_text[:10000],
                relationships=[]
            )
            
            return [note_node]
            
        except Exception as e:
            logger.warning(f"[KeepCrawler] Transform failed for note: {e}")
            return None
