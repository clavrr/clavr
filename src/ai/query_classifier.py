"""
Query Classification and Intent Detection

Uses LLM with structured outputs to classify user intent and extract entities from natural language queries.
Implements structured outputs (function calling/tool use) for reliable, type-safe classification.

Now located in ai/ module to eliminate circular dependencies and allow direct imports.

**ASYNC SUPPORT:** All classification methods are now async to prevent blocking the event loop
during LLM API calls (200-500ms each). This enables 10-100x throughput improvement for concurrent requests.
"""
import json
import re
import hashlib
import asyncio
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

from ..utils.logger import setup_logger
from ..utils.config import Config
from .llm_factory import LLMFactory
from .prompts import INTENT_CLASSIFICATION_PROMPT
from .prompts.utils import format_prompt

logger = setup_logger(__name__)


class IntentClassificationSchema(BaseModel):
    """
    Structured schema for intent classification results.
    
    This schema ensures type safety and consistent structure across all LLM providers.
    """
    intent: str = Field(
        description="The primary action intent. Options: list, search, send, reply, mark_read, analyze, summarize, schedule, create_task, multi_step",
        examples=["search", "list", "schedule"]
    )
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0",
        ge=0.0,
        le=1.0,
        examples=[0.85, 0.95]
    )
    entities: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted entities including recipients, senders, subjects, keywords, date_range, etc."
    )
    filters: List[str] = Field(
        default_factory=list,
        description="Filters to apply (important, unread, attachment, etc.)"
    )
    limit: int = Field(
        default=10,
        description="Maximum number of results to return",
        ge=1,
        le=100
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="Brief explanation of the classification decision"
    )


