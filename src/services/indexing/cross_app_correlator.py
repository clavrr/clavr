"""
Cross-App Correlator

Real-time cross-app content correlation service.
When new content is indexed, this service finds semantically similar content
across different apps and creates RELATED_TO relationships in the graph.

This enables:
- "Show me everything about Project X" (aggregates email, Slack, Notion, calendar)
- Proactive connection surfacing ("This meeting is related to a Slack discussion")
- Cross-app context in agent responses
"""
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from dataclasses import dataclass

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.parsers.base import ParsedNode
from src.services.indexing.graph import KnowledgeGraphManager, RelationType

if TYPE_CHECKING:
    from src.ai.rag import RAGEngine

logger = setup_logger(__name__)

# Configuration constants
DEFAULT_CORRELATION_THRESHOLD = 0.6  # Lowered from 0.7 for better recall
MAX_CROSS_APP_CORRELATIONS = 5
MIN_CONTENT_LENGTH = 50
CORRELATION_RELATIONSHIP = RelationType.RELATED_TO


@dataclass
class Correlation:
    """A discovered cross-app correlation."""
    source_node_id: str
    target_node_id: str
    target_source: str  # App source (gmail, slack, notion, etc.)
    similarity_score: float
    target_content_preview: str
    discovered_at: datetime


