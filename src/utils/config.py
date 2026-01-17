"""
Configuration management
"""
import os
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel


# ============================================
# CONFIGURATION DEFAULTS
# ============================================

class ConfigDefaults:
    """Default configuration values as constants"""
    
    # Email/IMAP/SMTP defaults
    IMAP_PORT = 993
    SMTP_PORT = 587
    EMAIL_FOLDER_INBOX = "INBOX"
    EMAIL_FOLDER_SENT = "Sent"
    EMAIL_FOLDER_ARCHIVE = "Archive"
    EMAIL_FOLDER_PROCESSED = "Processed"

    # Default promo patterns for email filtering
    EMAIL_PROMO_PATTERNS = [
        # Newsletter platforms
        '@substack.com', '@beehiiv.com',
        '@convertkit.com', '@ghost.io',
        '@interviewcake.com', 
        # Social media
        '@facebookmail.com', 
        # E-commerce / Streaming
        '@primevideo.com', '@email.amazon.com', '@netflix.com',
        '@spotify.com', '@doordash.com', 
        # Explicit marketing
        'newsletter@', 'marketing@',
    ]
    
    # Agent defaults
    AGENT_NAME = "Email AI Assistant"
    AGENT_CHECK_INTERVAL = 300  # seconds
    AGENT_MAX_CONCURRENT_EMAILS = 5
    AGENT_TIMEZONE_AUTO = "auto"
    AGENT_TIMEZONE_DEFAULT = "America/Los_Angeles"
    
    # AI/LLM defaults
    AI_PROVIDER_GEMINI = "gemini"
    AI_MODEL_DEFAULT = "gemini-3-flash-preview"
    AI_TEMPERATURE_DEFAULT = 0.0
    AI_MAX_TOKENS_DEFAULT = 1000
    AI_SYSTEM_PROMPT_DEFAULT = "You are a helpful email assistant."
    
    # Database defaults
    DATABASE_URL_DEFAULT = "sqlite:///./data/emails.db"
    DATABASE_POOL_SIZE = 5
    
    # RAG defaults
    RAG_EMBEDDING_PROVIDER_GEMINI = "gemini"
    RAG_EMBEDDING_MODEL_DEFAULT = "models/embedding-001"
    RAG_EMBEDDING_DIMENSION_DEFAULT = 768
    RAG_VECTOR_STORE_BACKEND_AUTO = "auto"
    RAG_COLLECTION_NAME_DEFAULT = "email-knowledge"
    RAG_CHUNK_SIZE_DEFAULT = 500
    RAG_CHUNK_OVERLAP_DEFAULT = 50
    RAG_DEFAULT_SEARCH_K = 10
    RAG_BATCH_SIZE_DEFAULT = 100
    RAG_EMBEDDING_BATCH_SIZE_DEFAULT = 50
    RAG_CACHE_TTL_HOURS_DEFAULT = 1
    RAG_EMBEDDING_CACHE_SIZE_DEFAULT = 1000
    RAG_EMBEDDING_CACHE_TTL_HOURS_DEFAULT = 24
    RAG_QUERY_CACHE_TTL_SECONDS_DEFAULT = 180
    RAG_QUERY_CACHE_SIZE_DEFAULT = 5000
    RAG_MAX_RETRIES_DEFAULT = 3
    RAG_RETRY_BASE_DELAY_DEFAULT = 1.0
    RAG_SEARCH_TIMEOUT_SECONDS_DEFAULT = 5.0
    RAG_PARALLEL_WORKERS_DEFAULT = 10
    RAG_RERANK_SEMANTIC_WEIGHT = 0.4
    RAG_RERANK_KEYWORD_WEIGHT = 0.2
    RAG_RERANK_METADATA_WEIGHT = 0.2
    RAG_RERANK_RECENCY_WEIGHT = 0.2
    RAG_MAX_QUERY_VARIANTS_DEFAULT = 3
    RAG_MIN_CONFIDENCE_DEFAULT = 0.3
    RAG_CIRCUIT_BREAKER_THRESHOLD_DEFAULT = 5
    RAG_CIRCUIT_BREAKER_TIMEOUT_DEFAULT = 60
    
    # Logging defaults
    LOGGING_LEVEL_INFO = "INFO"
    LOGGING_FILE_DEFAULT = "logs/agent.log"
    LOGGING_FORMAT_JSON = "json"
    LOGGING_ROTATION_DAILY = "daily"
    LOGGING_RETENTION_DEFAULT = "30 days"
    
    # Server defaults
    SERVER_HOST_DEFAULT = "0.0.0.0"
    SERVER_PORT_DEFAULT = 8000
    API_BASE_URL_DEFAULT = "http://localhost:8000"
    FRONTEND_URL_DEFAULT = "http://localhost:3000"
    
    # Ghost Collaborator defaults
    GHOST_BUG_KEYWORDS = ["bug", "broken", "error", "crash", "not working", "failed", "issue", "regression"]
    GHOST_URGENT_KEYWORDS = ["urgent", "asap", "blocker", "critical", "emergency", "p0", "p1"]
    GHOST_DECISION_KEYWORDS = ["should we", "what do you think", "decide", "vote", "alignment", "agreement"]
    GHOST_ACTION_KEYWORDS = ["todo", "action item", "follow up", "need to", "must", "deadline"]
    GHOST_CONFIDENCE_THRESHOLD = 0.3
    GHOST_HEATED_THRESHOLD = 0.5
    
    # Config file defaults
    CONFIG_PATH_DEFAULT = "config/config.yaml"
    
    # Timezone mapping
    TIMEZONE_AUTO = "auto"
    TIMEZONE_DEFAULT = "America/Los_Angeles"
    TIMEZONE_PST = "America/Los_Angeles"
    TIMEZONE_PDT = "America/Los_Angeles"
    TIMEZONE_EST = "America/New_York"
    TIMEZONE_EDT = "America/New_York"
    TIMEZONE_CST = "America/Chicago"
    TIMEZONE_CDT = "America/Chicago"
    TIMEZONE_MST = "America/Denver"
    TIMEZONE_MDT = "America/Denver"
    TIMEZONE_UTC = "UTC"
    TIMEZONE_GMT = "GMT"
    
    # Resilience defaults
    CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 30.0
    CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS = 3
    
    # Retry defaults
    RETRY_MAX_RETRIES = 3
    RETRY_BASE_DELAY = 1.0
    RETRY_MAX_DELAY = 60.0
    RETRY_EXPONENTIAL_BASE = 2.0
    
    # Middleware defaults
    AUTH_SESSION_TTL_MINUTES = 60
    AUTH_CACHE_TTL_SECONDS = 60
    AUTH_CACHE_MAX_SIZE = 1000
    CSRF_TOKEN_EXPIRES_SECONDS = 3600
    CSRF_EXCLUDED_PATHS = [
        "/health",
        "/",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/metrics",
        "/auth/google",
        "/auth/google/login",
        "/auth/google/callback",
    ]
    
    # Rate limit defaults
    RATE_LIMIT_PER_MINUTE = 60
    RATE_LIMIT_PER_HOUR = 1000
    RATE_LIMIT_EXCLUDED_PATHS = [
        "/health", "/docs", "/openapi.json", "/redoc", "/metrics",
        "/auth/google/login", "/auth/google/callback",
        "/api/auth/google/login", "/api/auth/google/callback",
        "/integrations/status", "/api/integrations/status",
        "/auth/session/status", "/api/auth/session/status",
        "/auth/me", "/api/auth/me", "/api/conversations"
    ]
    
    # Security headers defaults
    SECURITY_SENSITIVE_PATHS = [
        "/auth", "/api/auth", "/api/chat", "/api/emails",
        "/api/calendar", "/api/tasks", "/api/profile",
        "/api/admin", "/api/export"
    ]
    
    # OAuth Scopes
    OAUTH_SCOPE_GMAIL = "https://www.googleapis.com/auth/gmail.readonly"
    OAUTH_SCOPE_CALENDAR = "https://www.googleapis.com/auth/calendar"
    OAUTH_SCOPE_TASKS = "https://www.googleapis.com/auth/tasks.readonly"
    OAUTH_SCOPE_DRIVE = "https://www.googleapis.com/auth/drive.readonly"
    # NOTE: Keep scope requires Google Workspace Enterprise and is not included
    # OAUTH_SCOPE_KEEP = "https://www.googleapis.com/auth/keep"
    
    # Combined Google Scope (All services - excluding Keep which requires Enterprise)
    OAUTH_SCOPE_GOOGLE_ALL = f"{OAUTH_SCOPE_GMAIL} {OAUTH_SCOPE_CALENDAR} {OAUTH_SCOPE_TASKS} {OAUTH_SCOPE_DRIVE}"
    
    OAUTH_SCOPE_SLACK = "channels:read,chat:write,files:read,files:write,users:read,users:read.email"
    OAUTH_SCOPE_ASANA = "default"
    OAUTH_SCOPE_LINEAR = "read,write"
    
    # OAuth URLs
    OAUTH_URL_GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
    OAUTH_URL_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
    OAUTH_URL_SLACK_AUTH = "https://slack.com/oauth/v2/authorize"
    OAUTH_URL_SLACK_TOKEN = "https://slack.com/api/oauth.v2.access"
    OAUTH_URL_NOTION_AUTH = "https://api.notion.com/v1/oauth/authorize"
    OAUTH_URL_NOTION_TOKEN = "https://api.notion.com/v1/oauth/token"
    OAUTH_URL_ASANA_AUTH = "https://app.asana.com/-/oauth_authorize"
    OAUTH_URL_ASANA_TOKEN = "https://app.asana.com/-/oauth_token"
    OAUTH_URL_LINEAR_AUTH = "https://linear.app/oauth/authorize"
    OAUTH_URL_LINEAR_TOKEN = "https://api.linear.app/oauth/token"

    # Default OAuth Redirect URIs
    OAUTH_REDIRECT_GOOGLE = "${API_BASE_URL}/auth/google/callback"
    OAUTH_REDIRECT_SLACK = "${API_BASE_URL}/integrations/slack/callback"
    OAUTH_REDIRECT_NOTION = "${API_BASE_URL}/integrations/notion/callback"
    OAUTH_REDIRECT_ASANA = "${API_BASE_URL}/integrations/asana/callback"
    OAUTH_REDIRECT_LINEAR = "${API_BASE_URL}/integrations/linear/callback"
    
    # Calendar Tool Defaults
    CALENDAR_SEARCH_DAYS_BACK = 7
    CALENDAR_SEARCH_DAYS_AHEAD = 90
    CALENDAR_DEFAULT_DURATION = 60
    CALENDAR_NLP_FILLER_WORDS = ['my', 'meeting', 'scheduled', 'for', 'the', 'event', 'appointment']
    CALENDAR_DATE_CLEANUP_PATTERNS = [
        r'tomorrow', r'today', r'yesterday', 
        r'at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)', 
        r'\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)',
        r'next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)',
        r'this\s+(?:week|month|afternoon|morning|evening)',
        r'in\s+the\s+(?:morning|afternoon|evening)',
        r'just\s+for\s+me'
    ]
    CALENDAR_MOVE_PATTERNS = [
        r"(?:move|reschedule|change)\s+(.*?)\s+(?:to|to be at|at|for|till)\s+(.*)"
    ]
    CALENDAR_SUGGESTIONS_MAX = 3
    CALENDAR_SUGGESTIONS_DAYS_AHEAD = 2


