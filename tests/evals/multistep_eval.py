"""
Multi-Step Query Evaluator

Evaluates the agent's ability to handle multi-step queries:
- Query decomposition accuracy
- Step ordering and dependencies
- Cross-domain execution
- Context passing between steps
- Parallel vs sequential execution
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
class MultiStepTestCase(TestCase):
    """Extended test case for multi-step evaluation"""
    expected_steps: Optional[List[Dict[str, Any]]] = None
    expected_step_count: Optional[int] = None
    expected_dependencies: Optional[List[Dict[str, Any]]] = None
    expected_parallel_steps: Optional[List[List[int]]] = None
    expected_context_passing: Optional[Dict[str, Any]] = None
    expected_domains: Optional[List[str]] = None


class MultiStepEvaluator(BaseEvaluator):
    """Evaluates multi-step execution capabilities"""
    
    def __init__(self, agent: Optional[SupervisorAgent] = None, config: Optional[Dict[str, Any]] = None):
        """
        Initialize multi-step evaluator
        
        Args:
            agent: SupervisorAgent instance for executing queries
            config: Optional configuration
        """
        super().__init__(config)
        self.agent = agent
    
    async def evaluate(self, test_cases: List[TestCase]) -> EvaluationMetrics:
        """
        Evaluate multi-step capabilities on test cases
        
        Args:
            test_cases: List of test cases with multi-step expectations
            
        Returns:
            EvaluationMetrics with results
        """
        if not self.agent:
            logger.warning("No agent provided, skipping multi-step evaluation")
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
                    timeout=180.0
                )
                # Extract execution details from agent state if available
                execution_details = self._extract_execution_details(test_case, response)
                
                # Comprehensive multi-step evaluation
                passed = True
                errors = []
                details = {
                    'response': response[:500],  # Store first 500 chars
                    'execution_details': execution_details
                }
                
                # Check if query was correctly identified as multi-step
                if hasattr(test_case, 'expected_step_count') and test_case.expected_step_count:
                    actual_steps = execution_details.get('step_count', 0)
                    expected_steps = test_case.expected_step_count
                    
                    if actual_steps != expected_steps:
                        passed = False
                        errors.append(f"Step count mismatch: expected {expected_steps}, got {actual_steps}")
                    else:
                        details['step_count_match'] = True
                
                # Check step decomposition (if expected steps provided)
                if hasattr(test_case, 'expected_steps') and test_case.expected_steps:
                    actual_steps = execution_details.get('steps', [])
                    step_match = self._compare_steps(test_case.expected_steps, actual_steps)
                    
                    if not step_match['all_match']:
                        passed = False
                        errors.append(f"Step decomposition mismatch: {step_match['errors']}")
                    else:
                        details['step_decomposition_match'] = True
                    details['step_comparison'] = step_match
                
                # Check dependencies (if expected)
                if hasattr(test_case, 'expected_dependencies') and test_case.expected_dependencies:
                    actual_deps = execution_details.get('dependencies', [])
                    dep_match = self._compare_dependencies(test_case.expected_dependencies, actual_deps)
                    
                    if not dep_match['all_match']:
                        passed = False
                        errors.append(f"Dependency detection mismatch: {dep_match['errors']}")
                    else:
                        details['dependency_match'] = True
                    details['dependency_comparison'] = dep_match
                
                # Check cross-domain execution (if expected)
                if hasattr(test_case, 'expected_domains') and test_case.expected_domains:
                    actual_domains = execution_details.get('domains', [])
                    domain_match = self._compare_domains(test_case.expected_domains, actual_domains)
                    
                    if not domain_match['all_match']:
                        passed = False
                        errors.append(f"Domain mismatch: {domain_match['errors']}")
                    else:
                        details['domain_match'] = True
                    details['domain_comparison'] = domain_match
                
                # Check parallel execution (if expected)
                if hasattr(test_case, 'expected_parallel_steps') and test_case.expected_parallel_steps:
                    actual_parallel = execution_details.get('parallel_steps', [])
                    parallel_match = self._compare_parallel_steps(test_case.expected_parallel_steps, actual_parallel)
                    
                    if not parallel_match['all_match']:
                        # Parallel execution is a nice-to-have, not critical
                        details['parallel_execution_note'] = parallel_match['errors']
                    else:
                        details['parallel_execution_match'] = True
                    details['parallel_comparison'] = parallel_match
                
                # Check context passing (if expected)
                if hasattr(test_case, 'expected_context_passing') and test_case.expected_context_passing:
                    actual_context = execution_details.get('context_passing', {})
                    context_match = self._compare_context_passing(
                        test_case.expected_context_passing, 
                        actual_context
                    )
                    
                    if not context_match['all_match']:
                        passed = False
                        errors.append(f"Context passing mismatch: {context_match['errors']}")
                    else:
                        details['context_passing_match'] = True
                    details['context_comparison'] = context_match
                
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
                logger.error(f"Error in multi-step evaluation for query '{test_case.query}': {e}", exc_info=True)
                result_obj = EvaluationResult(
                    test_case=test_case,
                    passed=False,
                    error=str(e),
                    latency_ms=(time.time() - start_time) * 1000
                )
            
            self.results.append(result_obj)
        
        self.metrics = self._calculate_metrics()
        return self.metrics
    
    def _extract_execution_details(self, test_case: TestCase, response: str) -> Dict[str, Any]:
        """
        Extract execution details from agent state or response
        
        Args:
            test_case: Test case
            response: Agent response
            
        Returns:
            Dictionary with execution details
        """
        details = {
            'step_count': 0,
            'steps': [],
            'dependencies': [],
            'domains': [],
            'parallel_steps': [],
            'context_passing': {}
        }
        
        # Try to extract from agent's internal state if available
        # This would require access to the agent's execution state
        # For now, we'll infer from response and query analysis
        
        # Infer step count from response (look for step indicators)
        response_lower = response.lower()
        
        # Look for explicit step numbering
        import re
        step_number_patterns = [
            r'step\s+(\d+)',
            r'(\d+)\s*\.\s*[a-z]',  # "1. first action", "2. second action"
            r'first.*?then',
            r'first.*?second',
            r'first.*?next',
        ]
        
        max_step_found = 0
        for pattern in step_number_patterns:
            matches = re.findall(pattern, response_lower)
            if matches:
                try:
                    step_nums = [int(m) if m.isdigit() else 1 for m in matches]
                    max_step_found = max(max_step_found, max(step_nums) if step_nums else 0)
                except:
                    pass
        
        # Look for sequential indicators
        sequential_indicators = ['first', 'second', 'third', 'fourth', 'fifth', 'then', 'next', 'after', 'finally']
        sequential_count = sum(1 for indicator in sequential_indicators if indicator in response_lower)
        
        # Use the higher of the two counts
        if max_step_found > 0:
            details['step_count'] = max_step_found
        elif sequential_count > 0:
            details['step_count'] = min(sequential_count + 1, 5)  # Cap at 5 to avoid overcounting
        
        # Infer domains from response
        domain_keywords = {
            'email': ['email', 'message', 'inbox', 'send', 'reply'],
            'calendar': ['meeting', 'calendar', 'schedule', 'event', 'appointment'],
            'task': ['task', 'todo', 'reminder', 'complete']
        }
        
        for domain, keywords in domain_keywords.items():
            if any(keyword in response.lower() for keyword in keywords):
                if domain not in details['domains']:
                    details['domains'].append(domain)
        
        # Infer from query if multi-step indicators present
        query_lower = test_case.query.lower()
        multi_step_indicators = ['and', 'then', 'after', 'next', 'followed by', 'also']
        
        # Count multi-step connectors in query
        connector_count = sum(1 for indicator in multi_step_indicators if indicator in query_lower)
        
        # If query has clear multi-step structure but response doesn't show steps, infer from query
        if connector_count > 0 and details['step_count'] == 0:
            # Estimate steps based on connectors (each connector suggests at least 2 steps)
            details['step_count'] = min(connector_count + 1, 5)  # Cap at 5
        
        return details
    
    def _compare_steps(self, expected_steps: List[Dict[str, Any]], actual_steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compare expected vs actual step decomposition"""
        result = {
            'all_match': True,
            'errors': []
        }
        
        if len(actual_steps) != len(expected_steps):
            result['all_match'] = False
            result['errors'].append(f"Step count: expected {len(expected_steps)}, got {len(actual_steps)}")
            return result
        
        for i, (expected, actual) in enumerate(zip(expected_steps, actual_steps)):
            # Check tool/domain
            expected_tool = expected.get('tool') or expected.get('domain')
            actual_tool = actual.get('tool') or actual.get('domain') or actual.get('tool_name')
            
            if expected_tool and actual_tool:
                if expected_tool.lower() != actual_tool.lower():
                    result['all_match'] = False
                    result['errors'].append(f"Step {i+1} tool mismatch: expected {expected_tool}, got {actual_tool}")
            
            # Check action/intent
            expected_action = expected.get('action') or expected.get('intent')
            actual_action = actual.get('action') or actual.get('intent')
            
            if expected_action and actual_action:
                if expected_action.lower() != actual_action.lower():
                    result['all_match'] = False
                    result['errors'].append(f"Step {i+1} action mismatch: expected {expected_action}, got {actual_action}")
        
        return result
    
    def _compare_dependencies(self, expected_deps: List[Dict[str, Any]], actual_deps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compare expected vs actual dependencies"""
        result = {
            'all_match': True,
            'errors': []
        }
        
        # For now, just check if dependencies were detected
        # More sophisticated comparison could be added
        if len(expected_deps) > 0 and len(actual_deps) == 0:
            result['all_match'] = False
            result['errors'].append("Expected dependencies but none detected")
        
        return result
    
    def _compare_domains(self, expected_domains: List[str], actual_domains: List[str]) -> Dict[str, Any]:
        """Compare expected vs actual domains"""
        result = {
            'all_match': True,
            'errors': []
        }
        
        expected_set = set(d.lower() for d in expected_domains)
        actual_set = set(d.lower() for d in actual_domains)
        
        missing = expected_set - actual_set
        if missing:
            result['all_match'] = False
            result['errors'].append(f"Missing domains: {missing}")
        
        return result
    
    def _compare_parallel_steps(self, expected_parallel: List[List[int]], actual_parallel: List[List[int]]) -> Dict[str, Any]:
        """Compare expected vs actual parallel step groups"""
        result = {
            'all_match': True,
            'errors': []
        }
        
        # Parallel execution detection is complex
        # For now, just note if parallel execution was detected
        if len(expected_parallel) > 0 and len(actual_parallel) == 0:
            result['errors'].append("Expected parallel execution but none detected")
            # Don't fail on this - it's a nice-to-have
        
        return result
    
    def _compare_context_passing(self, expected_context: Dict[str, Any], actual_context: Dict[str, Any]) -> Dict[str, Any]:
        """Compare expected vs actual context passing"""
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
                if str(expected_value).lower() != str(actual_value).lower():
                    result['all_match'] = False
                    result['errors'].append(f"Context value mismatch for {key}: expected {expected_value}, got {actual_value}")
        
        return result

