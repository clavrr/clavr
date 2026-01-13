from typing import Optional, Type, Dict, Any, List
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
import asyncio
import logging

from ...utils.logger import setup_logger
from ...utils.config import Config
from ..base import WorkflowEventMixin
from ...services.dashboard.brief_service import BriefService
from ...ai.autonomy.briefing import BriefingGenerator

logger = setup_logger(__name__)

class BriefInput(BaseModel):
    action: Optional[str] = Field(default="briefing", description="Action to perform: 'briefing' (narrative summary) or 'reminders' (list of key items)")
    query: Optional[str] = Field(default="", description="Specific context or date for the briefing.")

class BriefTool(WorkflowEventMixin, BaseTool):
    name: str = "reminders"
    description: str = "Access your day's briefings and smart reminders. Use this whenever the user asks for 'reminders', 'summarize my day', 'bills', or 'deadlines'."
    args_schema: Type[BaseModel] = BriefInput
    
    config: Config = Field(exclude=True)
    brief_service: Optional[BriefService] = Field(default=None, exclude=True)
    brief_generator: Optional[BriefingGenerator] = Field(default=None, exclude=True)
    user_id: int = 1
    user_first_name: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True

    def _run(self, action: str = "briefing", query: str = "", **kwargs) -> str:
        """Sync execution - not recommended for this tool."""
        return "Please use the async version of this tool."

    async def _arun(self, action: str = "briefing", query: str = "", **kwargs) -> str:
        """Execute brief tool action."""
        logger.info(f"[BriefTool] Executing {action} for user {self.user_id}")
        
        # Ensure services are initialized
        if not self.brief_service and not self.brief_generator:
            return "Brief service not initialized."

        try:
            # Smart action detection for voice (if action is generic or mismatched)
            q = (query or "").lower()
            if action == "briefing" and any(k in q for k in ["remind", "bill", "deadline", "appointment", "due"]):
                logger.info(f"[BriefTool] Smart-switching action to 'reminders' based on query: {query}")
                action = "reminders"
            
            if action == "briefing":
                if not self.brief_generator:
                    return "Briefing generator not available."
                
                # Briefing generator needs services passed in
                email_svc = self.brief_service.email_service if self.brief_service else None
                task_svc = self.brief_service.task_service if self.brief_service else None
                cal_svc = self.brief_service.calendar_service if self.brief_service else None
                
                result = await self.brief_generator.generate_briefing(
                    user_id=self.user_id,
                    calendar_service=cal_svc,
                    email_service=email_svc,
                    task_service=task_svc,
                    fast_mode=True  # Optimized for voice
                )
                return result

            elif action in ["reminders", "check_reminders", "check"]:
                if not self.brief_service:
                    return "Brief service not available."
                
                briefs = await self.brief_service.get_dashboard_briefs(
                    user_id=self.user_id,
                    user_name=self.user_first_name or "there",
                    fast_mode=True  # Optimized for voice
                )
                
                reminders = briefs.get("reminders", {})
                summary = reminders.get("summary", "")
                items = reminders.get("items", [])
                
                if not items:
                    return summary or "You have no urgent reminders right now!"
                
                reply = f"{summary}\n\n"
                for i, item in enumerate(items[:5], 1):
                    title = item.get('title')
                    subtitle = item.get('subtitle')
                    reply += f"{i}. {title} ({subtitle})\n"
                
                return reply

            else:
                return f"Unknown action: {action}. Please use 'briefing' or 'reminders'."

        except Exception as e:
            logger.error(f"[BriefTool] Error: {e}", exc_info=True)
            return f"I encountered an error getting your briefs: {str(e)}"
