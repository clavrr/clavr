"""
Service Constants - Centralized configuration for all services

This module consolidates all hardcoded values, intervals, limits, and timeouts
used across services to eliminate duplication and enable easy configuration.
"""
import os
from typing import Dict, Any


class ServiceConstants:
    """Centralized constants for all services"""
    
    # ===================================================================
    # INDEXING CONSTANTS
    # ===================================================================
    
    # Time intervals (in seconds)
    EMAIL_INDEXING_INTERVAL_MIN = 30
    EMAIL_INDEXING_INTERVAL_MAX = 300
    EMAIL_INDEXING_INTERVAL_DEFAULT = int(os.getenv('EMAIL_INDEXING_INTERVAL', '60'))
    INBOX_INDEXING_INTERVAL_MIN = 15
    INBOX_INDEXING_INTERVAL_DEFAULT = int(os.getenv('INBOX_INDEXING_INTERVAL', '30'))
    
    # Batch sizes
    INDEXING_BATCH_SIZE_DEFAULT = 300
    INDEXING_BATCH_SIZE_SMALL = 150
    INDEXING_BATCH_SIZE_LARGE = 500
    INDEXING_BATCH_SIZE_MAX = 1000
    
    # Initial indexing
    INITIAL_INDEXING_DAYS = 30
    INITIAL_INDEXING_BATCH_SIZE = 300
    
    # Chunk sizes
    CHUNK_SIZE_DEFAULT = 500
    CHUNK_SIZE_LARGE = 1000
    
    # Rate limiting
    RATE_LIMIT_DELAY_DEFAULT = 0.1  # 100ms
    RATE_LIMIT_DELAY_INDEXING = float(os.getenv('INDEXING_RATE_LIMIT_DELAY', '0.5'))  # 500ms default to avoid 429s
    
    # ===================================================================
    # SYNC CONSTANTS
    # ===================================================================
    
    # Sync intervals
    SYNC_INTERVAL_DEFAULT = 900  # 15 minutes
    SYNC_INTERVAL_MIN = 300  # 5 minutes
    SYNC_RATE_LIMIT_DELAY = 0.1  # 100ms
    
    # Sync limits
    SYNC_LIMIT_FIRST_TIME = 300
    SYNC_LIMIT_INCREMENTAL = 500
    SYNC_LIMIT_FULL = 1000
    
    # ===================================================================
    # GMAIL WATCH CONSTANTS
    # ===================================================================
    
    WATCH_EXPIRATION_DAYS = 7
    
    # ===================================================================
    # PROFILE SERVICE CONSTANTS
    # ===================================================================
    
    PROFILE_STALE_THRESHOLD_DAYS = int(os.getenv('PROFILE_STALE_THRESHOLD_DAYS', '7'))
    PROFILE_MAX_UPDATES_PER_RUN = int(os.getenv('PROFILE_MAX_UPDATES_PER_RUN', '10'))
    PROFILE_UPDATE_INTERVAL_HOURS = int(os.getenv('PROFILE_UPDATE_INTERVAL_HOURS', '1'))
    PROFILE_SAMPLE_SIZE_FOR_CONFIDENCE = 50
    
    # ===================================================================
    # CACHE CONSTANTS
    # ===================================================================
    
    PROFILE_CACHE_MAX_SIZE = 1000
    PROFILE_CACHE_TTL_SECONDS = 3600  # 1 hour
    PROFILE_CACHE_CLEANUP_INTERVAL = 300  # 5 minutes
    
    # ===================================================================
    # GRAPH/RAG CONSTANTS
    # ===================================================================
    
    GRAPH_DEFAULT_TIME_RANGE_DAYS = 30
    GRAPH_MAX_QUERY_RESULTS = 1000

    GRAPH_LLM_ADVICE_MAX_LENGTH = 500
    
    # ===================================================================
    # CONFIGURATION CONSTANTS
    # ===================================================================
    
    CONFIG_SERVICE_TIMEOUT_DEFAULT = 30
    CONFIG_SERVICE_RETRY_ATTEMPTS_DEFAULT = 3
    
    # Tool preflight validation
    PREFLIGHT_CONFIDENCE_THRESHOLD = 0.7  # Minimum confidence for accepting entity resolutions
    
    # ===================================================================
    # QUERY LIMITS
    # ===================================================================
    
    QUERY_MAX_RESULTS_DEFAULT = 10
    QUERY_MAX_RESULTS_LARGE = 50
    QUERY_MAX_RESULTS_MAX = 100
    
    # ===================================================================
    # CONTENT TRUNCATION
    # ===================================================================
    
    CONTENT_PREVIEW_LENGTH = 200
    CONTENT_SUMMARY_LENGTH = 500
    CONTENT_FULL_TEXT_PREVIEW = 1000
    
    # ===================================================================
    # CRAWLER SYNC INTERVALS
    # ===================================================================
    
    # Sync intervals by crawler (in seconds)
    CALENDAR_SYNC_INTERVAL = 600   # 10 minutes - calendar changes frequently
    TASK_SYNC_INTERVAL = 600       # 10 minutes
    DRIVE_SYNC_INTERVAL = 3600     # 1 hour - files change less frequently
    NOTION_SYNC_INTERVAL = 1800    # 30 minutes
    ASANA_SYNC_INTERVAL = 900      # 15 minutes
    SLACK_SYNC_INTERVAL = 900      # 15 minutes
    KEEP_SYNC_INTERVAL = 3600      # 1 hour - notes change infrequently
    
    # Calendar lookback/lookahead
    CALENDAR_DAYS_AHEAD = 30  # Look ahead 30 days for calendar events
    CALENDAR_DAYS_BACK = 7    # Look back 7 days for calendar events
    
    # Event stream
    EVENT_TTL_SECONDS = 300  # 5 minute dedup window for event stream
    
    # Initial lookback for first-time sync
    INITIAL_LOOKBACK_DAYS = 7           # Default lookback for most crawlers
    INITIAL_LOOKBACK_DAYS_NOTES = 30    # Keep notes use longer lookback
    
    # Graph health
    STALE_NODE_THRESHOLD_DAYS = 180     # Nodes older than this may be stale
    
    # ===================================================================
    # INSIGHT SERVICE CONSTANTS
    # ===================================================================
    
    MIN_INSIGHT_CONFIDENCE = 0.75
    MAX_INSIGHTS_PER_RESPONSE = 2
    INSIGHT_MAX_AGE_HOURS = 48  # Don't show insights older than 48 hours
    
    # ===================================================================
    # HALLUCINATION CHECKER CONSTANTS
    # ===================================================================
    
    HALLUCINATION_BLOCK_THRESHOLD_NORMAL = 0.8
    HALLUCINATION_WARN_THRESHOLD_NORMAL = 0.5
    
    HALLUCINATION_BLOCK_THRESHOLD_STRICT = 0.6
    HALLUCINATION_WARN_THRESHOLD_STRICT = 0.3
    
    HALLUCINATION_BLOCK_THRESHOLD_LENIENT = 0.9
    HALLUCINATION_WARN_THRESHOLD_LENIENT = 0.7
    
    HALLUCINATION_NUMERICAL_TOLERANCE = 0.05
    
    # ===================================================================
    # VOICE SERVICE CONSTANTS
    # ===================================================================
    
    VOICE_ENERGY_THRESHOLD = 100  # Minimum RMS energy to process chunk
    
    # ===================================================================
    # CONFLICT DETECTOR CONSTANTS
    # ===================================================================
    
    CONFLICT_CALENDAR_OVERLAP_CONFIDENCE_BASE = 0.6
    CONFLICT_CALENDAR_OVERLAP_CONFIDENCE_MAX = 0.95
    CONFLICT_MAX_OVERLAP_MINUTES = 120
    
    CONFLICT_ATTENDEE_CONFIDENCE = 0.9
    
    CONFLICT_DEADLINE_CLUSTER_CONFIDENCE_BASE = 0.5
    CONFLICT_DEADLINE_CLUSTER_CONFIDENCE_MAX = 0.9
    
    CONFLICT_WORKLOAD_CONFIDENCE = 0.8
    CONFLICT_WORKLOAD_MEETING_HOURS = 5
    CONFLICT_WORKLOAD_TASK_COUNT = 2

    # ===================================================================
    # CONTEXT SERVICE CONSTANTS
    # ===================================================================
    
    CONTEXT_MAX_AGE_MINUTES = 30  # Max age for recent context entities
    
    # Integration display names
    INTEGRATION_NAMES = {
        'gmail': 'Gmail',
        'google_calendar': 'Google Calendar',
        'google_drive': 'Google Drive',
        'google_tasks': 'Google Tasks',
        'slack': 'Slack',
        'notion': 'Notion',
        'asana': 'Asana'
    }
    
    @classmethod
    def get_indexing_config(cls) -> Dict[str, Any]:
        """Get indexing configuration dictionary"""
        return {
            'interval': cls.EMAIL_INDEXING_INTERVAL_DEFAULT,
            'interval_min': cls.EMAIL_INDEXING_INTERVAL_MIN,
            'interval_max': cls.EMAIL_INDEXING_INTERVAL_MAX,
            'inbox_interval': cls.INBOX_INDEXING_INTERVAL_DEFAULT,
            'batch_size': cls.INDEXING_BATCH_SIZE_DEFAULT,
            'initial_days': cls.INITIAL_INDEXING_DAYS,
            'rate_limit_delay': cls.RATE_LIMIT_DELAY_INDEXING,
            'chunk_size': cls.CHUNK_SIZE_DEFAULT
        }
    
    @classmethod
    def get_sync_config(cls) -> Dict[str, Any]:
        """Get sync configuration dictionary"""
        return {
            'interval': cls.SYNC_INTERVAL_DEFAULT,
            'rate_limit_delay': cls.SYNC_RATE_LIMIT_DELAY,
            'limit_first_time': cls.SYNC_LIMIT_FIRST_TIME,
            'limit_incremental': cls.SYNC_LIMIT_INCREMENTAL,
            'limit_full': cls.SYNC_LIMIT_FULL
        }
    
    @classmethod
    def get_profile_config(cls) -> Dict[str, Any]:
        """Get profile service configuration dictionary"""
        return {
            'stale_threshold_days': cls.PROFILE_STALE_THRESHOLD_DAYS,
            'max_updates_per_run': cls.PROFILE_MAX_UPDATES_PER_RUN,
            'update_interval_hours': cls.PROFILE_UPDATE_INTERVAL_HOURS,
            'sample_size_for_confidence': cls.PROFILE_SAMPLE_SIZE_FOR_CONFIDENCE
        }
    
    @classmethod
    def get_cache_config(cls) -> Dict[str, Any]:
        """Get cache configuration dictionary"""
        return {
            'max_size': cls.PROFILE_CACHE_MAX_SIZE,
            'ttl_seconds': cls.PROFILE_CACHE_TTL_SECONDS,
            'cleanup_interval': cls.PROFILE_CACHE_CLEANUP_INTERVAL
        }

    @classmethod
    def get_integration_names(cls) -> Dict[str, str]:
        """Get mapping of provider keys to display names."""
        return cls.INTEGRATION_NAMES


# Convenience access
SERVICE_CONSTANTS = ServiceConstants()

