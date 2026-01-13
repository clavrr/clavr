"""
Autonomy Configuration Constants

Centralized configuration for all autonomy-related timing, thresholds, and rules.
Values can be overridden via environment variables.
"""
import os
import json

def get_env_int(key: str, default: int) -> int:
    """Helper to get int from env."""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default

def get_env_float(key: str, default: float) -> float:
    """Helper to get float from env."""
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default

def get_env_list_int(key: str, default: list) -> list:
    """Helper to get list of ints from env (comma separated)."""
    val = os.getenv(key)
    if not val:
        return default
    try:
        # Support JSON format "[1,2]" or comma "1,2"
        if val.strip().startswith("["):
            return json.loads(val)
        return [int(x.strip()) for x in val.split(",") if x.strip()]
    except Exception:
        return default

def get_env_tuple_int(key: str, default: tuple) -> tuple:
    """Helper to get tuple of ints from env."""
    return tuple(get_env_list_int(key, list(default)))

# ============================================================================
# Behavior Learner Configuration
# ============================================================================

# Initial delay before starting pattern mining (seconds)
LEARNING_INITIAL_DELAY_SECONDS = get_env_int("AUTONOMY_LEARNING_DELAY", 600)  # 10 minutes

# Interval between pattern mining cycles (seconds)
LEARNING_INTERVAL_SECONDS = get_env_int("AUTONOMY_LEARNING_INTERVAL", 21600)  # 6 hours

# Time window for considering events as sequential (seconds)
PATTERN_WINDOW_SECONDS = get_env_int("AUTONOMY_PATTERN_WINDOW", 1800)  # 30 minutes

# Minimum number of occurrences to consider a pattern valid
MIN_PATTERN_SUPPORT = get_env_int("AUTONOMY_MIN_PATTERN_SUPPORT", 3)

# Days to look back for pattern mining
PATTERN_LOOKBACK_DAYS = get_env_int("AUTONOMY_PATTERN_LOOKBACK", 30)

# ============================================================================
# Context Evaluator Configuration
# ============================================================================

# Hours range for morning briefing (start, end)
MORNING_BRIEF_HOURS = get_env_tuple_int("AUTONOMY_MORNING_HOURS", (8, 10))

# Hours range for end-of-day summary (start, end)
EOD_SUMMARY_HOURS = get_env_tuple_int("AUTONOMY_EOD_HOURS", (17, 19))

# Minutes before meeting to trigger brief preparation
MEETING_PREP_MINUTES = get_env_int("AUTONOMY_MEETING_PREP_MINS", 15)

# Weekdays for automatic briefings (0=Monday, 6=Sunday)
BRIEFING_WEEKDAYS = get_env_list_int("AUTONOMY_BRIEFING_WEEKDAYS", [0, 1, 2, 3, 4])  # Mon-Fri

# ============================================================================
# Briefing Configuration
# ============================================================================

# Default temperature for briefing LLM calls
BRIEFING_TEMPERATURE = get_env_float("AUTONOMY_BRIEFING_TEMP", 0.7)

# Default temperature for meeting brief LLM calls
MEETING_BRIEF_TEMPERATURE = get_env_float("AUTONOMY_MEETING_TEMP", 0.5)

# Maximum events to include in briefing context
MAX_BRIEFING_EVENTS = get_env_int("AUTONOMY_MAX_EVENTS", 10)

# Maximum tasks to include in briefing context
MAX_BRIEFING_TASKS = get_env_int("AUTONOMY_MAX_TASKS", 5)

# Maximum emails to include in briefing context
MAX_BRIEFING_EMAILS = get_env_int("AUTONOMY_MAX_EMAILS", 5)

# ============================================================================
# Planner Configuration
# ============================================================================

# Time window to check for free slots (minutes)
FREE_SLOT_CHECK_WINDOW_MINUTES = get_env_int("AUTONOMY_FREE_CHECK_MINS", 90)

# Default focus block duration (minutes)
DEFAULT_FOCUS_DURATION_MINUTES = get_env_int("AUTONOMY_FOCUS_DURATION_MINS", 60)

# ============================================================================
# Concurrency Configuration
# ============================================================================

# Maximum concurrent users for pattern mining
MAX_CONCURRENT_MINING_USERS = get_env_int("AUTONOMY_MAX_CONCURRENT_MINING", 5)
