"""
Interactions API Client for Google Gemini

A wrapper for Google's Interactions API that provides:
- Stateful conversation management via previous_interaction_id
- Background execution support for long-running tasks
- Streaming responses  
- Automatic fallback to LLMFactory if Interactions API fails

Usage:
    from src.ai.interactions_client import InteractionsClient
    
    client = InteractionsClient()
    
    # Simple interaction
    result = await client.create_interaction(
        input="What's the weather?",
        model="gemini-3-flash-preview"
    )
    
    # Stateful multi-turn
    result1 = await client.create_interaction(input="My name is Phil")
    result2 = await client.create_interaction(
        input="What's my name?",
        previous_interaction_id=result1.id
    )
    
    # Deep Research (background)
    result = await client.create_research_interaction(
        input="Research all Q4 discussions",
        timeout_seconds=300
    )
"""
import os
import asyncio
from typing import Optional, Dict, Any, AsyncGenerator, Callable, Awaitable
from threading import Lock
from dataclasses import dataclass

from ..utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class InteractionResult:
    """Result from an Interactions API call"""
    id: str
    status: str  # "completed", "running", "failed", "cancelled"
    text: str  # Final text output
    outputs: list  # All outputs (text, tool calls, etc.)
    usage: Optional[Dict[str, int]] = None
    error: Optional[str] = None
    
    @classmethod
    def from_api_response(cls, response) -> 'InteractionResult':
        """Create InteractionResult from API response"""
        text = ""
        outputs = []
        
        # Extract outputs
        if hasattr(response, 'outputs') and response.outputs:
            outputs = response.outputs
            # Find the text output
            for output in reversed(response.outputs):
                if hasattr(output, 'text'):
                    text = output.text
                    break
                elif hasattr(output, 'type') and output.type == 'text':
                    text = getattr(output, 'text', '')
                    break
        
        # Extract usage
        usage = None
        if hasattr(response, 'usage'):
            usage = {
                'total_tokens': getattr(response.usage, 'total_tokens', 0),
                'prompt_tokens': getattr(response.usage, 'prompt_tokens', 0),
                'completion_tokens': getattr(response.usage, 'completion_tokens', 0)
            }
        
        return cls(
            id=getattr(response, 'id', ''),
            status=getattr(response, 'status', 'completed'),
            text=text,
            outputs=outputs,
            usage=usage,
            error=None
        )


