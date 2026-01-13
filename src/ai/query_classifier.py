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
    Enhanced for Gemini 3.0 Flash to support complex workflow decomposition.
    """
    intent: str = Field(
        description="Primary action intent. Options: list, search, send, reply, mark_read, analyze, summarize, schedule, create_task, multi_step, none",
        examples=["search", "multi_step"]
    )
    confidence: float = Field(
        description="Confidence score (0.0 - 1.0)",
        ge=0.0,
        le=1.0
    )
    is_multi_step: bool = Field(
        default=False,
        description="Whether the query requires multiple sequential actions"
    )
    entities: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted entities: recipients (list), subjects (list), senders (list), date_range (str/dict), keywords (list), location (str), urgency (low|med|high)"
    )
    steps: List[str] = Field(
        default_factory=list,
        description="Natural language breakdown of steps if is_multi_step is True"
    )
    filters: List[str] = Field(
        default_factory=list,
        description="List of flags: important, unread, attachment, flag"
    )
    limit: int = Field(
        default=10,
        description="Max results to fetch (1-50)",
        ge=1,
        le=50
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="Linguistic justification for this classification"
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
            
            # Detect provider (Strictly Gemini per project policy)
            provider = self.config.ai.provider.lower()
            self.provider = provider
            self.supports_structured_outputs = True
            
            logger.info(f"[OK] Query classifier specialized for Gemini Flash")
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
        Classify query using Gemini's structured output support.
        """
        try:
            prompt = self._build_classification_prompt(query)
            
            # Use LangChain's with_structured_outputs specialized for Gemini
            structured_llm = self.llm_client.with_structured_outputs(IntentClassificationSchema)
            
            # Execute in thread pool to avoid blocking
            response = await asyncio.to_thread(structured_llm.invoke, prompt)
            
            if isinstance(response, IntentClassificationSchema):
                return self._normalize_classification(response.model_dump())
            elif isinstance(response, dict):
                return self._normalize_classification(response)
                
            return None
        except Exception as e:
            logger.warning(f"Gemini structured classification failed: {e}")
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
        normalized = {
            "intent": classification.get("intent", "list"),
            "confidence": float(classification.get("confidence", 0.5)),
            "is_multi_step": bool(classification.get("is_multi_step", False)),
            "entities": classification.get("entities", {}),
            "steps": classification.get("steps", []),
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
        # Use prompt template with enhanced instructions from centralized prompts
        # The INTENT_CLASSIFICATION_PROMPT already includes all necessary guidance
        return format_prompt(
            INTENT_CLASSIFICATION_PROMPT,
            query=query,
            context=""
        )
    
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
        """Fallback basic classification using patterns (Offline/Safe mode)"""
        query_lower = query.lower()
        
        intent = "list"
        confidence = 0.5
        is_multi_step = False
        steps = []
        
        # Simple multi-step detection (Prioritized)
        if any(p in query_lower for p in [" and then ", " then ", " and also ", "; "]):
            intent = "multi_step"
            is_multi_step = True
            confidence = 0.6
        
        # Intent keyword mapping (Only if not already a confident multi-step)
        # Use regex for better flexibility
        if any(re.search(r"\b(find|search|look (for|up))\b", query_lower) for _ in [0]):
            intent = "search" if not is_multi_step else "multi_step"
            confidence = 0.7
        elif any(re.search(r"\b(send|compose|write|draft)\b", query_lower) for _ in [0]):
            intent = "send" if not is_multi_step else "multi_step"
            confidence = 0.7
        elif any(re.search(r"\b(reply|respond|answer)\b", query_lower) for _ in [0]):
            intent = "reply" if not is_multi_step else "multi_step"
            confidence = 0.7
        elif any(re.search(r"\bmark\b.*\bread\b", query_lower) for _ in [0]):
            intent = "mark_read" if not is_multi_step else "multi_step"
            confidence = 0.7
        elif any(re.search(r"\b(summarize|summary)\b", query_lower) for _ in [0]):
            intent = "summarize" if not is_multi_step else "multi_step"
            confidence = 0.7
        elif any(re.search(r"\b(analyze|insight|report)\b", query_lower) for _ in [0]):
            intent = "analyze" if not is_multi_step else "multi_step"
            confidence = 0.7
        elif any(re.search(r"\b(schedule|meeting|calendar)\b", query_lower) for _ in [0]):
            intent = "schedule" if not is_multi_step else "multi_step"
            confidence = 0.7
        elif any(re.search(r"\b(task|todo|to do|remind)\b", query_lower) for _ in [0]):
            intent = "create_task" if not is_multi_step else "multi_step"
            confidence = 0.7
        
        return self._normalize_classification({
            "intent": intent,
            "confidence": confidence,
            "is_multi_step": is_multi_step,
            "steps": steps,
            "entities": {},
            "filters": [],
            "limit": 10,
            "reasoning": "Fallback pattern-based classification"
        })

