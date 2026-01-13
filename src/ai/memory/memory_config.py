"""
Memory Module Configuration

Centralizes constants and thresholds for the memory system.
Eliminates hardcoded values across memory components.
"""
from typing import Dict, Any
from enum import Enum


# ============================================================================
# Confidence Thresholds
# ============================================================================

# Minimum confidence for facts to be included in results
MIN_CONFIDENCE_THRESHOLD = 0.3

# Confidence boost when fact is reinforced
REINFORCEMENT_BOOST = 0.1

# Confidence penalty when fact is marked unhelpful
DECAY_PENALTY = 0.2

# Maximum confidence value
MAX_CONFIDENCE = 1.0

# ============================================================================
# Temporal Settings
# ============================================================================

# Default decay rate per day for temporal facts
DEFAULT_DECAY_RATE = 0.01

# Days after which a fact is considered stale
STALE_FACT_DAYS = 30

# Days to look back for recent facts
RECENT_FACT_DAYS = 7

# ============================================================================
# Persistence Settings
# ============================================================================

# How often to sync in-memory facts to database (seconds)
PERSISTENCE_SYNC_INTERVAL = 300  # 5 minutes

# Batch size for database operations
PERSISTENCE_BATCH_SIZE = 50

# ============================================================================
# Search Settings
# ============================================================================

# Default limit for fact searches
DEFAULT_SEARCH_LIMIT = 10

# Whether to use semantic search by default
DEFAULT_USE_SEMANTIC_SEARCH = True

# Minimum similarity score for semantic search results
MIN_SIMILARITY_SCORE = 0.5

# ============================================================================
# Inference Settings
# ============================================================================

# Maximum inferences to generate per cycle
MAX_INFERENCES_PER_CYCLE = 10

# Minimum supporting facts for inference
MIN_SUPPORTING_FACTS = 2

# Base confidence for inferred facts
INFERRED_FACT_BASE_CONFIDENCE = 0.7

# ============================================================================
# Context Injection Settings
# ============================================================================

# Token budget for system context
SYSTEM_CONTEXT_TOKEN_BUDGET = 1000

# Token budget for user context
USER_CONTEXT_TOKEN_BUDGET = 500

# Maximum facts per category in context
MAX_FACTS_PER_CATEGORY = 5

# ============================================================================
# Person Intelligence Settings
# ============================================================================

# Days to look back for recent communication
RECENT_COMMUNICATION_DAYS = 30

# Days for open loop detection
OPEN_LOOP_DAYS = 7

# Maximum talking points to generate
MAX_TALKING_POINTS = 5

# Cache TTL for person context (seconds)
PERSON_CONTEXT_CACHE_TTL = 3600  # 1 hour

# ============================================================================
# Incremental Learning Settings
# ============================================================================

# Minimum message length to attempt fact extraction
MIN_MESSAGE_LENGTH_FOR_EXTRACTION = 20

# Maximum facts to extract from a single message
MAX_FACTS_PER_MESSAGE = 5

# Confidence threshold for auto-learning extracted facts
AUTO_LEARN_CONFIDENCE_THRESHOLD = 0.7

# =============================================================================
# Feature Toggles (Memory-as-a-Service)
# =============================================================================

# Enable automatic fact learning from messages
ENABLE_AUTO_LEARNING = True

# Enable feedback loop (reinforce facts on use, decay on correction)
ENABLE_FEEDBACK_LOOP = True

# Boost amount when a fact is used in context (small, implicit reinforcement)
USAGE_REINFORCEMENT_BOOST = 0.02

# =============================================================================
# Embedding Settings
# =============================================================================

# Sentence transformer model for local embeddings
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Embedding dimension (for all-MiniLM-L6-v2)
EMBEDDING_DIMENSION = 384

# Minimum similarity score for embedding-based search results
EMBEDDING_MIN_SIMILARITY = 0.3