class InteractionsClient:
    """
    Client for Google's Interactions API with fallback support.
    
    Features:
    - Singleton pattern for efficient resource management
    - Automatic API key detection from environment
    - Fallback to LLMFactory if Interactions API unavailable
    - Thread-safe operations
    """
    
    _instance: Optional['InteractionsClient'] = None
    _lock: Lock = Lock()
    _initialized: bool = False
    _client = None
    _fallback_mode: bool = False
    
    # Default models
    DEFAULT_MODEL = "gemini-3-flash-preview"
    RESEARCH_AGENT = "deep-research-pro-preview-12-2025"
    
    def __new__(cls):
        """Thread-safe singleton implementation"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize the Interactions API client"""
        if self._initialized:
            return
            
        try:
            from google import genai
            
            # Initialize client (uses GOOGLE_API_KEY from environment)
            api_key = os.environ.get('GOOGLE_API_KEY')
            if not api_key:
                raise ValueError("GOOGLE_API_KEY environment variable not set")
            
            self._client = genai.Client(api_key=api_key)
            self._initialized = True
            self._fallback_mode = False
            
            logger.info("[OK] InteractionsClient initialized successfully")
            
        except ImportError as e:
            logger.warning(
                f"[WARNING] google-genai package not installed, using fallback mode: {e}"
            )
            self._fallback_mode = True
            self._initialized = True
            
        except Exception as e:
            logger.warning(
                f"[WARNING] Failed to initialize Interactions API, using fallback mode: {e}"
            )
            self._fallback_mode = True
            self._initialized = True
    
    @property
    def is_available(self) -> bool:
        """Check if Interactions API is available"""
        return self._initialized and not self._fallback_mode and self._client is not None
    
    async def create_interaction(
        self,
        input: str,
        model: str = DEFAULT_MODEL,
        previous_interaction_id: Optional[str] = None,
        tools: Optional[list] = None,
        response_format: Optional[Dict[str, Any]] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        stream: bool = False
    ) -> InteractionResult:
        """
        Create an interaction with the Interactions API.
        
        Args:
            input: User input/prompt
            model: Model to use (default: gemini-3-flash-preview)
            previous_interaction_id: ID of previous interaction for context
            tools: Optional list of tools/MCP servers
            response_format: Optional structured output format
            generation_config: Optional generation parameters
            stream: Whether to stream the response
            
        Returns:
            InteractionResult with response data
        """
        if not self.is_available:
            return await self._fallback_generate(input, model)
        
        try:
            # Build request parameters
            params = {
                "model": model,
                "input": input
            }
            
            if previous_interaction_id:
                params["previous_interaction_id"] = previous_interaction_id
                logger.debug(f"Using previous_interaction_id: {previous_interaction_id[:8]}...")
            
            if tools:
                params["tools"] = tools
            
            if response_format:
                params["response_format"] = response_format
            
            if generation_config:
                params["generation_config"] = generation_config
            
            if stream:
                params["stream"] = True
            
            # Make API call with timeout
            # Suppress experimental usage warning - we're aware it's experimental
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Interactions usage is experimental")
                try:
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._client.interactions.create,
                            **params
                        ),
                        timeout=30.0  # 30 second timeout for planning/interaction
                    )
                except asyncio.TimeoutError:
                    logger.error("[ERROR] Interactions API call timed out after 30s")
                    raise
            
            result = InteractionResult.from_api_response(response)
            
            logger.info(
                f"[OK] Interaction created (id={result.id[:8]}..., "
                f"tokens={result.usage.get('total_tokens', 'N/A') if result.usage else 'N/A'})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[ERROR] Interactions API call failed: {e}")
            # Fallback to LLMFactory
            return await self._fallback_generate(input, model)
    
    async def get_interaction(self, interaction_id: str) -> InteractionResult:
        """
        Get the status of an existing interaction.
        
        Useful for polling background tasks like Deep Research.
        
        Args:
            interaction_id: ID of the interaction to retrieve
            
        Returns:
            InteractionResult with current status and outputs
        """
        if not self.is_available:
            raise ValueError("Interactions API not available")
        
        try:
            response = await asyncio.to_thread(
                self._client.interactions.get,
                interaction_id
            )
            
            return InteractionResult.from_api_response(response)
            
        except Exception as e:
            logger.error(f"[ERROR] Failed to get interaction {interaction_id}: {e}")
            return InteractionResult(
                id=interaction_id,
                status="failed",
                text="",
                outputs=[],
                error=str(e)
            )
    
    async def create_research_interaction(
        self,
        input: str,
        timeout_seconds: int = 300,
        poll_interval: int = 10,
        on_progress: Optional[Callable[['InteractionResult', int], Awaitable[None]]] = None,
        previous_interaction_id: Optional[str] = None
    ) -> InteractionResult:
        """
        Create a Deep Research interaction and wait for completion.
        
        The Deep Research agent runs in the background and can take several minutes.
        This method polls for completion.
        
        Args:
            input: Research query
            timeout_seconds: Maximum time to wait (default: 5 minutes)
            poll_interval: Seconds between status polls (default: 10)
            on_progress: Optional async callback(result, elapsed_seconds)
            previous_interaction_id: ID of previous interaction for context
            
        Returns:
            InteractionResult with research findings
        """
        if not self.is_available:
            return await self._fallback_generate(
                f"Please research and summarize: {input}",
                self.DEFAULT_MODEL
            )
        
        try:
            # Start background research
            logger.info(f"[INFO] Starting Deep Research: {input[:50]}...")
            
            params = {
                "input": input,
                "agent": self.RESEARCH_AGENT,
                "background": True
            }
            if previous_interaction_id:
                params["previous_interaction_id"] = previous_interaction_id
            
            response = await asyncio.to_thread(
                self._client.interactions.create,
                **params
            )
            
            interaction_id = response.id
            logger.info(f"[OK] Research started (id={interaction_id[:8]}...)")
            
            # Poll for completion with adaptive backoff
            # Start frequent (2s) for quick results, then back off to conserve resources
            elapsed = 0
            adaptive_interval = 2.0  # Start with 2s
            max_interval = float(poll_interval)  # Cap at user provided interval (default 10)
            
            while elapsed < timeout_seconds:
                await asyncio.sleep(adaptive_interval)
                elapsed += adaptive_interval
                
                # Backoff logic for next loop
                if adaptive_interval < max_interval:
                    adaptive_interval = min(adaptive_interval * 1.5, max_interval)
                
                result = await self.get_interaction(interaction_id)
                logger.debug(f"Research status: {result.status} (elapsed: {int(elapsed)}s)")
                
                # Emit progress if callback provided
                if on_progress:
                    try:
                        await on_progress(result, elapsed)
                    except Exception as e:
                        logger.warning(f"Progress callback failed: {e}")
                
                if result.status == "completed":
                    logger.info(f"[OK] Research completed in {elapsed}s")
                    return result
                    
                elif result.status in ["failed", "cancelled"]:
                    logger.error(f"[ERROR] Research failed: {result.error}")
                    return result
            
            # Timeout
            logger.warning(f"[WARNING] Research timed out after {timeout_seconds}s")
            return InteractionResult(
                id=interaction_id,
                status="timeout",
                text="Research request timed out. Please try again with a narrower scope.",
                outputs=[],
                error=f"Timeout after {timeout_seconds} seconds"
            )
            
        except Exception as e:
            logger.error(f"[ERROR] Research failed: {e}")
            return InteractionResult(
                id="",
                status="failed",
                text=f"Research failed: {str(e)}",
                outputs=[],
                error=str(e)
            )
    
    async def stream_interaction(
        self,
        input: str,
        model: str = DEFAULT_MODEL,
        previous_interaction_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream an interaction response.
        
        Yields text chunks as they are generated.
        
        Args:
            input: User input/prompt
            model: Model to use
            previous_interaction_id: ID of previous interaction for context
            
        Yields:
            Text chunks as strings
        """
        if not self.is_available:
            # Fallback to LLMFactory streaming
            from .llm_factory import LLMFactory
            from ..utils.config import load_config
            
            config = load_config()
            async for chunk in LLMFactory.stream_llm_response(config, input):
                yield chunk
            return
        
        try:
            params = {
                "model": model,
                "input": input,
                "stream": True
            }
            
            if previous_interaction_id:
                params["previous_interaction_id"] = previous_interaction_id
            
            # Note: Streaming implementation depends on SDK structure
            # This is a simplified version
            stream = await asyncio.to_thread(
                self._client.interactions.create,
                **params
            )
            
            for chunk in stream:
                if hasattr(chunk, 'event_type'):
                    if chunk.event_type == "content.delta":
                        if hasattr(chunk, 'delta'):
                            if hasattr(chunk.delta, 'text'):
                                yield chunk.delta.text
                            elif hasattr(chunk.delta, 'thought'):
                                yield chunk.delta.thought
                                
        except Exception as e:
            logger.error(f"[ERROR] Streaming failed: {e}")
            yield f"Error: {str(e)}"
    
    async def _fallback_generate(
        self, 
        input: str, 
        model: str
    ) -> InteractionResult:
        """
        Fallback to LLMFactory when Interactions API is unavailable.
        
        Args:
            input: User input/prompt
            model: Model (used for logging, actual model from config)
            
        Returns:
            InteractionResult with generated text
        """
        logger.info("[INFO] Using LLMFactory fallback")
        
        try:
            from .llm_factory import LLMFactory
            from ..utils.config import load_config
            from langchain_core.messages import HumanMessage
            
            config = load_config()
            llm = LLMFactory.get_llm_for_provider(config, temperature=0.0)
            
            # Use sync invoke wrapped in thread
            response = await asyncio.to_thread(
                llm.invoke,
                [HumanMessage(content=input)]
            )
            
            text = response.content if hasattr(response, 'content') else str(response)
            
            return InteractionResult(
                id="fallback",
                status="completed",
                text=text,
                outputs=[{"type": "text", "text": text}],
                usage=None,
                error=None
            )
            
        except Exception as e:
            logger.error(f"[ERROR] Fallback generation failed: {e}")
            return InteractionResult(
                id="error",
                status="failed",
                text=f"Error: {str(e)}",
                outputs=[],
                error=str(e)
            )
    
    @classmethod
    def reset(cls):
        """Reset the singleton instance (useful for testing)"""
        with cls._lock:
            cls._instance = None
            cls._initialized = False
            cls._client = None
            cls._fallback_mode = False
        logger.info("[INFO] InteractionsClient reset")


# Convenience function for quick access
def get_interactions_client() -> InteractionsClient:
    """Get the singleton InteractionsClient instance"""
    return InteractionsClient()
