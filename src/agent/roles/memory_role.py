"""
Memory Role: Learn patterns and optimize execution

Responsible for:
- Learning from query execution patterns
- Caching frequently used queries
- Optimizing execution strategies
- Building user preference profiles
- ML-based pattern recognition and anomaly detection
- Short-term memory (Session/Message nodes in Neo4j)
- Long-term memory (User preferences, Goals, implicit context in Neo4j)
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio
import json

# Import enhanced pattern recognition
from ..capabilities.pattern_recognition import PatternRecognition
from ..memory.memory_constants import (
    SESSION_TTL_HOURS,
    SESSION_MESSAGE_LIMIT,
    SESSION_MESSAGE_MAX_LIMIT,
    USER_PREFERENCE_KEYS,
    GOAL_STATUS_ACTIVE,
    GOAL_STATUS_COMPLETED,
    MEMORY_RETRIEVAL_TIMEOUT_SECONDS,
    MEMORY_FALLBACK_ON_ERROR,
    MEMORY_LOG_ERRORS,
)
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


def _is_connection_error(error: Exception) -> bool:
    """
    Check if an error is a Neo4j connection error (DNS resolution, network issues, etc.)
    
    Args:
        error: Exception to check
        
    Returns:
        True if it's a connection error, False otherwise
    """
    error_str = str(error)
    error_type = type(error).__name__
    
    return (
        "Cannot resolve address" in error_str or
        "nodename nor servname" in error_str.lower() or
        "gaierror" in error_type.lower() or
        "Connection refused" in error_str or
        "ServiceUnavailable" in error_str or
        "Couldn't connect" in error_str or
        "Broken pipe" in error_str.lower() or
        "BrokenPipeError" in error_type or
        "defunct connection" in error_str.lower() or
        "Failed to write" in error_str or
        "Failed to read" in error_str or
        "DNS" in error_str
    )


@dataclass
class QueryPattern:
    """Learned pattern from query execution"""
    query_signature: str  # Generalized query pattern
    intent: str
    domains: List[str]
    execution_count: int = 1
    success_count: int = 0
    total_execution_time_ms: float = 0.0
    last_executed: datetime = field(default_factory=datetime.now)
    cached_results: Optional[Dict[str, Any]] = None
    cache_hit_count: int = 0


class MemoryRole:
    """
    Memory Role: Learns and optimizes from execution patterns
    
    The Memory Role tracks execution patterns and learns from them to:
    - Suggest faster execution strategies
    - Cache frequently used queries
    - Build user preference profiles
    - Predict future queries
    - Optimize resource allocation
    
    This role integrates with the existing MemorySystem but provides
    role-based access patterns.
    """
    
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        db: Optional[Any] = None,
        graph_manager: Optional[Any] = None
    ):
        """
        Initialize MemoryRole
        
        Args:
            config: Optional configuration dictionary
            db: Optional database connection
            graph_manager: Optional Neo4j graph manager for memory storage
        """
        self.config = config or {}
        self.db = db
        self.graph_manager = graph_manager
        
        # Pattern tracking
        self.query_patterns: Dict[str, QueryPattern] = {}
        self.query_cache: Dict[str, Dict[str, Any]] = {}
        self.query_cache_ttl: Dict[str, datetime] = {}
        
        # User preferences (in-memory cache, also stored in Neo4j)
        self.user_preferences: Dict[int, Dict[str, Any]] = {}
        
        # Initialize pattern recognition
        self.pattern_recognition = PatternRecognition(config)
        
        # Statistics
        self.stats = {
            'patterns_learned': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'optimizations_applied': 0,
            'short_term_memory_stored': 0,
            'long_term_memory_stored': 0,
        }
    
    async def learn_from_execution(
        self,
        query: str,
        intent: str,
        domains: List[str],
        execution_time_ms: float,
        success: bool,
        user_id: Optional[int] = None
    ) -> None:
        """
        Learn from a query execution
        
        Args:
            query: The user query
            intent: Classified intent
            domains: Involved domains
            execution_time_ms: Execution time
            success: Whether execution succeeded
            user_id: Optional user ID for personalization
        """
        # Generalize query to signature
        query_sig = self._generalize_query(query)
        
        # Update or create pattern
        if query_sig in self.query_patterns:
            pattern = self.query_patterns[query_sig]
            pattern.execution_count += 1
            pattern.total_execution_time_ms += execution_time_ms
            if success:
                pattern.success_count += 1
            pattern.last_executed = datetime.now()
        else:
            pattern = QueryPattern(
                query_signature=query_sig,
                intent=intent,
                domains=domains,
                execution_count=1,
                success_count=1 if success else 0,
                total_execution_time_ms=execution_time_ms
            )
            self.query_patterns[query_sig] = pattern
            self.stats['patterns_learned'] += 1
        
        # Use pattern recognition capability if available
        if self.pattern_recognition:
            pattern_signature = f"{intent}:{','.join(sorted(domains))}"
            pattern_data = {
                'intent': intent,
                'domains': domains,
                'execution_time_ms': execution_time_ms,
                'success': success,
                'complexity': 0.5  # Can be enhanced with actual complexity score
            }
            await self.pattern_recognition.analyze_pattern(
                pattern_signature=pattern_signature,
                pattern_data=pattern_data,
                user_id=user_id
            )
        
        # Update user preferences
        if user_id:
            self._update_user_preferences(user_id, intent, domains)
    
    async def get_optimization_suggestions(
        self,
        query: str,
        intent: str,
        domains: List[str]
    ) -> Dict[str, Any]:
        """
        Get optimization suggestions based on learned patterns
        
        Args:
            query: Query to optimize
            intent: Query intent
            domains: Query domains
            
        Returns:
            Dictionary with optimization suggestions
        """
        suggestions = {
            'can_use_cache': False,
            'cache_key': None,
            'cached_results': None,
            'estimated_speedup': 0.0,
            'recommended_parallel': False,
            'resource_hints': []
        }
        
        # Check if we've seen similar queries
        query_sig = self._generalize_query(query)
        if query_sig in self.query_patterns:
            pattern = self.query_patterns[query_sig]
            
            # Check cache
            cache_key = self._get_cache_key(query)
            if cache_key in self.query_cache and self._is_cache_valid(cache_key):
                suggestions['can_use_cache'] = True
                suggestions['cache_key'] = cache_key
                suggestions['cached_results'] = self.query_cache[cache_key]
                suggestions['estimated_speedup'] = pattern.total_execution_time_ms / len(self.query_patterns)
                self.stats['cache_hits'] += 1
                pattern.cache_hit_count += 1
                return suggestions
            
            self.stats['cache_misses'] += 1
            
            # Recommend parallelization
            if len(domains) > 1 and pattern.total_execution_time_ms > 100:
                suggestions['recommended_parallel'] = True
            
            # Resource hints
            if 'email' in domains:
                suggestions['resource_hints'].append('Allocate email service quota')
            if 'calendar' in domains:
                suggestions['resource_hints'].append('Allocate calendar API quota')
            if 'tasks' in domains:
                suggestions['resource_hints'].append('Allocate tasks API quota')
        
        return suggestions
    
    async def cache_results(
        self,
        query: str,
        results: Dict[str, Any],
        ttl_seconds: int = 300
    ) -> None:
        """
        Cache query results
        
        Args:
            query: The query
            results: Results to cache
            ttl_seconds: Time to live for cache entry
        """
        cache_key = self._get_cache_key(query)
        self.query_cache[cache_key] = results
        self.query_cache_ttl[cache_key] = datetime.now() + timedelta(seconds=ttl_seconds)
    
    def _generalize_query(self, query: str) -> str:
        """
        Generalize a query to create a signature
        
        This replaces specific values with placeholders to group similar queries
        
        Args:
            query: Original query
            
        Returns:
            Generalized query signature
        """
        normalized = query.lower().strip()
        
        # Replace names and numbers with placeholders
        import re
        
        # Replace email addresses
        normalized = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', normalized)
        
        # Replace dates
        normalized = re.sub(r'\d{1,2}/\d{1,2}/\d{2,4}', '[DATE]', normalized)
        normalized = re.sub(r'\d{1,2}-\d{1,2}-\d{2,4}', '[DATE]', normalized)
        
        # Replace numbers
        normalized = re.sub(r'\d+', '[NUM]', normalized)
        
        # Replace quoted strings
        normalized = re.sub(r'"[^"]*"', '[STRING]', normalized)
        normalized = re.sub(r"'[^']*'", '[STRING]', normalized)
        
        return normalized
    
    def _get_cache_key(self, query: str) -> str:
        """Generate cache key for a query"""
        return f"query_{hash(query.lower())}"
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if a cache entry is still valid"""
        if cache_key not in self.query_cache_ttl:
            return False
        
        expiry = self.query_cache_ttl[cache_key]
        if datetime.now() > expiry:
            # Clear expired entry
            del self.query_cache[cache_key]
            del self.query_cache_ttl[cache_key]
            return False
        
        return True
    
    def _update_user_preferences(
        self,
        user_id: int,
        intent: str,
        domains: List[str]
    ) -> None:
        """Update user preferences based on execution"""
        if user_id not in self.user_preferences:
            self.user_preferences[user_id] = {
                'preferred_domains': defaultdict(int),
                'preferred_intents': defaultdict(int),
                'query_frequency': 0,
                'last_activity': datetime.now()
            }
        
        prefs = self.user_preferences[user_id]
        
        # Track domain preferences
        for domain in domains:
            prefs['preferred_domains'][domain] += 1
        
        # Track intent preferences
        prefs['preferred_intents'][intent] += 1
        
        # Update stats
        prefs['query_frequency'] += 1
        prefs['last_activity'] = datetime.now()
    
    def get_user_preferences(self, user_id: int) -> Dict[str, Any]:
        """Get learned preferences for a user"""
        if user_id not in self.user_preferences:
            return {}
        
        prefs = self.user_preferences[user_id]
        
        # Get top domains
        top_domains = sorted(
            prefs['preferred_domains'].items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # Get top intents
        top_intents = sorted(
            prefs['preferred_intents'].items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        return {
            'top_domains': [d[0] for d in top_domains[:3]],
            'top_intents': [i[0] for i in top_intents[:3]],
            'query_frequency': prefs['query_frequency'],
            'last_activity': prefs['last_activity'].isoformat()
        }
    
    def get_top_patterns(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top learned patterns by execution frequency"""
        patterns_list = sorted(
            self.query_patterns.items(),
            key=lambda x: x[1].execution_count,
            reverse=True
        )
        
        result = []
        for sig, pattern in patterns_list[:limit]:
            result.append({
                'signature': sig,
                'intent': pattern.intent,
                'domains': pattern.domains,
                'execution_count': pattern.execution_count,
                'success_rate': f"{(pattern.success_count / pattern.execution_count) * 100:.0f}%",
                'avg_time_ms': f"{pattern.total_execution_time_ms / pattern.execution_count:.0f}ms",
                'cache_hits': pattern.cache_hit_count
            })
        
        return result
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory role statistics"""
        total_lookups = self.stats['cache_hits'] + self.stats['cache_misses']
        
        if total_lookups > 0:
            cache_hit_rate = (self.stats['cache_hits'] / total_lookups) * 100
        else:
            cache_hit_rate = 0
        
        return {
            'patterns_learned': self.stats['patterns_learned'],
            'cache_hits': self.stats['cache_hits'],
            'cache_misses': self.stats['cache_misses'],
            'cache_hit_rate': f"{cache_hit_rate:.1f}%",
            'total_cached_entries': len(self.query_cache),
            'users_profiled': len(self.user_preferences),
            'optimizations_applied': self.stats['optimizations_applied']
        }
    
    def clear_expired_cache(self) -> int:
        """Clear expired cache entries and return count removed"""
        expired_keys = []
        
        for cache_key in self.query_cache_ttl:
            if not self._is_cache_valid(cache_key):
                expired_keys.append(cache_key)
        
        for key in expired_keys:
            if key in self.query_cache:
                del self.query_cache[key]
            del self.query_cache_ttl[key]
        
        return len(expired_keys)
    
    def reset(self) -> None:
        """Reset all learned patterns and cache"""
        self.query_patterns.clear()
        self.query_cache.clear()
        self.query_cache_ttl.clear()
        self.user_preferences.clear()
    
    # ========================================================================
    # Short-Term Memory (Session Memory) - Neo4j Integration
    # ========================================================================
    
    async def store_session_message(
        self,
        session_id: str,
        user_id: int,
        role: str,
        text: str,
        intent: Optional[str] = None,
        entities: Optional[Dict[str, Any]] = None,
        confidence: Optional[float] = None,
        message_id: Optional[int] = None
    ) -> bool:
        """
        Store a conversation message in Neo4j Session/Message nodes
        
        Creates or updates Session node and creates ConversationMessage node
        linked via CONTAINS_TURN relationship.
        
        Args:
            session_id: Session identifier (e.g., "slack-channel-123")
            user_id: User ID
            role: 'user' or 'assistant'
            text: Message content
            intent: Optional detected intent
            entities: Optional extracted entities
            confidence: Optional confidence score
            message_id: Optional database message ID
            
        Returns:
            True if stored successfully, False otherwise
        """
        if not self.graph_manager:
            if MEMORY_LOG_ERRORS:
                logger.debug("[MEMORY] Graph manager not available, skipping session message storage")
            return False
        
        try:
            from ...services.indexing.graph.schema import NodeType, RelationType
            
            # Ensure Session node exists
            session_node_id = f"session_{session_id}"
            ttl_expiry = datetime.now() + timedelta(hours=SESSION_TTL_HOURS)
            
            session_props = {
                'id': session_id,
                'timestamp': datetime.now().isoformat(),
                'user_id': user_id,
                'ttl_expiry': ttl_expiry.isoformat(),
                'source': self._extract_source_from_session_id(session_id)
            }
            
            # Create or update Session node
            await self.graph_manager.add_node(
                node_id=session_node_id,
                node_type=NodeType.SESSION,
                properties=session_props
            )
            
            # Create ConversationMessage node
            message_node_id = f"msg_{message_id or int(datetime.now().timestamp() * 1000)}"
            message_props = {
                'text': text,
                'role': role,
                'user_id': user_id,
                'timestamp': datetime.now().isoformat(),
            }
            
            if intent:
                message_props['intent'] = intent
            if entities:
                # Convert entities dict to array format for Neo4j
                # Schema expects array, not string
                if isinstance(entities, dict):
                    # Flatten to array of strings: ["key1:value1", "key2:value2"]
                    entities_array = []
                    for key, value in entities.items():
                        if isinstance(value, list):
                            for item in value:
                                entities_array.append(f"{key}:{item}")
                        else:
                            entities_array.append(f"{key}:{value}")
                    message_props['entities'] = entities_array if entities_array else []
            if confidence is not None:
                message_props['confidence'] = float(confidence)
            if message_id:
                message_props['message_id'] = str(message_id)
            
            await self.graph_manager.add_node(
                node_id=message_node_id,
                node_type=NodeType.CONVERSATION_MESSAGE,
                properties=message_props
            )
            
            # Link Session -> Message via CONTAINS_TURN
            await self.graph_manager.add_relationship(
                from_node=session_node_id,
                to_node=message_node_id,
                rel_type=RelationType.CONTAINS_TURN,
                properties={'timestamp': datetime.now().isoformat()}
            )
            
            self.stats['short_term_memory_stored'] += 1
            logger.debug(f"[MEMORY] Stored {role} message in session {session_id}")
            return True
            
        except Exception as e:
            if MEMORY_LOG_ERRORS:
                logger.warning(f"[MEMORY] Failed to store session message: {e}", exc_info=True)
            if not MEMORY_FALLBACK_ON_ERROR:
                raise
            return False
    
    async def get_session_messages(
        self,
        session_id: str,
        user_id: int,
        limit: int = SESSION_MESSAGE_LIMIT
    ) -> List[Dict[str, Any]]:
        """
        Retrieve recent messages from a session (last N turns)
        
        Args:
            session_id: Session identifier
            user_id: User ID
            limit: Maximum number of messages to retrieve
            
        Returns:
            List of message dictionaries with role, text, intent, entities, timestamp
        """
        if not self.graph_manager:
            return []
        
        try:
            from ...services.indexing.graph.schema import NodeType, RelationType
            
            session_node_id = f"session_{session_id}"
            
            # Query Neo4j for messages in this session
            query = f"""
            MATCH (s:{NodeType.SESSION.value} {{id: $session_id}})
            -[r:{RelationType.CONTAINS_TURN.value}]->
            (m:{NodeType.CONVERSATION_MESSAGE.value})
            WHERE s.user_id = $user_id
            RETURN m
            ORDER BY m.timestamp DESC
            LIMIT $limit
            """
            
            def _execute():
                with self.graph_manager.driver.session() as session:
                    result = session.run(
                        query,
                        session_id=session_id,
                        user_id=user_id,
                        limit=limit
                    )
                    messages = []
                    for record in result:
                        node = record['m']
                        props = dict(node)
                        
                        # Parse entities if stored as JSON string
                        entities = props.get('entities')
                        if isinstance(entities, str):
                            try:
                                entities = json.loads(entities)
                            except:
                                entities = {}
                        
                        messages.append({
                            'role': props.get('role', 'user'),
                            'text': props.get('text', ''),
                            'intent': props.get('intent'),
                            'entities': entities or {},
                            'timestamp': props.get('timestamp'),
                            'confidence': props.get('confidence')
                        })
                    return messages
            
            messages = await asyncio.to_thread(_execute)
            
            # Reverse to chronological order (oldest first)
            messages.reverse()
            
            logger.debug(f"[MEMORY] Retrieved {len(messages)} messages from session {session_id}")
            return messages
            
        except Exception as e:
            # Check if it's a connection error (Neo4j unavailable)
            if _is_connection_error(e):
                # Connection errors - log briefly at debug level
                logger.debug(f"[MEMORY] Neo4j unavailable, skipping session messages retrieval for session {session_id[:20]}...")
            elif MEMORY_LOG_ERRORS:
                # Other errors - log with full details
                logger.warning(f"[MEMORY] Failed to retrieve session messages: {e}", exc_info=True)
            
            if not MEMORY_FALLBACK_ON_ERROR:
                raise
            return []
    
    # ========================================================================
    # Long-Term Memory (Personalization) - Neo4j Integration
    # ========================================================================
    
    async def get_user_preferences_from_graph(self, user_id: int) -> Dict[str, Any]:
        """
        Retrieve user preferences from Neo4j User node
        
        Args:
            user_id: User ID
            
        Returns:
            Dictionary of user preferences
        """
        if not self.graph_manager:
            return {}
        
        try:
            from ...services.indexing.graph.schema import NodeType
            
            # Find User node by user_id
            query = """
            MATCH (u:User)
            WHERE u.user_id = $user_id OR u.id = $user_id
            RETURN u.preferences as preferences
            LIMIT 1
            """
            
            def _execute():
                with self.graph_manager.driver.session() as session:
                    result = session.run(query, user_id=str(user_id))
                    record = result.single()
                    if record:
                        prefs = record.get('preferences')
                        if isinstance(prefs, str):
                            try:
                                return json.loads(prefs)
                            except:
                                return {}
                        return prefs or {}
                    return {}
            
            preferences = await asyncio.to_thread(_execute)
            return preferences
            
        except Exception as e:
            # Check if it's a connection error (Neo4j unavailable)
            if _is_connection_error(e):
                # Connection errors - log briefly at debug level
                logger.debug(f"[MEMORY] Neo4j unavailable, skipping user preferences retrieval for user {user_id}")
            elif MEMORY_LOG_ERRORS:
                # Other errors - log with full details
                logger.warning(f"[MEMORY] Failed to retrieve user preferences: {e}", exc_info=True)
            
            if not MEMORY_FALLBACK_ON_ERROR:
                raise
            return {}
    
    async def update_user_preferences_in_graph(
        self,
        user_id: int,
        preferences: Dict[str, Any]
    ) -> bool:
        """
        Update user preferences on Neo4j User node
        
        Args:
            user_id: User ID
            preferences: Dictionary of preferences to update
            
        Returns:
            True if updated successfully, False otherwise
        """
        if not self.graph_manager:
            return False
        
        try:
            from ...services.indexing.graph.schema import NodeType
            
            # Find or create User node
            user_node_id = f"user_{user_id}"
            
            # Get existing preferences
            existing_prefs = await self.get_user_preferences_from_graph(user_id)
            
            # Merge preferences
            merged_prefs = {**existing_prefs, **preferences}
            
            # Update User node
            user_props = {
                'user_id': user_id,
                'preferences': json.dumps(merged_prefs) if merged_prefs else None
            }
            
            await self.graph_manager.add_node(
                node_id=user_node_id,
                node_type=NodeType.USER,
                properties=user_props
            )
            
            self.stats['long_term_memory_stored'] += 1
            logger.debug(f"[MEMORY] Updated preferences for user {user_id}")
            return True
            
        except Exception as e:
            if MEMORY_LOG_ERRORS:
                logger.warning(f"[MEMORY] Failed to update user preferences: {e}", exc_info=True)
            if not MEMORY_FALLBACK_ON_ERROR:
                raise
            return False
    
    async def get_user_goals(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Retrieve user goals from Neo4j
        
        Args:
            user_id: User ID
            
        Returns:
            List of goal dictionaries
        """
        if not self.graph_manager:
            return []
        
        try:
            from ...services.indexing.graph.schema import NodeType, RelationType
            
            query = f"""
            MATCH (u:{NodeType.USER.value} {{user_id: $user_id}})
            -[r:{RelationType.MANAGES.value}]->
            (g:{NodeType.GOAL.value})
            RETURN g
            ORDER BY g.priority DESC, g.created_at DESC
            """
            
            def _execute():
                with self.graph_manager.driver.session() as session:
                    result = session.run(query, user_id=str(user_id))
                    goals = []
                    for record in result:
                        node = record['g']
                        props = dict(node)
                        goals.append({
                            'name': props.get('name', ''),
                            'description': props.get('description', ''),
                            'status': props.get('status', GOAL_STATUS_ACTIVE),
                            'priority': props.get('priority', 'medium'),
                            'due_date': props.get('due_date'),
                            'created_at': props.get('created_at'),
                            'completed_at': props.get('completed_at')
                        })
                    return goals
            
            goals = await asyncio.to_thread(_execute)
            return goals
            
        except Exception as e:
            # Check if it's a connection error (Neo4j unavailable)
            if _is_connection_error(e):
                # Connection errors - log briefly at debug level
                logger.debug(f"[MEMORY] Neo4j unavailable, skipping user goals retrieval for user {user_id}")
            elif MEMORY_LOG_ERRORS:
                # Other errors - log with full details
                logger.warning(f"[MEMORY] Failed to retrieve user goals: {e}", exc_info=True)
            
            if not MEMORY_FALLBACK_ON_ERROR:
                raise
            return []
    
    async def get_user_context(
        self,
        user_id: int,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retrieve comprehensive user context (short-term + long-term memory)
        
        Args:
            user_id: User ID
            session_id: Optional session ID for short-term memory
            
        Returns:
            Dictionary with:
            - recent_messages: List of recent session messages
            - preferences: User preferences
            - goals: User goals
            - projects: User projects (implicit context)
        """
        context = {
            'recent_messages': [],
            'preferences': {},
            'goals': [],
            'projects': []
        }
        
        # Short-term memory
        if session_id:
            context['recent_messages'] = await self.get_session_messages(
                session_id=session_id,
                user_id=user_id,
                limit=SESSION_MESSAGE_LIMIT
            )
        
        # Long-term memory
        context['preferences'] = await self.get_user_preferences_from_graph(user_id)
        context['goals'] = await self.get_user_goals(user_id)
        
        # Implicit context (projects/topics user works on)
        if self.graph_manager:
            try:
                from ...services.indexing.graph.schema import NodeType, RelationType
                
                query = f"""
                MATCH (u:{NodeType.USER.value} {{user_id: $user_id}})
                -[r:{RelationType.WORKS_ON.value}]->
                (p:{NodeType.PROJECT.value})
                RETURN p
                LIMIT 10
                """
                
                def _execute():
                    with self.graph_manager.driver.session() as session:
                        result = session.run(query, user_id=str(user_id))
                        projects = []
                        for record in result:
                            node = record['p']
                            props = dict(node)
                            projects.append({
                                'name': props.get('name', ''),
                                'description': props.get('description', ''),
                                'status': props.get('status', 'active')
                            })
                        return projects
                
                context['projects'] = await asyncio.to_thread(_execute)
            except Exception as e:
                # Check if it's a connection error (Neo4j unavailable)
                if _is_connection_error(e):
                    # Connection errors - log briefly at debug level
                    logger.debug(f"[MEMORY] Neo4j unavailable, skipping projects retrieval for user {user_id}")
                elif MEMORY_LOG_ERRORS:
                    # Other errors - log at debug level (projects are less critical)
                    logger.debug(f"[MEMORY] Failed to retrieve projects: {e}")
        
        return context
    
    def _extract_source_from_session_id(self, session_id: str) -> str:
        """Extract source (slack, web, api) from session ID"""
        if 'slack' in session_id.lower():
            return 'slack'
        elif 'web' in session_id.lower() or 'http' in session_id.lower():
            return 'web'
        else:
            return 'api'
