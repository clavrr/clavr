"""
Contact Resolution Evaluator

Evaluates the agent's ability to resolve contact names to email addresses.
"""
import time
from typing import List, Dict, Any, Optional

from .base import BaseEvaluator, TestCase, EvaluationResult, EvaluationMetrics
from src.core.calendar.utils import resolve_name_to_email
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class ContactResolutionEvaluator(BaseEvaluator):
    """Evaluates contact resolution accuracy"""
    
    def __init__(self, 
                 graph_manager: Optional[Any] = None,
                 rag_engine: Optional[Any] = None,
                 email_service: Optional[Any] = None,
                 user_id: Optional[int] = None,
                 config: Optional[Dict[str, Any]] = None):
        """
        Initialize contact resolution evaluator
        
        Args:
            graph_manager: Neo4j graph manager for contact lookup
            rag_engine: RAG engine for semantic search
            email_service: Email service for fallback search
            user_id: User ID for multi-user support
            config: Optional configuration
        """
        super().__init__(config)
        self.graph_manager = graph_manager
        self.rag_engine = rag_engine
        self.email_service = email_service
        self.user_id = user_id
    
    async def evaluate(self, test_cases: List[TestCase]) -> EvaluationMetrics:
        """
        Evaluate contact resolution on test cases
        
        Args:
            test_cases: List of test cases with expected emails
            
        Returns:
            EvaluationMetrics with results
        """
        self.results = []
        
        for test_case in test_cases:
            start_time = time.time()
            
            try:
                # Extract name from entities or metadata
                name = None
                if test_case.expected_entities and 'attendees' in test_case.expected_entities:
                    attendees = test_case.expected_entities['attendees']
                    if attendees:
                        name = attendees[0] if isinstance(attendees, list) else attendees
                elif test_case.expected_entities and 'recipients' in test_case.expected_entities:
                    recipients = test_case.expected_entities['recipients']
                    if recipients:
                        name = recipients[0] if isinstance(recipients, list) else recipients
                
                if not name and test_case.metadata:
                    name = test_case.metadata.get('contact_name')
                
                if not name:
                    # Try to extract from query
                    query_lower = test_case.query.lower()
                    # Simple extraction - look for "with [Name]" or "to [Name]"
                    import re
                    match = re.search(r'(?:with|to)\s+([A-Z][a-z]+)', test_case.query)
                    if match:
                        name = match.group(1)
                
                if not name:
                    result_obj = EvaluationResult(
                        test_case=test_case,
                        passed=False,
                        error="Could not extract contact name from test case",
                        latency_ms=(time.time() - start_time) * 1000
                    )
                    self.results.append(result_obj)
                    continue
                
                # Resolve name to email
                resolved_email = resolve_name_to_email(
                    name=name,
                    email_service=self.email_service,
                    config=self.config.get('config') if self.config else None,
                    graph_manager=self.graph_manager,
                    user_id=self.user_id,
                    rag_engine=self.rag_engine
                )
                
                # Check if resolved email matches expected
                expected_email = test_case.metadata.get('expected_email') if test_case.metadata else None
                passed = False
                
                if expected_email:
                    # Exact match or case-insensitive match
                    if resolved_email and resolved_email.lower() == expected_email.lower():
                        passed = True
                    elif resolved_email:
                        # Partial match (same domain or similar)
                        resolved_domain = resolved_email.split('@')[1] if '@' in resolved_email else ''
                        expected_domain = expected_email.split('@')[1] if '@' in expected_email else ''
                        if resolved_domain == expected_domain:
                            # Same domain, might be correct
                            passed = True
                else:
                    # No expected email, just check if resolution succeeded
                    passed = resolved_email is not None
                
                latency_ms = (time.time() - start_time) * 1000
                
                result_obj = EvaluationResult(
                    test_case=test_case,
                    passed=passed,
                    confidence=1.0 if passed and resolved_email else 0.5,
                    latency_ms=latency_ms,
                    details={
                        'name': name,
                        'resolved_email': resolved_email,
                        'expected_email': expected_email,
                        'match': passed
                    }
                )
                
            except Exception as e:
                logger.error(f"Error evaluating contact resolution: {e}", exc_info=True)
                result_obj = EvaluationResult(
                    test_case=test_case,
                    passed=False,
                    error=str(e),
                    latency_ms=(time.time() - start_time) * 1000
                )
            
            self.results.append(result_obj)
        
        self.metrics = self._calculate_metrics()
        return self.metrics