# ============================================
# CONFIGURATION MODELS
# ============================================

class IMAPConfig(BaseModel):
    """IMAP configuration"""
    server: str
    port: int = ConfigDefaults.IMAP_PORT
    use_ssl: bool = True


class SMTPConfig(BaseModel):
    """SMTP configuration"""
    server: str
    port: int = ConfigDefaults.SMTP_PORT
    use_tls: bool = True


class EmailFolders(BaseModel):
    """Email folder configuration"""
    inbox: str = ConfigDefaults.EMAIL_FOLDER_INBOX
    sent: str = ConfigDefaults.EMAIL_FOLDER_SENT
    archive: str = ConfigDefaults.EMAIL_FOLDER_ARCHIVE
    processed: str = ConfigDefaults.EMAIL_FOLDER_PROCESSED


class EmailConfig(BaseModel):
    """Email configuration"""
    address: str
    password: str
    imap: IMAPConfig
    smtp: SMTPConfig
    folders: EmailFolders = EmailFolders()


class AgentConfig(BaseModel):
    """Agent configuration"""
    name: str = ConfigDefaults.AGENT_NAME
    email: str
    check_interval: int = ConfigDefaults.AGENT_CHECK_INTERVAL
    auto_reply: bool = False
    dry_run: bool = True
    max_concurrent_emails: int = ConfigDefaults.AGENT_MAX_CONCURRENT_EMAILS
    timezone: str = ConfigDefaults.AGENT_TIMEZONE_AUTO  # "auto" to detect from system, or specify like "America/Los_Angeles", "America/New_York", "UTC"


