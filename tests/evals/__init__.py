"""
Evaluation Framework for Clavr Agent

Comprehensive evaluation suite for testing agent capabilities:
- Intent classification accuracy
- Entity extraction accuracy
- Tool selection correctness
- Response quality
- Preset functionality
- Contact resolution
- Conversation memory
- End-to-end task completion
"""

from .base import BaseEvaluator, EvaluationResult, EvaluationMetrics
from .intent_eval import IntentClassificationEvaluator
from .entity_eval import EntityExtractionEvaluator

from .response_eval import ResponseQualityEvaluator
from .preset_eval import PresetFunctionalityEvaluator
from .contact_eval import ContactResolutionEvaluator
from .memory_eval import ConversationMemoryEvaluator
from .e2e_eval import EndToEndEvaluator
from .runner import EvaluationRunner

__all__ = [
    'BaseEvaluator',
    'EvaluationResult',
    'EvaluationMetrics',
    'IntentClassificationEvaluator',
    'EntityExtractionEvaluator',

    'ResponseQualityEvaluator',
    'PresetFunctionalityEvaluator',
    'ContactResolutionEvaluator',
    'ConversationMemoryEvaluator',
    'EndToEndEvaluator',
    'EvaluationRunner'
]

