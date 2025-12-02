"""
Query Decomposer - Intelligent query decomposition

Integrates with:
- intent_patterns.py: analyze_query_complexity, extract_entities, _get_domain_keywords for intelligent analysis
- orchestrator_constants.py: MULTI_STEP_SEPARATORS, ACTION_PATTERNS for pattern matching
- ToolDomainConfig: Centralized domain detection
- orchestrator_config.py: Configuration constants (default action, context keywords)
- prompts module: LLM decomposition prompts
"""

import json
import re
from typing import Dict, List, Any, Optional

from ....utils.logger import setup_logger

# Import from orchestrator_constants - provides centralized pattern definitions
from ..config import (
    MULTI_STEP_SEPARATORS,
    MULTI_STEP_INDICATORS,
    LOG_INFO,
    LOG_ERROR,
    LOG_WARNING,
    LOG_CONTEXT
)

# Import from intent module - provides NLP analysis
from ...intent import (
    analyze_query_complexity,
    extract_entities,
    classify_query_intent,
    MULTI_STEP_PATTERNS,
    ACTION_VERBS
)

# Import config
from ..config.orchestrator_config import OrchestratorConfig

# Import domain config
from ..domain.tool_domain_config import get_tool_domain_config, Domain

# Import prompt
try:
    from ....ai.prompts.decomposition_prompts import QUERY_DECOMPOSITION_PROMPT
except ImportError:
    QUERY_DECOMPOSITION_PROMPT = None

logger = setup_logger(__name__)