class AIConfig(BaseModel):
    """AI/LLM configuration"""
    provider: str = ConfigDefaults.AI_PROVIDER_GEMINI
    model: str = ConfigDefaults.AI_MODEL_DEFAULT
    api_key: str
    temperature: float = ConfigDefaults.AI_TEMPERATURE_DEFAULT
    max_tokens: int = ConfigDefaults.AI_MAX_TOKENS_DEFAULT
    system_prompt: str = ConfigDefaults.AI_SYSTEM_PROMPT_DEFAULT


class DatabaseConfig(BaseModel):
    """Database configuration"""
    url: str = ConfigDefaults.DATABASE_URL_DEFAULT
    echo: bool = False
    pool_size: int = ConfigDefaults.DATABASE_POOL_SIZE


class RAGConfig(BaseModel):
    """RAG (Retrieval-Augmented Generation) configuration"""
    # Embedding configuration
    embedding_provider: str = ConfigDefaults.RAG_EMBEDDING_PROVIDER_GEMINI  # "gemini" or "sentence-transformers"
    embedding_model: str = ConfigDefaults.RAG_EMBEDDING_MODEL_DEFAULT  # Gemini model or sentence-transformer model name
    embedding_dimension: int = ConfigDefaults.RAG_EMBEDDING_DIMENSION_DEFAULT  # 768 for Gemini/all-mpnet-base-v2, 384 for all-MiniLM-L6-v2
    
    # Vector store configuration
    vector_store_backend: str = ConfigDefaults.RAG_VECTOR_STORE_BACKEND_AUTO  # "auto", "qdrant", or "postgres"
    collection_name: str = ConfigDefaults.RAG_COLLECTION_NAME_DEFAULT
    
    # Chunking configuration
    chunk_size: int = ConfigDefaults.RAG_CHUNK_SIZE_DEFAULT  # Target chunk size in words
    chunk_overlap: int = ConfigDefaults.RAG_CHUNK_OVERLAP_DEFAULT  # Overlap between chunks in words
    use_semantic_chunking: bool = True  # Respect sentence/paragraph boundaries
    
    # Search configuration
    default_search_k: int = ConfigDefaults.RAG_DEFAULT_SEARCH_K  # Default number of results (increased from 5 for better reranking)
    rerank_results: bool = True  # Enable reranking for better accuracy
    use_hybrid_search: bool = True  # Combine semantic + keyword search
    
    # Batch processing
    batch_size: int = ConfigDefaults.RAG_BATCH_SIZE_DEFAULT  # Documents per batch
    embedding_batch_size: int = ConfigDefaults.RAG_EMBEDDING_BATCH_SIZE_DEFAULT  # Embeddings per batch
    
    # Caching configuration
    cache_ttl_hours: int = ConfigDefaults.RAG_CACHE_TTL_HOURS_DEFAULT  # Context cache TTL
    embedding_cache_size: int = ConfigDefaults.RAG_EMBEDDING_CACHE_SIZE_DEFAULT  # LRU cache size for embeddings
    embedding_cache_ttl_hours: int = ConfigDefaults.RAG_EMBEDDING_CACHE_TTL_HOURS_DEFAULT  # Embedding cache TTL
    query_cache_ttl_seconds: int = ConfigDefaults.RAG_QUERY_CACHE_TTL_SECONDS_DEFAULT  # Query result cache TTL (reduced from 300 for fresher results)
    query_cache_size: int = ConfigDefaults.RAG_QUERY_CACHE_SIZE_DEFAULT  # Query cache size (increased from 1000)
    
    # Performance tuning
    max_retries: int = ConfigDefaults.RAG_MAX_RETRIES_DEFAULT  # Retry attempts for API calls
    retry_base_delay: float = ConfigDefaults.RAG_RETRY_BASE_DELAY_DEFAULT  # Base delay for exponential backoff
    search_timeout_seconds: float = ConfigDefaults.RAG_SEARCH_TIMEOUT_SECONDS_DEFAULT  # Maximum search timeout
    parallel_workers: int = ConfigDefaults.RAG_PARALLEL_WORKERS_DEFAULT  # Number of parallel workers for multi-query search
    enable_search_diversity: bool = True  # Remove near-duplicate results
    
    # Reranking weights (sum should be ~1.0)
    rerank_semantic_weight: float = ConfigDefaults.RAG_RERANK_SEMANTIC_WEIGHT
    rerank_keyword_weight: float = ConfigDefaults.RAG_RERANK_KEYWORD_WEIGHT
    rerank_metadata_weight: float = ConfigDefaults.RAG_RERANK_METADATA_WEIGHT
    rerank_recency_weight: float = ConfigDefaults.RAG_RERANK_RECENCY_WEIGHT  # Increased to prioritize recent emails
    
    # Query enhancement
    use_query_enhancement: bool = True
    use_llm_expansion: bool = False  # LLM-based expansion (slower but more accurate)
    
    # Multi-query retrieval
    use_multi_query: bool = True
    max_query_variants: int = ConfigDefaults.RAG_MAX_QUERY_VARIANTS_DEFAULT
    
    # Confidence filtering
    min_confidence: float = ConfigDefaults.RAG_MIN_CONFIDENCE_DEFAULT  # Minimum confidence threshold (0-1)
    
    # Circuit Breaker
    circuit_breaker_threshold: int = ConfigDefaults.RAG_CIRCUIT_BREAKER_THRESHOLD_DEFAULT
    circuit_breaker_timeout: int = ConfigDefaults.RAG_CIRCUIT_BREAKER_TIMEOUT_DEFAULT


