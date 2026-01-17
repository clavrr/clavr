"""
Proactive Planner 

Logic for Goal-Driven Autonomy.
Checks the user's "State" (Time, Energy, Location) against their "Goals" to propose actions.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.future import select

from ...database.models import AgentGoal
from ...utils.logger import setup_logger
from ...utils.config import Config
from .base import StructuredGenerator
from ..prompts.autonomy_prompts import (
    AUTONOMOUS_GOAL_SELECTION_SYSTEM_PROMPT,
    AUTONOMOUS_PLANNING_SYSTEM_PROMPT
)

logger = setup_logger(__name__)

class ActionPlan(dict):
    """
    Structured plan for an autonomous action found by the Planner.
    Inherits from dict for JSON serialization compatibility.
    """
    def __init__(self, type: str, goal_id: int, description: str, params: Dict[str, Any]):
        super().__init__(type=type, goal_id=goal_id, description=description, params=params)

class ProactivePlanner(StructuredGenerator):
    """
    Reasoning Engine: Goal vs State.
    Uses LLM to select goals and plan multi-step actions.
    """
    def __init__(self, db_session: Any, config: Config):
        super().__init__(config)
        self.db = db_session
        
    async def check_goals_against_state(self, 
                                        user_id: int, 
                                        calendar_service: Any) -> List[ActionPlan]:
        """
        Evaluate if any goals can be advanced right now using LLM reasoning.
        """
        plans = []
        try:
            # 1. Fetch Goals (Active/Pending)
            stmt = select(AgentGoal).where(
                AgentGoal.user_id == user_id,
                AgentGoal.status.in_(['active', 'pending'])
            ).order_by(AgentGoal.deadline.asc().nulls_last())
            
            result = await self.db.execute(stmt)
            goals = result.scalars().all()
            
            if not goals:
                return []
                
            # 2. Prepare Context for LLM
            goals_data = [
                {
                    "id": g.id,
                    "title": g.title,
                    "description": g.description,
                    "deadline": g.deadline.isoformat() if g.deadline else None,
                    "priority": g.priority
                } for g in goals
            ]
            
            # Check free time slots using CalendarService (Heuristic state check)
            # We provide this to the LLM as "options"
            now = datetime.utcnow()
            check_duration_mins = 60
            start_check_iso = now.isoformat()
            
            free_slots = []
            if calendar_service:
                # Look ahead 8 hours for slots
                search_end = (now + timedelta(hours=8)).isoformat()
                free_slots = calendar_service.find_free_time(
                    duration_minutes=check_duration_mins,
                    start_date=start_check_iso,
                    end_date=search_end,
                    max_suggestions=3
                )
            
            # 3. LLM Step 1: Goal Selection
            # This uses the structured prompt to pick the best goal
            import json
            context_str = f"Active Goals: {json.dumps(goals_data, indent=2)}\n"
            context_str += f"Current Time (UTC): {now.isoformat()}\n"
            context_str += f"Available Calendar Slots: {json.dumps(free_slots, indent=2)}\n"
            
            selection = await self._generate_structured(
                system_prompt=AUTONOMOUS_GOAL_SELECTION_SYSTEM_PROMPT,
                user_context=context_str
            )
            
            if not selection or not selection.get('goal'):
                logger.info("[Planner] LLM decided no immediate action needed.")
                return []
                
            logger.info(f"[Planner] Selected Goal: {selection.get('goal')} (Reason: {selection.get('reasoning')})")
            
            # 4. LLM Step 2: Planning
            # Now break the goal into steps
            plan_result = await self._generate_structured(
                system_prompt=AUTONOMOUS_PLANNING_SYSTEM_PROMPT,
                user_context=f"GOAL: {selection.get('goal')}\nTOOLS: Email, Calendar, Tasks"
            )
            
            if not plan_result or not plan_result.get('plan'):
                # Fallback to simple focus block if planning fails
                proposed_start = free_slots[0]['start'] if free_slots else start_check_iso
                target_goal_id = selection.get('goal_id') or goals[0].id
                
                plans.append(ActionPlan(
                    type="block_time",
                    goal_id=target_goal_id,
                    description=f"Focus Time: {selection.get('goal')}",
                    params={
                        "start": proposed_start,
                        "duration_minutes": check_duration_mins,
                        "summary": f"Focus: {selection.get('goal')}"
                    }
                ))
            else:
                # Convert LLM plan to ActionPlans
                # Iterate over all steps and validate
                target_goal_id = selection.get('goal_id') or goals[0].id
                
                for step in plan_result.get('plan', []):
                    action_type = step.get('type')
                    if not action_type:
                        continue
                        
                    plans.append(ActionPlan(
                        type=action_type,
                        goal_id=target_goal_id,
                        description=step.get('description', selection.get('goal')),
                        params=step.get('params', {})
                    ))
            
            return plans
            
        except Exception as e:
            logger.error(f"[Planner] Error checking goals: {e}", exc_info=True)
            return []
