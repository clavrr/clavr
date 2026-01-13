"""
Memory Integrator

Integrates memory system with ClavrAgent orchestrator.
"""
from typing import Dict, Any, Optional, List

from src.utils.logger import setup_logger
from ..core.base_memory import SimplifiedMemorySystem
from ..models.persistence import MemoryPattern

class MemoryIntegrator:
    """
    Integrates memory system with ClavrAgent orchestrator
    """
    
    def __init__(self, memory_system: SimplifiedMemorySystem):
        self.memory_system = memory_system
        self.logger = setup_logger(self.__class__.__name__)
    
    def learn_from_orchestrator_execution(self,
                                        query: str,
                                        execution_result: Dict[str, Any],
                                        user_id: Optional[int] = None):
        """
        Learn from ClavrAgent orchestrator execution
        """
        # Extract learning data
        success = execution_result.get('success', False)
        tools_used = execution_result.get('tools_used', [])
        execution_time_str = execution_result.get('execution_time', '0.0s')
        
        try:
            execution_time = float(execution_time_str.replace('s', ''))
        except:
            execution_time = 0.0
        
        execution_type = execution_result.get('execution_type', 'standard')
        intent = 'multi_step' if execution_type == 'orchestrated' else 'single_step'
        
        self.memory_system.learn_query_pattern(
            query=query,
            intent=intent,
            tools_used=tools_used,
            success=success,
            execution_time=execution_time,
            user_id=user_id
        )
        
        self.logger.debug(f"Learned from execution: query='{query[:50]}...', success={success}")
    
    def get_orchestrator_recommendations(self,
                                       query: str,
                                       user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get recommendations for orchestrator based on memory
        """
        intent = 'multi_step' if self._looks_like_multi_step(query) else 'single_step'
        
        similar_patterns = self.memory_system.get_similar_patterns(query, intent, user_id)
        recommended_tools = self.memory_system.get_tool_recommendations(query, intent, user_id)
        
        user_preferences = []
        if user_id:
            user_preferences = self.memory_system.get_user_preferences(user_id)
        
        return {
            'intent': intent,
            'similar_patterns': similar_patterns,
            'recommended_tools': recommended_tools,
            'user_preferences': user_preferences,
            'confidence': self._calculate_recommendation_confidence(similar_patterns)
        }
    
    def _looks_like_multi_step(self, query: str) -> bool:
        """Simple heuristic to determine if query looks multi-step"""
        query_lower = query.lower()
        multi_step_indicators = [
            ' and ', ' then ', ' after ', ' also ', ' plus ',
            'find and', 'search and', 'get and', 'create and'
        ]
        return any(indicator in query_lower for indicator in multi_step_indicators)
    
    def _calculate_recommendation_confidence(self, patterns: List[MemoryPattern]) -> float:
        """Calculate confidence in recommendations based on patterns"""
        if not patterns:
            return 0.5
        
        total_confidence = 0.0
        total_weight = 0.0
        
        for pattern in patterns:
            weight = pattern.success_count / max(1, pattern.success_count + pattern.failure_count)
            total_confidence += pattern.confidence * weight
            total_weight += weight
        
        return total_confidence / total_weight if total_weight > 0 else 0.5