class LoggingConfig(BaseModel):
    """Logging configuration"""
    level: str = ConfigDefaults.LOGGING_LEVEL_INFO
    file: str = ConfigDefaults.LOGGING_FILE_DEFAULT
    format: str = ConfigDefaults.LOGGING_FORMAT_JSON
    rotation: str = ConfigDefaults.LOGGING_ROTATION_DAILY
    retention: str = ConfigDefaults.LOGGING_RETENTION_DEFAULT


class SecurityConfig(BaseModel):
    """Security configuration"""
    secret_key: str
    encryption_key: str
    encrypt_stored_emails: bool = True
    
    # Session settings
    session_ttl_minutes: int = ConfigDefaults.AUTH_SESSION_TTL_MINUTES
    session_cache_ttl_seconds: int = ConfigDefaults.AUTH_CACHE_TTL_SECONDS
    session_cache_max_size: int = ConfigDefaults.AUTH_CACHE_MAX_SIZE
    
    # CSRF settings
    csrf_token_expires: int = ConfigDefaults.CSRF_TOKEN_EXPIRES_SECONDS
    csrf_excluded_paths: List[str] = ConfigDefaults.CSRF_EXCLUDED_PATHS
    
    # Security Headers settings
    sensitive_paths: List[str] = ConfigDefaults.SECURITY_SENSITIVE_PATHS


