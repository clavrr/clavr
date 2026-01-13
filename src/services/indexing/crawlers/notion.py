"""
Notion Crawler

Background indexer that crawls Notion pages and databases for the knowledge graph.
Extracts content, links to topics, and creates temporal relationships.

Features:
- Indexes Notion pages as Document nodes
- Extracts page content (blocks) for searchability
- Links to TimeBlocks for temporal queries
- Extracts topics from page content
- Tracks relationship strengths
"""
from typing import List, Any, Optional, Dict
from datetime import datetime, timedelta
import asyncio

from src.services.indexing.base_indexer import BaseIndexer
from src.services.indexing.parsers.base import ParsedNode, Relationship
from src.services.indexing.graph.schema import NodeType, RelationType
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class NotionCrawler(BaseIndexer):
    """
    Crawler that periodically indexes Notion pages.
    
    Processes:
    - Pages from specified databases
    - Page content (converted to text for indexing)
    - Page properties (title, dates, people mentions)
    """
    
    def __init__(
        self,
        config,
        user_id: int,
        notion_client=None,
        database_ids: Optional[List[str]] = None,
        **kwargs
    ):
        """
        Initialize Notion crawler.
        
        Args:
            config: Application configuration
            user_id: User ID to index for
            notion_client: NotionClient instance
            database_ids: Optional list of database IDs to crawl
        """
        super().__init__(config, user_id, **kwargs)
        self.notion_client = notion_client
        self.database_ids = database_ids or []
        self.last_sync_time = datetime.now() - timedelta(days=7)  # 7 day lookback on first run
        self._page_cache = {}  # Cache page IDs to avoid re-indexing
        
        # Notion-specific settings from ServiceConstants
        from src.services.service_constants import ServiceConstants
        self.sync_interval = ServiceConstants.NOTION_SYNC_INTERVAL
    
    @property
    def name(self) -> str:
        return "notion"
    
    async def fetch_delta(self) -> List[Any]:
        """
        Fetch Notion pages that have changed since last sync.
        """
        if not self.notion_client:
            logger.warning("[NotionCrawler] No Notion client available, skipping sync")
            return []
        
        new_items = []
        
        try:
            # Method 1: If database IDs are specified, query those databases
            if self.database_ids:
                for db_id in self.database_ids:
                    try:
                        # Query database for pages modified since last sync
                        # Note: Notion API doesn't support direct "last_edited_time > X" filter
                        # So we fetch recent pages and filter locally
                        response = await asyncio.to_thread(
                            self.notion_client.query_database,
                            db_id,
                            None,  # No filter - get all
                            [{"property": "Last edited time", "direction": "descending"}]
                        )
                        
                        pages = response.get('results', [])
                        logger.debug(f"[NotionCrawler] Found {len(pages)} pages in database {db_id}")
                        
                        for page in pages:
                            # Check if modified since last sync
                            last_edited = page.get('last_edited_time')
                            if last_edited:
                                edited_dt = datetime.fromisoformat(last_edited.replace('Z', '+00:00'))
                                if edited_dt.replace(tzinfo=None) > self.last_sync_time:
                                    page['_database_id'] = db_id
                                    new_items.append(page)
                                else:
                                    # Pages are sorted by last_edited desc, so stop if we hit old ones
                                    break
                                    
                    except Exception as e:
                        logger.warning(f"[NotionCrawler] Failed to query database {db_id}: {e}")
                        
            # Method 2: Use search API to find recently modified pages
            else:
                try:
                    results = await asyncio.to_thread(
                        self.notion_client.search,
                        "",  # Empty query returns all
                        "page"  # Filter to pages only
                    )
                    
                    for page in results:
                        last_edited = page.get('last_edited_time')
                        if last_edited:
                            edited_dt = datetime.fromisoformat(last_edited.replace('Z', '+00:00'))
                            if edited_dt.replace(tzinfo=None) > self.last_sync_time:
                                new_items.append(page)
                                
                except Exception as e:
                    logger.warning(f"[NotionCrawler] Search failed: {e}")
            
            # Update last sync time
            self.last_sync_time = datetime.now()
            
            logger.info(f"[NotionCrawler] Found {len(new_items)} updated pages to index")
            return new_items
            
        except Exception as e:
            logger.error(f"[NotionCrawler] Fetch delta failed: {e}")
            return []
    
    async def transform_item(self, item: Any) -> Optional[List[ParsedNode]]:
        """
        Transform a Notion page into graph nodes.
        """
        try:
            nodes = []
            
            page_id = item.get('id')
            if not page_id:
                return None
            
            # Skip if already processed recently
            if page_id in self._page_cache:
                return None
            self._page_cache[page_id] = True
            
            # Extract page properties
            properties = item.get('properties', {})
            
            # Get title from Name or Title property
            title = self._extract_title(properties)
            
            # Get page content (blocks)
            content = await self._get_page_content(page_id)
            
            # Extract timestamp
            last_edited = item.get('last_edited_time')
            created_time = item.get('created_time')
            
            # Build searchable text
            searchable_text = f"{title} {content}".strip()
            
            if not searchable_text or len(searchable_text) < 10:
                return None
            
            # Create Document node for page
            node_id = f"notion_page_{page_id.replace('-', '_')}"
            
            page_node = ParsedNode(
                node_id=node_id,
                node_type=NodeType.DOCUMENT,
                properties={
                    'title': title or 'Untitled',
                    'filename': title or 'Untitled',  # Required for Document type
                    'content': content[:5000] if content else '',  # Truncate for storage
                    'notion_page_id': page_id,
                    'notion_database_id': item.get('_database_id'),
                    'source': 'notion',
                    'user_id': self.user_id,
                    'timestamp': last_edited,
                    'created_at': created_time,
                    'url': item.get('url'),
                    'doc_type': 'notion_page',
                },
                searchable_text=searchable_text[:10000],  # Limit searchable text
                relationships=[]
            )
            
            nodes.append(page_node)
            
            # Extract and create Person nodes from page mentions/assignments
            people_rels = await self._extract_people_relationships(properties, node_id)
            if people_rels:
                for person_node, rel in people_rels:
                    if person_node:
                        nodes.append(person_node)
                    page_node.relationships.append(rel)
            
            return nodes
            
        except Exception as e:
            logger.warning(f"[NotionCrawler] Transform failed for page: {e}")
            return None
    
    def _extract_title(self, properties: Dict[str, Any]) -> Optional[str]:
        """Extract title from Notion page properties."""
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
        
        return None
    
    async def _get_page_content(self, page_id: str) -> str:
        """Get page content by fetching blocks."""
        if not self.notion_client:
            return ""
        
        try:
            blocks = await asyncio.to_thread(
                self.notion_client.get_block_children,
                page_id
            )
            
            # Extract text from blocks
            content_parts = []
            for block in blocks:
                text = self._extract_block_text(block)
                if text:
                    content_parts.append(text)
            
            return ' '.join(content_parts)
            
        except Exception as e:
            logger.debug(f"[NotionCrawler] Failed to get page content: {e}")
            return ""
    
    def _extract_block_text(self, block: Dict[str, Any]) -> str:
        """Extract text from a Notion block."""
        block_type = block.get('type')
        if not block_type:
            return ""
        
        # Get the block data for this type
        block_data = block.get(block_type, {})
        
        # Common text-bearing structures
        text_types = ['rich_text', 'text', 'caption']
        
        for text_type in text_types:
            rich_text = block_data.get(text_type, [])
            if rich_text:
                return ' '.join([t.get('plain_text', '') for t in rich_text])
        
        # Handle special block types
        if block_type == 'code':
            return block_data.get('text', '')
        elif block_type in ['bulleted_list_item', 'numbered_list_item', 'to_do']:
            rich_text = block_data.get('rich_text', [])
            return ' '.join([t.get('plain_text', '') for t in rich_text])
        elif block_type == 'child_page':
            return block_data.get('title', '')
        
        return ""
    
    async def _extract_people_relationships(
        self,
        properties: Dict[str, Any],
        page_node_id: str
    ) -> List[tuple]:
        """Extract people from page properties and create relationships."""
        results = []
        
        for prop_name, prop_value in properties.items():
            if not isinstance(prop_value, dict):
                continue
            
            prop_type = prop_value.get('type')
            
            # Handle people type properties (assignees, etc.)
            if prop_type == 'people':
                people = prop_value.get('people', [])
                for person in people:
                    person_id = person.get('id')
                    person_name = person.get('name', 'Unknown')
                    person_email = person.get('person', {}).get('email')
                    
                    if not person_id:
                        continue
                    
                    # Use email-based ID if available for cross-source merging
                    from src.services.indexing.node_id_utils import generate_person_id
                    if person_email:
                        person_node_id = generate_person_id(email=person_email)
                    else:
                        person_node_id = generate_person_id(source='notion', source_id=person_id)
                    
                    # Create Person node
                    person_node = ParsedNode(
                        node_id=person_node_id,
                        node_type=NodeType.PERSON,
                        properties={
                            'name': person_name,
                            'notion_user_id': person_id,
                            'source': 'notion',
                            'email': person_email,
                        },
                        searchable_text=person_name
                    )
                    
                    # Determine relationship type based on property name
                    rel_type = RelationType.MENTIONS
                    if 'assign' in prop_name.lower():
                        rel_type = RelationType.ASSIGNED_TO
                    elif 'created' in prop_name.lower() or 'author' in prop_name.lower():
                        rel_type = RelationType.CREATED_BY
                    
                    # Create relationship
                    rel = Relationship(
                        from_node=page_node_id,
                        to_node=person_node_id,
                        rel_type=rel_type
                    )
                    
                    results.append((person_node, rel))
        
        return results
    
    def add_database(self, database_id: str) -> None:
        """Add a database to the crawl list."""
        if database_id not in self.database_ids:
            self.database_ids.append(database_id)
            logger.info(f"[NotionCrawler] Added database {database_id} to crawl list")
    
    def remove_database(self, database_id: str) -> None:
        """Remove a database from the crawl list."""
        if database_id in self.database_ids:
            self.database_ids.remove(database_id)
            logger.info(f"[NotionCrawler] Removed database {database_id} from crawl list")
