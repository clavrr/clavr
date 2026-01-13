"""
LLM Factory Constants

Centralized constants for LLM provider names and configuration.
Strictly specialized for Gemini Flash series (2.5 & 3.0).
"""
from typing import List, Tuple

# Provider Names
PROVIDER_GEMINI = "gemini"
PROVIDER_GOOGLE = "google"

# Model Identifiers - Google Gemini Flash Series
MODEL_GEMINI_3_FLASH = "gemini-3-flash-preview"
MODEL_GEMINI_2_5_FLASH = "gemini-2.5-flash"

# Provider Aliases (for flexible matching)
GEMINI_ALIASES: Tuple[str, ...] = (PROVIDER_GEMINI, PROVIDER_GOOGLE)
SUPPORTED_PROVIDERS: List[str] = [PROVIDER_GEMINI, PROVIDER_GOOGLE]

# Allowed Model List (Strict Enforcement)
ALLOWED_MODELS: List[str] = [MODEL_GEMINI_3_FLASH, MODEL_GEMINI_2_5_FLASH]

# Default Values
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TOP_P = 0.95
DEFAULT_TOP_K = 40
DEFAULT_TRANSPORT = "rest"
DEFAULT_PRIMARY_LLM = PROVIDER_GEMINI
DEFAULT_MODEL_NAME = MODEL_GEMINI_3_FLASH

# Gemini Safety Settings
# Default for productive use: BLOCK_ONLY_HIGH (very loose) or BLOCK_MEDIUM_AND_ABOVE (standard)
GEMINI_SAFETY_SETTINGS = {
    "HARM_CATEGORY_HARASSMENT": "BLOCK_MEDIUM_AND_ABOVE",
    "HARM_CATEGORY_HATE_SPEECH": "BLOCK_MEDIUM_AND_ABOVE",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_MEDIUM_AND_ABOVE",
    "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_MEDIUM_AND_ABOVE",
}

# Model Metadata (Context Windows and Capabilities)
MODEL_METADATA = {
    MODEL_GEMINI_3_FLASH: {"context_window": 1000000, "vision": True, "function_calling": True},
    MODEL_GEMINI_2_5_FLASH: {"context_window": 1000000, "vision": True, "function_calling": True},
}

# Log Prefix Constants
LOG_ERROR = "[ERROR]"
LOG_INFO = "[INFO]"
LOG_DEBUG = "[DEBUG]"
LOG_OK = "[OK]"

