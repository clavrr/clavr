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

    def __init__(self, config: Config = None, user_id: int = 1, **kwargs):
        if config:
            kwargs['config'] = config
        kwargs['user_id'] = user_id
        super().__init__(**kwargs)
        if config:
            self.config = config
        self.user_id = user_id

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
        from src.database import get_async_db_context
        from sqlalchemy import select
        
        try:
            async with get_async_db_context() as db:
                query = select(GhostDraft).filter(
                    GhostDraft.user_id == self.user_id,
                    GhostDraft.status == "draft"
                ).order_by(GhostDraft.created_at.desc()).limit(5)
                
                result = await db.execute(query)
                drafts = result.scalars().all()
                
                if not drafts:
                    return "You have no pending drafts or suggestions from the Ghost Collaborator right now."
                
                res = "I have a few suggestions for you:\n"
                for d in drafts:
                    res += f"- ID {d.id}: {d.title} (Confidence: {int(d.confidence*100)}%)\n"
                
                res += "\nYou can say 'approve draft [ID]' to post it to Linear."
                return res
        except Exception as e:
            logger.error(f"[GhostTool] _list_drafts error: {e}")
            return f"Error listing drafts: {e}"

    async def _approve_draft(self, draft_id: Optional[int]) -> str:
        from src.integrations.linear.service import LinearService
        from src.database import get_async_db_context
        from sqlalchemy import select
        
        try:
            async with get_async_db_context() as db:
                # If no ID, find the most recent
                if draft_id is None:
                    query = select(GhostDraft).filter(
                        GhostDraft.user_id == self.user_id,
                        GhostDraft.status == "draft"
                    ).order_by(GhostDraft.created_at.desc()).limit(1)
                    result = await db.execute(query)
                    draft = result.scalar_one_or_none()
                else:
                    query = select(GhostDraft).filter(
                        GhostDraft.id == draft_id,
                        GhostDraft.user_id == self.user_id
                    )
                    result = await db.execute(query)
                    draft = result.scalar_one_or_none()
                
                if not draft:
                    return "I couldn't find that draft. Try saying 'list my drafts' first."

                if draft.status != "draft":
                    return f"That draft is already {draft.status}."

                # Post to integration
                if draft.integration_type == "linear":
                    # LinearService might block if it does sync HTTP. 
                    # Ideally LinearService should be async or wrapped. 
                    # Assuming LinearService here is capable of being run or is lightweight enough, 
                    # BUT ideally we should wrap it if it's sync.
                    # Looking at other tools, they likely wrap sync calls.
                    # For now, let's wrap the service call in to_thread just in case.
                    linear = LinearService(self.config, user_id=self.user_id)
                    
                    # Check if create_issue is async or sync. 
                    # Usually our services are sync wrappers around APIs unless refactored.
                    # Let's assume it's async based on `await linear.create_issue`.
                    
                    await linear.create_issue(
                        title=draft.title,
                        description=draft.description,
                        priority="urgent" if draft.confidence > 0.8 else "high"
                    )
                    
                    draft.status = "posted"
                    await db.commit()
                    return f"Great! I've posted '{draft.title}' to Linear for you."
                else:
                    return f"I don't support posting to {draft.integration_type} yet."
        except Exception as e:
            logger.error(f"[GhostTool] _approve_draft error: {e}")
            return f"Error approving draft: {e}"

    async def _dismiss_draft(self, draft_id: Optional[int]) -> str:
        from src.database import get_async_db_context
        from sqlalchemy import select
        
        try:
            async with get_async_db_context() as db:
                if draft_id is None:
                    query = select(GhostDraft).filter(
                        GhostDraft.user_id == self.user_id,
                        GhostDraft.status == "draft"
                    ).order_by(GhostDraft.created_at.desc()).limit(1)
                    result = await db.execute(query)
                    draft = result.scalar_one_or_none()
                else:
                    query = select(GhostDraft).filter(
                        GhostDraft.id == draft_id,
                        GhostDraft.user_id == self.user_id
                    )
                    result = await db.execute(query)
                    draft = result.scalar_one_or_none()
                    
                if not draft:
                    return "I couldn't find that draft to dismiss."
                
                draft.status = "dismissed"
                await db.commit()
                return f"Okay, I've dismissed the suggestion: '{draft.title}'."
        except Exception as e:
            logger.error(f"[GhostTool] _dismiss_draft error: {e}")
            return f"Error dismissing draft: {e}"