class ServerConfig(BaseModel):
    """Server configuration"""
    host: str = ConfigDefaults.SERVER_HOST_DEFAULT
    port: int = ConfigDefaults.SERVER_PORT_DEFAULT
    api_base_url: str = "${API_BASE_URL}"
    frontend_url: str = "${FRONTEND_URL}"
    
    # Rate limiting
    rate_limit_per_minute: int = ConfigDefaults.RATE_LIMIT_PER_MINUTE
    rate_limit_per_hour: int = ConfigDefaults.RATE_LIMIT_PER_HOUR
    rate_limit_excluded_paths: List[str] = ConfigDefaults.RATE_LIMIT_EXCLUDED_PATHS


class FilterConfig(BaseModel):
    """Email filter configuration"""
    name: str
    type: str
    patterns: List[str]
    priority: Optional[int] = None
    action: Optional[str] = None


class STTConfig(BaseModel):
    """Speech-to-Text configuration"""
    provider: str = "google"  # "google" or other providers
    language: str = "en-US"  # Language code (e.g., "en-US", "en-GB")
    sample_rate: int = 24000  # Audio sample rate in Hz (24000 for webm/opus)


class TTSConfig(BaseModel):
    """Text-to-Speech configuration"""
    provider: str = "gemini"  # "gemini" (recommended) or "google" (cloud)
    voice: str = "en-US-Neural2-D"  # Voice name (e.g., "en-US-Neural2-D", "en-US-Neural2-F")
    language: str = "en-US"  # Language code
    speaking_rate: float = 1.0  # Speaking rate (0.25 to 4.0, 1.0 = normal)
    pitch: float = 0.0  # Pitch adjustment (-20.0 to 20.0 semitones, 0.0 = normal)