class QueryClassifier:
    """
    Classify user queries using LLM with structured outputs for reliable classification.
    
    Uses structured outputs (function calling/tool use) when supported by the LLM provider,
    falling back to prompt-based JSON parsing for compatibility.
    
    Benefits of structured outputs:
    - Guaranteed JSON structure and type safety
    - Better accuracy than parsing free-form text
    - Provider-optimized for each LLM
    - Reduced parsing errors and edge cases
    
    Now located in ai/ module to eliminate circular dependencies.
    Direct imports are now possible since ai/ can import from utils/ without cycles.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.llm_client = None
        self.provider = None
        self.supports_structured_outputs = False
        self._classification_cache = {} 
        self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM client and detect structured output support"""
        try:
            # Direct import now possible - no circular dependency!
            self.llm_client = LLMFactory.get_llm_for_provider(
                self.config,
                temperature=0.1  # Low temperature for consistent classification
            )
            
            # Detect provider and structured output support
            provider = self.config.ai.provider.lower()
            self.provider = provider
            
            # Check if provider supports structured outputs
            if provider in ["gemini", "google"]:
                # Google Gemini supports structured outputs via response_schema
                self.supports_structured_outputs = True
            elif provider == "openai":
                # OpenAI supports structured outputs via response_format
                self.supports_structured_outputs = True
            elif provider == "anthropic":
                # Anthropic supports structured outputs via tool use
                self.supports_structured_outputs = True
            else:
                self.supports_structured_outputs = False
            
            logger.info(f"[OK] Query classifier LLM initialized (provider: {provider}, structured_outputs: {self.supports_structured_outputs})")
        except Exception as e:
            logger.error(f"Failed to initialize LLM for query classification: {e}")
            self.llm_client = None
            self.supports_structured_outputs = False
    
    async def classify_query(self, query: str) -> Dict[str, Any]:
        """
        Classify user query and extract entities using structured outputs when available.
        
        **NOW ASYNC** to prevent blocking the event loop during LLM API calls.
        Uses asyncio.to_thread() to run blocking LLM calls in a thread pool.
        
        Uses structured outputs for reliable, type-safe classification when supported,
        falling back to prompt-based JSON parsing for compatibility.
        
        Args:
            query: User query string
            
        Returns:
            Classification dictionary with intent, confidence, entities, etc.
        """
        if not self.llm_client:
            logger.warning("LLM not available, using basic classification")
            return self._basic_classify(query)
        
        # Check cache first to prevent hitting rate limits
        query_hash = hashlib.md5(query.lower().strip().encode()).hexdigest()
        if query_hash in self._classification_cache:
            logger.debug(f"Using cached classification for: {query[:30]}...")
            return self._classification_cache[query_hash]
        
        # Try structured outputs first if supported
        if self.supports_structured_outputs:
            try:
                classification = await self._classify_with_structured_outputs(query)
                if classification:
                    # Cache the result
                    self._classification_cache[query_hash] = classification
                    logger.info(f"[SEARCH] Query classified (structured): intent={classification.get('intent')}, "
                               f"confidence={classification.get('confidence')}")
                    return classification
            except Exception as e:
                logger.warning(f"Structured output classification failed: {e}, falling back to prompt-based")
        
        # Fallback to prompt-based classification
        try:
            classification = await self._classify_with_prompt(query)
            # Cache the result
            self._classification_cache[query_hash] = classification
            logger.info(f"[SEARCH] Query classified (prompt-based): intent={classification.get('intent')}, "
                       f"confidence={classification.get('confidence')}")
            return classification
        except Exception as e:
            error_msg = str(e)
            # Better handling for rate limit errors
            if "429" in error_msg or "TooManyRequests" in error_msg or "quota" in error_msg.lower():
                logger.warning(f"Rate limit hit, falling back to basic classification")
                # Don't cache to allow retry later
                return self._basic_classify(query)
            
            logger.error(f"LLM classification failed: {e}")
            return self._basic_classify(query)
    
    async def _classify_with_structured_outputs(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Classify query using LangChain's unified structured output support.
        
        **NOW ASYNC** - Runs LLM calls in thread pool to avoid blocking.
        
        Uses LangChain's `with_structured_outputs()` method which works across
        all supported providers (Google Gemini, OpenAI, Anthropic). This provides
        guaranteed JSON structure and type safety.
        
        Args:
            query: User query string
            
        Returns:
            Classification dictionary or None if structured outputs fail
        """
        try:
            prompt = self._build_classification_prompt(query)
            
            # Use LangChain's unified structured output support
            # This works with all providers (Gemini, OpenAI, Anthropic)
            if hasattr(self.llm_client, 'with_structured_outputs'):
                try:
                    # Create structured output wrapper
                    structured_llm = self.llm_client.with_structured_outputs(IntentClassificationSchema)
                    
                    # LangChain can accept both string prompts and message objects
                    # Try string first (simpler), then messages if needed
                    try:
                        response = await asyncio.to_thread(structured_llm.invoke, prompt)
                    except (TypeError, AttributeError):
                        # If string doesn't work, try with HumanMessage
                        messages = [HumanMessage(content=prompt)]
                        response = await asyncio.to_thread(structured_llm.invoke, messages)
                    
                    # Convert Pydantic model to dict
                    if isinstance(response, IntentClassificationSchema):
                        classification = response.model_dump()
                    elif isinstance(response, dict):
                        classification = response
                    else:
                        # Try to extract from response object
                        if hasattr(response, 'model_dump'):
                            classification = response.model_dump()
                        elif hasattr(response, '__dict__'):
                            classification = dict(response)
                        else:
                            classification = {}
                    
                    # Validate and normalize
                    if classification:
                        return self._normalize_classification(classification)
                except (AttributeError, TypeError, ValueError) as e:
                    logger.debug(f"LangChain structured output not available: {e}")
                    return None
            else:
                # Try provider-specific methods as fallback
                return await self._classify_with_provider_specific_structured_outputs(query)
            
        except Exception as e:
            logger.warning(f"Structured output classification failed: {e}")
            return None
    
    async def _classify_with_provider_specific_structured_outputs(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Fallback: Try provider-specific structured output methods.
        
        **NOW ASYNC** - Runs provider-specific LLM calls in thread pool.
        
        Some providers may support structured outputs through different APIs.
        This method attempts provider-specific implementations as a fallback.
        """
        prompt = self._build_classification_prompt(query)
        
        # Try Google Gemini's response_schema parameter (if available)
        if self.provider in ["gemini", "google"]:
            try:
                # Gemini 1.5+ supports response_schema via invoke kwargs
                if hasattr(self.llm_client, 'bind'):
                    # Try binding structured output parameters
                    bound_llm = self.llm_client.bind(
                        response_mime_type="application/json"
                    )
                    response = await asyncio.to_thread(bound_llm.invoke, prompt)
                    
                    if hasattr(response, 'content'):
                        content = response.content
                    else:
                        content = str(response)
                    
                    classification = json.loads(content)
                    return self._normalize_classification(classification)
            except Exception as e:
                logger.debug(f"Gemini provider-specific structured output failed: {e}")
        
        # Try OpenAI's response_format parameter (if available)
        elif self.provider == "openai":
            try:
                # OpenAI supports response_format via invoke kwargs
                if hasattr(self.llm_client, 'bind'):
                    schema = IntentClassificationSchema.model_json_schema()
                    response_format = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "intent_classification",
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "intent": {
                                        "type": "string",
                                        "enum": ["list", "search", "send", "reply", "mark_read", "analyze", "summarize", "schedule", "create_task", "multi_step"]
                                    },
                                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                                    "entities": {"type": "object"},
                                    "filters": {"type": "array", "items": {"type": "string"}},
                                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                                    "reasoning": {"type": "string"}
                                },
                                "required": ["intent", "confidence"]
                            }
                        }
                    }
                    
                    bound_llm = self.llm_client.bind(response_format=response_format)
                    response = await asyncio.to_thread(bound_llm.invoke, prompt)
                    
                    if hasattr(response, 'content'):
                        content = response.content
                    else:
                        content = str(response)
                    
                    classification = json.loads(content)
                    return self._normalize_classification(classification)
            except Exception as e:
                logger.debug(f"OpenAI provider-specific structured output failed: {e}")
        
        return None
    
    async def _classify_with_prompt(self, query: str) -> Dict[str, Any]:
        """
        Classify using prompt-based approach (fallback method).
        
        **NOW ASYNC** - Runs LLM call in thread pool to avoid blocking.
        
        Uses traditional prompt engineering with JSON parsing as a fallback
        when structured outputs are not available or fail.
        """
        prompt = self._build_classification_prompt(query)
        
        response = await asyncio.to_thread(self.llm_client.invoke, prompt)
        content = response.content
        
        # Parse JSON from response
        classification = self._parse_llm_response(content)
        
        return classification
    
    def _normalize_classification(self, classification: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize classification result to ensure consistent structure.
        
        Ensures all required fields are present and properly typed,
        regardless of the classification method used.
        """
        # Ensure required fields
        normalized = {
            "intent": classification.get("intent", "list"),
            "confidence": float(classification.get("confidence", 0.5)),
            "entities": classification.get("entities", {}),
            "filters": classification.get("filters", []),
            "limit": int(classification.get("limit", 10)),
            "reasoning": classification.get("reasoning")
        }
        
        # Validate intent is in allowed values
        allowed_intents = ["list", "search", "send", "reply", "mark_read", "analyze", "summarize", "schedule", "create_task", "multi_step"]
        if normalized["intent"] not in allowed_intents:
            logger.warning(f"Invalid intent '{normalized['intent']}', defaulting to 'list'")
            normalized["intent"] = "list"
        
        # Clamp confidence to valid range
        normalized["confidence"] = max(0.0, min(1.0, normalized["confidence"]))
        
        # Clamp limit to valid range
        normalized["limit"] = max(1, min(100, normalized["limit"]))
        
        return normalized
    
    def _build_classification_prompt(self, query: str) -> str:
        """
        Build prompt for LLM classification with enhanced natural language understanding.
        
        Emphasizes understanding user intent even with:
        - Casual language and slang
        - Incomplete sentences
        - Context-dependent references
        - Implicit actions
        - Multiple possible interpretations
        """
        # Direct import now possible - no circular dependency!
        # Use prompt template with enhanced instructions
        enhanced_prompt = format_prompt(
            INTENT_CLASSIFICATION_PROMPT,
            query=query,
            context=""
        )
        
        # Add additional guidance for natural language understanding
        additional_guidance = """

CRITICAL: Understand the user's INTENT, not just keywords. Consider:
- Casual language: "what's up with my emails" = list/search emails
- Incomplete sentences: "emails from john" = search emails from john
- Context references: "that email" = last email mentioned
- Implicit actions: "my day" = calendar events
- Conversational queries: "can you check" = list/search
- Ambiguous queries: Infer the most likely intent based on available tools

CRITICAL: Single-Step vs Multi-Step Classification

DO NOT classify as "multi_step" if:
- Query asks multiple questions about the SAME thing (e.g., "Do I have email from X? What is it about?")
- Query asks "when" AND "what" about the same email (e.g., "When did X respond and what was it about?")
- Query asks for information + details about that information (e.g., "Show emails from X. What are they about?")

ONLY classify as "multi_step" if:
- Query contains multiple DISTINCT actions on DIFFERENT things (e.g., "Search emails AND send a reply")
- Query requires sequential operations on different entities (e.g., "Find emails, then archive them")
- Query combines different tool types (e.g., "Schedule meeting AND create task")

Remember: Questions about the same email/entity are SINGLE-STEP, not multi-step.

Be generous with intent detection - it's better to try and clarify than to fail.
If multiple intents are possible, choose the most likely one with highest confidence.

IMPORTANT: Return ONLY valid JSON matching the schema. Do not include any explanatory text outside the JSON object."""
        
        return enhanced_prompt + additional_guidance
    
    def _parse_llm_response(self, content: str) -> Dict[str, Any]:
        """Parse LLM response and extract JSON"""
        # Clean the response
        content = content.strip()
        
        # Remove markdown code blocks if present
        content = re.sub(r'```json\n?', '', content)
        content = re.sub(r'```\n?', '', content)
        content = re.sub(r'```', '', content)
        
        # Extract JSON object
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group(0)
            try:
                classification = json.loads(json_str)
                return self._normalize_classification(classification)
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                logger.error(f"Content was: {content}")
        
        # Fallback parsing attempt
        return self._parse_json_fallback(content)
    
    def _parse_json_fallback(self, content: str) -> Dict[str, Any]:
        """Fallback JSON parsing for partial matches"""
        classification = {
            "intent": "list",
            "confidence": 0.5,
            "entities": {},
            "filters": [],
            "limit": 10
        }
        
        # Try to extract intent from text
        if '"intent"' in content or "'intent'" in content:
            intent_match = re.search(r'["\']intent["\']:\s*["\']([^"\']+)["\']', content)
            if intent_match:
                classification["intent"] = intent_match.group(1)
        
        # Try to extract confidence
        if '"confidence"' in content or "'confidence'" in content:
            conf_match = re.search(r'["\']confidence["\']:\s*([0-9.]+)', content)
            if conf_match:
                classification["confidence"] = float(conf_match.group(1))
        
        return self._normalize_classification(classification)
    
    def _basic_classify(self, query: str) -> Dict[str, Any]:
        """Fallback basic classification using patterns"""
        query_lower = query.lower()
        
        intent = "list"
        confidence = 0.6
        
        if any(word in query_lower for word in ["search", "find", "look for", "look up"]):
            intent = "search"
            confidence = 0.7
        elif any(word in query_lower for word in ["send", "compose", "write", "draft"]):
            intent = "send"
            confidence = 0.7
        elif any(word in query_lower for word in ["reply", "respond", "answer"]):
            intent = "reply"
            confidence = 0.7
        elif any(word in query_lower for word in ["mark as read", "mark read"]):
            intent = "mark_read"
            confidence = 0.7
        
        return self._normalize_classification({
            "intent": intent,
            "confidence": confidence,
            "entities": {},
            "filters": [],
            "limit": 10
        })

