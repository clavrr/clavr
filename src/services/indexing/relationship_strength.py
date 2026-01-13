"""
Relationship Strength Manager

Manages the strength and decay of relationships in the Knowledge Graph.
Relationships that are frequently reinforced stay strong, while
stale relationships decay over time.

This enables:
- Prioritizing recent/frequent connections in queries
- Natural forgetting of outdated information
- Relationship quality scoring

Key Concepts:
- Strength: 0.0 to 1.0 score based on interaction frequency
- Decay: Strength reduces over time without interaction
- Reinforcement: Interactions boost relationship strength

Version: 1.0.0
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import asyncio
import math

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import RelationType
from src.services.indexing.graph.schema_constants import (
    DEFAULT_RELATIONSHIP_STRENGTH,
    MAX_RELATIONSHIP_STRENGTH,
    MIN_RELATIONSHIP_STRENGTH,
    STRENGTH_INCREMENT_BASE,
    DEFAULT_DECAY_RATE,
    DECAY_GRACE_PERIOD_DAYS,
)

logger = setup_logger(__name__)


class RelationshipStrengthManager:
    """
    Manages relationship strength scoring and decay.
    
    Strength Calculation:
    - New relationships start at DEFAULT_RELATIONSHIP_STRENGTH (0.5)
    - Each interaction increases strength logarithmically
    - Strength decays daily after DECAY_GRACE_PERIOD_DAYS without interaction
    
    Decay Formula:
    strength_new = strength * (1 - decay_rate) ^ days_since_last_interaction
    """
    
    def __init__(
        self, 
        config: Config, 
        graph_manager: KnowledgeGraphManager,
        decay_rate: float = DEFAULT_DECAY_RATE
    ):
        self.config = config
        self.graph = graph_manager
        self.decay_rate = decay_rate
        self.is_running = False
        self._stop_event = asyncio.Event()
        
    async def start_decay_job(self, interval_hours: int = 24):
        """
        Start background job that runs decay on all relationships periodically.
        
        Args:
            interval_hours: How often to run decay (default: once per day)
        """
        if self.is_running:
            return
            
        self.is_running = True
        self._stop_event.clear()
        
        logger.info(f"[RelationshipStrength] Decay job started (interval: {interval_hours}h)")
        asyncio.create_task(self._decay_loop(interval_hours))
        
    async def stop_decay_job(self):
        """Stop the background decay job."""
        self.is_running = False
        self._stop_event.set()
        logger.info("[RelationshipStrength] Decay job stopped")
        
    async def _decay_loop(self, interval_hours: int):
        """Main decay loop."""
        interval_seconds = interval_hours * 3600
        
        while self.is_running:
            try:
                stats = await self.apply_decay_all()
                logger.info(f"[RelationshipStrength] Decay cycle complete: {stats}")
                
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), 
                        timeout=interval_seconds
                    )
                except asyncio.TimeoutError:
                    pass
                    
            except Exception as e:
                logger.error(f"[RelationshipStrength] Decay loop error: {e}", exc_info=True)
                await asyncio.sleep(3600)  # Retry in 1 hour on error

    async def reinforce_relationship(
        self,
        from_id: str,
        to_id: str,
        rel_type: RelationType,
        interaction_weight: float = 1.0
    ) -> Dict[str, Any]:
        """
        Reinforce a relationship when an interaction occurs.
        
        This should be called whenever:
        - An email is sent/received between two people
        - A meeting occurs with attendees
        - Someone is mentioned in a document
        - A task is assigned or completed
        
        Args:
            from_id: Source node ID
            to_id: Target node ID
            rel_type: Relationship type
            interaction_weight: Weight of this interaction (default 1.0)
            
        Returns:
            Updated relationship properties
        """
        now = datetime.utcnow()
        
        # Get current relationship properties - AQL version
        query = """
        FOR a IN UNION(
            (FOR n IN Email FILTER n.id == @from_id RETURN n),
            (FOR n IN Person FILTER n.id == @from_id RETURN n),
            (FOR n IN ActionItem FILTER n.id == @from_id RETURN n),
            (FOR n IN CalendarEvent FILTER n.id == @from_id RETURN n)
        )
            FOR b IN UNION(
                (FOR n IN Email FILTER n.id == @to_id RETURN n),
                (FOR n IN Person FILTER n.id == @to_id RETURN n),
                (FOR n IN ActionItem FILTER n.id == @to_id RETURN n),
                (FOR n IN CalendarEvent FILTER n.id == @to_id RETURN n)
            )
                FOR r IN @@rel_collection
                    FILTER r._from == a._id AND r._to == b._id
                    LIMIT 1
                    RETURN {
                        strength: r.strength,
                        interaction_count: r.interaction_count,
                        last_interaction: r.last_interaction,
                        first_seen: r.first_seen
                    }
        """
        
        try:
            # Extract raw string value if it's an Enum
            rel_collection_name = rel_type.value if hasattr(rel_type, 'value') else rel_type
            
            result = await self.graph.execute_query(query, {
                "from_id": from_id,
                "to_id": to_id,
                "@rel_collection": rel_collection_name
            })
            
            if result and len(result) > 0:
                current = result[0]
                current_strength = current.get("strength") or DEFAULT_RELATIONSHIP_STRENGTH
                interaction_count = (current.get("interaction_count") or 0) + 1
                first_seen = current.get("first_seen") or now.isoformat()
            else:
                # New relationship - create with tracking properties
                current_strength = DEFAULT_RELATIONSHIP_STRENGTH
                interaction_count = 1
                first_seen = now.isoformat()
            
            # Calculate new strength using logarithmic growth
            # This prevents strength from growing too fast with many interactions
            # Formula: strength + (base_increment / log(interaction_count + 1))
            strength_increment = STRENGTH_INCREMENT_BASE * interaction_weight / math.log(interaction_count + 1 + math.e)
            new_strength = min(MAX_RELATIONSHIP_STRENGTH, current_strength + strength_increment)
            
            # Update the relationship - AQL version
            update_query = """
            FOR a IN UNION(
                (FOR n IN Email FILTER n.id == @from_id RETURN n),
                (FOR n IN Person FILTER n.id == @from_id RETURN n),
                (FOR n IN ActionItem FILTER n.id == @from_id RETURN n),
                (FOR n IN CalendarEvent FILTER n.id == @from_id RETURN n)
            )
                FOR b IN UNION(
                    (FOR n IN Email FILTER n.id == @to_id RETURN n),
                    (FOR n IN Person FILTER n.id == @to_id RETURN n),
                    (FOR n IN ActionItem FILTER n.id == @to_id RETURN n),
                    (FOR n IN CalendarEvent FILTER n.id == @to_id RETURN n)
                )
                    FOR r IN @@rel_collection
                        FILTER r._from == a._id AND r._to == b._id
                        UPDATE r WITH {
                            strength: @strength,
                            interaction_count: @interaction_count,
                            last_interaction: @last_interaction,
                            first_seen: @first_seen
                        } IN @@rel_collection
                        RETURN { strength: NEW.strength }
            """
            
            # Extract raw string value if it's an Enum
            rel_collection_name = rel_type.value if hasattr(rel_type, 'value') else rel_type
            
            await self.graph.execute_query(update_query, {
                "from_id": from_id,
                "to_id": to_id,
                "@rel_collection": rel_collection_name,
                "strength": new_strength,
                "interaction_count": interaction_count,
                "last_interaction": now.isoformat(),
                "first_seen": first_seen
            })
            
            logger.debug(
                f"[RelationshipStrength] Reinforced {from_id} -[{rel_collection_name}]-> {to_id}: "
                f"{current_strength:.3f} -> {new_strength:.3f}"
            )
            
            return {
                "strength": new_strength,
                "interaction_count": interaction_count,
                "last_interaction": now.isoformat(),
                "strength_change": new_strength - current_strength
            }
            
        except Exception as e:
            logger.error(f"[RelationshipStrength] Failed to reinforce relationship: {e}")
            return {"error": str(e)}

    async def apply_decay_all(self) -> Dict[str, int]:
        """
        Apply decay to all relationships that haven't been interacted with recently.
        
        Returns:
            Stats on relationships processed, decayed, and pruned
        """
        stats = {"processed": 0, "decayed": 0, "pruned": 0}
        
        now = datetime.utcnow()
        grace_threshold = (now - timedelta(days=DECAY_GRACE_PERIOD_DAYS)).isoformat()
        
        # Get all relationships with strength tracking - AQL approach
        # Note: This queries common edge collections. Adjust as needed for your schema.
        query = """
        FOR r IN UNION(
            (FOR e IN SENT FILTER e.strength != null AND e.last_interaction != null AND e.last_interaction < @grace_threshold RETURN e),
            (FOR e IN RECEIVED FILTER e.strength != null AND e.last_interaction != null AND e.last_interaction < @grace_threshold RETURN e),
            (FOR e IN MENTIONS FILTER e.strength != null AND e.last_interaction != null AND e.last_interaction < @grace_threshold RETURN e),
            (FOR e IN RELATED_TO FILTER e.strength != null AND e.last_interaction != null AND e.last_interaction < @grace_threshold RETURN e),
            (FOR e IN ATTENDED_BY FILTER e.strength != null AND e.last_interaction != null AND e.last_interaction < @grace_threshold RETURN e)
        )
            LET from_doc = DOCUMENT(r._from)
            LET to_doc = DOCUMENT(r._to)
            LIMIT 1000
            RETURN {
                from_id: from_doc.id,
                to_id: to_doc.id,
                rel_type: PARSE_IDENTIFIER(r._id).collection,
                strength: r.strength,
                last_interaction: r.last_interaction
            }
        """
        
        try:
            results = await self.graph.execute_query(query, {
                "grace_threshold": grace_threshold
            })
            
            if not results:
                return stats
            
            for rel in results:
                stats["processed"] += 1
                
                # Calculate days since last interaction
                last_interaction = rel.get("last_interaction")
                if not last_interaction:
                    continue

                try:
                    if isinstance(last_interaction, str):
                        # Handle Z and other ISO formats
                        dt_str = last_interaction.replace('Z', '+00:00')
                        last_dt = datetime.fromisoformat(dt_str)
                    elif isinstance(last_interaction, datetime):
                        last_dt = last_interaction
                    else:
                        logger.warning(f"Unexpected type for last_interaction: {type(last_interaction)}")
                        continue
                        
                    # Calculate days since, ensuring no timezone mismatch
                    last_dt_naive = last_dt.replace(tzinfo=None) if hasattr(last_dt, 'replace') else last_dt
                    days_since = (now - last_dt_naive).days
                except Exception as e:
                    logger.warning(f"Failed to parse last_interaction '{last_interaction}': {e}")
                    continue

                
                if days_since <= DECAY_GRACE_PERIOD_DAYS:
                    continue
                
                # Apply decay
                current_strength = rel.get("strength", DEFAULT_RELATIONSHIP_STRENGTH)
                days_to_decay = days_since - DECAY_GRACE_PERIOD_DAYS
                
                # Decay formula: strength * (1 - decay_rate) ^ days
                new_strength = current_strength * ((1 - self.decay_rate) ** days_to_decay)
                
                if new_strength < MIN_RELATIONSHIP_STRENGTH:
                    # Prune very weak relationships
                    await self._remove_weak_relationship(
                        rel["from_id"], 
                        rel["to_id"], 
                        rel["rel_type"]
                    )
                    stats["pruned"] += 1
                else:
                    # Update with decayed strength
                    await self._update_strength(
                        rel["from_id"],
                        rel["to_id"],
                        rel["rel_type"],
                        new_strength
                    )
                    stats["decayed"] += 1
                    
        except Exception as e:
            logger.error(f"[RelationshipStrength] Decay application failed: {e}")
            
        return stats

    async def _update_strength(
        self,
        from_id: str,
        to_id: str,
        rel_type: str,
        new_strength: float
    ) -> None:
        """Update a relationship's strength."""
        query = """
        FOR r IN @@rel_collection
            LET from_doc = (FOR n IN UNION(
                (FOR x IN Email FILTER x._id == r._from RETURN x),
                (FOR x IN Person FILTER x._id == r._from RETURN x),
                (FOR x IN ActionItem FILTER x._id == r._from RETURN x)
            ) RETURN n)[0]
            LET to_doc = (FOR n IN UNION(
                (FOR x IN Email FILTER x._id == r._to RETURN x),
                (FOR x IN Person FILTER x._id == r._to RETURN x),
                (FOR x IN ActionItem FILTER x._id == r._to RETURN x)
            ) RETURN n)[0]
            FILTER from_doc.id == @from_id AND to_doc.id == @to_id
            UPDATE r WITH {
                strength: @strength,
                decayed_at: @now
            } IN @@rel_collection
        """
        
        await self.graph.execute_query(query, {
            "from_id": from_id,
            "to_id": to_id,
            "@rel_collection": rel_type,
            "strength": new_strength,
            "now": datetime.utcnow().isoformat()
        })

    async def _remove_weak_relationship(
        self,
        from_id: str,
        to_id: str,
        rel_type: str
    ) -> None:
        """Remove a relationship that has decayed below threshold."""
        # Instead of deleting, we could archive or mark as inactive
        # For now, we'll just set a very low strength and mark as pruned
        query = """
        FOR r IN @@rel_collection
            LET from_doc = (FOR n IN UNION(
                (FOR x IN Email FILTER x._id == r._from RETURN x),
                (FOR x IN Person FILTER x._id == r._from RETURN x),
                (FOR x IN ActionItem FILTER x._id == r._from RETURN x)
            ) RETURN n)[0]
            LET to_doc = (FOR n IN UNION(
                (FOR x IN Email FILTER x._id == r._to RETURN x),
                (FOR x IN Person FILTER x._id == r._to RETURN x),
                (FOR x IN ActionItem FILTER x._id == r._to RETURN x)
            ) RETURN n)[0]
            FILTER from_doc.id == @from_id AND to_doc.id == @to_id
            UPDATE r WITH {
                strength: 0,
                pruned: true,
                pruned_at: @now
            } IN @@rel_collection
        """
        
        await self.graph.execute_query(query, {
            "from_id": from_id,
            "to_id": to_id,
            "@rel_collection": rel_type,
            "now": datetime.utcnow().isoformat()
        })
        
        logger.debug(f"[RelationshipStrength] Pruned weak relationship: {from_id} -[{rel_type}]-> {to_id}")

    async def get_strongest_relationships(
        self,
        node_id: str,
        limit: int = 10,
        min_strength: float = 0.0,
        rel_types: Optional[List[RelationType]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get the strongest relationships for a node.
        
        Args:
            node_id: Node to get relationships for
            limit: Maximum results
            min_strength: Minimum strength threshold
            rel_types: Optional filter by relationship types
            
        Returns:
            List of relationships sorted by strength
        """
        type_filter = ""
        if rel_types:
            type_values = [rt.value if hasattr(rt, 'value') else rt for rt in rel_types]
            # Use raw string literals aka 'SENT', 'RECEIVED'
            type_filter = f"AND PARSE_IDENTIFIER(r._id).collection IN {type_values}"
        
        query = f"""
        FOR start_node IN UNION(
            (FOR n IN Email FILTER n.id == @node_id RETURN n),
            (FOR n IN Person FILTER n.id == @node_id RETURN n),
            (FOR n IN ActionItem FILTER n.id == @node_id RETURN n),
            (FOR n IN CalendarEvent FILTER n.id == @node_id RETURN n),
            (FOR n IN Topic FILTER n.id == @node_id RETURN n)
        )
            FOR r IN UNION(
                (FOR e IN SENT FILTER e._from == start_node._id OR e._to == start_node._id RETURN e),
                (FOR e IN RECEIVED FILTER e._from == start_node._id OR e._to == start_node._id RETURN e),
                (FOR e IN MENTIONS FILTER e._from == start_node._id OR e._to == start_node._id RETURN e),
                (FOR e IN RELATED_TO FILTER e._from == start_node._id OR e._to == start_node._id RETURN e)
            )
                FILTER r.strength != null AND r.strength >= @min_strength
                   AND (r.pruned == null OR r.pruned == false)
                LET connected = r._from == start_node._id ? DOCUMENT(r._to) : DOCUMENT(r._from)
                SORT r.strength DESC
                LIMIT @limit
                RETURN {{
                    connected_id: connected.id,
                    connected_name: connected.name,
                    rel_type: PARSE_IDENTIFIER(r._id).collection,
                    strength: r.strength,
                    interaction_count: r.interaction_count,
                    last_interaction: r.last_interaction
                }}
        """
        
        try:
            results = await self.graph.execute_query(query, {
                "node_id": node_id,
                "min_strength": min_strength,
                "limit": limit
            })
            return results or []
        except Exception as e:
            logger.error(f"[RelationshipStrength] Failed to get strongest relationships: {e}")
            return []

    async def get_relationship_strength(
        self,
        from_id: str,
        to_id: str,
        rel_type: Optional[RelationType] = None
    ) -> Optional[float]:
        """Get the strength of a specific relationship."""
        type_filter = ""
        if rel_type:
            rt_val = rel_type.value if hasattr(rel_type, 'value') else rel_type
            type_filter = f"AND PARSE_IDENTIFIER(r._id).collection == '{rt_val}'"
        
        query = f"""
        FOR a IN UNION(
            (FOR n IN Email FILTER n.id == @from_id RETURN n),
            (FOR n IN Person FILTER n.id == @from_id RETURN n),
            (FOR n IN ActionItem FILTER n.id == @from_id RETURN n)
        )
            FOR b IN UNION(
                (FOR n IN Email FILTER n.id == @to_id RETURN n),
                (FOR n IN Person FILTER n.id == @to_id RETURN n),
                (FOR n IN ActionItem FILTER n.id == @to_id RETURN n)
            )
                FOR r IN UNION(
                    (FOR e IN SENT FILTER (e._from == a._id AND e._to == b._id) OR (e._from == b._id AND e._to == a._id) RETURN e),
                    (FOR e IN RECEIVED FILTER (e._from == a._id AND e._to == b._id) OR (e._from == b._id AND e._to == a._id) RETURN e),
                    (FOR e IN MENTIONS FILTER (e._from == a._id AND e._to == b._id) OR (e._from == b._id AND e._to == a._id) RETURN e)
                )
                    FILTER r.strength != null {type_filter}
                    LIMIT 1
                    RETURN {{ strength: r.strength }}
        """
        
        try:
            results = await self.graph.execute_query(query, {
                "from_id": from_id,
                "to_id": to_id
            })
            if results and len(results) > 0:
                return results[0].get("strength")
            return None
        except Exception as e:
            logger.error(f"[RelationshipStrength] Failed to get relationship strength: {e}")
            return None

    async def initialize_relationship_strength(
        self,
        from_id: str,
        to_id: str,
        rel_type: RelationType,
        initial_strength: float = DEFAULT_RELATIONSHIP_STRENGTH
    ) -> bool:
        """
        Initialize strength tracking for a relationship.
        
        Should be called when a new relationship is created.
        """
        now = datetime.utcnow().isoformat()
        
        query = """
        FOR a IN UNION(
            (FOR n IN Email FILTER n.id == @from_id RETURN n),
            (FOR n IN Person FILTER n.id == @from_id RETURN n),
            (FOR n IN ActionItem FILTER n.id == @from_id RETURN n),
        )
            FOR b IN UNION(
                (FOR n IN Email FILTER n.id == @to_id RETURN n),
                (FOR n IN Person FILTER n.id == @to_id RETURN n),
                (FOR n IN ActionItem FILTER n.id == @to_id RETURN n)
            )
                FOR r IN @@rel_collection
                    FILTER r._from == a._id AND r._to == b._id AND r.strength == null
                    UPDATE r WITH {
                        strength: @strength,
                        interaction_count: 1,
                        first_seen: @now,
                        last_interaction: @now
                    } IN @@rel_collection
                    RETURN { strength: NEW.strength }
        """
        
        # Extract raw string value if it's an Enum
        rel_collection_name = rel_type.value if hasattr(rel_type, 'value') else rel_type
        
        try:
            results = await self.graph.execute_query(query, {
                "from_id": from_id,
                "to_id": to_id,
                "@rel_collection": rel_collection_name,
                "strength": initial_strength,
                "now": now
            })
            return len(results) > 0 if results else False
        except Exception as e:
            logger.error(f"[RelationshipStrength] Failed to initialize strength: {e}")
            return False

    def calculate_decay(
        self,
        current_strength: float,
        days_since_interaction: int,
        custom_decay_rate: Optional[float] = None
    ) -> float:
        """
        Calculate what the strength would be after decay.
        
        Useful for preview/simulation without actually applying decay.
        """
        rate = custom_decay_rate or self.decay_rate
        
        if days_since_interaction <= DECAY_GRACE_PERIOD_DAYS:
            return current_strength
            
        days_to_decay = days_since_interaction - DECAY_GRACE_PERIOD_DAYS
        return current_strength * ((1 - rate) ** days_to_decay)
