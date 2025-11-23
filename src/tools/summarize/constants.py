"""
Constants for Summarization Tool

Configuration values, thresholds, and scoring weights for the summarization tool.
"""

# Content length thresholds for adaptive behavior
SHORT_CONTENT_THRESHOLD = 500  # chars
MEDIUM_CONTENT_THRESHOLD = 2000  # chars

# Length guidelines for different content sizes and summary lengths
LENGTH_GUIDELINES = {
    'short': {
        'short_content': '1-2 sentences or 2-3 bullet points',
        'medium_content': '2-3 sentences or 3-4 bullet points',
        'long_content': '3-4 sentences or 4-5 bullet points'
    },
    'medium': {
        'short_content': '2-3 sentences or 3-5 bullet points',
        'medium_content': '1 paragraph or 5-7 bullet points',
        'long_content': '1-2 paragraphs or 7-9 bullet points'
    },
    'long': {
        'short_content': '3-4 sentences or 5-7 bullet points',
        'medium_content': '2-3 paragraphs or 8-10 bullet points',
        'long_content': '2-3 paragraphs or 12-15 bullet points'
    }
}

# Sentence scoring weights for extractive summarization
SENTENCE_SCORING = {
    'optimal_length_min': 50,
    'optimal_length_max': 200,
    'acceptable_length_min': 20,
    'acceptable_length_max': 50,
    'optimal_score': 2,
    'acceptable_score': 1,
    'has_numbers_bonus': 1,
    'has_questions_bonus': 1,
    'min_length_penalty': -10,
    'min_length_threshold': 10
}

# NLP enhancement settings
NLP_ENHANCEMENT_MIN_LENGTH = 500  # Minimum content length for NLP enhancement
NLP_SAMPLE_LENGTH = 500  # Length of sample for NLP classification
MAX_KEYWORDS_IN_CONTEXT = 3  # Max keywords to include in context

# LLM settings
LLM_TEMPERATURE = 0.3  # Lower temperature for more focused summaries
LLM_MAX_TOKENS = 1000  # Max tokens for LLM response
MAX_CONTENT_FOR_LLM = 3000  # Max content length to send to LLM (chars)
MAX_CONTENT_FOR_NLP = 2000  # Max content length for NLP processing

# Content processing
CONTENT_LENGTH_BASELINE = 1000  # Baseline for dynamic sentence count calculation
MAX_CONTENT_LENGTH = 100000  # Maximum allowed content length (100K chars)

# Format configuration
VALID_FORMATS = ['paragraph', 'bullet_points', 'key_points']
VALID_LENGTHS = ['short', 'medium', 'long']

# Default format and length for specialized summarizers
DEFAULT_FORMAT = 'bullet_points'  # Default format for email threads, calendar events, conversations
DEFAULT_LENGTH = 'medium'  # Default length for all summarizers

# Format display
FORMAT_EMOJIS = {
    'bullet_points': '📋',
    'key_points': '🔑',
    'paragraph': '📄'
}

FORMAT_TITLES = {
    'bullet_points': 'Summary (Bullet Points)',
    'key_points': 'Key Takeaways',
    'paragraph': 'Summary'
}

# Cache settings
CACHE_MAX_SIZE = 100  # Maximum number of cached summaries
HASH_LENGTH = 16  # Length of content hash for caching

# Progressive summarization (for very long documents)
PROGRESSIVE_CHUNK_SIZE = 5000  # Chunk size for progressive summarization
PROGRESSIVE_THRESHOLD = 10000  # Content length threshold for progressive summarization

# Word count estimation
CHARS_PER_WORD_ESTIMATE = 5  # Average characters per word for estimation

# Target word count thresholds for abstractive summarization
WORD_COUNT_THRESHOLD_SMALL = 100  # Small content threshold (words)
WORD_COUNT_THRESHOLD_MEDIUM = 500  # Medium content threshold (words)

# Target word counts by length preference
TARGET_WORDS_SHORT_SMALL = 20  # Short summary for small content
TARGET_WORDS_SHORT_MEDIUM = 50  # Short summary for medium content
TARGET_WORDS_SHORT_LARGE = 75  # Short summary for large content
TARGET_WORDS_MEDIUM_SMALL = 30  # Medium summary for small content
TARGET_WORDS_MEDIUM_MEDIUM = 100  # Medium summary for medium content
TARGET_WORDS_MEDIUM_LARGE = 150  # Medium summary for large content
TARGET_WORDS_LONG_SMALL = 40  # Long summary for small content
TARGET_WORDS_LONG_MEDIUM = 150  # Long summary for medium content
TARGET_WORDS_LONG_LARGE = 250  # Long summary for large content

# Word count division factors for dynamic calculation
WORD_DIVISOR_SHORT = 4  # Divide by 4 for short summaries
WORD_DIVISOR_MEDIUM = 3  # Divide by 3 for medium summaries
WORD_DIVISOR_LONG = 2  # Divide by 2 for long summaries

# Sentence count multipliers for extractive summarization
SENTENCE_MULTIPLIER_SHORT = 1  # Base multiplier for short summaries
SENTENCE_MULTIPLIER_MEDIUM = 2  # Base multiplier for medium summaries
SENTENCE_MULTIPLIER_LONG = 3  # Base multiplier for long summaries

# Minimum sentence counts by length
MIN_SENTENCES_SHORT = 2  # Minimum sentences for short summary
MIN_SENTENCES_MEDIUM = 4  # Minimum sentences for medium summary
MIN_SENTENCES_LONG = 6  # Minimum sentences for long summary
DEFAULT_SENTENCE_COUNT = 4  # Default sentence count fallback

# Content truncation threshold
TRUNCATION_BOUNDARY_THRESHOLD = 0.8  # Keep 80%+ if truncating at sentence boundary

# Quality validation thresholds
QUALITY_MIN_COMPRESSION = 0.1  # Minimum compression ratio (10% - summary should be at least 10% of original)
QUALITY_MAX_COMPRESSION = 0.8  # Maximum compression ratio (80% - summary should not exceed 80% of original)
QUALITY_MIN_COVERAGE = 0.2  # Minimum coverage ratio (20% - at least 20% of original words should appear in summary)
QUALITY_MIN_DENSITY = 5.0  # Minimum information density (5 words/line - avoid extremely sparse summaries)
