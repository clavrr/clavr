"""
Response Quality Evaluator

Evaluates the quality and correctness of agent responses.
"""
import time
from typing import List, Dict, Any, Optional

from .base import BaseEvaluator, TestCase, EvaluationResult, EvaluationMetrics
from src.agents.supervisor import SupervisorAgent
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class ResponseQualityEvaluator(BaseEvaluator):
    """Evaluates response quality and correctness"""
    
    def __init__(self, agent: Optional[SupervisorAgent] = None, config: Optional[Dict[str, Any]] = None):
        """
        Initialize response quality evaluator
        
        Args:
            agent: SupervisorAgent instance for executing queries
            config: Optional configuration
        """
        super().__init__(config)
        self.agent = agent
    
    async def evaluate(self, test_cases: List[TestCase]) -> EvaluationMetrics:
        """
        Evaluate response quality on test cases
        
        Args:
            test_cases: List of test cases with expected response criteria
            
        Returns:
            EvaluationMetrics with results
        """
        if not self.agent:
            logger.warning("No agent provided, skipping response quality evaluation")
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
                # SupervisorAgent uses route_and_execute(query, user_id)
                # It does not take session_id directly in the same way, usually handles internally via user_id
                response = await asyncio.wait_for(
                    self.agent.route_and_execute(
                        query=test_case.query,
                        user_id=test_case.context.get('user_id', 1) if test_case.context else 1
                    ),
                    timeout=60.0  # 60 second timeout per query
                )
                
                # Check response quality criteria
                passed = True
                errors = []
                
                # Check if response contains required terms
                if test_case.expected_response_contains:
                    if not self._check_response_contains(response, test_case.expected_response_contains):
                        passed = False
                        errors.append(f"Response missing required terms: {test_case.expected_response_contains}")
                
                # Check if response excludes forbidden terms
                if test_case.expected_response_excludes:
                    if not self._check_response_excludes(response, test_case.expected_response_excludes):
                        passed = False
                        errors.append(f"Response contains forbidden terms: {test_case.expected_response_excludes}")
                
                # Check response length (should not be empty)
                if not response or len(response.strip()) < 10:
                    passed = False
                    errors.append("Response too short or empty")
                
                latency_ms = (time.time() - start_time) * 1000
                
                result_obj = EvaluationResult(
                    test_case=test_case,
                    actual_response=response,
                    passed=passed,
                    confidence=1.0 if passed else 0.0,
                    latency_ms=latency_ms,
                    error="; ".join(errors) if errors else None,
                    details={
                        'response_length': len(response),
                        'contains_check': self._check_response_contains(response, test_case.expected_response_contains or []),
                        'excludes_check': self._check_response_excludes(response, test_case.expected_response_excludes or [])
                    }
                )
                
            except Exception as e:
                logger.error(f"Error evaluating response for query '{test_case.query}': {e}", exc_info=True)
                result_obj = EvaluationResult(
                    test_case=test_case,
                    passed=False,
                    error=str(e),
                    latency_ms=(time.time() - start_time) * 1000
                )
            
            self.results.append(result_obj)
        
        self.metrics = self._calculate_metrics()
        return self.metrics

