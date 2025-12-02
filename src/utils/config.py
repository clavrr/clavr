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
    
    # Agent defaults
    AGENT_NAME = "Email AI Assistant"
    AGENT_CHECK_INTERVAL = 300  # seconds
    AGENT_MAX_CONCURRENT_EMAILS = 5
    AGENT_TIMEZONE_AUTO = "auto"
    AGENT_TIMEZONE_DEFAULT = "America/Los_Angeles"
    
    # AI/LLM defaults
    AI_PROVIDER_GEMINI = "gemini"
    AI_MODEL_DEFAULT = "gemini-2.5-flash"
    AI_TEMPERATURE_DEFAULT = 0.7
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
    vector_store_backend: str = ConfigDefaults.RAG_VECTOR_STORE_BACKEND_AUTO  # "auto", "pinecone", or "postgres" only
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


class ServerConfig(BaseModel):
    """Server configuration"""
    host: str = ConfigDefaults.SERVER_HOST_DEFAULT
    port: int = ConfigDefaults.SERVER_PORT_DEFAULT
    api_base_url: str = "${API_BASE_URL}"  # Defaults to http://localhost:8000 if not set
    frontend_url: str = "${FRONTEND_URL}"  # Defaults to http://localhost:3000 if not set


class FilterConfig(BaseModel):
    """Email filter configuration"""
    name: str
    type: str
    patterns: List[str]
    priority: Optional[int] = None
    action: Optional[str] = None


class Config(BaseModel):
    """Main configuration"""
    agent: AgentConfig
    email: EmailConfig
    ai: AIConfig
    database: DatabaseConfig = DatabaseConfig()
    logging: LoggingConfig = LoggingConfig()
    security: Optional[SecurityConfig] = None
    server: Optional[ServerConfig] = None
    filters: List[FilterConfig] = []
    rag: Optional[RAGConfig] = None  # RAG configuration (optional, uses defaults if not provided)


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
    
    # Create and validate config
    return Config(**config_dict)


def _replace_env_vars(obj: Any) -> Any:
    """
    Recursively replace ${VAR} placeholders with environment variables.
    """
    if isinstance(obj, dict):
        return {k: _replace_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_replace_env_vars(item) for item in obj]
    elif isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
        var_name = obj[2:-1]
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
                }
                if tz_name in tz_map:
                    return tz_map[tz_name]
                # Default to system timezone if available
                import datetime
                local_tz = datetime.datetime.now().astimezone().tzinfo
                if hasattr(local_tz, 'key'):
                    return local_tz.key
            except Exception:
                pass
            # Fallback to default
            return ConfigDefaults.TIMEZONE_DEFAULT
        return tz
    
    # Default fallback
    return ConfigDefaults.TIMEZONE_DEFAULT