class VoiceConfig(BaseModel):
    """Voice interface configuration"""
    stt: STTConfig = STTConfig()
    tts: TTSConfig = TTSConfig()
    enabled: bool = True  # Enable/disable voice features


class OAuthConfig(BaseModel):
    """ OAuth provider configuration """
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    auth_url: str
    token_url: str
    scopes: Optional[str] = None
    redirect_uri: str
    owner: Optional[str] = None


class OAuthConfigs(BaseModel):
    """ Collection of OAuth configurations """
    providers: Dict[str, OAuthConfig]


class IndexingConfig(BaseModel):
    """Indexing/Graph configuration"""
    graph_backend: str = "arangodb"
    arango_url: str = "http://localhost:8529"
    arango_user: str = "root"
    arango_password: str = "password"
    arango_database: str = "clavr"
    enable_knowledge_graph: bool = True
    validation_mode: str = "strict"
    vector_score_weight: float = 0.6
    graph_score_weight: float = 0.4


class Config(BaseModel):
    """Main configuration"""
    agent: AgentConfig
    email: EmailConfig
    ai: AIConfig
    google_maps_api_key: Optional[str] = None
    linear_api_key: Optional[str] = None
    linear_webhook_secret: Optional[str] = None
    database: DatabaseConfig = DatabaseConfig()
    logging: LoggingConfig = LoggingConfig()
    security: Optional[SecurityConfig] = None
    server: Optional[ServerConfig] = None
    filters: List[FilterConfig] = []
    rag: Optional[RAGConfig] = None  # RAG configuration (optional, uses defaults if not provided)
    indexing: IndexingConfig = IndexingConfig() # Indexing/Graph configuration
    voice: Optional[VoiceConfig] = None  # Voice configuration (optional, uses defaults if not provided)
    oauth: Optional[OAuthConfigs] = None # OAuth configurations (optional)


