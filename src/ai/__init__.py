"""
AI/LLM integration modules

This package uses TYPE_CHECKING imports to provide type hints without forcing
dependencies to be loaded at import time. This is especially important for
optional dependencies like transformers.

Import the specific modules you need directly, e.g.:
    from src.ai.llm_factory import LLMFactory
    from src.ai.rag import RAGEngine
"""

from typing import TYPE_CHECKING

# Type checking imports (no runtime cost, only for type hints and linters)
# These imports ONLY run during static type checking, not at runtime
if TYPE_CHECKING:
    from .llm_factory import LLMFactory
    from .conversation_memory import ConversationMemory
    from .profile_builder import ProfileBuilder
    from .query_classifier import QueryClassifier, IntentClassificationSchema
    from .rag import RAGEngine, EmbeddingProvider, VectorStore

__all__ = [
    "LLMFactory",
    "ConversationMemory",
    "ProfileBuilder",
    "QueryClassifier",
    "IntentClassificationSchema",
    "RAGEngine",
    "EmbeddingProvider",
    "VectorStore",
]

def __getattr__(name: str):
    """
    Lazy import modules on demand to avoid dependency issues.
    
    This function is called when accessing attributes that don't exist in the module.
    It allows us to defer importing until the attribute is actually used.
    """
    if name == "LLMFactory":
        from .llm_factory import LLMFactory
        return LLMFactory
    elif name == "ConversationMemory":
        from .conversation_memory import ConversationMemory
        return ConversationMemory
    elif name == "ProfileBuilder":
        from .profile_builder import ProfileBuilder
        return ProfileBuilder
    elif name == "QueryClassifier":
        from .query_classifier import QueryClassifier
        return QueryClassifier
    elif name == "IntentClassificationSchema":
        from .query_classifier import IntentClassificationSchema
        return IntentClassificationSchema
    elif name == "RAGEngine":
        from .rag import RAGEngine
        return RAGEngine
    elif name == "EmbeddingProvider":
        from .rag import EmbeddingProvider
        return EmbeddingProvider
    elif name == "VectorStore":
        from .rag import VectorStore
        return VectorStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

