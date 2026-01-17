"""
Intent Classification Evaluator

Evaluates the agent's ability to correctly classify user query intents.
"""
import time
from typing import List, Dict, Any, Optional
from datetime import datetime

from .base import BaseEvaluator, TestCase, EvaluationResult, EvaluationMetrics
from src.agents.intent import classify_query_intent
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class IntentClassificationEvaluator(BaseEvaluator):
    """Evaluates intent classification accuracy"""
    
    async def evaluate(self, test_cases: List[TestCase]) -> EvaluationMetrics:
        """
        Evaluate intent classification on test cases
        
        Args:
            test_cases: List of test cases with expected intents
            
        Returns:
            EvaluationMetrics with results
        """
        self.results = []
        
        for test_case in test_cases:
            start_time = time.time()
            
            try:
                # Classify intent using agent's intent classification
                result = classify_query_intent(test_case.query)
                predicted_intent = result.get('intent', result.get('primary_intent', 'unknown'))
                confidence_str = result.get('confidence', 'low')
                predicted_domain = result.get('domain', 'general')
                
                # Convert confidence string to float
                confidence_map = {'high': 0.9, 'medium': 0.7, 'low': 0.5}
                confidence = confidence_map.get(confidence_str.lower(), 0.5)
                
                # Check if intent matches (handle domain mapping)
                expected_intent = test_case.expected_intent
                passed = self._check_intent_match(expected_intent, predicted_intent, predicted_domain)
                
                latency_ms = (time.time() - start_time) * 1000
                
                result_obj = EvaluationResult(
                    test_case=test_case,
                    predicted_intent=predicted_intent,
                    passed=passed,
                    confidence=confidence,
                    latency_ms=latency_ms,
                    details={
                        'predicted_domain': predicted_domain,
                        'confidence_str': confidence_str
                    }
                )
                
            except Exception as e:
                logger.error(f"Error evaluating intent for query '{test_case.query}': {e}", exc_info=True)
                result_obj = EvaluationResult(
                    test_case=test_case,
                    passed=False,
                    error=str(e),
                    latency_ms=(time.time() - start_time) * 1000
                )
            
            self.results.append(result_obj)
        
        self.metrics = self._calculate_metrics()
        return self.metrics
    
    def _check_intent_match(self, expected: Optional[str], predicted: str, domain: str) -> bool:
        """
        Check if predicted intent matches expected intent
        """
        if expected is None:
            return True  # No expectation, consider passed
        
        expected_lower = expected.lower()
        predicted_lower = predicted.lower()
        
        # Exact match
        if expected_lower == predicted_lower:
            return True
        
        # Domain-based matching (Dynamic from constants)
        from src.agents.constants import INTENT_KEYWORDS
        
        if domain in INTENT_KEYWORDS:
            valid_intents = INTENT_KEYWORDS[domain].keys()
            
            # 1. Category match (e.g. predicted 'search' matches expected 'email_search')
            for valid_intent in valid_intents:
                if valid_intent in expected_lower and valid_intent == predicted_lower:
                    return True
                if valid_intent in predicted_lower and valid_intent == expected_lower:
                    return True
            
            # 2. Keyword containment (e.g. Expected='manage', Predicted='archive')
            # Check if expected is a category and predicted is a keyword in it
            if expected_lower in INTENT_KEYWORDS[domain]:
                if predicted_lower in INTENT_KEYWORDS[domain][expected_lower]:
                    return True
            
            # Check reverse (Expected='archive', Predicted='manage') - less likely but possible
            if predicted_lower in INTENT_KEYWORDS[domain]:
                if expected_lower in INTENT_KEYWORDS[domain][predicted_lower]:
                    return True
        
        return False
    
    def _calculate_precision(self) -> float:
        """Calculate precision for intent classification"""
        if not self.results:
            return 0.0
        
        true_positives = sum(1 for r in self.results if r.passed and r.test_case.expected_intent)
        false_positives = sum(1 for r in self.results if not r.passed and r.test_case.expected_intent)
        
        if true_positives + false_positives == 0:
            return 0.0
        
        return true_positives / (true_positives + false_positives)
    
    def _calculate_recall(self) -> float:
        """Calculate recall for intent classification"""
        if not self.results:
            return 0.0
        
        true_positives = sum(1 for r in self.results if r.passed and r.test_case.expected_intent)
        false_negatives = sum(1 for r in self.results if not r.passed and r.test_case.expected_intent)
        
        if true_positives + false_negatives == 0:
            return 0.0
        
        return true_positives / (true_positives + false_negatives)

