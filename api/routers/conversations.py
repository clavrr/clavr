"""
Conversations Router - Manage user conversation history.
"""
from fastapi import APIRouter, Depends
from typing import List, Dict, Any

from api.dependencies import get_current_user, get_async_db
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.models import User
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

@router.get("")
async def get_recent_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get recent conversations for the current user.
    """
    logger.info(f"Fetching conversations for user: {current_user.id}")
    
    from src.ai.conversation_memory import ConversationMemory
    
    memory = ConversationMemory(db)
    conversations = await memory.list_conversations(current_user.id)
    return conversations
