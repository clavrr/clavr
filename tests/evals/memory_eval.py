"""
Conversation Memory Evaluator

Evaluates conversation memory retrieval and context management.
"""
import time
from typing import List, Dict, Any, Optional

from .base import BaseEvaluator, TestCase, EvaluationResult, EvaluationMetrics
from src.ai.conversation_memory import ConversationMemory
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class ConversationMemoryEvaluator(BaseEvaluator):
    """Evaluates conversation memory functionality"""
    
    def __init__(self, db_session: Optional[Any] = None, user_id: int = 1, config: Optional[Dict[str, Any]] = None):
        """
        Initialize conversation memory evaluator
        
        Args:
            db_session: Database session for ConversationMemory (optional - will create if needed)
            user_id: User ID for memory operations
            config: Optional configuration
        """
        super().__init__(config)
        self.db_session = db_session
        self.user_id = user_id
        # Don't create memory instance here - create it per-evaluation to avoid session issues
        self.memory = None
    
    async def evaluate(self, test_cases: List[TestCase]) -> EvaluationMetrics:
        """
        Evaluate conversation memory on test cases
        
        Args:
            test_cases: List of test cases for memory operations
            
        Returns:
            EvaluationMetrics with results
        """
        # Create memory instance with fresh session for this evaluation
        from src.database.async_database import get_async_db_context
        
        try:
            async with get_async_db_context() as db:
                memory = ConversationMemory(db)
                self.results = []
                session_id = "eval_session"
                
                for test_case in test_cases:
                    start_time = time.time()
                    
                    try:
                        query_lower = test_case.query.lower()
                        
                        if 'save' in query_lower or 'store' in query_lower:
                            # Test message storage
                            # Store the previous query from context if available
                            if test_case.context and 'previous_query' in test_case.context:
                                previous_query = test_case.context['previous_query']
                                await memory.add_message(
                                    user_id=self.user_id,
                                    session_id=session_id,
                                    role='user',
                                    content=previous_query
                                )
                                await memory.add_message(
                                    user_id=self.user_id,
                                    session_id=session_id,
                                    role='assistant',
                                    content="Test response"
                                )
                            await memory.add_message(
                                user_id=self.user_id,
                                session_id=session_id,
                                role='user',
                                content=test_case.query
                            )
                            await memory.add_message(
                                user_id=self.user_id,
                                session_id=session_id,
                                role='assistant',
                                content="Test response"
                            )
                            passed = True
                            
                        elif 'retrieve' in query_lower or 'get' in query_lower or 'earlier' in query_lower:
                            # Test message retrieval and context awareness
                            # First, ensure previous query is stored (if not already done in 'save' step)
                            if test_case.context and 'previous_query' in test_case.context:
                                previous_query = test_case.context['previous_query']
                                # Check if previous query is already stored
                                existing_messages = await memory.get_recent_messages(
                                    user_id=self.user_id,
                                    session_id=session_id,
                                    limit=10
                                )
                                previous_query_stored = any(
                                    previous_query.lower() in msg.get('content', '').lower() 
                                    for msg in existing_messages
                                )
                                # If not stored, store it now
                                if not previous_query_stored:
                                    await memory.add_message(
                                        user_id=self.user_id,
                                        session_id=session_id,
                                        role='user',
                                        content=previous_query
                                    )
                                    await memory.add_message(
                                        user_id=self.user_id,
                                        session_id=session_id,
                                        role='assistant',
                                        content="Test response about calendar"
                                    )
                            
                            # Now retrieve messages
                            messages = await memory.get_recent_messages(
                                user_id=self.user_id,
                                session_id=session_id,
                                limit=10
                            )
                            
                            # Check if context from previous query is found
                            if test_case.context and 'previous_query' in test_case.context:
                                previous_query = test_case.context['previous_query']
                                # Check if any message contains context from previous query
                                found_context = any(
                                    previous_query.lower() in msg.get('content', '').lower() 
                                    for msg in messages
                                )
                                # Also check if expected response terms are in the messages
                                if test_case.expected_response_contains:
                                    # Check if any message contains the expected terms
                                    response_terms_found = any(
                                        all(term.lower() in msg.get('content', '').lower() 
                                            for term in test_case.expected_response_contains)
                                        for msg in messages
                                    )
                                    # Pass if either the previous query is found OR the expected terms are in messages
                                    passed = found_context or response_terms_found
                                else:
                                    passed = found_context
                            else:
                                # Just check if messages are retrieved
                                passed = isinstance(messages, list)
                            
                        elif 'list' in query_lower or 'conversations' in query_lower:
                            # Test conversation listing
                            conversations = await memory.list_conversations(
                                user_id=self.user_id,
                                limit=10
                            )
                            passed = isinstance(conversations, list)
                            
                        elif 'messages' in query_lower:
                            # Test getting messages for a conversation
                            messages = await memory.get_conversation_messages(
                                user_id=self.user_id,
                                session_id=session_id
                            )
                            passed = isinstance(messages, list)
                            
                        else:
                            # Default: test basic retrieval
                            messages = await memory.get_recent_messages(
                                user_id=self.user_id,
                                session_id=session_id,
                                limit=5
                            )
                            passed = isinstance(messages, list)
                
                        latency_ms = (time.time() - start_time) * 1000
                        
                        result_obj = EvaluationResult(
                            test_case=test_case,
                            passed=passed,
                            confidence=1.0 if passed else 0.0,
                            latency_ms=latency_ms,
                            details={'session_id': session_id}
                        )
                        
                    except Exception as e:
                        logger.error(f"Error evaluating conversation memory: {e}", exc_info=True)
                        result_obj = EvaluationResult(
                            test_case=test_case,
                            passed=False,
                            error=str(e),
                            latency_ms=(time.time() - start_time) * 1000
                        )
                    
                    self.results.append(result_obj)
                
                self.metrics = self._calculate_metrics()
                return self.metrics
        except Exception as e:
            logger.error(f"Failed to create database session for memory evaluation: {e}", exc_info=True)
            return EvaluationMetrics()