def load_config(config_path: str = ConfigDefaults.CONFIG_PATH_DEFAULT) -> Config:
    """
    Load configuration from YAML file and environment variables.
    """
    # Load environment variables
    load_dotenv()
    
    # Read YAML config
    with open(config_path, 'r') as f:
        config_dict = yaml.safe_load(f)
    
    # Replace environment variable placeholders
    config_dict = _replace_env_vars(config_dict)
    
    # Load Google Maps API key from environment if not in YAML
    if not config_dict.get('google_maps_api_key'):
        config_dict['google_maps_api_key'] = os.getenv('GOOGLE_MAPS_API_KEY')
    
    # Load Linear API key from environment if not in YAML
    if not config_dict.get('linear_api_key'):
        config_dict['linear_api_key'] = os.getenv('LINEAR_API_KEY')
    
    if not config_dict.get('linear_webhook_secret'):
        config_dict['linear_webhook_secret'] = os.getenv('LINEAR_WEBHOOK_SECRET')
    
    # Initialize OAuth providers if missing
    if 'oauth' not in config_dict:
        config_dict['oauth'] = {'providers': {}}
    
    _ensure_oauth_defaults(config_dict['oauth']['providers'])
    
    # Create and validate config
    return Config(**config_dict)

def _ensure_oauth_defaults(providers: Dict[str, Any]):
    """Ensure default OAuth providers are present and configured from env vars."""
    api_url = os.getenv("API_BASE_URL", ConfigDefaults.API_BASE_URL_DEFAULT).rstrip('/')
    
    defaults = {
        "google": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_url": ConfigDefaults.OAUTH_URL_GOOGLE_AUTH,
            "token_url": ConfigDefaults.OAUTH_URL_GOOGLE_TOKEN,
            "scopes": ConfigDefaults.OAUTH_SCOPE_GOOGLE_ALL,
            "redirect_uri": f"{api_url}/auth/google/callback"
        },
        "slack": {
            "client_id": os.getenv("SLACK_CLIENT_ID"),
            "client_secret": os.getenv("SLACK_CLIENT_SECRET"),
            "auth_url": ConfigDefaults.OAUTH_URL_SLACK_AUTH,
            "token_url": ConfigDefaults.OAUTH_URL_SLACK_TOKEN,
            "scopes": ConfigDefaults.OAUTH_SCOPE_SLACK,
            "redirect_uri": f"{api_url}/integrations/slack/callback"
        },
        "notion": {
            "client_id": os.getenv("NOTION_CLIENT_ID"),
            "client_secret": os.getenv("NOTION_CLIENT_SECRET"),
            "auth_url": ConfigDefaults.OAUTH_URL_NOTION_AUTH,
            "token_url": ConfigDefaults.OAUTH_URL_NOTION_TOKEN,
            "redirect_uri": f"{api_url}/integrations/notion/callback",
            "owner": "user"
        },
        "asana": {
            "client_id": os.getenv("ASANA_CLIENT_ID"),
            "client_secret": os.getenv("ASANA_CLIENT_SECRET"),
            "auth_url": ConfigDefaults.OAUTH_URL_ASANA_AUTH,
            "token_url": ConfigDefaults.OAUTH_URL_ASANA_TOKEN,
            "scopes": ConfigDefaults.OAUTH_SCOPE_ASANA,
            "redirect_uri": f"{api_url}/integrations/asana/callback"
        },
        "linear": {
            "client_id": os.getenv("LINEAR_CLIENT_ID"),
            "client_secret": os.getenv("LINEAR_CLIENT_SECRET"),
            "auth_url": ConfigDefaults.OAUTH_URL_LINEAR_AUTH,
            "token_url": ConfigDefaults.OAUTH_URL_LINEAR_TOKEN,
            "scopes": ConfigDefaults.OAUTH_SCOPE_LINEAR,
            "redirect_uri": f"{api_url}/integrations/linear/callback"
        }
    }
    
    for provider, default_config in defaults.items():
        if provider not in providers:
            providers[provider] = default_config
        else:
            # Update missing fields from env/defaults
            for key, val in default_config.items():
                if providers[provider].get(key) is None:
                    providers[provider][key] = val


