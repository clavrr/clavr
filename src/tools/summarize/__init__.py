"""
Summarize module - Modular summarization system
Provides extractive, abstractive, and specialized summarization
"""
from .constants import (
    VALID_FORMATS,
    VALID_LENGTHS,
    DEFAULT_FORMAT,
    DEFAULT_LENGTH,
    MAX_CONTENT_LENGTH,
    SHORT_CONTENT_THRESHOLD,
    MEDIUM_CONTENT_THRESHOLD,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    FORMAT_EMOJIS,
    FORMAT_TITLES,
    NLP_ENHANCEMENT_MIN_LENGTH,
    # Word count constants
    CHARS_PER_WORD_ESTIMATE,
    WORD_COUNT_THRESHOLD_SMALL,
    WORD_COUNT_THRESHOLD_MEDIUM,
    # Sentence count constants
    SENTENCE_MULTIPLIER_SHORT,
    SENTENCE_MULTIPLIER_MEDIUM,
    SENTENCE_MULTIPLIER_LONG,
    MIN_SENTENCES_SHORT,
    MIN_SENTENCES_MEDIUM,
    MIN_SENTENCES_LONG,
    DEFAULT_SENTENCE_COUNT,
    # Truncation constants
    TRUNCATION_BOUNDARY_THRESHOLD,
    # Quality validation constants
    QUALITY_MIN_COMPRESSION,
    QUALITY_MAX_COMPRESSION,
    QUALITY_MIN_COVERAGE,
    QUALITY_MIN_DENSITY
)
from .extractive import ExtractiveSummarizer
from .abstractive import AbstractiveSummarizer
from .specialized import (
    EmailThreadSummarizer,
    CalendarEventSummarizer,
    ConversationSummarizer
)
from .quality import QualityMetrics
from .utils import (
    SummaryCache,
    InputValidator,
    ContentPreprocessor,
    generate_cache_key,
    format_summary_output
)

__all__ = [
    # Constants
    'VALID_FORMATS',
    'VALID_LENGTHS',
    'DEFAULT_FORMAT',
    'DEFAULT_LENGTH',
    'MAX_CONTENT_LENGTH',
    'SHORT_CONTENT_THRESHOLD',
    'MEDIUM_CONTENT_THRESHOLD',
    'LLM_TEMPERATURE',
    'LLM_MAX_TOKENS',
    'FORMAT_EMOJIS',
    'FORMAT_TITLES',
    # Quality validation constants
    'QUALITY_MIN_COMPRESSION',
    'QUALITY_MAX_COMPRESSION',
    'QUALITY_MIN_COVERAGE',
    'QUALITY_MIN_DENSITY',
    # Summarizers
    'ExtractiveSummarizer',
    'AbstractiveSummarizer',
    'EmailThreadSummarizer',
    'CalendarEventSummarizer',
    'ConversationSummarizer',
    # Quality
    'QualityMetrics',
    # Utils
    'SummaryCache',
    'InputValidator',
    'ContentPreprocessor',
    'generate_cache_key',
    'format_summary_output',
]
