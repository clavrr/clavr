"""
Autonomy Evaluator

Evaluates the agent's autonomous capabilities:
- Confidence-based decision making
- Error recovery and partial results
- Context awareness and memory integration
- Adaptive planning and re-planning
"""
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import json

from .base import BaseEvaluator, TestCase, EvaluationResult, EvaluationMetrics
from src.agents.supervisor import SupervisorAgent
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class AutonomyTestCase(TestCase):
    """Extended test case for autonomy evaluation"""
    expected_confidence_level: Optional[str] = None  # 'high', 'medium', 'low'
    expected_autonomous_execution: Optional[bool] = None
    expected_clarification_request: Optional[bool] = None
    expected_error_recovery: Optional[bool] = None
    expected_partial_success: Optional[bool] = None
    expected_context_usage: Optional[Dict[str, Any]] = None
    expected_plan_adaptation: Optional[bool] = None


class AutonomyEvaluator(BaseEvaluator):
    """Evaluates autonomous agent capabilities"""
    
    def __init__(self, agent: Optional[SupervisorAgent] = None, config: Optional[Dict[str, Any]] = None):
        """
        Initialize autonomy evaluator
        
        Args:
            agent: SupervisorAgent instance for executing queries
            config: Optional configuration
        """
        super().__init__(config)
        self.agent = agent
    
    async def evaluate(self, test_cases: List[TestCase]) -> EvaluationMetrics:
        """
        Evaluate autonomous capabilities on test cases
        
        Args:
            test_cases: List of test cases with autonomy expectations
            
        Returns:
            EvaluationMetrics with results
        """
        if not self.agent:
            logger.warning("No agent provided, skipping autonomy evaluation")
            return EvaluationMetrics()
        
        self.results = []
        
        for test_case in test_cases:
            start_time = time.time()
            
            try:
                # Validate query is not empty
                if not test_case.query or not test_case.query.strip():
                    raise ValueError("Query is empty")
                
                # Execute query using agent
                import asyncio
                response = await asyncio.wait_for(
                    self.agent.route_and_execute(
                        query=test_case.query,
                        user_id=test_case.context.get('user_id', 1) if test_case.context else 1
                    ),
                    timeout=120.0  # 2 minute timeout
                )
                
                # Extract autonomy details from response and execution
                autonomy_details = self._extract_autonomy_details(test_case, response)
                
                # Comprehensive autonomy evaluation
                passed = True
                errors = []
                details = {
                    'response': response[:500],  # Store first 500 chars
                    'autonomy_details': autonomy_details
                }
                
                # Check confidence-based decision making
                if hasattr(test_case, 'expected_confidence_level') and test_case.expected_confidence_level:
                    actual_confidence = autonomy_details.get('confidence_level', 'unknown')
                    expected_confidence = test_case.expected_confidence_level.lower()
                    
                    if actual_confidence != expected_confidence:
                        # This is informational, not a failure
                        details['confidence_mismatch'] = f"Expected {expected_confidence}, got {actual_confidence}"
                    else:
                        details['confidence_match'] = True
                
                # Check autonomous execution
                if hasattr(test_case, 'expected_autonomous_execution') and test_case.expected_autonomous_execution is not None:
                    actual_autonomous = autonomy_details.get('autonomous_execution', False)
                    expected_autonomous = test_case.expected_autonomous_execution
                    
                    if actual_autonomous != expected_autonomous:
                        passed = False
                        errors.append(f"Autonomous execution mismatch: expected {expected_autonomous}, got {actual_autonomous}")
                    else:
                        details['autonomous_execution_match'] = True
                
                # Check clarification request
                if hasattr(test_case, 'expected_clarification_request') and test_case.expected_clarification_request is not None:
                    actual_clarification = autonomy_details.get('clarification_requested', False)
                    expected_clarification = test_case.expected_clarification_request
                    
                    if actual_clarification != expected_clarification:
                        passed = False
                        errors.append(f"Clarification request mismatch: expected {expected_clarification}, got {actual_clarification}")
                    else:
                        details['clarification_match'] = True
                
                # Check error recovery
                if hasattr(test_case, 'expected_error_recovery') and test_case.expected_error_recovery is not None:
                    actual_recovery = autonomy_details.get('error_recovery', False)
                    expected_recovery = test_case.expected_error_recovery
                    
                    if expected_recovery and not actual_recovery:
                        passed = False
                        errors.append("Expected error recovery but none detected")
                    else:
                        details['error_recovery_match'] = True
                
                # Check partial success handling
                if hasattr(test_case, 'expected_partial_success') and test_case.expected_partial_success is not None:
                    actual_partial = autonomy_details.get('partial_success', False)
                    expected_partial = test_case.expected_partial_success
                    
                    if expected_partial and not actual_partial:
                        # Partial success is a nice-to-have, not critical
                        details['partial_success_note'] = "Expected partial success handling but none detected"
                    else:
                        details['partial_success_match'] = True
                
                # Check context usage
                if hasattr(test_case, 'expected_context_usage') and test_case.expected_context_usage:
                    actual_context = autonomy_details.get('context_used', {})
                    context_match = self._compare_context_usage(
                        test_case.expected_context_usage,
                        actual_context
                    )
                    
                    if not context_match['all_match']:
                        passed = False
                        errors.append(f"Context usage mismatch: {context_match['errors']}")
                    else:
                        details['context_usage_match'] = True
                    details['context_comparison'] = context_match
                
                # Check plan adaptation
                if hasattr(test_case, 'expected_plan_adaptation') and test_case.expected_plan_adaptation is not None:
                    actual_adaptation = autonomy_details.get('plan_adapted', False)
                    expected_adaptation = test_case.expected_plan_adaptation
                    
                    if expected_adaptation and not actual_adaptation:
                        # Plan adaptation is a nice-to-have, not critical
                        details['plan_adaptation_note'] = "Expected plan adaptation but none detected"
                    else:
                        details['plan_adaptation_match'] = True
                
                # Check response quality
                if test_case.expected_response_contains:
                    if not self._check_response_contains(response, test_case.expected_response_contains):
                        passed = False
                        errors.append(f"Response missing required terms: {test_case.expected_response_contains}")
                
                if test_case.expected_response_excludes:
                    if not self._check_response_excludes(response, test_case.expected_response_excludes):
                        passed = False
                        errors.append(f"Response contains forbidden terms: {test_case.expected_response_excludes}")
                
                # Check response is not empty
                if not response or len(response.strip()) < 10:
                    passed = False
                    errors.append("Response too short or empty")
                
                latency_ms = (time.time() - start_time) * 1000
                
                result_obj = EvaluationResult(
                    test_case=test_case,
                    actual_response=response,
                    passed=passed,
                    confidence=1.0 if passed else 0.5,
                    latency_ms=latency_ms,
                    error="; ".join(errors) if errors else None,
                    details=details
                )
                
            except Exception as e:
                logger.error(f"Error in autonomy evaluation for query '{test_case.query}': {e}", exc_info=True)
                result_obj = EvaluationResult(
                    test_case=test_case,
                    passed=False,
                    error=str(e),
                    latency_ms=(time.time() - start_time) * 1000
                )
            
            self.results.append(result_obj)
        
        self.metrics = self._calculate_metrics()
        return self.metrics
    
    def _extract_autonomy_details(self, test_case: TestCase, response: str) -> Dict[str, Any]:
        """
        Extract autonomy details from response and execution
        
        Args:
            test_case: Test case
            response: Agent response
            
        Returns:
            Dictionary with autonomy details
        """
        details = {
            'confidence_level': 'unknown',
            'autonomous_execution': False,
            'clarification_requested': False,
            'error_recovery': False,
            'partial_success': False,
            'context_used': {},
            'plan_adapted': False
        }
        
        response_lower = response.lower()
        
        # Detect autonomous execution (no clarification questions, direct action)
        # Use more sophisticated detection that looks for question patterns, not just words
        clarification_patterns = [
            r'\bwho\s+(?:is|are|do|does|did|should|can|could|will|would)\b',  # "who is", "who do"
            r'\bwhat\s+(?:is|are|do|does|did|should|can|could|will|would|did you mean)\b',  # "what is", "what do you mean"
            r'\bwhen\s+(?:is|are|do|does|did|should|can|could|will|would)\b',  # "when is", "when do"
            r'\bwhere\s+(?:is|are|do|does|did|should|can|could|will|would)\b',  # "where is", "where do"
            r'\bwhich\s+(?:one|person|email|meeting|task|do|does|did|should|can|could)\b',  # "which one", "which person"
            r'\bhow\s+(?:do|does|did|should|can|could|will|would)\b',  # "how do", "how should"
            r'\bcould you clarify\b',
            r'\bcan you tell me\b',
            r'\bi need to know\b',
            r'\bplease specify\b',
            r'\bwhat do you mean\b',
            r'\bi\'m not sure\b',
            r'\bcan you clarify\b',
            r'\bwould you clarify\b',
            r'\bneed more information\b',
            r'\bneed clarification\b',
            r'\bunclear\b',
            r'\bnot sure what\b',
            r'\bnot sure which\b',
            r'\bnot sure who\b',
        ]
        
        import re
        clarification_found = any(
            re.search(pattern, response_lower) for pattern in clarification_patterns
        )
        
        # Additional check: if response contains action verbs and results, it's autonomous
        action_indicators = [
            'scheduled', 'sent', 'found', 'created', 'completed', 'done',
            'successfully', 'finished', 'executed', 'performed'
        ]
        has_action_results = any(indicator in response_lower for indicator in action_indicators)
        
        # If we have action results, it's autonomous even if there's a question
        # (questions might be rhetorical or informational)
        if has_action_results:
            details['clarification_requested'] = False
            details['autonomous_execution'] = True
        else:
            details['clarification_requested'] = clarification_found
            details['autonomous_execution'] = not clarification_found
        
        # Detect error recovery (mentions of retry, alternative, fallback)
        error_recovery_indicators = [
            'retry', 'trying again', 'alternative', 'fallback',
            'instead', 'another way', 'workaround', 'recovered'
        ]
        
        details['error_recovery'] = any(
            indicator in response_lower for indicator in error_recovery_indicators
        )
        
        # Detect partial success (mentions of "some", "partially", "most")
        partial_success_indicators = [
            'some', 'partially', 'most', 'a few', 'several',
            'not all', 'some succeeded', 'partial'
        ]
        
        details['partial_success'] = any(
            indicator in response_lower for indicator in partial_success_indicators
        )
        
        # Infer confidence level from response tone
        if details['clarification_requested']:
            details['confidence_level'] = 'low'
        elif 'error' in response_lower or 'failed' in response_lower:
            details['confidence_level'] = 'low'
        elif 'successfully' in response_lower or 'done' in response_lower or 'completed' in response_lower:
            details['confidence_level'] = 'high'
        else:
            details['confidence_level'] = 'medium'
        
        # Detect context usage (references to previous conversation)
        context_indicators = [
            'earlier', 'previous', 'last time', 'before',
            'as mentioned', 'from earlier', 'that', 'the same'
        ]
        
        if any(indicator in response_lower for indicator in context_indicators):
            details['context_used'] = {'detected': True}
        
        # Detect plan adaptation (mentions of change, adjust, modify plan)
        adaptation_indicators = [
            'adjusting', 'modifying', 'changing', 'updating',
            'revising', 'adapting', 'new plan'
        ]
        
        details['plan_adapted'] = any(
            indicator in response_lower for indicator in adaptation_indicators
        )
        
        return details
    
    def _compare_context_usage(self, expected_context: Dict[str, Any], actual_context: Dict[str, Any]) -> Dict[str, Any]:
        """Compare expected vs actual context usage"""
        result = {
            'all_match': True,
            'errors': []
        }
        
        # Check if expected context keys are present
        for key, expected_value in expected_context.items():
            if key not in actual_context:
                result['all_match'] = False
                result['errors'].append(f"Missing context key: {key}")
            else:
                actual_value = actual_context[key]
                # Simple comparison - could be enhanced
                if isinstance(expected_value, bool):
                    if expected_value != actual_value:
                        result['all_match'] = False
                        result['errors'].append(f"Context value mismatch for {key}: expected {expected_value}, got {actual_value}")
        
        return result