class QueryDecomposer:
    """
    Intelligent query decomposer with pattern-based and LLM fallback
    
    Features:
    - Atomic operation detection (no decomposition for single actions)
    - Multi-step pattern matching using orchestrator_constants
    - Cross-domain query detection
    - LLM-based decomposition fallback
    - Entity extraction for rich context
    
    Integration:
    - Uses intent_patterns for complexity analysis
    - Uses orchestrator_constants for patterns and mappings
    - Uses routing_analytics for tracking decisions
    """
    
    def __init__(self, llm_client=None):
        """
        Initialize query decomposer
        
        Args:
            llm_client: Optional LLM client for advanced decomposition
        """
        self.llm_client = llm_client
        
        # Initialize patterns from centralized constants
        self.action_verbs = ACTION_VERBS
        self.multi_step_separators = MULTI_STEP_SEPARATORS
        self.multi_step_indicators = MULTI_STEP_INDICATORS
        
        # Use ToolDomainConfig for domain normalization (fallback only)
        self.tool_domain_config = get_tool_domain_config()
        
        logger.info(
            f"[DECOMPOSER] Initialized with {len(self.action_verbs)} action verbs, "
            f"{len(self.multi_step_separators)} separators"
        )
    
    def should_use_multi_step_execution(self, query: str) -> bool:
        """
        Determine if query requires multi-step execution
        
        Uses intent_patterns.analyze_query_complexity() for intelligent decision-making
        """
        # Use centralized complexity analysis
        complexity = analyze_query_complexity(query)
        should_orchestrate = complexity.get("should_use_orchestration", False)
        
        logger.debug(
            f"{LOG_INFO} Complexity analysis: "
            f"score={complexity.get('complexity_score', 0)}, "
            f"level={complexity.get('complexity_level', 'low')}, "
            f"orchestrate={should_orchestrate}"
        )
        
        return should_orchestrate
    
    def decompose_query(
        self,
        query: str,
        memory_recommendations: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Decompose query into execution steps with entity extraction
        
        Args:
            query: User query string
            memory_recommendations: Optional memory-based recommendations with similar patterns
            
        Returns:
            List of step dictionaries with id, query, intent, action, dependencies
        """
        # Extract entities using intent_patterns for richer context
        entities = extract_entities(query)
        logger.debug(
            f"{LOG_CONTEXT} Extracted entities: "
            f"time={entities.get('time_references', [])}, "
            f"priorities={entities.get('priorities', [])}, "
            f"actions={len(entities.get('actions', []))} actions, "
            f"domains={entities.get('domains', [])}"
        )
        
        # Use memory recommendations if available
        if memory_recommendations:
            similar_patterns = memory_recommendations.get('similar_patterns', [])
            if similar_patterns:
                logger.info(f"{LOG_INFO} Using {len(similar_patterns)} similar patterns from memory")
                # Adjust decomposition based on successful patterns
                intent = memory_recommendations.get('intent', 'general')
                entities['memory_intent'] = intent
        
        # Check if single-step query
        if not self.should_use_multi_step_execution(query):
            return [self._create_single_step(query, entities)]
        
        # Try pattern-based decomposition first
        steps = self._pattern_based_decomposition(query, entities)
        
        # Fallback to LLM if available and pattern-based returns too few steps
        if len(steps) <= 1 and self.llm_client:
            try:
                logger.info(f"{LOG_INFO} Using LLM for query decomposition")
                llm_steps = self._llm_based_decomposition(query)
                if llm_steps and len(llm_steps) > len(steps):
                    steps = llm_steps
            except Exception as e:
                logger.warning(f"{LOG_WARNING} LLM decomposition failed: {e}")
        
        return steps or [self._create_single_step(query, entities)]
    
    def _create_single_step(
        self,
        query: str,
        entities: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Create a single execution step
        
        Args:
            query: Query string
            entities: Extracted entities from intent_patterns
            
        Returns:
            Step dictionary
        """
        intent = self._identify_primary_intent(query)
        action = self._extract_primary_action(query)
        
        return {
            'id': 'step_1',
            'query': query,
            'intent': intent,
            'action': action,
            'dependencies': [],
            'context_requirements': {},
            'entities': entities or {}
        }
    
    def _pattern_based_decomposition(
        self,
        query: str,
        entities: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Decompose using MULTI_STEP_SEPARATORS from orchestrator_constants
        
        Args:
            query: Query string
            entities: Extracted entities
            
        Returns:
            List of step dictionaries
        """
        steps = []
        
        # Split on separators
        query_parts = [query]
        for separator in self.multi_step_separators:
            new_parts = []
            for part in query_parts:
                if separator in part:
                    new_parts.extend(part.split(separator))
                else:
                    new_parts.append(part)
            query_parts = new_parts
        
        # Create steps from parts
        for i, part in enumerate(query_parts):
            part = part.strip()
            if part:
                intent = self._identify_primary_intent(part)
                action = self._extract_primary_action(part)
                
                steps.append({
                    'id': f'step_{i + 1}',
                    'query': part,
                    'intent': intent,
                    'action': action,
                    'dependencies': [f'step_{j}' for j in range(1, i + 1)] if i > 0 else [],
                    'context_requirements': self._determine_context_requirements(part, intent),
                    'entities': entities
                })
        
        return steps
    
    def _llm_based_decomposition(self, query: str) -> List[Dict[str, Any]]:
        """
        Use LLM for decomposition with fallback to JSON parsing
        
        Args:
            query: Query string
            
        Returns:
            List of step dictionaries or empty list if LLM not available
        """
        if not self.llm_client:
            return []
        
        # Use prompt from prompts module
        if QUERY_DECOMPOSITION_PROMPT:
            prompt = QUERY_DECOMPOSITION_PROMPT.format(query=query)
        else:
            # Fallback if prompt not available
            prompt = f'Decompose this query into sequential execution steps: "{query}"\n\nReturn JSON list with objects containing: id, query, intent, action, dependencies'
        
        try:
            response = self.llm_client.invoke(prompt)
            content = self._extract_response_content(response)
            
            if not content:
                logger.warning(f"{LOG_WARNING} LLM returned empty response, using fallback")
                return []
            
            # Extract JSON from response (handles markdown code blocks)
            content_stripped = self._extract_json_from_content(content)
            result = json.loads(content_stripped)
            
            # Ensure result is a list
            if not isinstance(result, list):
                logger.warning(f"{LOG_WARNING} LLM response is not a list, using fallback")
                return []
            
            for step in result:
                step['context_requirements'] = self._determine_context_requirements(
                    step['query'], step['intent']
                )
                if 'entities' not in step:
                    step['entities'] = {}
            
            logger.info(f"{LOG_INFO} LLM decomposition produced {len(result)} steps")
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"{LOG_ERROR} LLM decomposition failed - invalid JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"{LOG_ERROR} LLM decomposition failed: {e}")
            return []
    
    def _identify_primary_intent(self, query: str) -> str:
        """
        Identify primary domain intent using agent/intent/ module.
        
        Uses classify_query_intent() from agent/intent/ which provides:
        - Sophisticated pattern matching (EMAIL_PATTERNS, TASK_CREATE_PATTERNS, etc.)
        - Confidence scoring
        - Proper domain detection
        
        Args:
            query: Query string
            
        Returns:
            Domain string (email, calendar, task, or general)
        """
        # Use agent/intent/ module for proper intent classification
        intent_result = classify_query_intent(query)
        domain = intent_result.get('domain', 'general')
        
        # Normalize domain name (e.g., 'task' -> 'tasks' for consistency)
        if domain == 'task':
            domain = 'tasks'
        
        return domain
    
    def _extract_primary_action(self, query: str) -> str:
        """
        Extract action verb from query
        
        Args:
            query: Query string
            
        Returns:
            Action string (from ACTION_VERBS or default from config)
        """
        query_lower = query.lower()
        
        for verb in self.action_verbs:
            if verb in query_lower:
                return verb
        
        return OrchestratorConfig.DEFAULT_ACTION
    
    def _determine_context_requirements(
        self,
        query: str,
        intent: str
    ) -> Dict[str, Any]:
        """
        Determine context dependencies for the step
        
        Args:
            query: Step query
            intent: Step intent
            
        Returns:
            Dictionary of context requirements
        """
        requirements = {}
        query_lower = query.lower()
        
        # Use context keywords from config
        if any(keyword in query_lower for keyword in OrchestratorConfig.CONTEXT_KEYWORDS):
            requirements['needs_previous_results'] = True
        
        if intent == 'task' and any(word in query_lower for word in ['meeting', 'email']):
            requirements['needs_source_data'] = True
        
        if intent == 'calendar' and 'email' in query_lower:
            requirements['needs_participant_data'] = True
        
        return requirements
    
    def _extract_response_content(self, response: Any) -> str:
        """
        Extract content from LLM response (handles multiple formats).
        
        Args:
            response: LLM response object
            
        Returns:
            Content string or empty string if extraction fails
        """
        if hasattr(response, 'content'):
            return response.content
        elif isinstance(response, str):
            return response
        else:
            return str(response)
    
    def _extract_json_from_content(self, content: str) -> str:
        """
        Extract JSON from content, handling markdown code blocks.
        
        Args:
            content: Raw content string
            
        Returns:
            Extracted JSON string
        """
        content_stripped = content.strip()
        
        # Try to extract JSON from markdown code blocks
        if '```json' in content_stripped:
            start_idx = content_stripped.find('```json') + 7
            end_idx = content_stripped.find('```', start_idx)
            if end_idx != -1:
                return content_stripped[start_idx:end_idx].strip()
        elif '```' in content_stripped:
            start_idx = content_stripped.find('```') + 3
            end_idx = content_stripped.find('```', start_idx)
            if end_idx != -1:
                return content_stripped[start_idx:end_idx].strip()
        
        return content_stripped
