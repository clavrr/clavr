from typing import Optional, Type, Dict, Any, List
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
import asyncio
import logging

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.database import get_db_context
from src.database.models import GhostDraft
from sqlalchemy import select, update

logger = setup_logger(__name__)

class GhostInput(BaseModel):
    action: str = Field(description="Action to perform: 'list' (show pending drafts), 'approve' (post a draft), or 'dismiss' (remove a draft)")
    draft_id: Optional[int] = Field(default=None, description="The ID of the draft to approve or dismiss. If not provided for approve, the most recent draft is used.")
    detail: Optional[str] = Field(default="", description="Optional feedback or additional detail.")

class GhostTool(BaseTool):
    name: str = "ghost_collaborator"
    description: str = "Manage drafts and suggestions from your proactive Ghost Collaborator. Use this for 'what did you find on slack?', 'show me my drafts', 'approve that issue', or 'dismiss that suggestion'."
    args_schema: Type[BaseModel] = GhostInput
    
    config: Config = Field(exclude=True)
    user_id: int = 1

    class Config:
        arbitrary_types_allowed = True

    def _run(self, action: str, draft_id: Optional[int] = None, **kwargs) -> str:
        return "Please use the async version of this tool."

    async def _arun(self, action: str, draft_id: Optional[int] = None, **kwargs) -> str:
        """Execute ghost tool action."""
        logger.info(f"[GhostTool] Executing {action} for user {self.user_id}")
        
        try:
            if action == "list":
                return await self._list_drafts()
            elif action == "approve":
                return await self._approve_draft(draft_id)
            elif action == "dismiss":
                return await self._dismiss_draft(draft_id)
            else:
                return f"Unknown action: {action}. Please use 'list', 'approve', or 'dismiss'."
        except Exception as e:
            logger.error(f"[GhostTool] Error: {e}")
            return f"I had trouble with the Ghost Collaborator: {str(e)}"

    async def _list_drafts(self) -> str:
        with get_db_context() as db:
            drafts = db.query(GhostDraft).filter(
                GhostDraft.user_id == self.user_id,
                GhostDraft.status == "draft"
            ).order_by(GhostDraft.created_at.desc()).limit(5).all()
            
            if not drafts:
                return "You have no pending drafts or suggestions from the Ghost Collaborator right now."
            
            res = "I have a few suggestions for you:\n"
            for d in drafts:
                res += f"- ID {d.id}: {d.title} (Confidence: {int(d.confidence*100)}%)\n"
            
            res += "\nYou can say 'approve draft [ID]' to post it to Linear."
            return res

    async def _approve_draft(self, draft_id: Optional[int]) -> str:
        from src.integrations.linear.service import LinearService
        
        with get_db_context() as db:
            # If no ID, find the most recent
            if draft_id is None:
                draft = db.query(GhostDraft).filter(
                    GhostDraft.user_id == self.user_id,
                    GhostDraft.status == "draft"
                ).order_by(GhostDraft.created_at.desc()).first()
            else:
                draft = db.query(GhostDraft).filter(
                    GhostDraft.id == draft_id,
                    GhostDraft.user_id == self.user_id
                ).first()
            
            if not draft:
                return "I couldn't find that draft. Try saying 'list my drafts' first."

            if draft.status != "draft":
                return f"That draft is already {draft.status}."

            # Post to integration
            if draft.integration_type == "linear":
                linear = LinearService(self.config, user_id=self.user_id)
                await linear.create_issue(
                    title=draft.title,
                    description=draft.description,
                    priority="urgent" if draft.confidence > 0.8 else "high"
                )
                
                draft.status = "posted"
                db.commit()
                return f"Great! I've posted '{draft.title}' to Linear for you."
            else:
                return f"I don't support posting to {draft.integration_type} yet."

    async def _dismiss_draft(self, draft_id: Optional[int]) -> str:
        with get_db_context() as db:
            if draft_id is None:
                draft = db.query(GhostDraft).filter(
                    GhostDraft.user_id == self.user_id,
                    GhostDraft.status == "draft"
                ).order_by(GhostDraft.created_at.desc()).first()
            else:
                draft = db.query(GhostDraft).filter(
                    GhostDraft.id == draft_id,
                    GhostDraft.user_id == self.user_id
                ).first()
                
            if not draft:
                return "I couldn't find that draft to dismiss."
            
            draft.status = "dismissed"
            db.commit()
            return f"Okay, I've dismissed the suggestion: '{draft.title}'."
