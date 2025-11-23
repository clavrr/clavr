"""
Email Indexing Module - Tool Layer Wrapper

This module provides a tool-friendly wrapper around IntelligentEmailIndexer from the services layer.

Architecture:
    EmailTool → EmailIndexing (wrapper) → IntelligentEmailIndexer (service) → Graph/Vector Stores

Why this wrapper exists:
    - Provides sync interfaces for async operations (tools are typically sync)
    - Formats results for tool consumption (human-readable strings)
    - Handles fallback logic (RAG when graph unavailable)
    - Simplifies tool integration (EmailService → EmailIndexing → IntelligentEmailIndexer)
"""
from typing import Optional, List, Dict, Any
import asyncio

from ...utils.logger import setup_logger
from ...integrations.gmail.service import EmailService
from .constants import LIMITS

logger = setup_logger(__name__)

# Constants for indexing operations
DEFAULT_GRAPH_DEPTH = 2  # Default graph traversal depth (2 hops)
MAX_GRAPH_RESULTS_DISPLAY = 5  # Max graph results to display
CONTENT_PREVIEW_LENGTH = 200  # Preview length for content snippets
DEFAULT_EMBEDDING_DIMENSION = 768  # Default embedding dimension

# Import indexer components
try:
    from ...services.indexing import IntelligentEmailIndexer
    from ...services.indexing.hybrid_index import HybridIndexCoordinator
    INDEXER_AVAILABLE = True
except ImportError:
    INDEXER_AVAILABLE = False
    logger.warning("IntelligentEmailIndexer not available")

# Import RAG engine for backward compatibility
try:
    from ...ai.rag import RAGEngine
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False


