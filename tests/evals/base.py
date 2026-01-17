"""
Base Evaluation Framework

Provides base classes and utilities for all evaluations.
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from abc import ABC, abstractmethod
import json

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class EvaluationMetrics:
    """Metrics for evaluation results"""
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    average_confidence: float = 0.0
    average_latency_ms: float = 0.0
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'accuracy': self.accuracy,
            'precision': self.precision,
            'recall': self.recall,
            'f1_score': self.f1_score,
            'total_tests': self.total_tests,
            'passed_tests': self.passed_tests,
            'failed_tests': self.failed_tests,
            'pass_rate': self.passed_tests / self.total_tests if self.total_tests > 0 else 0.0,
            'average_confidence': self.average_confidence,
            'average_latency_ms': self.average_latency_ms,
            'error_count': len(self.errors)
        }


@dataclass
class TestCase:
    """Single test case for evaluation"""
    query: str
    expected_intent: Optional[str] = None
    expected_entities: Optional[Dict[str, Any]] = None
    expected_tool: Optional[str] = None
    expected_response_contains: Optional[List[str]] = None
    expected_response_excludes: Optional[List[str]] = None
    context: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    # Multi-step evaluation fields
    expected_step_count: Optional[int] = None
    expected_domains: Optional[List[str]] = None
    expected_dependencies: Optional[List[Dict[str, Any]]] = None
    expected_parallel_steps: Optional[List[List[int]]] = None
    expected_context_passing: Optional[Dict[str, Any]] = None
    # Autonomy evaluation fields
    expected_confidence_level: Optional[str] = None
    expected_autonomous_execution: Optional[bool] = None
    expected_clarification_request: Optional[bool] = None
    expected_error_recovery: Optional[bool] = None
    expected_partial_success: Optional[bool] = None
    expected_context_usage: Optional[Dict[str, Any]] = None
    expected_plan_adaptation: Optional[bool] = None


@dataclass
class EvaluationResult:
    """Result of a single evaluation"""
    test_case: TestCase
    predicted_intent: Optional[str] = None
    predicted_entities: Optional[Dict[str, Any]] = None
    predicted_tool: Optional[str] = None
    actual_response: Optional[str] = None
    passed: bool = False
    confidence: float = 0.0
    latency_ms: float = 0.0
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'query': self.test_case.query,
            'passed': self.passed,
            'confidence': self.confidence,
            'latency_ms': self.latency_ms,
            'error': self.error,
            'expected': {
                'intent': self.test_case.expected_intent,
                'entities': self.test_case.expected_entities,
                'tool': self.test_case.expected_tool
            },
            'predicted': {
                'intent': self.predicted_intent,
                'entities': self.predicted_entities,
                'tool': self.predicted_tool
            },
            'details': self.details
        }


class BaseEvaluator(ABC):
    """Base class for all evaluators"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize evaluator
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.results: List[EvaluationResult] = []
        self.metrics = EvaluationMetrics()
    
    @abstractmethod
    async def evaluate(self, test_cases: List[TestCase]) -> EvaluationMetrics:
        """
        Run evaluation on test cases
        
        Args:
            test_cases: List of test cases to evaluate
            
        Returns:
            EvaluationMetrics with results
        """
        pass
    
    def _calculate_metrics(self) -> EvaluationMetrics:
        """Calculate metrics from results"""
        if not self.results:
            return EvaluationMetrics()
        
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        
        # Calculate accuracy
        accuracy = passed / total if total > 0 else 0.0
        
        # Calculate average confidence
        confidences = [r.confidence for r in self.results if r.confidence > 0]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        
        # Calculate average latency
        latencies = [r.latency_ms for r in self.results if r.latency_ms > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        
        # Collect errors
        errors = [r.error for r in self.results if r.error]
        
        # Calculate precision, recall, F1 (if applicable)
        precision = self._calculate_precision()
        recall = self._calculate_recall()
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        return EvaluationMetrics(
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1_score,
            total_tests=total,
            passed_tests=passed,
            failed_tests=failed,
            average_confidence=avg_confidence,
            average_latency_ms=avg_latency,
            errors=errors
        )
    
    def _calculate_precision(self) -> float:
        """Calculate precision (subclass can override)"""
        # Default implementation - can be overridden
        return self.metrics.accuracy
    
    def _calculate_recall(self) -> float:
        """Calculate recall (subclass can override)"""
        # Default implementation - can be overridden
        return self.metrics.accuracy
    
    def _compare_entities(self, expected: Optional[Dict[str, Any]], predicted: Optional[Dict[str, Any]]) -> bool:
        """
        Compare entities with fuzzy matching
        
        Args:
            expected: Expected entities
            predicted: Predicted entities
            
        Returns:
            True if entities match (with tolerance)
        """
        if expected is None and predicted is None:
            return True
        if expected is None or predicted is None:
            return False
        
        # Check each expected entity
        for key, expected_value in expected.items():
            if key not in predicted:
                # Allow partial matches for some entity types
                if key in ['date_range', 'time', 'duration']:
                    continue  # Time entities are fuzzy
                return False
            
            predicted_value = predicted[key]
            
            # Handle different types
            if isinstance(expected_value, list):
                if not isinstance(predicted_value, list):
                    return False
                # Check if all expected items are in predicted (order doesn't matter)
                if not all(item in predicted_value for item in expected_value):
                    return False
            elif isinstance(expected_value, dict):
                if not isinstance(predicted_value, dict):
                    return False
                # Recursive comparison for nested dicts
                if not self._compare_entities(expected_value, predicted_value):
                    return False
            else:
                # String comparison with case insensitivity
                if str(expected_value).lower() != str(predicted_value).lower():
                    return False
        
        return True
    
    def _check_response_contains(self, response: str, contains: List[str]) -> bool:
        """
        Check if response contains all required strings.
        Uses flexible matching with synonyms and word boundaries.
        """
        if not contains:
            return True
        response_lower = response.lower()
        
        # Define synonyms for common terms
        synonyms = {
            'meeting': ['meeting', 'appointment', 'event', 'schedule', 'scheduled'],
            'email': ['email', 'message', 'mail', 'message'],
            'john': ['john', 'joh'],
            'sarah': ['sarah', 'sara'],
            'tomorrow': ['tomorrow', 'tomorrow\'s', 'next day'],
            'schedule': ['schedule', 'scheduled', 'scheduling', 'set up', 'arrange'],
            'task': ['task', 'todo', 'reminder', 'action item'],
            'reply': ['reply', 'replied', 'response', 'respond'],
            'send': ['send', 'sent', 'sending', 'deliver'],
            'find': ['find', 'found', 'search', 'searched', 'locate'],
        }
        
        # Check each term - allow synonyms and partial matches
        for term in contains:
            term_lower = term.lower()
            # Try exact match first
            if term_lower in response_lower:
                continue
            
            # Try synonyms
            term_synonyms = synonyms.get(term_lower, [])
            if any(syn in response_lower for syn in term_synonyms):
                continue
            
            # Try word boundary match (more flexible)
            import re
            # Allow partial word matches (e.g., "john" matches "john's", "johns")
            pattern = r'\b' + re.escape(term_lower) + r'[a-z]*\b'
            if re.search(pattern, response_lower):
                continue
            
            # If still not found, check if it's a name (capitalized) - try case-insensitive
            if term[0].isupper():
                # Try finding the name in any case
                name_pattern = r'\b' + re.escape(term_lower) + r'[a-z]*\b'
                if re.search(name_pattern, response_lower, re.IGNORECASE):
                    continue
            
            # Term not found
            return False
        
        return True
    
    def _check_response_excludes(self, response: str, excludes: List[str]) -> bool:
        """Check if response excludes all forbidden strings"""
        if not excludes:
            return True
        response_lower = response.lower()
        return all(term.lower() not in response_lower for term in excludes)
    
    def save_results(self, filepath: str) -> None:
        """Save evaluation results to JSON file"""
        output = {
            'timestamp': datetime.utcnow().isoformat(),
            'metrics': self.metrics.to_dict(),
            'results': [r.to_dict() for r in self.results]
        }
        
        with open(filepath, 'w') as f:
            json.dump(output, f, indent=2)
        
        logger.info(f"Saved evaluation results to {filepath}")
    
    def print_summary(self) -> None:
        """Print evaluation summary"""
        print("\n" + "="*60)
        print("EVALUATION SUMMARY")
        print("="*60)
        print(f"Total Tests: {self.metrics.total_tests}")
        print(f"Passed: {self.metrics.passed_tests}")
        print(f"Failed: {self.metrics.failed_tests}")
        print(f"Accuracy: {self.metrics.accuracy:.2%}")
        print(f"Precision: {self.metrics.precision:.2%}")
        print(f"Recall: {self.metrics.recall:.2%}")
        print(f"F1 Score: {self.metrics.f1_score:.2%}")
        print(f"Average Confidence: {self.metrics.average_confidence:.2%}")
        print(f"Average Latency: {self.metrics.average_latency_ms:.2f}ms")
        if self.metrics.errors:
            print(f"\nErrors ({len(self.metrics.errors)}):")
            for error in self.metrics.errors[:5]:  # Show first 5
                print(f"  - {error}")
        print("="*60 + "\n")

