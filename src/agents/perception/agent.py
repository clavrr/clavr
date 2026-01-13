"""
Perception Agent

Acts as the "Sensory Gating" system for the Ambient Autonomy loop.
Role: Filters low-value noise and identifies high-signal "Triggers" by grounding events 
in the user's Knowledge Graph (Semantic Memory).

Phase 5 of Ambient Autonomy.
"""
from typing import Dict, Any, List, Optional, NamedTuple
from enum import Enum
import re

from ...utils.logger import setup_logger
from ...ai.memory.semantic_memory import SemanticMemory
from .types import SignalType, PerceptionEvent, Trigger

logger = setup_logger(__name__)


from ...services.indexing.graph import KnowledgeGraphManager, NodeType, RelationType
from ...services.indexing.graph.schema import GraphSchema

class PerceptionAgent:
    """
    Evaluates raw events to determine if they are worth the Supervisor's attention.
    Now backed by the Knowledge Graph for deep grounding.
    """
    
    async def perceive_event(self, event: PerceptionEvent, user_id: int) -> Optional[Trigger]:
        """
        Main entry point. Evaluates a single event.
        Returns a Trigger if actionable, None if Noise.
        """
        try:
            # 1. Grounding: Check for relationships/facts in the Graph via Orchestrator
            is_grounded = await self._ground_event(event, user_id)
            
            # 2. Evaluate Signal
            trigger = await self._evaluate_signal(event, user_id, is_grounded)
            
            if trigger:
                logger.info(f"[Perception] 🔔  SIGNAL detected: {trigger.category} (Reason: {trigger.reason})")
                return trigger
            else:
                return None
                
        except Exception as e:
            logger.error(f"[Perception] Error perceiving event: {e}")
            return None

    def __init__(self):
        from ...memory.orchestrator import get_memory_orchestrator
        self.memory_orchestrator = get_memory_orchestrator()

    async def _ground_event(self, event: PerceptionEvent, user_id: int) -> Dict[str, Any]:
        """
        Check Knowledge Graph and Memory for connections via Orchestrator.
        """
        grounding = {
            "is_vip": False,
            "is_blocked": False,
            "relevant_project": None
        }
        
        if not self.memory_orchestrator:
             logger.warning("[Perception] MemoryOrchestrator not available, skipping grounding")
             return grounding
        
        # 1. Construct Query from Event
        query = ""
        if event.type == "email":
             sender = event.content.get("from", "")
             subject = event.content.get("subject", "")
             query = f"Email from {sender} about {subject}"
        elif event.type == "calendar":
             title = event.content.get("summary", "")
             query = f"Meeting about {title}"
        else:
             return grounding

        # 2. Get Context from Orchestrator
        # This triggers Graph lookup (Project/Person) and Semantic lookup (Preferences/Facts)
        context = await self.memory_orchestrator.get_context_for_agent(
             user_id=user_id,
             agent_name="PerceptionAgent",
             query=query,
             task_type="perception", # Specialized task type
             include_layers=["graph", "semantic"]
        )

        # 3. Analyze Context for Signals
        
        # Check Preferences (Blocking)
        for pref in context.user_preferences:
             if "block" in pref.get("content", "").lower():
                  grounding["is_blocked"] = True

        # Check Related People (VIP Status)
        for person in context.related_people:
             # Orchestrator returns summarized people context
             # If they appear in "related_people", they exist in the graph.
             # We check context string for keywords.
             ctx_str = person.get("context", "").lower() 
             if "vip" in ctx_str or "important" in ctx_str or "manager" in ctx_str:
                  grounding["is_vip"] = True
             # If we found the sender in the graph, that's already a signal (relationship exists)
             if event.type == "email" and event.content.get("from", "") in person.get("name", ""):
                  # Implicit VIP if they are a known contact with strong ties?
                  # For now, we rely on context keywords.
                  pass

        # Check Graph Context (Projects)
        for item in context.graph_context:
             node_type = item.get("type", "")
             content = item.get("content", "").lower()
             
             if node_type == "Project" or "project" in content:
                  grounding["relevant_project"] = item.get("content")
                  grounding["is_vip"] = True # Working on active project implies importance
             
             # Also check "Works For" or other strong relations if returned in graph_context
             if "works for" in content and "vip" in content:
                  grounding["is_vip"] = True

        return grounding

    async def _evaluate_signal(self, 
                               event: PerceptionEvent, 
                               user_id: int, 
                               grounding: Dict[str, Any]) -> Optional[Trigger]:
        """
        Decision logic: Noise vs Trigger.
        """
        
        # Immediate NOISE
        if grounding["is_blocked"]:
            return None
            
        if event.type == "email":
            email_data = event.content
            
            # TRIGGER 1: Project Relevance (Specific Context)
            if grounding["relevant_project"]:
                return Trigger(
                    priority="medium",
                    category="work_update",
                    reason=f"Related to Active Project: {grounding['relevant_project']}",
                    context={"email_id": email_data.get("id"), "subject": email_data.get("subject")}
                )

            # TRIGGER 2: VIP Sender (General Context)
            if grounding["is_vip"]:
                 return Trigger(
                     priority="high",
                     category="urgent_email",
                     reason="Sender is VIP/Relationship (Graph Verified)",
                     context={"email_id": email_data.get("id"), "sender": email_data.get("from")}
                 )
                
            # TRIGGER 3: Explicit High Priority (Metadata)
            if "important" in email_data.get("labels", []) or "urgent" in email_data.get("subject", "").lower():
                 return Trigger(
                     priority="medium",
                     category="urgent_email",
                     reason="Marked Important/Urgent",
                     context={"email_id": email_data.get("id")}
                 )
                 
        elif event.type == "calendar":
            pass
            
        return None
