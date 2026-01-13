"""
Unified Search Service - Coordinator for cross-platform data retrieval
"""
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime

from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)

class UnifiedSearchService:
    """
    Coordinates searches across Email, Drive, and Knowledge Graph.
    This enables "Deep Search" for historical and financial context.
    """
    
    def __init__(self, config: Config, email_service=None, drive_service=None, graph_manager=None, user_id: int = 1):
        self.config = config
        self.email_service = email_service
        self.drive_service = drive_service
        self.graph_manager = graph_manager
        self.user_id = user_id

    async def deep_search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Run parallel searches across all available platforms and merge results.
        """
        logger.info(f"[UnifiedSearch] Starting deep search for: '{query}'")
        
        tasks = []
        
        # 1. Graph Search (Structured Data / Receipts / Entities)
        if self.graph_manager:
            tasks.append(self._search_graph(query, limit))
            
        # 2. Email Search
        if self.email_service:
            tasks.append(self._search_email(query, limit))
            
        # 3. Drive Search
        if self.drive_service:
            tasks.append(self._search_drive(query, limit))
            
        if not tasks:
            logger.warning("[UnifiedSearch] No search platforms available")
            return []
            
        # Execute in parallel
        results_nested = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Flatten and deduplicate
        merged_results = []
        for res in results_nested:
            if isinstance(res, list):
                merged_results.extend(res)
            elif isinstance(res, Exception):
                logger.error(f"[UnifiedSearch] A search task failed: {res}")
                
        # Simple priority-based sorting (Graph > Email > Drive)
        # In a real scenario, we'd use an LLM or cross-encoder here.
        merged_results.sort(key=lambda x: self._get_priority(x), reverse=True)
        
        return merged_results[:limit]

    async def _search_graph(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Search structured entities in the graph"""
        try:
            # Look for Receipts or categorized nodes
            aql = """
            FOR doc IN KnowledgeNode
            FILTER doc.user_id == @user_id
            AND (doc.name =~ @query OR doc.content =~ @query OR doc.merchant =~ @query)
            SORT doc.date DESC
            LIMIT @limit
            RETURN doc
            """
            bind_vars = {
                'user_id': self.user_id,
                'query': f"(?i){query}",
                'limit': limit
            }
            results = await self.graph_manager.query(aql, bind_vars)
            for r in results: r['_platform'] = 'graph'
            return results
        except Exception as e:
            logger.error(f"Graph search failed: {e}")
            return []

    async def _search_email(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Search Gmail messages"""
        try:
            results = self.email_service.search_emails(query=query, limit=limit)
            for r in results: r['_platform'] = 'email'
            return results
        except Exception as e:
            logger.error(f"Email search failed: {e}")
            return []

    async def _search_drive(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Search Google Drive files"""
        try:
            # Assuming drive_service has a search_files method
            if hasattr(self.drive_service, 'search_files'):
                results = self.drive_service.search_files(query=query, limit=limit)
                for r in results: r['_platform'] = 'drive'
                return results
            return []
        except Exception as e:
            logger.error(f"Drive search failed: {e}")
            return []

    def _get_priority(self, item: Dict[str, Any]) -> int:
        """Heuristic for result importance"""
        platform = item.get('_platform')
        if platform == 'graph': return 100 # Structured facts are best
        if platform == 'email': return 80  # Recent emails second
        if platform == 'drive': return 60  # Drive files third
        return 0
