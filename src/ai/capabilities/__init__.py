"""
Capabilities Module

Provides advanced capabilities for agents:
- NLP Processor: Detailed language understanding
- Response Personalizer: Adaptive response formatting
- Pattern Recognition: Behavioral analysis and proactive suggestions
"""

from .nlp_processor import NLPProcessor, EntityLink, SentimentType
from .response_personalizer import ResponsePersonalizer, UserPreferences, ResponseFormat, DetailLevel
from .pattern_recognition import PatternRecognition

__all__ = [
    'NLPProcessor',
    'EntityLink',
    'SentimentType',
    'ResponsePersonalizer',
    'UserPreferences',
    'ResponseFormat',
    'DetailLevel',
    'PatternRecognition'
]
