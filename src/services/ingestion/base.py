"""
Base Ingestion Framework

Defines the contract for "Ingestors" (Crawlers) that utilize the 
KnowledgeGraphManager to synchronize external application state into the Graph.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime

from ..indexing.graph import KnowledgeGraphManager, NodeType, RelationType
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class BaseIngestor(ABC):
    """
    Abstract base class for all application ingestors (Asana, Notion, Slack, etc.).
    """
    
    def __init__(self, graph_manager: KnowledgeGraphManager, config: Any):
        self.graph = graph_manager
        self.config = config
        
    @abstractmethod
    async def fetch_delta(self, last_sync_time: Optional[datetime]) -> List[Any]:
        """
        Fetch items that have changed since the last sync.
        """
        raise NotImplementedError("Subclasses must implement fetch_delta()")
        
    @abstractmethod
    async def ingest_item(self, item: Any) -> None:
        """
        Process a single item (Task, Page, etc.) and write Nodes/Relationships to the Graph.
        """
        raise NotImplementedError("Subclasses must implement ingest_item()")
        
    async def run_sync(self, last_sync_time: Optional[datetime] = None) -> Dict[str, int]:
        """
        Main entry point. Fetches delta and ingests items.
        Returns stats (added, updated, errors).
        """
        items = await self.fetch_delta(last_sync_time)
        stats = {"processed": 0, "errors": 0}
        
        for item in items:
            try:
                await self.ingest_item(item)
                stats["processed"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.warning(f"[Ingest] Error processing item: {e}")
                
        return stats

