"""
Conversations Router - Manage user conversation history.
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from api.dependencies import get_current_user, get_async_db
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.models import User
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


class MessagePayload(BaseModel):
    role: str
    content: str
    intent: Optional[str] = None
    entities: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None


class ConversationPayload(BaseModel):
    session_id: Optional[str] = None
    messages: List[MessagePayload]


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


@router.get("/{session_id}")
async def get_conversation(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get a specific conversation with all its messages.
    """
    logger.info(f"Fetching conversation {session_id} for user: {current_user.id}")
    
    from src.ai.conversation_memory import ConversationMemory
    
    memory = ConversationMemory(db)
    messages = await memory.get_conversation_messages(current_user.id, session_id)
    
    return {
        "session_id": session_id,
        "messages": messages,
        "total": len(messages) if messages else 0
    }


@router.post("")
async def create_conversation(
    payload: ConversationPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Create a new conversation or add messages to an existing one.
    """
    import uuid
    
    session_id = payload.session_id or f"conv-{uuid.uuid4().hex[:12]}"
    
    logger.info(f"Creating/saving conversation {session_id} for user: {current_user.id} with {len(payload.messages)} messages")
    
    from src.ai.conversation_memory import ConversationMemory
    
    memory = ConversationMemory(db)
    message_ids = []
    
    for msg in payload.messages:
        try:
            msg_id = await memory.add_message(
                user_id=current_user.id,
                session_id=session_id,
                role=msg.role,
                content=msg.content,
                intent=msg.intent,
                entities=msg.entities,
                confidence=msg.confidence
            )
            if msg_id:
                message_ids.append(str(msg_id))
        except Exception as e:
            logger.error(f"Failed to save message in conversation {session_id}: {e}")
    
    return {
        "session_id": session_id,
        "message_ids": message_ids,
        "success": len(message_ids) > 0
    }


@router.put("/{session_id}")
async def update_conversation(
    session_id: str,
    payload: ConversationPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Add new messages to an existing conversation.
    """
    logger.info(f"Updating conversation {session_id} for user: {current_user.id} with {len(payload.messages)} new messages")
    
    from src.ai.conversation_memory import ConversationMemory
    
    memory = ConversationMemory(db)
    message_ids = []
    
    for msg in payload.messages:
        try:
            msg_id = await memory.add_message(
                user_id=current_user.id,
                session_id=session_id,
                role=msg.role,
                content=msg.content,
                intent=msg.intent,
                entities=msg.entities,
                confidence=msg.confidence
            )
            if msg_id:
                message_ids.append(str(msg_id))
        except Exception as e:
            logger.error(f"Failed to save message in conversation {session_id}: {e}")
    
    return {
        "session_id": session_id,
        "message_ids": message_ids,
        "success": len(message_ids) > 0
    }

