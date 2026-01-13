"""
AI Module

Provides AI/ML capabilities for the Clavr platform.

Core Components:
- LLM Factory: Create and manage LLM instances (Gemini via LangChain)
- Prompts: Centralized prompt templates for all domains
- RAG: Retrieval-Augmented Generation for context-aware responses
- Query Classifier: LLM-based query intent classification
- Conversation Memory: Track and summarize conversation context
- Profile Builder: Build user profiles from interaction history

Example Usage:
    from src.ai import LLMFactory, RAGEngine, QueryClassifier
    from src.ai.prompts import get_agent_system_prompt
    
    llm = LLMFactory.get_llm_for_provider(config)
    rag = RAGEngine()
    classifier = QueryClassifier(config)
"""

# LLM Factory
from .llm_factory import LLMFactory

# LLM Constants
from .llm_constants import (
    DEFAULT_TEMPERATURE,
    DEFAULT_PRIMARY_LLM,
    SUPPORTED_PROVIDERS,
)

# Query Classifier
from .query_classifier import QueryClassifier

# Conversation Memory
from .conversation_memory import ConversationMemory

# Profile Builder
from .profile_builder import ProfileBuilder

# Context Assembler (unified context for agents)
from .context_assembler import (
    ContextAssembler,
    AssembledContext,
    get_context_assembler,
    init_context_assembler
)

# RAG (re-export from submodule)
from .rag import (
    RAGEngine,
    EmbeddingProvider,
    VectorStore,
    create_embedding_provider,
    create_vector_store,
    QueryEnhancer,
    ResultReranker,
)

__all__ = [
    # LLM
    "LLMFactory",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_PRIMARY_LLM",
    "SUPPORTED_PROVIDERS",
    
    # Query Classification
    "QueryClassifier",
    
    # Conversation
    "ConversationMemory",
    
    # Profile
    "ProfileBuilder",
    
    # RAG
    "RAGEngine",
    "EmbeddingProvider",
    "VectorStore",
    "create_embedding_provider",
    "create_vector_store",
    "QueryEnhancer",
    "ResultReranker",
    
    # Context Assembler
    "ContextAssembler",
    "AssembledContext",
    "get_context_assembler",
    "init_context_assembler",
]

# ============================================================================
# Agent Infrastructure Submodules (relocated from src/agents/)
# ============================================================================

# Intent Detection
try:
    from .intent import (
        classify_query_intent,
        extract_entities,
        analyze_query_complexity,
        has_email_keywords,
        has_calendar_keywords,
        has_task_keywords,
        DomainDetector,
        detect_domain,
    )
    __all__.extend([
        "classify_query_intent",
        "extract_entities", 
        "analyze_query_complexity",
        "has_email_keywords",
        "has_calendar_keywords",
        "has_task_keywords",
        "DomainDetector",
        "detect_domain",
    ])
except ImportError:
    pass

# Capabilities
try:
    from .capabilities import (
        NLPProcessor,
        ResponsePersonalizer,
        PatternRecognition,
    )
    __all__.extend([
        "NLPProcessor",
        "ResponsePersonalizer",
        "PatternRecognition",
    ])
except ImportError:
    pass

# Formatting
try:
    from .formatting import ResponseFormatter, VoiceFormatter, VoiceConfig
    __all__.extend(["ResponseFormatter", "VoiceFormatter", "VoiceConfig"])
except ImportError:
    pass

# Caching
try:
    from .caching import ComplexityAwareCache, IntentPatternsCache
    __all__.extend(["ComplexityAwareCache", "IntentPatternsCache"])
except ImportError:
    pass

# Schemas
try:
    from .schemas import (
        StepDecompositionSchema,
        QueryDecompositionSchema,
        ContextExtractionSchema,
    )
    __all__.extend([
        "StepDecompositionSchema",
        "QueryDecompositionSchema",
        "ContextExtractionSchema",
    ])
except ImportError:
    pass

# Preprocessing
try:
    from .preprocessing import TextNormalizer, normalize_query
    __all__.extend(["TextNormalizer", "normalize_query"])
except ImportError:
    pass
