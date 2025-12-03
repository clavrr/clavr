"""
Advanced Agent Capabilities Module

Provides advanced capabilities to core agent roles:
- Advanced NLP processing (AnalyzerRole)
- Predictive execution planning (OrchestratorRole)
- ML-based pattern recognition (MemoryRole)
- Response personalization (SynthesizerRole)
"""

from .nlp_processor import (
    NLPProcessor,
    NLPAnalysisResult,
    EntityLink,
    SentimentType
)

from .predictive_executor import (
    PredictiveExecutor,
    PredictedStep,
    ExecutionAdaptation,
    PredictionConfidence
)

from .pattern_recognition import (
    PatternRecognition,
    PatternCluster,
    DetectedAnomaly,
    AnomalyType
)

from .response_personalizer import (
    ResponsePersonalizer,
    PersonalizedResponse,
    UserPreferences,
    ResponseFormat,
    DetailLevel
)

__all__ = [
    # NLP Processor
    'NLPProcessor',
    'NLPAnalysisResult',
    'EntityLink',
    'SentimentType',
    
    # Predictive Executor
    'PredictiveExecutor',
    'PredictedStep',
    'ExecutionAdaptation',
    'PredictionConfidence',
    
    # Pattern Recognition
    'PatternRecognition',
    'PatternCluster',
    'DetectedAnomaly',
    'AnomalyType',
    
    # Response Personalizer
    'ResponsePersonalizer',
    'PersonalizedResponse',
    'UserPreferences',
    'ResponseFormat',
    'DetailLevel',
]