def _replace_env_vars(obj: Any) -> Any:
    """
    Recursively replace ${VAR} and ${VAR:-default} placeholders with environment variables.
    Supports bash-style default values with ${VAR:-default_value} syntax.
    """
    if isinstance(obj, dict):
        return {k: _replace_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_replace_env_vars(item) for item in obj]
    elif isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
        inner = obj[2:-1]  # Extract content between ${ and }
        
        # Handle ${VAR:-default} syntax
        if ":-" in inner:
            var_name, default_value = inner.split(":-", 1)
            env_value = os.getenv(var_name)
            return env_value if env_value else default_value
        
        # Handle simple ${VAR} syntax
        var_name = inner
        env_value = os.getenv(var_name)
        if env_value:
            return env_value
        # Provide defaults for common URLs
        if var_name == "API_BASE_URL":
            return os.getenv("API_BASE_URL", ConfigDefaults.API_BASE_URL_DEFAULT)
        if var_name == "FRONTEND_URL":
            return os.getenv("FRONTEND_URL", ConfigDefaults.FRONTEND_URL_DEFAULT)
        return obj
    return obj


def get_api_base_url(config: Optional[Config] = None) -> str:
    """Get API base URL from config or environment"""
    if config and config.server and config.server.api_base_url:
        return config.server.api_base_url
    return os.getenv("API_BASE_URL", ConfigDefaults.API_BASE_URL_DEFAULT)


def get_frontend_url(config: Optional[Config] = None) -> str:
    """Get frontend URL from config or environment"""
    if config and config.server and config.server.frontend_url:
        return config.server.frontend_url
    return os.getenv("FRONTEND_URL", ConfigDefaults.FRONTEND_URL_DEFAULT)


def get_timezone(config: Optional[Config] = None) -> str:
    """
    Get timezone from config or environment variable.
    
    Args:
        config: Optional Config object
        
    Returns:
        Timezone string (e.g., "America/Los_Angeles", "UTC")
        Defaults to "America/Los_Angeles" if not configured
    """
    # Check environment variable first
    env_tz = os.getenv("TIMEZONE")
    if env_tz and env_tz != ConfigDefaults.TIMEZONE_AUTO:
        return env_tz
    
    # Check config
    if config and config.agent and config.agent.timezone:
        tz = config.agent.timezone
        if tz == ConfigDefaults.TIMEZONE_AUTO:
            # Auto-detect from system
            try:
                import time
                tz_name = time.tzname[0] if time.daylight == 0 else time.tzname[1]
                # Try to map common timezone abbreviations to IANA names
                tz_map = {
                    'PST': ConfigDefaults.TIMEZONE_PST,
                    'PDT': ConfigDefaults.TIMEZONE_PDT,
                    'EST': ConfigDefaults.TIMEZONE_EST,
                    'EDT': ConfigDefaults.TIMEZONE_EDT,
                    'CST': ConfigDefaults.TIMEZONE_CST,
                    'CDT': ConfigDefaults.TIMEZONE_CDT,
                    'MST': ConfigDefaults.TIMEZONE_MST,
                    'MDT': ConfigDefaults.TIMEZONE_MDT,
                    'UTC': ConfigDefaults.TIMEZONE_UTC,
                    'GMT': ConfigDefaults.TIMEZONE_GMT,
                }
                if tz_name in tz_map:
                    return tz_map[tz_name]
                
                # Check for lowercase as well
                if tz_name.upper() in tz_map:
                    return tz_map[tz_name.upper()]

                # Default to system timezone if available
                import datetime
                local_tz = datetime.datetime.now().astimezone().tzinfo
                if hasattr(local_tz, 'key'):
                    return local_tz.key
                if hasattr(local_tz, 'zone'): # For pytz
                    return local_tz.zone
            except Exception as e:
                import logging
                logging.getLogger(__name__).debug(f"Timezone detection failed: {e}")
            # Fallback to default
            return ConfigDefaults.TIMEZONE_DEFAULT
        return tz
    
    # Default fallback
    return ConfigDefaults.TIMEZONE_DEFAULT
