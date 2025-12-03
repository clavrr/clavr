"""
Notion Learning System - Learn from user feedback and improve parsing

Tracks successful queries and corrections to improve future parsing accuracy.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class NotionLearningSystem:
    """Learning system for Notion parser"""
    
    def __init__(self, memory=None):
        self.memory = memory
        self.successful_queries: List[Dict[str, Any]] = []
        self.corrections: List[Dict[str, Any]] = []
    
    def record_classification_result(
        self,
        query: str,
        predicted_action: str,
        llm_classification: Optional[Dict[str, Any]],
        success: bool
    ):
        """
        Record classification result for learning
        
        Args:
            query: User query
            predicted_action: Action that was predicted
            llm_classification: LLM classification result
            success: Whether the classification was successful
        """
        result = {
            'query': query,
            'predicted_action': predicted_action,
            'llm_classification': llm_classification,
            'success': success,
            'timestamp': datetime.now().isoformat()
        }
        
        if success:
            self.successful_queries.append(result)
            # Keep only recent successful queries
            if len(self.successful_queries) > 50:
                self.successful_queries = self.successful_queries[-50:]
        else:
            self.corrections.append(result)
            # Keep only recent corrections
            if len(self.corrections) > 100:
                self.corrections = self.corrections[-100:]
    
    def get_similar_examples(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """
        Get similar successful examples for few-shot learning
        
        Args:
            query: Current query
            limit: Maximum number of examples to return
            
        Returns:
            List of similar example queries
        """
        # Simple implementation - would use embeddings in production
        query_lower = query.lower()
        similar = []
        
        for example in self.successful_queries:
            example_query = example.get('query', '').lower()
            # Simple keyword overlap
            query_words = set(query_lower.split())
            example_words = set(example_query.split())
            
            if query_words & example_words:
                similar.append(example)
                if len(similar) >= limit:
                    break
        
        return similar

