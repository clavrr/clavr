"""
Centralized LLM Client Factory for Google Gemini with streaming capabilities, caching, and error handling

This module provides a singleton factory pattern for creating and managing
Google Gemini LLM clients.

Features:
- Singleton pattern for efficient resource management
- Intelligent caching of LLM instances
- Support for streaming (sync and async)
- Comprehensive error handling and validation
- Type-safe client creation
- Thread-safe operations

Usage:
    from src.ai.llm_factory import LLMFactory
    from src.utils.config import load_config
    
    config = load_config()
    
    # Get LLM for configured provider
    llm = LLMFactory.get_llm_for_provider(config, temperature=0.7)
    
    # Stream responses
    async for chunk in LLMFactory.stream_llm_response(config, "Hello"):
        print(chunk, end="")
"""
from typing import Optional, AsyncGenerator, Generator, Dict, Any, List
from threading import Lock
import asyncio

from langchain_google_genai import ChatGoogleGenerativeAI, HarmCategory, HarmBlockThreshold

from ..utils.config import Config
from ..utils.logger import setup_logger
from .llm_constants import (
    PROVIDER_GEMINI, PROVIDER_GOOGLE,
    GEMINI_ALIASES, ALLOWED_MODELS, DEFAULT_TEMPERATURE, DEFAULT_MAX_TOKENS,
    DEFAULT_TOP_P, DEFAULT_TOP_K, DEFAULT_TRANSPORT,
    GEMINI_SAFETY_SETTINGS,
    LOG_ERROR, LOG_INFO, LOG_DEBUG, LOG_OK
)

logger = setup_logger(__name__)

# Constants for validation
MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 2.0
MIN_MAX_TOKENS = 1
MAX_MAX_TOKENS = 100000


