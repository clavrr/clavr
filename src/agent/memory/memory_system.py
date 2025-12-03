"""
Memory System for Agent Learning

Memory architecture that integrates with the cleaned ClavrAgent:
- Query pattern learning and success tracking
- User preference learning with confidence scor        # Learn user preferences if user_id provided
        if user_id and success:
            self._learn_user_preference(user_id, pattern, intent, tools_used)
        
        # Persist to database if available (with batching)
        if self.has_database:
            self._pending_pattern_updates.append((pattern, memory_pattern, user_id))
            self._pending_executions.append((query, tools_used, success, execution_time, user_id))
            if len(self._pending_pattern_updates) >= self.batch_size:
                self._commit_pending_changes()
        
        # Clear caches after pattern update
        self._clear_caches()Simple execution pattern memory
- Integration with ClavrAgent orchestrator and intent patterns
- Clean, maintainable architecture

Features:
- Basic in-memory storage with optional database persistence
- Query success/failure tracking for orchestrator improvement
- User intent pattern learning
- Integration with intent patterns system
- Simple, functional design
- LRU caching for performance optimization
- Batch database commits
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from functools import lru_cache

from ...utils.logger import setup_logger

logger = setup_logger(__name__)

# Optional intent module integration
try:
    from ..intent import (
        classify_query_intent,
        extract_entities,
        analyze_query_complexity
    )
    HAS_INTENT_PATTERNS = True
    logger.info("intent module integration enabled for memory system")
except ImportError:
    HAS_INTENT_PATTERNS = False
    logger.warning("intent_patterns not available - using fallback intent detection")

# Optional database support
try:
    from sqlalchemy import Column, String, Integer, Float, DateTime, Text, Boolean
    from sqlalchemy.orm import Session
    from ...database.models import Base
    HAS_DATABASE = True
    
    class QueryPattern(Base):
        """Simple query pattern storage"""
        __tablename__ = 'query_patterns'
        
        id = Column(Integer, primary_key=True)
        user_id = Column(Integer, nullable=True)
        pattern = Column(String(500), nullable=False)
        intent = Column(String(100), nullable=False)
        success_count = Column(Integer, default=0)
        failure_count = Column(Integer, default=0)
        confidence = Column(Float, default=0.5)
        last_used = Column(DateTime, default=datetime.now)
        created_at = Column(DateTime, default=datetime.now)
        
    class ExecutionMemory(Base):
        """Simple execution memory storage"""
        __tablename__ = 'execution_memory'
        
        id = Column(Integer, primary_key=True)
        user_id = Column(Integer, nullable=True)
        query = Column(Text, nullable=False)
        tools_used = Column(Text, nullable=False)  # JSON string
        success = Column(Boolean, nullable=False)
        execution_time = Column(Float, default=0.0)
        step_count = Column(Integer, default=1)
        created_at = Column(DateTime, default=datetime.now)

except ImportError:
    HAS_DATABASE = False
    logger.info("PostgreSQL database not available for memory patterns - using in-memory storage (Neo4j and Pinecone still available)")
    QueryPattern = None  # type: ignore
    ExecutionMemory = None  # type: ignore


@dataclass
class MemoryPattern:
    """Simple memory pattern for learning with entity and complexity awareness"""
    pattern: str
    intent: str
    success_count: int = 0
    failure_count: int = 0
    confidence: float = 0.5
    last_used: Optional[datetime] = None
    tools_used: Optional[List[str]] = None
    # New fields for Phase 2 integration
    complexity_level: Optional[str] = None  # low, medium, high
    estimated_steps: Optional[int] = None
    domains_detected: Optional[List[str]] = None
    entities: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.last_used is None:
            self.last_used = datetime.now()
        if self.tools_used is None:
            self.tools_used = []
        if self.domains_detected is None:
            self.domains_detected = []
        if self.entities is None:
            self.entities = {}


@dataclass
class UserPreference:
    """User preference pattern"""
    user_id: int
    preference_type: str
    pattern: str
    frequency: int = 1
    confidence: float = 0.5
    last_used: Optional[datetime] = None
    
    def __post_init__(self):
        if self.last_used is None:
            self.last_used = datetime.now()


class SimplifiedMemorySystem:
    """
    Simplified memory system for ClavrAgent learning
    
    Provides basic memory capabilities:
    - Query pattern learning
    - User preference tracking  
    - Execution success/failure memory
    - Integration with orchestrator
    - LRU caching for performance
    - Batch database commits
    """
    
    def __init__(self, db: Optional[Session] = None, batch_size: int = 10):
        self.db = db
        self.has_database = HAS_DATABASE and db is not None
        self.batch_size = batch_size
        
        # In-memory storage (always available)
        self.query_patterns: Dict[str, MemoryPattern] = {}
        self.user_preferences: Dict[int, List[UserPreference]] = {}
        self.execution_history: List[Dict[str, Any]] = []
        
        # Batch commit tracking
        self._pending_pattern_updates: List[Tuple[str, MemoryPattern, Optional[int]]] = []
        self._pending_executions: List[Tuple] = []
        
        # Simple LRU cache for expensive operations (max 100 entries each)
        self._pattern_cache: Dict[str, List[MemoryPattern]] = {}
        self._tool_cache: Dict[str, List[str]] = {}
        self._cache_max_size = 100
        
        # Load from database if available
        if self.has_database:
            self._load_from_database()
            
        logger.info(f"Simplified memory system initialized (database: {self.has_database}, batch_size: {batch_size})")
    
    def learn_query_pattern(self, 
                           query: str, 
                           intent: str,
                           tools_used: List[str],
                           success: bool,
                           execution_time: float = 0.0,
                           user_id: Optional[int] = None):
        """
        Learn from query execution for future improvement
        
        Args:
            query: Original query
            intent: Detected intent
            tools_used: List of tools used in execution
            success: Whether execution was successful
            execution_time: Time taken for execution
            user_id: Optional user ID for personalization
        """
        # Extract entities and analyze complexity if intent_patterns available
        entities = {}
        complexity_info = {}
        if HAS_INTENT_PATTERNS:
            entities = extract_entities(query)
            complexity_info = analyze_query_complexity(query)
            logger.debug(f"Entities extracted: {len(entities.get('entities', []))} items, "
                        f"Complexity: {complexity_info.get('complexity_level', 'unknown')}")
        
        # Extract pattern from query (enhanced with entity awareness)
        pattern = self._extract_pattern(query, intent, entities)
        
        # Update in-memory pattern
        if pattern not in self.query_patterns:
            self.query_patterns[pattern] = MemoryPattern(
                pattern=pattern,
                intent=intent,
                tools_used=tools_used.copy(),
                complexity_level=complexity_info.get('complexity_level') if complexity_info else None,
                estimated_steps=complexity_info.get('estimated_steps') if complexity_info else None,
                domains_detected=complexity_info.get('domains_detected', []) if complexity_info else [],
                entities=entities if entities else {}
            )
        
        memory_pattern = self.query_patterns[pattern]
        
        if success:
            memory_pattern.success_count += 1
            memory_pattern.confidence = min(1.0, memory_pattern.confidence + 0.1)
        else:
            memory_pattern.failure_count += 1
            memory_pattern.confidence = max(0.1, memory_pattern.confidence - 0.05)
        
        memory_pattern.last_used = datetime.now()
        if memory_pattern.tools_used is None:
            memory_pattern.tools_used = []
        memory_pattern.tools_used = list(set(memory_pattern.tools_used + tools_used))
        
        # Store execution history
        execution_record = {
            'query': query,
            'pattern': pattern,
            'intent': intent,
            'tools_used': tools_used,
            'success': success,
            'execution_time': execution_time,
            'user_id': user_id,
            'timestamp': datetime.now()
        }
        
        # Add complexity metadata if available
        if complexity_info:
            execution_record['complexity_level'] = complexity_info.get('complexity_level', 'medium')
            execution_record['estimated_steps'] = complexity_info.get('estimated_steps', 1)
            execution_record['domains_detected'] = complexity_info.get('domains_detected', [])
        
        # Add extracted entities if available
        if entities:
            execution_record['entities'] = entities
        
        self.execution_history.append(execution_record)
        
        # Limit history size - keep last 500 when exceeding 500
        if len(self.execution_history) > 500:
            self.execution_history = self.execution_history[-500:]
        
        # Learn user preferences if user_id provided
        if user_id and success:
            self._learn_user_preference(user_id, pattern, intent, tools_used)
        
        # Track pending updates for batch commit (regardless of database availability)
        self._pending_pattern_updates.append((pattern, memory_pattern, user_id))
        self._pending_executions.append((query, tools_used, success, execution_time, user_id))
        
        # Commit batch if threshold reached and database is available
        if len(self._pending_pattern_updates) >= self.batch_size:
            self._commit_pending_changes()
        
        # Clear caches after pattern update
        self._clear_caches()
    
    def get_similar_patterns(self, 
                           query: str, 
                           intent: str,
                           user_id: Optional[int] = None) -> List[MemoryPattern]:
        """
        Get similar successful patterns for query optimization
        
        Args:
            query: Current query
            intent: Detected intent
            user_id: Optional user ID for personalization
            
        Returns:
            List of relevant memory patterns
        """
        # Create cache key
        cache_key = f"{query}:{intent}:{user_id}"
        
        # Check cache first
        if cache_key in self._pattern_cache:
            return self._pattern_cache[cache_key]
        
        current_pattern = self._extract_pattern(query, intent)
        similar_patterns = []
        
        # Find patterns with good success rates
        for pattern_key, pattern in self.query_patterns.items():
            if pattern.confidence >= 0.6 and pattern.success_count > 0:
                similarity = self._calculate_pattern_similarity(current_pattern, pattern_key)
                if similarity > 0.3:  # Similarity threshold
                    similar_patterns.append(pattern)
        
        # Sort by confidence and success rate
        similar_patterns.sort(key=lambda p: (p.confidence, p.success_count), reverse=True)
        result = similar_patterns[:5]  # Return top 5
        
        # Cache the result (with size limit)
        if len(self._pattern_cache) >= self._cache_max_size:
            # Remove oldest entry
            self._pattern_cache.pop(next(iter(self._pattern_cache)))
        self._pattern_cache[cache_key] = result
        
        return result
    
    def get_user_preferences(self, user_id: int) -> List[UserPreference]:
        """Get user preferences for personalization"""
        return self.user_preferences.get(user_id, [])
    
    def get_tool_recommendations(self, 
                                query: str, 
                                intent: str,
                                user_id: Optional[int] = None) -> List[str]:
        """
        Get tool recommendations based on learned patterns
        
        Args:
            query: Current query
            intent: Detected intent
            user_id: Optional user ID for personalization
            
        Returns:
            List of recommended tools
        """
        # Get intent confidence if intent_patterns available
        intent_confidence = "medium"
        if HAS_INTENT_PATTERNS:
            intent_data = classify_query_intent(query)
            intent_confidence = intent_data.get("confidence", "medium")
            logger.debug(f"Intent confidence for recommendations: {intent_confidence}")
        
        # Create cache key
        cache_key = f"{query}:{intent}:{user_id}"
        
        # Check cache first
        if cache_key in self._tool_cache:
            return self._tool_cache[cache_key]
        
        similar_patterns = self.get_similar_patterns(query, intent, user_id)
        
        tool_scores = {}
        for pattern in similar_patterns:
            # Apply confidence-based filtering
            # Higher intent confidence = stricter pattern matching
            confidence_threshold = 0.3 if intent_confidence == "high" else 0.2
            if pattern.confidence < confidence_threshold:
                continue  # Skip low-confidence patterns for high-confidence intents
            
            weight = pattern.confidence * (pattern.success_count / max(1, pattern.failure_count + pattern.success_count))
            if pattern.tools_used:  # Check if tools_used is not None
                for tool in pattern.tools_used:
                    tool_scores[tool] = tool_scores.get(tool, 0) + weight
        
        # Sort tools by score
        recommended_tools = sorted(tool_scores.items(), key=lambda x: x[1], reverse=True)
        result = [tool for tool, score in recommended_tools[:5]]  # Top 5 tools
        
        # Cache the result (with size limit)
        if len(self._tool_cache) >= self._cache_max_size:
            # Remove oldest entry
            self._tool_cache.pop(next(iter(self._tool_cache)))
        self._tool_cache[cache_key] = result
        
        return result
    
    def get_execution_stats(self) -> Dict[str, Any]:
        """Get memory system statistics"""
        total_patterns = len(self.query_patterns)
        successful_patterns = sum(1 for p in self.query_patterns.values() if p.confidence > 0.5)
        
        recent_executions = [e for e in self.execution_history 
                           if (datetime.now() - e['timestamp']).days < 7]
        
        recent_success_rate = 0.0
        if recent_executions:
            recent_success_rate = sum(1 for e in recent_executions if e['success']) / len(recent_executions)
        
        return {
            'total_patterns': total_patterns,
            'successful_patterns': successful_patterns,
            'total_executions': len(self.execution_history),
            'recent_executions': len(recent_executions),
            'recent_success_rate': recent_success_rate,
            'user_count': len(self.user_preferences),
            'database_enabled': self.has_database
        }
    
    def clear_old_patterns(self, max_age_days: int = 30):
        """Clear old patterns to maintain performance"""
        cutoff_date = datetime.now() - timedelta(days=max_age_days)
        
        # Remove old in-memory patterns
        patterns_to_remove = []
        for pattern_key, pattern in self.query_patterns.items():
            if (pattern.last_used and pattern.last_used < cutoff_date and pattern.confidence < 0.3):
                patterns_to_remove.append(pattern_key)
        
        for pattern_key in patterns_to_remove:
            del self.query_patterns[pattern_key]
        
        # Remove old execution history
        self.execution_history = [
            e for e in self.execution_history 
            if (datetime.now() - e['timestamp']).days < max_age_days
        ]
        
        logger.info(f"Cleared {len(patterns_to_remove)} old patterns")
    
    def _extract_pattern(self, query: str, intent: str, entities: Optional[Dict] = None) -> str:
        """Extract abstract pattern from query and intent with entity awareness"""
        query_lower = query.lower().strip()
        
        # If entities available, use them for better pattern extraction
        if entities and HAS_INTENT_PATTERNS:
            # Normalize specific time references
            for time_ref in entities.get('time_references', []):
                if time_ref.lower() in query_lower:
                    query_lower = query_lower.replace(time_ref.lower(), '<TIME>')
            
            # Normalize specific priorities
            for priority in entities.get('priorities', []):
                if priority.lower() in query_lower:
                    query_lower = query_lower.replace(priority.lower(), '<PRIORITY>')
            
            # Extract action verbs for pattern
            actions = entities.get('actions', [])
            if len(actions) >= 2:
                return f"{intent}_multi_action_{len(actions)}"
        
        # Normalize query patterns (existing logic)
        if 'find' in query_lower and 'create' in query_lower:
            return f"{intent}_find_and_create"
        elif 'search' in query_lower and 'schedule' in query_lower:
            return f"{intent}_search_and_schedule"
        elif 'show' in query_lower and 'send' in query_lower:
            return f"{intent}_show_and_send"
        elif 'action item' in query_lower:
            return f"{intent}_action_items"
        elif len(query_lower.split(' and ')) > 1:
            return f"{intent}_multi_step"
        else:
            return f"{intent}_single_step"
    
    def _calculate_pattern_similarity(self, pattern1: str, pattern2: str) -> float:
        """Calculate similarity between patterns"""
        # Simple word-based similarity
        words1 = set(pattern1.lower().split('_'))
        words2 = set(pattern2.lower().split('_'))
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0
    
    def _learn_user_preference(self, 
                              user_id: int, 
                              pattern: str, 
                              intent: str, 
                              tools_used: List[str]):
        """Learn user preferences from successful executions"""
        if user_id not in self.user_preferences:
            self.user_preferences[user_id] = []
        
        user_prefs = self.user_preferences[user_id]
        
        # Find existing preference or create new one
        existing_pref = None
        for pref in user_prefs:
            if pref.pattern == pattern and pref.preference_type == intent:
                existing_pref = pref
                break
        
        if existing_pref:
            existing_pref.frequency += 1
            existing_pref.confidence = min(1.0, existing_pref.confidence + 0.05)
            existing_pref.last_used = datetime.now()
        else:
            new_pref = UserPreference(
                user_id=user_id,
                preference_type=intent,
                pattern=pattern,
                frequency=1,
                confidence=0.6
            )
            user_prefs.append(new_pref)
        
        # Keep only recent preferences
        cutoff_date = datetime.now() - timedelta(days=60)
        self.user_preferences[user_id] = [
            p for p in user_prefs if (p.last_used and p.last_used > cutoff_date) or p.frequency > 5
        ]
    
    def _load_from_database(self):
        """Load patterns from database if available"""
        if not self.has_database:
            return
        
        try:
            # Load query patterns
            patterns = self.db.query(QueryPattern).limit(1000).all()
            for pattern in patterns:
                memory_pattern = MemoryPattern(
                    pattern=pattern.pattern,
                    intent=pattern.intent,
                    success_count=pattern.success_count,
                    failure_count=pattern.failure_count,
                    confidence=pattern.confidence,
                    last_used=pattern.last_used
                )
                self.query_patterns[pattern.pattern] = memory_pattern
            
            logger.info(f"Loaded {len(patterns)} patterns from database")
            
        except Exception as e:
            logger.warning(f"Failed to load from database: {e}")
    
    def _persist_pattern_to_database(self, 
                                   pattern_key: str, 
                                   pattern: MemoryPattern,
                                   user_id: Optional[int]):
        """Persist pattern to database (without committing)"""
        if not self.has_database:
            return
        
        try:
            # Check if pattern exists
            existing = self.db.query(QueryPattern).filter(
                QueryPattern.pattern == pattern_key,
                QueryPattern.user_id == user_id
            ).first()
            
            if existing:
                existing.success_count = pattern.success_count
                existing.failure_count = pattern.failure_count
                existing.confidence = pattern.confidence
                existing.last_used = pattern.last_used
            else:
                new_pattern = QueryPattern(
                    user_id=user_id,
                    pattern=pattern_key,
                    intent=pattern.intent,
                    success_count=pattern.success_count,
                    failure_count=pattern.failure_count,
                    confidence=pattern.confidence,
                    last_used=pattern.last_used
                )
                self.db.add(new_pattern)
            # Note: No commit here - will be done in batch
        except Exception as e:
            logger.warning(f"Failed to persist pattern: {e}")
            self.db.rollback()
    
    def _persist_execution_to_database(self,
                                     query: str,
                                     tools_used: List[str],
                                     success: bool,
                                     execution_time: float,
                                     user_id: Optional[int]):
        """Persist execution to database (without committing)"""
        if not self.has_database:
            return
        
        try:
            execution = ExecutionMemory(
                user_id=user_id,
                query=query,
                tools_used=json.dumps(tools_used),
                success=success,
                execution_time=execution_time,
                step_count=len(tools_used)
            )
            self.db.add(execution)
            # Note: No commit here - will be done in batch
        except Exception as e:
            logger.warning(f"Failed to persist execution: {e}")
            self.db.rollback()
    
    def _commit_pending_changes(self):
        """Commit pending changes to the database"""
        # Return early if there are no pending changes
        if not self._pending_pattern_updates and not self._pending_executions:
            return
        
        # If we have a database, persist the changes
        if self.has_database:
            try:
                # Batch add all pending pattern updates
                for pattern_key, pattern, user_id in self._pending_pattern_updates:
                    self._persist_pattern_to_database(pattern_key, pattern, user_id)
                
                # Batch add all pending executions
                for query, tools_used, success, execution_time, user_id in self._pending_executions:
                    self._persist_execution_to_database(query, tools_used, success, execution_time, user_id)
                
                # Single commit for all changes
                self.db.commit()
                
                logger.debug(f"Batch committed {len(self._pending_pattern_updates)} patterns and {len(self._pending_executions)} executions")
            except Exception as e:
                logger.warning(f"Failed to commit pending changes: {e}")
                if self.has_database:
                    self.db.rollback()
        
        # Always clear pending lists after batch processing (regardless of database availability)
        # This prevents memory buildup and allows batch tracking to work without a database
        self._pending_pattern_updates.clear()
        self._pending_executions.clear()
    
    def _clear_caches(self):
        """Clear caches when patterns are updated"""
        # Clear manual caches
        self._pattern_cache.clear()
        self._tool_cache.clear()
        
        # Also clear any @lru_cache decorated methods (for backwards compatibility)
        if hasattr(self.get_similar_patterns, 'cache_clear'):
            self.get_similar_patterns.cache_clear()
        if hasattr(self.get_tool_recommendations, 'cache_clear'):
            self.get_tool_recommendations.cache_clear()


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
        
        Args:
            query: Original query
            execution_result: Result from orchestrator execution
            user_id: Optional user ID
        """
        # Extract learning data from orchestrator result
        success = execution_result.get('success', False)
        tools_used = execution_result.get('tools_used', [])
        execution_time_str = execution_result.get('execution_time', '0.0s')
        
        # Parse execution time
        try:
            execution_time = float(execution_time_str.replace('s', ''))
        except:
            execution_time = 0.0
        
        # Determine intent based on execution type
        execution_type = execution_result.get('execution_type', 'standard')
        if execution_type == 'orchestrated':
            intent = 'multi_step'
        else:
            intent = 'single_step'
        
        # Learn from this execution
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
        
        Args:
            query: Current query
            user_id: Optional user ID
            
        Returns:
            Recommendations for orchestrator
        """
        # Determine likely intent
        intent = 'multi_step' if self._looks_like_multi_step(query) else 'single_step'
        
        # Get similar patterns
        similar_patterns = self.memory_system.get_similar_patterns(query, intent, user_id)
        
        # Get tool recommendations
        recommended_tools = self.memory_system.get_tool_recommendations(query, intent, user_id)
        
        # Get user preferences if available
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
            return 0.5  # Default confidence
        
        # Average confidence weighted by success rate
        total_confidence = 0.0
        total_weight = 0.0
        
        for pattern in patterns:
            weight = pattern.success_count / max(1, pattern.success_count + pattern.failure_count)
            total_confidence += pattern.confidence * weight
            total_weight += weight
        
        return total_confidence / total_weight if total_weight > 0 else 0.5


# Factory function for easy integration
def create_memory_system(db: Optional[Session] = None, batch_size: int = 10) -> SimplifiedMemorySystem:
    """
    Factory function to create memory system
    
    Args:
        db: Optional database session
        batch_size: Number of updates to batch before committing (default: 10)
        
    Returns:
        SimplifiedMemorySystem instance
    """
    return SimplifiedMemorySystem(db, batch_size)


def create_memory_integrator(memory_system: SimplifiedMemorySystem) -> MemoryIntegrator:
    """
    Factory function to create memory integrator
    
    Args:
        memory_system: Memory system instance
        
    Returns:
        MemoryIntegrator instance
    """
    return MemoryIntegrator(memory_system)


# Hybrid memory system with semantic and conversational layers

# Optional imports for hybrid capabilities
try:
    from ...ai.rag import RAGEngine
    from ...database.models import ConversationMessage
    # Try to get RAGEngine from AppState for vector store access
    try:
        from api.dependencies import AppState
        HAS_HYBRID_SUPPORT = True
    except ImportError:
        HAS_HYBRID_SUPPORT = False
        logger.debug("Hybrid memory extensions: AppState not available (RAG engine can be passed directly)")
except ImportError:
    HAS_HYBRID_SUPPORT = False
    logger.debug("Hybrid memory extensions: RAG or conversation models not available (Pinecone/Neo4j still work independently)")


@dataclass
class UnifiedContext:
    """
    Unified context from all three memory layers
    
    Combines:
    - Behavioral memory (patterns, tools, preferences)
    - Semantic memory (Pinecone documents)
    - Conversational memory (PostgreSQL chat history)
    """
    # Behavioral layer (from SimplifiedMemorySystem)
    recommended_tools: List[str] = field(default_factory=list)
    similar_patterns: List[MemoryPattern] = field(default_factory=list)
    user_preferences: List[UserPreference] = field(default_factory=list)
    
    # Semantic layer (from Pinecone)
    relevant_documents: List[Dict[str, Any]] = field(default_factory=list)
    semantic_summary: str = ""
    
    # Conversational layer (from PostgreSQL)
    recent_messages: List[Dict[str, Any]] = field(default_factory=list)
    conversation_summary: str = ""
    mentioned_entities: List[str] = field(default_factory=list)
    
    # Metadata
    confidence: float = 0.5
    retrieval_time_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "recommended_tools": self.recommended_tools,
            "similar_patterns": [
                {"pattern": p.pattern, "intent": p.intent, "confidence": p.confidence}
                for p in self.similar_patterns
            ],
            "user_preferences": [
                {"pattern": p.pattern, "frequency": p.frequency}
                for p in self.user_preferences
            ],
            "relevant_documents": self.relevant_documents,
            "semantic_summary": self.semantic_summary,
            "recent_messages": self.recent_messages,
            "conversation_summary": self.conversation_summary,
            "mentioned_entities": self.mentioned_entities,
            "confidence": self.confidence,
            "retrieval_time_ms": self.retrieval_time_ms
        }


class HybridMemorySystem(SimplifiedMemorySystem):
    """
    Extended memory system with semantic and conversational capabilities
    
    Inherits all behavioral memory from SimplifiedMemorySystem and adds:
    - Semantic search via Pinecone (optional)
    - Conversation history from PostgreSQL (optional)
    - Unified context combining all three layers
    
    Example:
        >>> hybrid = HybridMemorySystem(db, vector_collection="emails")
        >>> context = hybrid.get_unified_context("Find budget emails", user_id=123)
        >>> print(context.recommended_tools)  # ['email', 'search']
        >>> print(context.semantic_summary)   # Email summaries from Pinecone
        >>> print(context.conversation_summary)  # Recent chat topics
    """
    
    def __init__(
        self,
        db: Optional[Session] = None,
        batch_size: int = 10,
        vector_collection: str = "emails",
        enable_semantic: bool = True,
        rag_engine: Optional[Any] = None
    ):
        """
        Initialize hybrid memory system
        
        Args:
            db: Database session (required for conversational memory)
            batch_size: Batch size for database commits
            vector_collection: Pinecone collection name
            enable_semantic: Whether to enable Pinecone semantic search
            rag_engine: Optional RAGEngine instance (if not provided, will try AppState)
        """
        # Initialize base behavioral memory
        super().__init__(db, batch_size)
        
        # Initialize semantic memory (Pinecone) - optional
        self.has_semantic = False
        self.rag_engine: Optional[RAGEngine] = None
        
        # Use provided RAGEngine or try to get from AppState
        if enable_semantic:
            if rag_engine:
                # Use provided RAGEngine directly
                self.rag_engine = rag_engine
                self.has_semantic = True
                logger.info(f"Semantic memory enabled via provided RAGEngine (collection={vector_collection})")
            elif HAS_HYBRID_SUPPORT:
                try:
                    # Try to get RAGEngine from AppState (only works in FastAPI context)
                    from api.dependencies import AppState
                    self.rag_engine = AppState.get_rag_engine()
                    self.has_semantic = True
                    logger.info(f"Semantic memory enabled via AppState RAGEngine (collection={vector_collection})")
                except Exception as e:
                    logger.debug(f"Semantic memory via AppState unavailable (this is normal outside FastAPI context): {e}")
            else:
                logger.debug(f"Semantic memory disabled (RAGEngine not provided and AppState not available)")
        
        logger.info(f"Hybrid memory initialized (semantic={self.has_semantic}, conversational={self.has_database}, behavioral=True)")
    
    def get_unified_context(
        self,
        query: str,
        user_id: int,
        session_id: Optional[str] = None,
        top_k: int = 5
    ) -> UnifiedContext:
        """
        Get unified context from all three memory layers
        
        Args:
            query: User's query
            user_id: User ID for personalization and data isolation
            session_id: Optional conversation session ID
            top_k: Number of results from each layer
            
        Returns:
            UnifiedContext with data from all available layers
        """
        start_time = datetime.now()
        
        # Detect intent for pattern matching (use intent_patterns if available)
        if HAS_INTENT_PATTERNS:
            intent_data = classify_query_intent(query)
            intent = intent_data.get("domain", "general")
            logger.debug(f"Intent classified: {intent} (confidence: {intent_data.get('confidence', 'unknown')})")
        else:
            intent = self._detect_simple_intent(query)
        
        # Layer 1: Behavioral memory (always available)
        recommended_tools = self.get_tool_recommendations(query, intent, user_id)
        similar_patterns = self.get_similar_patterns(query, intent, user_id)
        user_prefs = self.get_user_preferences(user_id)
        
        # Layer 2: Semantic memory (Pinecone) - if available
        relevant_docs = []
        semantic_summary = ""
        if self.has_semantic:
            relevant_docs = self._query_semantic_memory(query, user_id, top_k)
            semantic_summary = self._summarize_documents(relevant_docs)
        
        # Layer 3: Conversational memory (PostgreSQL) - if available
        messages = []
        conv_summary = ""
        entities = []
        if self.has_database and HAS_HYBRID_SUPPORT:
            messages = self._query_conversational_memory(user_id, session_id, top_k)
            conv_summary = self._summarize_conversation(messages)
            entities = self._extract_entities(messages)
        
        # Calculate unified confidence
        confidence = self._calculate_unified_confidence(
            num_patterns=len(similar_patterns),
            num_docs=len(relevant_docs),
            num_messages=len(messages)
        )
        
        retrieval_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        logger.debug(
            f"Unified context: {len(similar_patterns)} patterns, "
            f"{len(relevant_docs)} docs, {len(messages)} messages ({retrieval_ms:.2f}ms)"
        )
        
        return UnifiedContext(
            recommended_tools=recommended_tools,
            similar_patterns=similar_patterns,
            user_preferences=user_prefs,
            relevant_documents=relevant_docs,
            semantic_summary=semantic_summary,
            recent_messages=messages,
            conversation_summary=conv_summary,
            mentioned_entities=entities,
            confidence=confidence,
            retrieval_time_ms=retrieval_ms
        )
    
    def learn_from_interaction(
        self,
        query: str,
        response: str,
        user_id: int,
        session_id: str,
        tools_used: List[str],
        success: bool,
        intent: Optional[str] = None,
        entities: Optional[Dict] = None,
        execution_time: float = 0.0
    ):
        """
        Learn from interaction across all memory layers
        
        Args:
            query: User's query
            response: Agent's response
            user_id: User ID
            session_id: Conversation session ID
            tools_used: Tools used in execution
            success: Whether execution was successful
            intent: Optional intent (auto-detected if None)
            entities: Optional extracted entities
            execution_time: Execution time in seconds
        """
        # Auto-detect intent if not provided (use intent_patterns if available)
        if not intent:
            if HAS_INTENT_PATTERNS:
                intent_data = classify_query_intent(query)
                intent = intent_data.get("domain", "general")
                logger.debug(f"Intent auto-detected: {intent} (confidence: {intent_data.get('confidence', 'unknown')})")
            else:
                intent = self._detect_simple_intent(query)
        
        # Layer 1: Behavioral learning (always happens)
        self.learn_query_pattern(
            query=query,
            intent=intent,
            tools_used=tools_used,
            success=success,
            execution_time=execution_time,
            user_id=user_id
        )
        
        # Layer 2: Conversational learning (if database available)
        if self.has_database and HAS_HYBRID_SUPPORT:
            try:
                self._save_conversation(
                    user_id=user_id,
                    session_id=session_id,
                    user_message=query,
                    assistant_message=response,
                    intent=intent,
                    entities=entities
                )
            except Exception as e:
                logger.error(f"Conversational learning failed: {e}")
        
        # Layer 3: Semantic learning (index important responses in Pinecone)
        if self.has_semantic and self._should_index_response(response):
            try:
                self._index_response(user_id, query, response)
            except Exception as e:
                logger.error(f"Semantic indexing failed: {e}")
        
        logger.debug(f"Learned from interaction: intent={intent}, success={success}")
    
    def _detect_simple_intent(self, query: str) -> str:
        """Simple intent detection from query"""
        q = query.lower()
        if any(w in q for w in ["email", "mail", "inbox"]): return "email"
        if any(w in q for w in ["task", "todo", "action"]): return "tasks"
        if any(w in q for w in ["calendar", "meeting", "schedule"]): return "calendar"
        if " and " in q or " then " in q: return "multi_step"
        return "general"
    
    def _query_semantic_memory(self, query: str, user_id: int, k: int) -> List[Dict]:
        """Query RAGEngine for relevant documents"""
        try:
            if not self.rag_engine:
                return []
            
            # Use RAGEngine.search() with user_id filter
            results = self.rag_engine.search(
                query=query,
                k=k,
                filters={"user_id": user_id} if user_id else None
            )
            
            # Format results to match expected structure
            return [
                {
                    "content": result.get("content") or result.get("text", ""),
                    "metadata": result.get("metadata", {}),
                    "score": result.get("score") or result.get("confidence", 0.0)
                }
                for result in results
            ]
        except Exception as e:
            logger.error(f"Semantic query failed: {e}")
            return []
    
    def _query_conversational_memory(
        self,
        user_id: int,
        session_id: Optional[str],
        k: int
    ) -> List[Dict]:
        """Query PostgreSQL for conversation history"""
        try:
            query = self.db.query(ConversationMessage).filter_by(user_id=user_id)
            if session_id:
                query = query.filter_by(session_id=session_id)
            
            messages = query.order_by(
                ConversationMessage.timestamp.desc()
            ).limit(k).all()
            
            return [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "intent": msg.intent,
                    "entities": msg.entities or {}
                }
                for msg in reversed(messages)
            ]
        except Exception as e:
            logger.error(f"Conversational query failed: {e}")
            return []
    
    def _save_conversation(
        self,
        user_id: int,
        session_id: str,
        user_message: str,
        assistant_message: str,
        intent: Optional[str],
        entities: Optional[Dict]
    ):
        """Save conversation to PostgreSQL"""
        self.db.add(ConversationMessage(
            user_id=user_id,
            session_id=session_id,
            role="user",
            content=user_message,
            intent=intent,
            entities=entities
        ))
        self.db.add(ConversationMessage(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content=assistant_message,
            intent=intent,
            entities=entities
        ))
        self.db.commit()
    
    def _should_index_response(self, response: str) -> bool:
        """Determine if response should be indexed in Pinecone"""
        return len(response) > 200 and any(
            kw in response.lower()
            for kw in ["summary", "found", "created", "scheduled", "analysis"]
        )
    
    def _index_response(self, user_id: int, query: str, response: str):
        """Index response in RAGEngine for future retrieval"""
        if not self.rag_engine:
            return
        
        try:
            # Use RAGEngine.index_document() instead of vector_store.add_documents()
            doc_id = f"conversation_{user_id}_{datetime.now().timestamp()}"
            self.rag_engine.index_document(
                doc_id=doc_id,
                content=f"Q: {query}\nA: {response}",
                metadata={
                    "user_id": user_id,
                    "type": "conversation",
                    "timestamp": datetime.now().isoformat()
                }
            )
        except Exception as e:
            logger.warning(f"Failed to index response: {e}")
    
    def _summarize_documents(self, docs: List[Dict]) -> str:
        """Summarize top documents"""
        if not docs:
            return ""
        summaries = []
        for doc in docs[:3]:
            metadata = doc.get("metadata", {})
            if metadata.get("type") == "email":
                sender = metadata.get("from", "Unknown")
                subject = metadata.get("subject", "No subject")
                summaries.append(f"- {sender}: {subject}")
            else:
                title = metadata.get("title", "Document")
                summaries.append(f"- {title}")
        return "\n".join(summaries)
    
    def _summarize_conversation(self, messages: List[Dict]) -> str:
        """Summarize conversation"""
        if not messages:
            return ""
        intents = [str(m.get("intent")) for m in messages if m.get("intent")]
        if intents:
            unique = list(set(intents))[:3]
            return f"Recently: {', '.join(unique)}"
        return f"{len(messages)} messages"
    
    def _extract_entities(self, messages: List[Dict]) -> List[str]:
        """Extract entities from messages"""
        entities = set()
        for msg in messages:
            if msg.get("entities"):
                for values in msg["entities"].values():
                    if isinstance(values, list):
                        entities.update(values)
                    else:
                        entities.add(str(values))
        return list(entities)[:10]
    
    def _calculate_unified_confidence(
        self,
        num_patterns: int,
        num_docs: int,
        num_messages: int
    ) -> float:
        """Calculate unified confidence based on available data"""
        scores = []
        if num_patterns > 0: scores.append(0.4)   # Has behavioral data
        if num_docs > 0: scores.append(0.3)       # Has semantic data  
        if num_messages > 0: scores.append(0.3)   # Has conversational data
        return sum(scores) if scores else 0.5


def create_hybrid_memory(
    db: Optional[Session] = None,
    batch_size: int = 10,
    vector_collection: str = "emails",
    enable_semantic: bool = True,
    rag_engine: Optional[Any] = None
) -> HybridMemorySystem:
    """
    Create hybrid memory system with all three layers
    
    Args:
        db: Database session (required for conversational memory)
        batch_size: Batch size for database commits
        vector_collection: Pinecone collection name
        enable_semantic: Whether to enable Pinecone semantic search
    
    Returns:
        HybridMemorySystem instance with:
        - Behavioral memory (always enabled)
        - Conversational memory (if db provided)
        - Semantic memory (if Pinecone available and enabled)
    
    Example:
        >>> from src.database.database import get_db
        >>> db = next(get_db())
        >>> hybrid = create_hybrid_memory(db, vector_collection="emails")
        >>> 
        >>> # Get unified context
        >>> context = hybrid.get_unified_context("Find budget emails", user_id=123)
        >>> print(context.recommended_tools)  # ['email', 'search']
        >>> 
        >>> # Learn from interaction
        >>> hybrid.learn_from_interaction(
        ...     query="Find budget emails",
        ...     response="Found 5 emails",
        ...     user_id=123,
        ...     session_id="abc",
        ...     tools_used=["email"],
        ...     success=True
        ... )
    """
    return HybridMemorySystem(db, batch_size, vector_collection, enable_semantic, rag_engine=rag_engine)
