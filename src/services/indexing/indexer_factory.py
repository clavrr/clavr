"""
Indexer Factory - Create Email Indexer with RAG Integration

This factory provides a unified interface for creating email indexers with:
- Advanced document parsing (Docling integration)
- Semantic chunking for optimal retrieval
- Knowledge graph support (optional)
- Email-aware chunking
- Intelligent attachment processing

"""
import os
from typing import Optional, Any

from ...utils.config import Config, load_config
from ...utils.logger import setup_logger
from ...core.email.google_client import GoogleGmailClient
from ...ai.rag import RAGEngine

logger = setup_logger(__name__)


def create_email_indexer(
    config: Optional[Config] = None,
    rag_engine: Optional[RAGEngine] = None,
    google_client: Optional[GoogleGmailClient] = None,
    llm_client: Optional[Any] = None,
    user_id: Optional[int] = None,
    collection_name: Optional[str] = None,
    use_knowledge_graph: Optional[bool] = None
):
    """
    Factory function to create an intelligent email indexer with RAG integration.
    
    The indexer includes:
    - DocumentProcessor for advanced document parsing (Docling + semantic chunking)
    - UnifiedParserRAGBridge for intelligent email processing
    - Email-aware chunking for better email indexing
    - Structure-aware attachment processing
    
    Args:
        config: Configuration object
        rag_engine: RAG engine for vector indexing
        google_client: Gmail client
        llm_client: LLM client for intent extraction and parsing
        user_id: Optional user ID for per-user indexing
        collection_name: Optional collection name
        use_knowledge_graph: Enable knowledge graph mode (default: from config)
    
    Returns:
        IntelligentEmailIndexer instance with full RAG integration
    
    Environment Variables:
        USE_KNOWLEDGE_GRAPH: "true" or "false" (default: "true")
    """
    config = config or load_config("config/config.yaml")
    
    # Determine if knowledge graph should be used
    if use_knowledge_graph is None:
        # Check config and environment
        graph_env = os.getenv('USE_KNOWLEDGE_GRAPH', 'true').lower()
        use_knowledge_graph = graph_env in ('true', '1', 'yes')
        
        if hasattr(config, 'indexing') and isinstance(config.indexing, dict):
            use_knowledge_graph = config.indexing.get('use_knowledge_graph', True)
    
    # Create intelligent indexer with RAG integration
    logger.info(
        f"Creating intelligent email indexer with RAG integration "
        f"(knowledge_graph: {use_knowledge_graph})"
    )
    
    from .indexer import IntelligentEmailIndexer
    return IntelligentEmailIndexer(
        config=config,
        rag_engine=rag_engine,
        google_client=google_client,
        llm_client=llm_client,
        user_id=user_id,
        collection_name=collection_name,
        use_knowledge_graph=use_knowledge_graph
    )


def is_knowledge_graph_enabled(config: Optional[Config] = None) -> bool:
    """
    Check if knowledge graph is enabled.
    
    Args:
        config: Configuration object
    
    Returns:
        True if knowledge graph should be used, False otherwise
    """
    # Check environment variable
    graph_env = os.getenv('USE_KNOWLEDGE_GRAPH', '').lower()
    if graph_env in ('false', '0', 'no'):
        return False
    elif graph_env in ('true', '1', 'yes'):
        return True
    
    # Check config
    config = config or load_config("config/config.yaml")
    if hasattr(config, 'indexing') and isinstance(config.indexing, dict):
        return config.indexing.get('use_knowledge_graph', True)
    
    # Default to enabled
    return True