class LLMFactory:
    """
    Factory for creating and managing Google Gemini LLM clients with intelligent caching.
    
    Implements singleton pattern to ensure efficient resource management
    and consistent client reuse across the application.
    
    Thread-safe singleton implementation ensures safe concurrent access.
    """
    
    _instance: Optional['LLMFactory'] = None
    _lock: Lock = Lock()
    
    # Google Gemini client cache (keyed by configuration parameters)
    _client_cache: Dict[str, ChatGoogleGenerativeAI] = {}
    
    def __new__(cls):
        """Thread-safe singleton implementation"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    @staticmethod
    def _validate_temperature(temperature: float) -> None:
        """
        Validate temperature parameter.
        
        Args:
            temperature: Temperature value to validate
            
        Raises:
            ValueError: If temperature is out of valid range
        """
        if not (MIN_TEMPERATURE <= temperature <= MAX_TEMPERATURE):
            raise ValueError(
                f"Temperature must be between {MIN_TEMPERATURE} and {MAX_TEMPERATURE}, "
                f"got {temperature}"
            )
    
    @staticmethod
    def _validate_max_tokens(max_tokens: Optional[int]) -> None:
        """
        Validate max_tokens parameter.
        
        Args:
            max_tokens: Max tokens value to validate
            
        Raises:
            ValueError: If max_tokens is out of valid range
        """
        if max_tokens is not None and not (MIN_MAX_TOKENS <= max_tokens <= MAX_MAX_TOKENS):
            raise ValueError(
                f"max_tokens must be between {MIN_MAX_TOKENS} and {MAX_MAX_TOKENS}, "
                f"got {max_tokens}"
            )
    
    @staticmethod
    def _validate_config(config: Config) -> None:
        """
        Validate configuration object.
        
        Args:
            config: Configuration object to validate
            
        Raises:
            ValueError: If config is invalid or missing required fields
        """
        if not config:
            raise ValueError("Config object is required")
        
        if not hasattr(config, 'ai') or not config.ai:
            raise ValueError("Config must have 'ai' attribute")
        
        if not config.ai.api_key:
            raise ValueError("API key is required in config.ai.api_key")
        
        if not config.ai.provider:
            raise ValueError("Provider is required in config.ai.provider")
        
        # Validate provider is Gemini/Google
        provider = config.ai.provider.lower()
        if provider not in GEMINI_ALIASES:
            raise ValueError(
                f"Unsupported provider: '{provider}'. "
                f"Only Gemini/Google providers are supported: {', '.join(GEMINI_ALIASES)}"
            )
    
    @staticmethod
    def _resolve_safety_settings(settings: Optional[Any]) -> Dict[HarmCategory, HarmBlockThreshold]:
        """
        Convert string-based safety settings to official enums.
        """
        if not settings:
            return {}
            
        resolved = {}
        # Mapping for string to enum conversion
        category_map = {
            "HARM_CATEGORY_HARASSMENT": HarmCategory.HARM_CATEGORY_HARASSMENT,
            "HARM_CATEGORY_HATE_SPEECH": HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            "HARM_CATEGORY_SEXUALLY_EXPLICIT": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            "HARM_CATEGORY_DANGEROUS_CONTENT": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        }
        threshold_map = {
            "BLOCK_NONE": HarmBlockThreshold.BLOCK_NONE,
            "BLOCK_LOW_AND_ABOVE": HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
            "BLOCK_MEDIUM_AND_ABOVE": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            "BLOCK_ONLY_HIGH": HarmBlockThreshold.BLOCK_ONLY_HIGH,
        }
        
        # Handle list of dicts (Google format)
        if isinstance(settings, list):
            for item in settings:
                cat_str = item.get('category')
                thr_str = item.get('threshold')
                cat = category_map.get(cat_str)
                thr = threshold_map.get(thr_str)
                if cat and thr:
                    resolved[cat] = thr
                    
        # Handle dict format
        elif isinstance(settings, dict):
            for cat_str, thr_str in settings.items():
                cat = category_map.get(cat_str)
                thr = threshold_map.get(thr_str)
                if cat and thr:
                    resolved[cat] = thr
                    
        return resolved

    @staticmethod
    def _extract_chunk_content(chunk) -> str:
        """
        Extract text content from a streaming chunk.
        
        Handles various chunk formats from Google Gemini:
        - LangChain message chunks (with .content attribute)
        - Plain strings
        - Other object types (converted to string)
        
        Args:
            chunk: Chunk from LLM stream (various formats)
            
        Returns:
            Extracted text content as string
        """
        if hasattr(chunk, 'content'):
            content = chunk.content
            return content if isinstance(content, str) else str(content)
        elif isinstance(chunk, str):
            return chunk
        else:
            return str(chunk)
    
    @staticmethod
    def get_google_llm(
        config: Config,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: Optional[int] = None,
        top_p: float = DEFAULT_TOP_P,
        top_k: int = DEFAULT_TOP_K,
        safety_settings: Optional[Dict[str, str]] = None
    ) -> ChatGoogleGenerativeAI:
        """
        Get or create Google Gemini LLM client with caching.
        
        The client is cached and reused if temperature matches.
        A new client is created if temperature differs.
        
        Args:
            config: Configuration object with API credentials
            temperature: Model temperature (0.0 = factual, 1.0 = creative)
            max_tokens: Maximum output tokens (uses config default if None)
            
        Returns:
            Configured ChatGoogleGenerativeAI instance
            
        Raises:
            ValueError: If config or parameters are invalid
        """
        LLMFactory._validate_config(config)
        LLMFactory._validate_temperature(temperature)
        LLMFactory._validate_max_tokens(max_tokens)
        
        # Strict project-wide model validation
        model_name = config.ai.model
        if model_name not in ALLOWED_MODELS:
            raise ValueError(
                f"Model '{model_name}' is not allowed. "
                f"This project strictly uses only: {', '.join(ALLOWED_MODELS)}"
            )
        
        factory = LLMFactory()
        
        # Resolve parameters
        limit = max_tokens or config.ai.max_tokens or DEFAULT_MAX_TOKENS
        resolved_safety = LLMFactory._resolve_safety_settings(safety_settings or GEMINI_SAFETY_SETTINGS)
        
        # Generate stable cache key based on configuration
        # Safety settings are stabilized to ensure consistent keys
        safety_parts = []
        for cat, thr in sorted(resolved_safety.items(), key=lambda x: str(x[0])):
            safety_parts.append(f"{cat}:{thr}")
        safety_key = "|".join(safety_parts)
            
        cache_key = f"{config.ai.model}:{temperature}:{limit}:{top_p}:{top_k}:{safety_key}"
        
        # Return cached client if available
        if cache_key in factory._client_cache:
            return factory._client_cache[cache_key]
            
        try:
            # Create new client 
            client = ChatGoogleGenerativeAI(
                model=config.ai.model,  # type: ignore[arg-type]
                google_api_key=config.ai.api_key,  # type: ignore[arg-type]
                temperature=temperature,
                max_output_tokens=limit,  # type: ignore[arg-type]
                top_p=top_p,
                top_k=top_k,
                safety_settings=resolved_safety, # type: ignore[arg-type]
                transport=DEFAULT_TRANSPORT  # type: ignore[arg-type]
            )
            
            # Cache the new client
            factory._client_cache[cache_key] = client
            
            logger.debug(
                f"{LOG_DEBUG} Created Google LLM client "
                f"(key={cache_key})"
            )
            return client
            
        except Exception as e:
            logger.error(f"{LOG_ERROR} Failed to create Google LLM client: {e}")
            raise ValueError(f"Failed to create Google LLM client: {e}") from e
    
    @staticmethod
    def get_llm_for_provider(
        config: Config, 
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        top_k: Optional[int] = None,
        safety_settings: Optional[Dict[str, str]] = None
    ) -> ChatGoogleGenerativeAI:
        """
        Get LLM client for configured provider (main entry point).
        
        Optimized for Google Gemini 1.5. Uses intelligent caching to reuse
        clients with identical parameters.
        
        Args:
            config: Configuration object
            temperature: Model temperature (0.0 - 2.0)
            max_tokens: Max output tokens
            top_p: Top-p sampling
            top_k: Top-k sampling
            safety_settings: Gemini safety settings dict
            
        Returns:
            ChatGoogleGenerativeAI instance
        """
        LLMFactory._validate_config(config)
        
        provider = config.ai.provider.lower()
        temp = temperature if temperature is not None else (config.ai.temperature or DEFAULT_TEMPERATURE)
        p = top_p if top_p is not None else DEFAULT_TOP_P
        k = top_k if top_k is not None else DEFAULT_TOP_K
        
        if provider in GEMINI_ALIASES:
            return LLMFactory.get_google_llm(
                config, 
                temperature=temp, 
                max_tokens=max_tokens,
                top_p=p,
                top_k=k,
                safety_settings=safety_settings
            )
        else:
            raise ValueError(
                f"Unsupported AI provider: '{provider}'. "
                f"This project is strictly specialized for Google Gemini Flash."
            )
    
    @staticmethod
    async def stream_llm_response(
        config: Config,
        prompt: str,
        temperature: Optional[float] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream LLM response asynchronously for real-time output.
        
        This method yields text chunks as they are generated, enabling
        real-time streaming responses in async contexts.
        
        Args:
            config: Configuration object
            prompt: Input prompt text
            temperature: Model temperature (uses config default if not specified)
            
        Yields:
            Text chunks as they are generated (strings)
            
        Example:
            >>> async for chunk in LLMFactory.stream_llm_response(config, "Tell me a story"):
            ...     print(chunk, end="", flush=True)
        """
        LLMFactory._validate_config(config)
        
        if not prompt or not prompt.strip():
            logger.warning(f"{LOG_ERROR} Empty prompt provided to stream_llm_response")
            yield "Error: Empty prompt"
            return
        
        temp = temperature if temperature is not None else config.ai.temperature
        
        try:
            llm = LLMFactory.get_google_llm(config, temperature=temp)
            
            # Using synchronous stream in an async generator loop as a robust fallback.
            # astream currently has a ResponseIterator await bug in some library versions.
            # We yield control with asyncio.sleep(0) to keep the loop responsive.
            for chunk in llm.stream(prompt):
                content = LLMFactory._extract_chunk_content(chunk)
                if content:
                    yield content
                await asyncio.sleep(0)
                        
        except ValueError as e:
            logger.error(f"{LOG_ERROR} Unsupported provider for streaming: {e}", exc_info=True)
            yield f"Error: {str(e)}"
        except Exception as e:
            logger.error(f"{LOG_ERROR} Streaming error: {e}", exc_info=True)
            yield f"Error: {str(e)}"
    
    @staticmethod
    def stream_llm_response_sync(
        config: Config,
        prompt: str,
        temperature: Optional[float] = None
    ) -> Generator[str, None, None]:
        """
        Stream LLM response synchronously for compatibility.
        
        This method yields text chunks as they are generated in a synchronous
        context. Use this when async/await is not available.
        
        Args:
            config: Configuration object
            prompt: Input prompt text
            temperature: Model temperature (uses config default if not specified)
            
        Yields:
            Text chunks as they are generated (strings)
            
        Example:
            >>> for chunk in LLMFactory.stream_llm_response_sync(config, "Tell me a story"):
            ...     print(chunk, end="", flush=True)
        """
        LLMFactory._validate_config(config)
        
        if not prompt or not prompt.strip():
            logger.warning(f"{LOG_ERROR} Empty prompt provided to stream_llm_response_sync")
            yield "Error: Empty prompt"
            return
        
        temp = temperature if temperature is not None else config.ai.temperature
        
        try:
            llm = LLMFactory.get_google_llm(config, temperature=temp)
            
            # Stream the response using sync iteration
            for chunk in llm.stream(prompt):
                yield LLMFactory._extract_chunk_content(chunk)
                        
        except ValueError as e:
            logger.error(f"{LOG_ERROR} Unsupported provider for streaming: {e}", exc_info=True)
            yield f"Error: {str(e)}"
        except Exception as e:
            logger.error(f"{LOG_ERROR} Streaming error: {e}", exc_info=True)
            yield f"Error: {str(e)}"
    
    @staticmethod
    def reset() -> None:
        """
        Reset all cached clients (useful for testing and debugging).
        
        Clears all cached LLM instances, forcing new instances to be created
        on next access. This is particularly useful in testing scenarios
        where you need fresh instances.
        
        Example:
            >>> LLMFactory.reset()  # Clear all caches
            >>> llm = LLMFactory.get_llm_for_provider(config)  # Creates new instance
        """
        factory = LLMFactory()
        factory._client_cache.clear()
        logger.info(f"{LOG_INFO} Reset all LLM clients and caches")
    
    @staticmethod
    def get_cache_stats() -> dict[str, Any]:
        """
        Get statistics about cached LLM instances.
        
        Returns:
            Dictionary with cache statistics:
            - client_count: Number of cached clients
            - cache_keys: List of cache keys
        """
        factory = LLMFactory()
        return {
            'client_count': len(factory._client_cache),
            'cache_keys': list(factory._client_cache.keys())
        }
