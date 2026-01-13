"""
Behavior Learner Service

Analyzes the graph to find sequential patterns in user behavior.
Example: "User often creates an Asana task after receiving an email from 'Client X'"

This service runs in the background and creates PATTERN nodes in the graph.
"""
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
import asyncio

from ...utils.logger import setup_logger
from ...utils.config import Config
from ...services.indexing.graph.manager import KnowledgeGraphManager
from ...services.indexing.graph.schema import NodeType, RelationType

from .autonomy_config import (
    LEARNING_INITIAL_DELAY_SECONDS,
    LEARNING_INTERVAL_SECONDS,
    PATTERN_WINDOW_SECONDS,
    MIN_PATTERN_SUPPORT,
    PATTERN_LOOKBACK_DAYS,
    MAX_CONCURRENT_MINING_USERS,
)

logger = setup_logger(__name__)

class BehaviorLearner:
    """
    Service for learning user behavioral patterns.
    
    Responsibilities:
    1. Scan for repeated sequences of actions (A -> B)
    2. Create PATTERN nodes for high-confidence sequences
    3. Use patterns to predict next actions
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        self.is_running = False
        self._task = None
        
    async def start(self):
        """Start the background learning loop."""
        if self.is_running:
            return
            
        self.is_running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("[BehaviorLearner] Service started")
        
    async def stop(self):
        """Stop the background learning loop."""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[BehaviorLearner] Service stopped")
        
    async def _run_loop(self):
        """Main loop for mining patterns."""
        # Initial delay to let graph population start
        await asyncio.sleep(LEARNING_INITIAL_DELAY_SECONDS)
        
        while self.is_running:
            try:
                await self._run_mining_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[BehaviorLearner] Mining cycle failed: {e}")
                
            # Run at configured interval
            await asyncio.sleep(LEARNING_INTERVAL_SECONDS)

    async def _run_mining_cycle(self):
        """Run pattern mining for all active users with concurrency limits."""
        # Deferred imports to avoid circular dependencies if any
        from ...database.models import User
        from ...database import get_async_db_context
        from sqlalchemy import select
        
        async with get_async_db_context() as db:
            result = await db.execute(select(User))
            users = result.scalars().all()
            
            # Apply concurrency limits
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_MINING_USERS)
            
            async def process_user(user):
                async with semaphore:
                    try:
                        await self.find_sequential_patterns(user.id)
                    except Exception as e:
                        logger.warning(f"[BehaviorLearner] Failed pattern mining for user {user.id}: {e}")
            
            await asyncio.gather(*[process_user(u) for u in users])

    async def find_sequential_patterns(self, user_id: int):
        """
        Find sequential patterns A -> B using efficient TimeBlock traversal.
        """
        # 1. Get recent TimeBlocks (Strict UTC)
        # We look back N days from NOW (UTC)
        lookback_date = (datetime.now(timezone.utc) - timedelta(days=PATTERN_LOOKBACK_DAYS)).isoformat()
        
        query = """
        FOR tb IN TimeBlock
            FILTER tb.user_id == @user_id 
              AND tb.granularity == 'day'
              AND tb.start_time >= @lookback_date
            RETURN { id: tb.id }
        """
        
        try:
            results = await self.graph.execute_query(query, {"user_id": user_id, "lookback_date": lookback_date})
            if not results:
                return []
                
            # 2. Analyze events in each block
            sequences = {} # (TypeA, TypeB) -> count
            
            for res in results:
                block_id = res.get('id')
                block_sequences = await self._analyze_block_sequences(block_id)
                
                # Aggregate counts
                for seq, count in block_sequences.items():
                    sequences[seq] = sequences.get(seq, 0) + count
                    
            # 3. Filter for high-confidence patterns
            valid_patterns = []
            for (type_a, type_b), count in sequences.items():
                if count >= MIN_PATTERN_SUPPORT:
                    # Calculate simple confidence
                    confidence = min(0.5 + (count * 0.1), 0.95)
                    
                    pattern = await self._create_pattern(
                        user_id,
                        name=f"{type_a} -> {type_b}",
                        trigger=type_a,
                        action=type_b,
                        confidence=confidence,
                        pattern_type="sequential",
                        observation_count=count
                    )
                    if pattern:
                        valid_patterns.append(pattern)
                        
            return valid_patterns
            
        except Exception as e:
            logger.error(f"[BehaviorLearner] Pattern mining failed: {e}")
            return []
            
    async def _analyze_block_sequences(self, timeblock_id: str) -> Dict[Tuple[str, str], int]:
        """Find sequences within a single TimeBlock."""
        # Native AQL traversal to get events in time order
        query = """
        FOR tb IN TimeBlock
            FILTER tb.id == @id
            FOR e IN INBOUND tb OCCURRED_DURING
                SORT e.timestamp ASC
                RETURN {
                    type: e.node_type,
                    time: e.timestamp,
                    source: e.source
                }
        """
        
        sequences = {}
        try:
            results = await self.graph.execute_query(query, {"id": timeblock_id})
            if not results or len(results) < 2:
                return {}
                
            # Scan for pairs
            for i in range(len(results) - 1):
                a = results[i]
                b = results[i+1]
                
                # Parse times (Robust)
                try:
                    # Handling ISO strings with or without Z
                    t_a_str = str(a.get('time', '')).replace('Z', '+00:00')
                    t_b_str = str(b.get('time', '')).replace('Z', '+00:00')
                    
                    time_a = datetime.fromisoformat(t_a_str)
                    time_b = datetime.fromisoformat(t_b_str)
                    
                    # Ensure awareness for comparison
                    if time_a.tzinfo is None: time_a = time_a.replace(tzinfo=timezone.utc)
                    if time_b.tzinfo is None: time_b = time_b.replace(tzinfo=timezone.utc)
                    
                    # Check if close in time
                    delta = time_b - time_a
                    if delta.total_seconds() < PATTERN_WINDOW_SECONDS:
                        type_a = a.get('type')
                        type_b = b.get('type')
                        
                        # Filter out same-type noise unless different sources
                        # e.g. Email (Gmail) -> Email (Gmail) is usually just inbox churn
                        if type_a != type_b:
                            key = (type_a, type_b)
                            sequences[key] = sequences.get(key, 0) + 1
                            
                except ValueError:
                    continue
                    
        except Exception:
            pass
            
        return sequences

    async def _create_pattern(
        self, 
        user_id: int, 
        name: str, 
        trigger: str, 
        action: str, 
        confidence: float,
        pattern_type: str,
        observation_count: int
    ) -> Optional[Dict[str, Any]]:
        """Create a PATTERN node."""
        
        # Schema-compliant properties for GRAPH_PATTERN
        properties = {
            "description": f"Pattern: {name}", # Required: description
            "pattern_type": pattern_type,      # Required: pattern_type (e.g. 'sequential')
            "confidence": confidence,          # Required: confidence
            "trigger": trigger,
            "action": action,
            "frequency": float(observation_count), # Required: frequency (float)
            "observation_count": observation_count, # Required: observation_count (int)
            "user_id": user_id,
            "source": "behavior_learner",
            "last_observed": datetime.now(timezone.utc).isoformat()
        }
        
        try:
            # Upsert logic logic would be better here (e.g. update count if exists), 
            # but for MVP we create. Assuming graph manager handles IDs or we blindly create.
            # Ideally we check existence first.
            
            # Use GRAPH_PATTERN node type
            await self.graph.create_node(NodeType.GRAPH_PATTERN, properties)
            logger.info(f"[BehaviorLearner] Learned pattern: {name} (Count: {observation_count})")
            return properties
        except Exception as e:
            logger.error(f"[BehaviorLearner] Failed to create pattern node: {e}")
            return None
