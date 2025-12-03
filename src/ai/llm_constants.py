"""
LLM Factory Constants

Centralized constants for LLM provider names and configuration.
"""
from typing import List, Tuple

# Provider Names
PROVIDER_GEMINI = "gemini"
PROVIDER_GOOGLE = "google"
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"

# Provider Aliases (for flexible matching)
GEMINI_ALIASES: Tuple[str, ...] = (PROVIDER_GEMINI, PROVIDER_GOOGLE)
SUPPORTED_PROVIDERS: List[str] = [PROVIDER_GEMINI, PROVIDER_GOOGLE, PROVIDER_OPENAI, PROVIDER_ANTHROPIC]

# Default Values
DEFAULT_TEMPERATURE = 0.0
DEFAULT_TRANSPORT = "rest"  # REST is more stable than gRPC for Google
DEFAULT_PRIMARY_LLM = PROVIDER_GEMINI  # Primary LLM provider for all AI operations
DEFAULT_MODEL_NAME = "gpt-3.5-turbo"  # Default model for tiktoken token counting (MUST be OpenAI model for encoding)

# Log Prefix Constants
LOG_ERROR = "[ERROR]"
LOG_INFO = "[INFO]"
LOG_DEBUG = "[DEBUG]"

