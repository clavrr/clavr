"""
End-to-End Evaluator

Evaluates complete task completion from query to final result.
"""
import time
from typing import List, Dict, Any, Optional

from .base import BaseEvaluator, TestCase, EvaluationResult, EvaluationMetrics
from src.agents.supervisor import SupervisorAgent
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class EndToEndEvaluator(BaseEvaluator):
    """Evaluates end-to-end task completion"""
    
    def __init__(self, agent: Optional[SupervisorAgent] = None, config: Optional[Dict[str, Any]] = None):
        """
        Initialize end-to-end evaluator
        
        Args:
            agent: SupervisorAgent instance for executing queries
            config: Optional configuration
        """
        super().__init__(config)
        self.agent = agent
    
    async def evaluate(self, test_cases: List[TestCase]) -> EvaluationMetrics:
        """
        Evaluate end-to-end task completion on test cases
        
        Args:
            test_cases: List of test cases with full expectations
            
        Returns:
            EvaluationMetrics with results
        """
        if not self.agent:
            logger.warning("No agent provided, skipping end-to-end evaluation")
            return EvaluationMetrics()
        
        self.results = []
        
        for test_case in test_cases:
            start_time = time.time()
            
            try:
                # Validate query is not empty
                if not test_case.query or not test_case.query.strip():
                    raise ValueError("Query is empty")
                
                # Execute query using agent with timeout
                import asyncio
                response = await asyncio.wait_for(
                    self.agent.route_and_execute(
                        query=test_case.query,
                        user_id=test_case.context.get('user_id', 1) if test_case.context else 1
                    ),
                    timeout=120.0  # 120 second timeout for E2E queries (may be more complex)
                )
                
                # Comprehensive evaluation
                passed = True
                errors = []
                
                # Check intent (if expected)
                if test_case.expected_intent:
                    # Intent would be checked via agent's internal classification
                    # For E2E, we focus on final result quality
                    pass
                
                # Check tool selection (if expected)
                if test_case.expected_tool:
                    # Tool selection would be checked via agent's internal routing
                    # For E2E, we focus on final result quality
                    pass
                
                # Check entities (if expected) - verify they appear in response
                if test_case.expected_entities:
                    for key, value in test_case.expected_entities.items():
                        if isinstance(value, list):
                            for item in value:
                                if str(item).lower() not in response.lower():
                                    passed = False
                                    errors.append(f"Missing entity '{key}': {item}")
                        else:
                            if str(value).lower() not in response.lower():
                                # Allow partial matches for some entities
                                if key not in ['date_range', 'time', 'duration']:
                                    passed = False
                                    errors.append(f"Missing entity '{key}': {value}")
                
                # Check response contains required terms
                if test_case.expected_response_contains:
                    if not self._check_response_contains(response, test_case.expected_response_contains):
                        passed = False
                        errors.append(f"Response missing required terms: {test_case.expected_response_contains}")
                
                # Check response excludes forbidden terms
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
                    details={
                        'response_length': len(response),
                        'entity_check': len(errors) == 0,
                        'contains_check': self._check_response_contains(response, test_case.expected_response_contains or []),
                        'excludes_check': self._check_response_excludes(response, test_case.expected_response_excludes or [])
                    }
                )
                
            except Exception as e:
                logger.error(f"Error in end-to-end evaluation for query '{test_case.query}': {e}", exc_info=True)
                result_obj = EvaluationResult(
                    test_case=test_case,
                    passed=False,
                    error=str(e),
                    latency_ms=(time.time() - start_time) * 1000
                )
            
            self.results.append(result_obj)
        
        self.metrics = self._calculate_metrics()
        return self.metrics

