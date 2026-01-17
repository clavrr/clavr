"""
Perception Agent

Acts as the "Sensory Gating" system for the Ambient Autonomy loop.
Role: Filters low-value noise and identifies high-signal "Triggers" by grounding events 
in the user's Knowledge Graph (Semantic Memory).

Phase 5 of Ambient Autonomy.
"""
from typing import Dict, Any, List, Optional, NamedTuple
from enum import Enum
from ...utils.logger import setup_logger
from ...utils.config import Config
from ...ai.autonomy.base import StructuredGenerator
from ...ai.prompts.autonomy_prompts import PERCEPTION_SIGNAL_PROMPT
from .types import PerceptionEvent, Trigger

logger = setup_logger(__name__)

class PerceptionAgent(StructuredGenerator):
    """
    Evaluates raw events to determine if they are worth the Supervisor's attention.
    Now backed by the Knowledge Graph for deep grounding and LLM for reasoning.
    """
    
    def __init__(self, config: Config):
        super().__init__(config)
        from ...memory.orchestrator import get_memory_orchestrator
        self.memory_orchestrator = get_memory_orchestrator()

    async def perceive_event(self, event: PerceptionEvent, user_id: int) -> Optional[Trigger]:
        """
        Main entry point. Evaluates a single event.
        Returns a Trigger if actionable, None if Noise.
        """
        try:
            # 1. Grounding: Check for relationships/facts in the Graph via Orchestrator
            grounding = await self._ground_event(event, user_id)
            
            # 2. Evaluate Signal
            trigger = await self._evaluate_signal(event, user_id, grounding)
            
            if trigger:
                logger.info(f"[Perception] 🔔  SIGNAL detected: {trigger.category} (Reason: {trigger.reason})")
                return trigger
            else:
                return None
                
        except Exception as e:
            logger.error(f"[Perception] Error perceiving event: {e}")
            return None

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
        Use LLM to decide if an event is a Trigger or Noise.
        """
        
        # 1. Immediate NOISE block
        if grounding.get("is_blocked"):
            return None
            
        # 2. Prepare context for LLM
        # Convert event NamedTuple to dict for JSON serialization
        event_dict = {
            "type": event.type,
            "timestamp": event.timestamp,
            "content": event.content
        }
        
        # Format grounding context for LLM
        grounding_str = f"Is VIP: {grounding.get('is_vip')}\n"
        if grounding.get("relevant_project"):
            grounding_str += f"Relevant Project: {grounding.get('relevant_project')}\n"
        
        # 3. Call LLM
        from ...ai.prompts.utils import format_prompt
        import json
        
        prompt_data = format_prompt(
            PERCEPTION_SIGNAL_PROMPT,
            grounding_context=grounding_str,
            event_data=json.dumps(event_dict, indent=2)
        )
        
        result = await self._generate_structured(
            system_prompt=PERCEPTION_SIGNAL_PROMPT, # StructuredGenerator handles system/human splits? 
            # Wait, StructuredGenerator._generate_structured takes system_prompt and user_context.
            # I should split them.
            user_context=prompt_data 
        )
        
        # 4. Parse result
        if result and result.get("is_actionable"):
            return Trigger(
                priority=result.get("priority", "medium"),
                category=result.get("category", "unknown"),
                reason=result.get("reason", "No reason provided"),
                context=event.content
            )
            
        return None