class EmailIndexing:
    """Email indexing and knowledge graph integration"""
    
    def __init__(
        self,
        email_service: EmailService,
        config: Optional[Any] = None,
        llm_client: Optional[Any] = None,
        rag_engine: Optional[Any] = None
    ):
        """
        Initialize email indexing
        
        Args:
            email_service: Email service instance
            config: Configuration object
            llm_client: LLM client for AI-powered indexing
            rag_engine: RAG engine for semantic search
        """
        self.email_service = email_service
        # Get Gmail client from email service (always available via service)
        self.google_client = getattr(email_service, 'gmail_client', None)
        self.config = config
        self.llm_client = llm_client
        self.rag_engine = rag_engine
        self._indexer = None
        self._hybrid_coordinator = None
    
    @property
    def indexer(self) -> Optional[Any]:
        """Get or create intelligent email indexer (lazy loading)"""
        if self._indexer is None and INDEXER_AVAILABLE and self.config:
            try:
                self._indexer = IntelligentEmailIndexer(
                    config=self.config,
                    google_client=self.google_client,
                    llm_client=self.llm_client,
                    use_knowledge_graph=True  # Enable graph mode by default
                )
                logger.info("[OK] IntelligentEmailIndexer initialized with knowledge graph")
            except Exception as e:
                logger.error(f"Failed to initialize IntelligentEmailIndexer: {e}")
                self._indexer = None
        
        return self._indexer
    
    @property
    def hybrid_coordinator(self) -> Optional[Any]:
        """Get hybrid index coordinator (from indexer)"""
        if self.indexer:
            # Access coordinator via indexer's hybrid_coordinator property
            return getattr(self.indexer, 'coordinator', None)
        return None
    
    async def index_email_async(self, email_data: Dict[str, Any]) -> bool:
        """
        Index a single email using the intelligent indexer
        
        Args:
            email_data: Email data dictionary
            
        Returns:
            True if indexed successfully, False otherwise
        """
        if not self.indexer:
            logger.warning("Indexer not available - cannot index email")
            return False
        
        try:
            await self.indexer.index_email(email_data)
            return True
        except Exception as e:
            logger.error(f"Failed to index email: {e}")
            return False
    
    def index_email(self, email_data: Dict[str, Any]) -> bool:
        """
        Index a single email (sync wrapper)
        
        Args:
            email_data: Email data dictionary
            
        Returns:
            True if indexed successfully, False otherwise
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Create a task if loop is running
                asyncio.create_task(self.index_email_async(email_data))
                return True
            else:
                # Run synchronously if no loop
                return loop.run_until_complete(self.index_email_async(email_data))
        except Exception as e:
            logger.error(f"Failed to index email: {e}")
            return False
    
    async def semantic_search_async(
        self,
        query: str,
        limit: int = LIMITS.DEFAULT_LIMIT,
        use_graph: bool = True,
        use_vector: bool = True
    ) -> str:
        """
        Perform hybrid semantic search (graph + vector)
        
        Args:
            query: Search query
            limit: Maximum number of results
            use_graph: Use knowledge graph search
            use_vector: Use vector search
            
        Returns:
            Formatted search results
        """
        if not self.hybrid_coordinator:
            # Fallback to RAG engine if available
            if self.rag_engine and RAG_AVAILABLE:
                logger.info("[SEARCH] Using fallback RAG engine for semantic search")
                return await self._rag_semantic_search(query, limit)
            else:
                return "[ERROR] Semantic search not available - neither knowledge graph nor RAG engine configured"
        
        try:
            # Use hybrid coordinator for combined graph + vector search
            results = await self.hybrid_coordinator.query(
                text_query=query,
                use_graph=use_graph,
                use_vector=use_vector,
                graph_depth=DEFAULT_GRAPH_DEPTH,
                limit=limit
            )
            
            # Format results
            if not results:
                return ""
            
            output = ""
            
            # Show graph results if available
            if use_graph and 'graph_results' in results and results['graph_results']:
                output += "**Knowledge Graph Results:**\n\n"
                for i, node in enumerate(results['graph_results'][:MAX_GRAPH_RESULTS_DISPLAY], 1):
                    node_type = node.get('node_type', 'Unknown')
                    node_id = node.get('id', 'Unknown')
                    properties = node.get('properties', {})
                    
                    if node_type == 'Email':
                        subject = properties.get('subject', 'No Subject')
                        sender = properties.get('sender', 'Unknown')
                        output += f"{i}. **{subject}**\n"
                        output += f"   From: {sender}\n"
                        output += f"   Type: Email (Graph)\n\n"
                    elif node_type == 'Contact':
                        name = properties.get('name', 'Unknown')
                        email = properties.get('email', '')
                        output += f"{i}. **{name}**\n"
                        output += f"   Email: {email}\n"
                        output += f"   Type: Contact (Graph)\n\n"
                output += "\n"
            
            # Show vector results if available
            if use_vector and 'vector_results' in results and results['vector_results']:
                output += "**Semantic Search Results:**\n\n"
                for i, result in enumerate(results['vector_results'][:limit], 1):
                    doc_id = result.get('id', 'Unknown')
                    content = result.get('content', '')
                    score = result.get('score', 0.0)
                    
                    output += f"{i}. **Email ID: {doc_id}**\n"
                    output += f"   Relevance: {score:.2f}\n"
                    output += f"   Preview: {content[:CONTENT_PREVIEW_LENGTH]}...\n\n"
            
            return output if output else ""
            
        except Exception as e:
            logger.error(f"Hybrid semantic search failed: {e}")
            return f"[ERROR] Semantic search failed: {str(e)}"
    
    def semantic_search(self, query: str, limit: int = LIMITS.DEFAULT_LIMIT) -> str:
        """
        Perform semantic search (sync wrapper)
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            Formatted search results
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, we can't use run_until_complete
                # Return a placeholder and log
                logger.warning("Cannot run async semantic search in running event loop")
                return "[ERROR] Async semantic search requires async context"
            else:
                return loop.run_until_complete(self.semantic_search_async(query, limit))
        except Exception as e:
            logger.error(f"Failed to perform semantic search: {e}")
            return f"[ERROR] Semantic search failed: {str(e)}"
    
    async def graph_query_async(self, query: str, limit: int = LIMITS.DEFAULT_LIMIT) -> str:
        """
        Perform graph-only query using Cypher-like syntax
        
        Examples:
        - "MATCH (e:Email)-[:FROM]->(c:Contact) WHERE c.name = 'John' RETURN e"
        - "MATCH (e:Email) WHERE e.subject CONTAINS 'meeting' RETURN e"
        
        Args:
            query: Cypher-like query string
            limit: Maximum number of results
            
        Returns:
            Formatted query results
        """
        if not self.hybrid_coordinator:
            return "[ERROR] Knowledge graph not available"
        
        try:
            # Use graph manager's query parser
            graph_manager = self.hybrid_coordinator.graph_manager
            results = graph_manager.query(query)
            
            if not results:
                return ""
            
            output = "**Graph Query Results:**\n\n"
            
            for i, result in enumerate(results[:limit], 1):
                if isinstance(result, dict):
                    node_type = result.get('node_type', 'Unknown')
                    properties = result.get('properties', {})
                    
                    if node_type == 'Email':
                        subject = properties.get('subject', 'No Subject')
                        sender = properties.get('sender', 'Unknown')
                        output += f"{i}. **{subject}**\n"
                        output += f"   From: {sender}\n"
                    elif node_type == 'Contact':
                        name = properties.get('name', 'Unknown')
                        email = properties.get('email', '')
                        output += f"{i}. **{name}** ({email})\n"
                    else:
                        output += f"{i}. {node_type}: {properties}\n"
                    
                    output += "\n"
            
            return output
            
        except Exception as e:
            logger.error(f"Graph query failed: {e}")
            return f"[ERROR] Graph query failed: {str(e)}"
    
    def graph_query(self, query: str, limit: int = LIMITS.DEFAULT_LIMIT) -> str:
        """
        Perform graph query (sync wrapper)
        
        Args:
            query: Cypher-like query string
            limit: Maximum number of results
            
        Returns:
            Formatted query results
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                logger.warning("Cannot run async graph query in running event loop")
                return "[ERROR] Async graph query requires async context"
            else:
                return loop.run_until_complete(self.graph_query_async(query, limit))
        except Exception as e:
            logger.error(f"Failed to perform graph query: {e}")
            return f"[ERROR] Graph query failed: {str(e)}"
    
    async def _rag_semantic_search(self, query: str, limit: int) -> str:
        """Fallback semantic search using RAG engine"""
        try:
            results = self.rag_engine.search(query, k=limit)
            
            if not results:
                return ""
            
            output = ""
            for i, result in enumerate(results, 1):
                doc_id = result.get('id', 'Unknown')
                content = result.get('content', '')
                score = result.get('score', 0.0)
                
                output += f"{i}. **Email ID: {doc_id}**\n"
                output += f"   Relevance: {score:.2f}\n"
                output += f"   Preview: {content[:200]}...\n\n"
            
            return output
            
        except Exception as e:
            logger.error(f"RAG semantic search failed: {e}")
            return f"[ERROR] Semantic search failed: {str(e)}"
    
    def get_indexing_stats(self) -> Dict[str, Any]:
        """Get statistics about email indexing"""
        if not self.indexer:
            if self.rag_engine and RAG_AVAILABLE:
                # Fallback to RAG stats
                try:
                    collection_stats = self.rag_engine.get_stats()
                    return {
                        'backend': 'rag_only',
                        'total_indexed': collection_stats.get('total_documents', 0),
                        'embedding_dimension': collection_stats.get('embedding_dim', DEFAULT_EMBEDDING_DIMENSION),
                        'collection_name': self.rag_engine.rag_config.collection_name
                    }
                except Exception as e:
                    logger.error(f"Failed to get RAG stats: {e}")
                    return {'error': str(e)}
            else:
                return {
                    'backend': 'none',
                    'message': 'No indexing available'
                }
        
        try:
            stats = {
                'backend': 'intelligent_indexer',
                'knowledge_graph_enabled': self.indexer.use_knowledge_graph,
            }
            
            # Get graph stats if available
            if self.hybrid_coordinator and self.hybrid_coordinator.graph_manager:
                graph_stats = self.hybrid_coordinator.graph_manager.get_stats()
                stats['graph_nodes'] = graph_stats.get('node_count', 0)
                stats['graph_relationships'] = graph_stats.get('relationship_count', 0)
            
            # Get vector stats if available
            if self.hybrid_coordinator and self.hybrid_coordinator.vector_store:
                vector_stats = self.hybrid_coordinator.vector_store.get_stats()
                stats['total_indexed'] = vector_stats.get('total_documents', 0)
                stats['embedding_dimension'] = vector_stats.get('embedding_dim', DEFAULT_EMBEDDING_DIMENSION)
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get indexing stats: {e}")
            return {'error': str(e)}
