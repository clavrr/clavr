"""
Base Memory System

Core implementation of the behavioral memory system.
"""
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

from src.utils.logger import setup_logger

# Optional orchestration components (may have been removed)
try:
    from src.orchestration.components.query_extractor import QueryExtractor
    HAS_QUERY_EXTRACTOR = True
except ImportError:
    QueryExtractor = None
    HAS_QUERY_EXTRACTOR = False

try:
    from src.orchestration.domain.tool_domain_config import get_tool_domain_config
    HAS_TOOL_DOMAIN_CONFIG = True
except ImportError:
    get_tool_domain_config = None
    HAS_TOOL_DOMAIN_CONFIG = False

from ..config import memory_constants as const
from ..models.persistence import QueryPattern, ExecutionMemory, MemoryPattern, UserPreference
from ..utils.similarity import calculate_pattern_similarity

logger = setup_logger(__name__)

# Optional intent module integration
try:
    from src.ai.intent import (
        classify_query_intent,
        extract_entities,
        analyze_query_complexity
    )
    HAS_INTENT_PATTERNS = True
except ImportError:
    HAS_INTENT_PATTERNS = False

# Optional database support
try:
    from sqlalchemy.orm import Session
    HAS_DATABASE = True
except ImportError:
    HAS_DATABASE = False

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
    
    def __init__(self, db: Optional[Any] = None, batch_size: int = 10, config: Optional[Any] = None):
        self.db = db
        self.has_database = HAS_DATABASE and db is not None
        self.batch_size = batch_size
        self.config = config
        
        # Initialize QueryExtractor and ToolDomainConfig (optional)
        self.query_extractor = QueryExtractor(config=config) if HAS_QUERY_EXTRACTOR else None
        self.tool_domain_config = get_tool_domain_config() if HAS_TOOL_DOMAIN_CONFIG else None
        
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
        """
        # Extract entities and analyze complexity
        entities = {}
        complexity_info = {}
        
        # Use QueryExtractor for consistent entity extraction (if available)
        if self.query_extractor:
            extracted_terms = self.query_extractor.extract_all_terms(query)
            if extracted_terms:
                entities.update(extracted_terms)
            
        if HAS_INTENT_PATTERNS:
            intent_entities = extract_entities(query)
            if intent_entities:
                entities.update(intent_entities)
            complexity_info = analyze_query_complexity(query)
        
        # Extract pattern from query
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
                entities=entities
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
        
        if complexity_info:
            execution_record['complexity_level'] = complexity_info.get('complexity_level', 'medium')
            execution_record['estimated_steps'] = complexity_info.get('estimated_steps', 1)
            execution_record['domains_detected'] = complexity_info.get('domains_detected', [])
        
        if entities:
            execution_record['entities'] = entities
        
        self.execution_history.append(execution_record)
        
        # Limit history size
        if len(self.execution_history) > 500:
            self.execution_history = self.execution_history[-500:]
        
        # Learn user preferences if user_id provided
        if user_id and success:
            self._learn_user_preference(user_id, pattern, intent, tools_used)
        
        # Track pending updates
        self._pending_pattern_updates.append((pattern, memory_pattern, user_id))
        self._pending_executions.append((query, tools_used, success, execution_time, user_id))
        
        # Commit batch if threshold reached
        if len(self._pending_pattern_updates) >= self.batch_size:
            self._commit_pending_changes()
        
        # Clear caches
        self._clear_caches()
    
    def get_similar_patterns(self, 
                           query: str, 
                           intent: str,
                           user_id: Optional[int] = None) -> List[MemoryPattern]:
        """Get similar successful patterns for query optimization"""
        cache_key = f"{query}:{intent}:{user_id}"
        
        if cache_key in self._pattern_cache:
            return self._pattern_cache[cache_key]
        
        current_pattern = self._extract_pattern(query, intent)
        similar_patterns = []
        
        for pattern_key, pattern in self.query_patterns.items():
            if pattern.confidence >= 0.6 and pattern.success_count > 0:
                similarity = calculate_pattern_similarity(current_pattern, pattern_key)
                if similarity > const.SIMILARITY_THRESHOLD_LOW:
                    similar_patterns.append(pattern)
        
        similar_patterns.sort(key=lambda p: (p.confidence, p.success_count), reverse=True)
        result = similar_patterns[:5]
        
        if len(self._pattern_cache) >= self._cache_max_size:
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
        """Get tool recommendations based on learned patterns"""
        # Get intent confidence
        intent_confidence = "medium"
        if HAS_INTENT_PATTERNS:
            intent_data = classify_query_intent(query)
            intent_confidence = intent_data.get("confidence", "medium")
        
        cache_key = f"{query}:{intent}:{user_id}"
        
        if cache_key in self._tool_cache:
            return self._tool_cache[cache_key]
        
        similar_patterns = self.get_similar_patterns(query, intent, user_id)
        
        tool_scores = {}
        for pattern in similar_patterns:
            confidence_threshold = 0.3 if intent_confidence == "high" else 0.2
            if pattern.confidence < confidence_threshold:
                continue
            
            weight = pattern.confidence * (pattern.success_count / max(1, pattern.failure_count + pattern.success_count))
            if pattern.tools_used:
                for tool in pattern.tools_used:
                    tool_scores[tool] = tool_scores.get(tool, 0) + weight
        
        recommended_tools = sorted(tool_scores.items(), key=lambda x: x[1], reverse=True)
        result = [tool for tool, score in recommended_tools[:5]]
        
        if len(self._tool_cache) >= self._cache_max_size:
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
        
        patterns_to_remove = []
        for pattern_key, pattern in self.query_patterns.items():
            if (pattern.last_used and pattern.last_used < cutoff_date and pattern.confidence < 0.3):
                patterns_to_remove.append(pattern_key)
        
        for pattern_key in patterns_to_remove:
            del self.query_patterns[pattern_key]
        
        self.execution_history = [
            e for e in self.execution_history 
            if (datetime.now() - e['timestamp']).days < max_age_days
        ]
        
        logger.info(f"Cleared {len(patterns_to_remove)} old patterns")
    
    def _extract_pattern(self, query: str, intent: str, entities: Optional[Dict] = None) -> str:
        """Extract abstract pattern from query and intent with entity awareness"""
        query_lower = query.lower().strip()
        
        # Use QueryExtractor logic implicitly via entities if available
        if entities:
            # Normalize specific time references
            for time_ref in entities.get('time_references', []):
                if time_ref.lower() in query_lower:
                    query_lower = query_lower.replace(time_ref.lower(), '<TIME>')
            
            # Extract action verbs for pattern
            actions = entities.get('action_keywords', [])
            if len(actions) >= 2:
                return f"{intent}_multi_action_{len(actions)}"
        
        # Fallback to simple normalization if no entities
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
    
    def _learn_user_preference(self, 
                              user_id: int, 
                              pattern: str, 
                              intent: str, 
                              tools_used: List[str]):
        """Learn user preferences from successful executions"""
        if user_id not in self.user_preferences:
            self.user_preferences[user_id] = []
        
        user_prefs = self.user_preferences[user_id]
        
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
        
        cutoff_date = datetime.now() - timedelta(days=60)
        self.user_preferences[user_id] = [
            p for p in user_prefs if (p.last_used and p.last_used > cutoff_date) or p.frequency > 5
        ]
    
    def _load_from_database(self):
        """Load patterns from database if available"""
        if not self.has_database:
            return
        
        try:
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
        except Exception as e:
            logger.warning(f"Failed to persist execution: {e}")
            self.db.rollback()
    
    def _commit_pending_changes(self):
        """Commit pending changes to the database"""
        if not self._pending_pattern_updates and not self._pending_executions:
            return
        
        if self.has_database:
            try:
                for pattern_key, pattern, user_id in self._pending_pattern_updates:
                    self._persist_pattern_to_database(pattern_key, pattern, user_id)
                
                for query, tools_used, success, execution_time, user_id in self._pending_executions:
                    self._persist_execution_to_database(query, tools_used, success, execution_time, user_id)
                
                self.db.commit()
                logger.debug(f"Batch committed {len(self._pending_pattern_updates)} patterns and {len(self._pending_executions)} executions")
            except Exception as e:
                logger.warning(f"Failed to commit pending changes: {e}")
                if self.has_database:
                    self.db.rollback()
        
        self._pending_pattern_updates.clear()
        self._pending_executions.clear()
    
    def _clear_caches(self):
        """Clear caches when patterns are updated"""
        self._pattern_cache.clear()
        self._tool_cache.clear()
