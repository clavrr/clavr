"""
AI Memory Module

Provides memory management components for AI agents:
- SemanticMemory: Long-term fact storage and retrieval
- FactGraphManager: Hierarchical user preferences
- EpisodeDetector: Active project/conversation detection
- DynamicContextInjector: LTM → STM context injection
- PersonIntelligenceService: Contact relationship tracking
- IncrementalLearner: Continuous fact extraction from conversations
"""

# Core memory components
from .semantic_memory import SemanticMemory, FactValidationResult
from .enhanced_semantic_memory import EnhancedSemanticMemory, FactProvenance, EnhancedFactResult
from .fact_graph import FactGraphManager, FactGraph, FactNode, FactCategory
from .episode_detector import EpisodeDetector, Episode, EpisodeType, EpisodeContext
from .context_injector import (
    DynamicContextInjector, 
    InjectionResult, 
    ContextPriority,
    ContextChunk,
    format_injection_for_prompt,
    inject_context_into_messages
)

# Fact extraction and inference
from .extractor import FactExtractor
from .fact_inference import FactInferenceEngine, InferredFact, InferenceType

# Incremental learning (Memory-as-a-Service)
from .incremental_learner import (
    IncrementalLearner,
    ExtractedFact,
    LearningResult,
    get_incremental_learner,
    init_incremental_learner
)

# Configuration
from .memory_config import (
    MIN_CONFIDENCE_THRESHOLD,
    REINFORCEMENT_BOOST,
    DECAY_PENALTY,
    DEFAULT_DECAY_RATE,
    DEFAULT_USE_SEMANTIC_SEARCH,
)

# Person/contact management
from src.services.person_intelligence import PersonIntelligenceService
from src.services.person_intelligence import PersonDossier as PersonContext
from .person_unification import PersonUnificationService, UnifiedPerson
from .resolution import EntityResolutionService

# Graph observation and learning
from .observer import GraphObserverService
from .reasoning_chain import ReasoningChain, ReasoningEngine, ReasoningStep

# Temporal and clustering
from .temporal_facts import TemporalQueryEngine, TemporalFact, TemporalScope
from .semantic_clustering import SemanticClusterer, FactCluster

__all__ = [
    # Core
    'SemanticMemory',
    'FactValidationResult', 
    'EnhancedSemanticMemory',
    'FactProvenance',
    'EnhancedFactResult',
    'FactGraphManager',
    'FactGraph',
    'FactNode',
    'FactCategory',
    'EpisodeDetector',
    'Episode',
    'EpisodeType',
    'EpisodeContext',
    
    # Context injection
    'DynamicContextInjector',
    'InjectionResult',
    'ContextPriority',
    'ContextChunk',
    'format_injection_for_prompt',
    'inject_context_into_messages',
    
    # Extraction
    'FactExtractor',
    'FactInferenceEngine',
    'InferredFact',
    'InferenceType',
    
    # Incremental learning
    'IncrementalLearner',
    'ExtractedFact',
    'LearningResult',
    'get_incremental_learner',
    'init_incremental_learner',
    
    # Configuration
    'MIN_CONFIDENCE_THRESHOLD',
    'REINFORCEMENT_BOOST',
    'DECAY_PENALTY',
    
    # Person management
    'PersonIntelligenceService',
    'PersonContext',
    'PersonUnificationService',
    'UnifiedPerson',
    'EntityResolutionService',
    
    # Graph learning
    'GraphObserverService',
    'ReasoningChain',
    'ReasoningEngine',
    'ReasoningStep',
    
    # Temporal/clustering
    'TemporalQueryEngine',
    'TemporalFact',
    'TemporalScope',
    'SemanticClusterer',
    'FactCluster',
]
