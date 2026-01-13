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

logger = setup_logger(__name__)

class ActionPlan(dict):
    """
    Structured plan for an autonomous action found by the Planner.
    Inherits from dict for JSON serialization compatibility.
    """
    def __init__(self, type: str, goal_id: int, description: str, params: Dict[str, Any]):
        super().__init__(type=type, goal_id=goal_id, description=description, params=params)

class ProactivePlanner:
    """
    Reasoning Engine: Goal vs State.
    """
    def __init__(self, db_session: Any):
        self.db = db_session
        
    async def check_goals_against_state(self, 
                                        user_id: int, 
                                        calendar_service: Any) -> List[ActionPlan]:
        """
        Evaluate if any goals can be advanced right now.
        
        Logic:
        1. Fetch active goals (sorted by deadline).
        2. Check for free time slots using CalendarService.
        3. Match Goal -> Slot.
        """
        plans = []
        try:
            # 1. Fetch Goals (Active/Pending), sorted by deadline
            # Prioritize goals with upcoming deadlines
            stmt = select(AgentGoal).where(
                AgentGoal.user_id == user_id,
                AgentGoal.status.in_(['active', 'pending'])
            ).order_by(AgentGoal.deadline.asc().nulls_last())
            
            result = await self.db.execute(stmt)
            goals = result.scalars().all()
            
            if not goals:
                return []
                
            # 2. Check State (Time)
            if not calendar_service:
                logger.warning("[Planner] No CalendarService available. Cannot check state.")
                return []
            
            now = datetime.utcnow()
            check_duration_mins = 60
            
            # Scenario A: Is the user free RIGHT NOW?
            # We assume "Now" is the next 60s start.
            start_check_iso = now.isoformat()
            
            # Use find_conflicts to see if immediate execution is possible.
            # find_conflicts returns list of conflicting events
            conflicts = calendar_service.find_conflicts(
                start_time=start_check_iso,
                end_time=None,
                duration_minutes=check_duration_mins
            )
            
            proposed_start = None
            
            if not conflicts:
                # Free now!
                proposed_start = start_check_iso
                logger.info("[Planner] User is free NOW.")
            else:
                # Busy. Look ahead 4 hours for a slot.
                logger.info(f"[Planner] User busy now ({len(conflicts)} conflicts). Searching next 4 hours...")
                search_end = (now + timedelta(hours=4)).isoformat()
                
                # find_free_time returns dicts with 'start', 'end' keys
                free_slots = calendar_service.find_free_time(
                    duration_minutes=check_duration_mins,
                    start_date=start_check_iso,
                    end_date=search_end,
                    working_hours_only=False, # Be aggressive/flexible for goals
                    max_suggestions=1
                )
                
                if free_slots:
                    proposed_start = free_slots[0]['start']
                    logger.info(f"[Planner] Found free slot at {proposed_start}")
            
            if proposed_start:
                # 3. Propose Action for Top Priority Goal
                target_goal = goals[0]
                
                plan = ActionPlan(
                    type="block_time",
                    goal_id=target_goal.id,
                    description=f"Focus Time: {target_goal.title}",
                    params={
                        "start": proposed_start,
                        "duration_minutes": check_duration_mins,
                        "summary": f"Focus: {target_goal.title}"
                    }
                )
                
                plans.append(plan)
            
            return plans
            
        except Exception as e:
            logger.error(f"[Planner] Error checking goals: {e}")
            return []