class CrossAppCorrelator:
    """
    Real-time cross-app content correlation service.
    
    When a new email arrives about "Q4 Budget Review", automatically:
    1. Find matching Notion pages discussing budgets
    2. Find Slack conversations with related keywords
    3. Find calendar events with similar titles
    4. Create RELATED_TO links with semantic confidence scores
    
    Usage:
        correlator = CrossAppCorrelator(config, rag_engine, graph_manager)
        
        # Called automatically during indexing
        correlations = await correlator.correlate_on_index(new_node)
        
        # Manual correlation search
        correlations = await correlator.find_correlations(node_id, user_id)
    """
    
    def __init__(
        self,
        config: Config,
        rag_engine: 'RAGEngine',
        graph_manager: KnowledgeGraphManager,
        similarity_threshold: float = DEFAULT_CORRELATION_THRESHOLD
    ):
        self.config = config
        self.rag_engine = rag_engine
        self.graph_manager = graph_manager
        self.similarity_threshold = similarity_threshold
        
    async def correlate_on_index(
        self,
        node: ParsedNode,
        create_relationships: bool = True
    ) -> List[Correlation]:
        """
        Called immediately after any content is indexed.
        
        Finds semantically similar content from OTHER apps and optionally
        creates graph relationships to link them.
        
        Args:
            node: The newly indexed ParsedNode
            create_relationships: If True, create RELATED_TO edges in graph
            
        Returns:
            List of discovered correlations
        """
        # Skip nodes without meaningful content
        if not self._is_correlatable(node):
            return []
            
        source_app = self._get_source_app(node)
        user_id = node.properties.get('user_id')
        
        if not user_id:
            logger.debug(f"[CrossAppCorrelator] Skipping node {node.node_id}: no user_id")
            return []
            
        correlations: List[Correlation] = []
        
        try:
            # 1. Semantic search for similar content
            search_results = await self._search_similar_content(
                query=node.searchable_text,
                user_id=user_id,
                exclude_source=source_app,
                exclude_node_id=node.node_id
            )
            
            if not search_results:
                return []
                
            # 2. Filter to cross-app matches above threshold
            for result in search_results[:MAX_CROSS_APP_CORRELATIONS]:
                metadata = result.get('metadata', {})
                target_source = metadata.get('source', 'unknown')
                similarity = result.get('score', 0.0)
                
                # Skip same-app matches
                if target_source == source_app:
                    continue
                    
                # Skip below threshold
                if similarity < self.similarity_threshold:
                    continue
                    
                target_node_id = metadata.get('graph_node_id')
                if not target_node_id:
                    continue
                    
                # Create correlation record
                correlation = Correlation(
                    source_node_id=node.node_id,
                    target_node_id=target_node_id,
                    target_source=target_source,
                    similarity_score=similarity,
                    target_content_preview=result.get('content', '')[:200],
                    discovered_at=datetime.utcnow()
                )
                correlations.append(correlation)
                
                # 3. Create graph relationship
                if create_relationships and self.graph_manager:
                    await self._create_correlation_relationship(correlation)
                    
            if correlations:
                logger.info(
                    f"[CrossAppCorrelator] Found {len(correlations)} cross-app correlations "
                    f"for {node.node_id} from {source_app}"
                )
                
            return correlations
            
        except Exception as e:
            logger.warning(f"[CrossAppCorrelator] Error correlating {node.node_id}: {e}")
            return []
            
    async def find_correlations(
        self,
        node_id: str,
        user_id: int,
        max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Find existing correlations for a node from the graph.
        
        Used for queries like "What else is related to this email?"
        
        Args:
            node_id: Node ID to find correlations for
            user_id: User ID for filtering
            max_results: Maximum correlations to return
            
        Returns:
            List of correlated nodes with metadata
        """
        if not self.graph_manager:
            return []
            
        try:
            # Query graph for RELATED_TO relationships
            query = """
            FOR n IN UNION(
                (FOR x IN Email RETURN x),
                (FOR x IN Message RETURN x),
                (FOR x IN CalendarEvent RETURN x),
                (FOR x IN ActionItem RETURN x),
                (FOR x IN Project RETURN x),
                (FOR x IN Page RETURN x),
                (FOR x IN Note RETURN x),
                (FOR x IN Document RETURN x),
                (FOR x IN Contact RETURN x),
                (FOR x IN Person RETURN x)
            )
             FILTER n.id == @node_id
             
             FOR related, r IN 1..1 OUTBOUND n @@edge_collection
                FILTER r.correlation_type == 'semantic'
                SORT r.confidence DESC
                LIMIT @limit
                RETURN {
                    node_id: related.id,
                    type: related.node_type,
                    confidence: r.confidence,
                    discovered_at: r.discovered_at,
                    label: PARSE_IDENTIFIER(related._id).collection
                }
            """
            
            # We need to bind edge_collection to RELATED_TO (which is the collection name for that relation type)
            # Assuming RelationType.RELATED_TO.value is the collection name.
            
            # Wait, KnowledgeGraphManager.query takes params.
            # I'll need to update the params to include 'edge_collection'.
            # Or just hardcode 'RELATED_TO' in the query if consistent.
            # RelationType.RELATED_TO.value is 'RELATED_TO'.
            
            # AQL query
            query = """
            FOR n IN UNION(
                (FOR x IN Email RETURN x),
                (FOR x IN Message RETURN x),
                (FOR x IN CalendarEvent RETURN x),
                (FOR x IN ActionItem RETURN x),
                (FOR x IN Project RETURN x),
                (FOR x IN Page RETURN x),
                (FOR x IN Note RETURN x),
                (FOR x IN Document RETURN x)
            )
             FILTER n.id == @node_id
             
             FOR related, r IN 1..1 OUTBOUND n RELATED_TO
                FILTER r.correlation_type == 'semantic'
                SORT r.confidence DESC
                LIMIT @limit
                RETURN {
                    node_id: related.id,
                    type: related.node_type,
                    confidence: r.confidence,
                    discovered_at: r.discovered_at,
                    label: PARSE_IDENTIFIER(related._id).collection
                }
            """
            
            results = await self.graph_manager.query(query, {
                'node_id': node_id,
                'limit': max_results
            })
            
            return [dict(r) for r in results] if results else []
            
        except Exception as e:
            logger.warning(f"[CrossAppCorrelator] Error finding correlations: {e}")
            return []
            
    async def get_cross_app_context(
        self,
        query: str,
        user_id: int,
        primary_source: str,
        max_per_app: int = 3
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get context from all apps related to a query.
        
        Used to enrich agent responses with cross-app information.
        
        Args:
            query: Search query
            user_id: User ID
            primary_source: The primary app being queried (to deprioritize)
            max_per_app: Max results per app
            
        Returns:
            Dict mapping app name -> list of relevant content
        """
        try:
            # Search across all apps
            results = await asyncio.to_thread(
                self.rag_engine.search,
                query,
                k=max_per_app * 5,  # Fetch more, then filter
                filters={'user_id': str(user_id)}
            )
            
            # Group by source app
            by_app: Dict[str, List[Dict[str, Any]]] = {}
            
            for result in results:
                metadata = result.get('metadata', {})
                source = metadata.get('source', 'unknown')
                
                if source not in by_app:
                    by_app[source] = []
                    
                if len(by_app[source]) < max_per_app:
                    by_app[source].append({
                        'content': result.get('content', ''),
                        'node_id': metadata.get('graph_node_id'),
                        'score': result.get('score', 0.0),
                        'metadata': metadata
                    })
                    
            return by_app
            
        except Exception as e:
            logger.warning(f"[CrossAppCorrelator] Error getting cross-app context: {e}")
            return {}
    
    async def find_related_documents_for_meeting(
        self,
        event_node_id: str,
        event_title: str,
        event_description: str,
        attendee_emails: List[str],
        user_id: int,
        max_docs: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find Drive documents related to a specific calendar meeting.
        
        This enables proactive meeting prep by surfacing relevant docs before meetings.
        
        Strategy:
        1. Semantic search using event title + description
        2. Boost documents owned/shared by attendees
        3. Create RELATED_TO edges for high-confidence matches
        
        Args:
            event_node_id: Calendar event node ID
            event_title: Meeting title
            event_description: Meeting description
            attendee_emails: List of attendee email addresses
            user_id: User ID
            max_docs: Maximum documents to return
            
        Returns:
            List of related documents with metadata
        """
        try:
            # Build search query from title + description
            search_query = f"{event_title} {event_description[:500] if event_description else ''}"
            
            if len(search_query.strip()) < 10:
                return []
            
            # Search for Drive documents specifically
            results = await asyncio.to_thread(
                self.rag_engine.search,
                search_query,
                k=max_docs * 3,  # Fetch more, then rank
                filters={'user_id': str(user_id)},
                min_confidence=0.5
            )
            
            related_docs = []
            
            for result in results:
                metadata = result.get('metadata', {})
                source = metadata.get('source', '')
                
                # Focus on Drive documents
                if source not in ('google_drive', 'drive'):
                    continue
                    
                doc_node_id = metadata.get('graph_node_id')
                if not doc_node_id:
                    continue
                
                similarity = result.get('score', 0.0)
                
                # Boost score if document owner is an attendee
                owner_email = metadata.get('owner_email', '').lower()
                if owner_email and owner_email in [e.lower() for e in attendee_emails]:
                    similarity = min(1.0, similarity * 1.3)  # 30% boost
                
                if similarity < self.similarity_threshold:
                    continue
                
                doc_info = {
                    'node_id': doc_node_id,
                    'filename': metadata.get('filename', 'Unknown'),
                    'similarity': similarity,
                    'owner_email': owner_email,
                    'web_link': metadata.get('web_link'),
                    'content_preview': result.get('content', '')[:200]
                }
                related_docs.append(doc_info)
                
                # Create RELATED_TO edge if both nodes exist
                if self.graph_manager and similarity > 0.65:
                    try:
                        self.graph_manager.add_relationship(
                            from_node=event_node_id,
                            to_node=doc_node_id,
                            rel_type=RelationType.RELATED_TO,
                            properties={
                                'correlation_type': 'meeting_prep',
                                'confidence': similarity,
                                'discovered_at': datetime.utcnow().isoformat(),
                                'context': 'calendar_document_correlation'
                            }
                        )
                        logger.debug(f"[CrossAppCorrelator] Linked {event_node_id} -> {doc_node_id}")
                    except Exception as e:
                        logger.debug(f"[CrossAppCorrelator] Failed to create edge: {e}")
            
            # Sort by similarity and limit
            related_docs.sort(key=lambda x: x['similarity'], reverse=True)
            related_docs = related_docs[:max_docs]
            
            if related_docs:
                logger.info(
                    f"[CrossAppCorrelator] Found {len(related_docs)} Drive docs related to meeting '{event_title}'"
                )
            
            return related_docs
            
        except Exception as e:
            logger.warning(f"[CrossAppCorrelator] Error finding meeting docs: {e}")
            return []
            
    def _is_correlatable(self, node: ParsedNode) -> bool:
        """Check if a node has enough content for correlation."""
        # Must have searchable text
        if not node.searchable_text:
            return False
            
        # Must be long enough
        if len(node.searchable_text) < MIN_CONTENT_LENGTH:
            return False
            
        # Focus on content-bearing node types
        content_types = {
            'Email', 'Message', 'Document', 'Calendar_Event',
            'Task', 'Page', 'Note', 'ActionItem'
        }
        
        if node.node_type not in content_types:
            return False
            
        return True
        
    def _get_source_app(self, node: ParsedNode) -> str:
        """Determine the source app for a node."""
        # Check explicit source property
        source = node.properties.get('source')
        if source:
            return source
            
        # Infer from node type
        type_to_source = {
            'Email': 'gmail',
            'Message': 'slack',
            'Page': 'notion',
            'Calendar_Event': 'calendar',
            'Task': 'tasks',
            'ActionItem': 'asana',
            'Note': 'keep'
        }
        
        return type_to_source.get(node.node_type, 'unknown')
        
    async def _search_similar_content(
        self,
        query: str,
        user_id: int,
        exclude_source: str,
        exclude_node_id: str
    ) -> List[Dict[str, Any]]:
        """Search for semantically similar content."""
        try:
            results = await asyncio.to_thread(
                self.rag_engine.search,
                query,
                k=20,  # Fetch more, filter later
                filters={'user_id': str(user_id)},
                min_confidence=self.similarity_threshold
            )
            
            # Filter out same source and same node
            filtered = []
            for r in results:
                metadata = r.get('metadata', {})
                node_id = metadata.get('graph_node_id')
                source = metadata.get('source', '')
                
                # Skip same node
                if node_id == exclude_node_id:
                    continue
                    
                # Keep cross-app matches (we filter by source in caller)
                filtered.append(r)
                
            return filtered
            
        except Exception as e:
            logger.warning(f"[CrossAppCorrelator] Search failed: {e}")
            return []

    async def _create_correlation_relationship(self, correlation: Correlation) -> bool:
        """Create a graph relationship with appropriate type."""
        try:
            # Check if both nodes exist
            source_exists = self.graph_manager.get_node(correlation.source_node_id)
            target_exists = self.graph_manager.get_node(correlation.target_node_id)
            
            if not source_exists or not target_exists:
                return False
                
            # Determine relationship type
            rel_type = RelationType.RELATED_TO
            context = "semantic_similarity"
            
            # Check for temporal "FOLLOWS"
            # If high confidence and source is significantly later than target
            if correlation.similarity_score > 0.8:
                # Need to fetch timestamps to be sure, but simplified logic:
                # If preview suggests follow up
                content_lower = correlation.target_content_preview.lower()
                if "follow up" in content_lower or "continuation" in content_lower:
                    rel_type = RelationType.FOLLOWS
                    context = "follow_up"
            
            # Create relationship
            self.graph_manager.add_relationship(
                from_node=correlation.source_node_id,
                to_node=correlation.target_node_id,
                rel_type=rel_type,
                properties={
                    'correlation_type': 'semantic',
                    'confidence': correlation.similarity_score,
                    'discovered_at': correlation.discovered_at.isoformat(),
                    'cross_app': True,
                    'target_source': correlation.target_source,
                    'context': context
                }
            )
            
            logger.debug(
                f"[CrossAppCorrelator] Linking {correlation.source_node_id} -[{rel_type}]-> {correlation.target_node_id}"
            )
            
            return True
            
        except Exception as e:
            logger.warning(f"[CrossAppCorrelator] Failed to create relationship: {e}")
            return False


# Global instance management
_correlator_instance: Optional[CrossAppCorrelator] = None

def get_cross_app_correlator() -> Optional[CrossAppCorrelator]:
    """Get the global CrossAppCorrelator instance."""
    return _correlator_instance

def set_cross_app_correlator(instance: CrossAppCorrelator):
    """Set the global CrossAppCorrelator instance."""
    global _correlator_instance
    _correlator_instance = instance

def init_cross_app_correlator(
    config: Config, 
    rag_engine: 'RAGEngine', 
    graph_manager: KnowledgeGraphManager
) -> CrossAppCorrelator:
    """Initialize the global CrossAppCorrelator instance."""
    global _correlator_instance
    _correlator_instance = CrossAppCorrelator(config, rag_engine, graph_manager)
    return _correlator_instance
