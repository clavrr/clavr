"""
Chat Router - Smart chat, RAG search, and agent orchestration.
"""
from fastapi import APIRouter, Depends, Request, HTTPException, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from api.dependencies import get_db, get_chat_service, get_config, get_current_user
from src.database.models import User
from src.utils.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

class QueryRequest(BaseModel):
    query: str
    max_results: Optional[int] = 5

@router.post("/query")
async def chat_with_emails(
    request: Request,
    body: QueryRequest,
    user: User = Depends(get_current_user),
    chat_service = Depends(get_chat_service)
):
    """Smart chat with email knowledge and fallback to actions."""
    return await chat_service.process_chat_query(
        user=user,
        query_text=body.query,
        max_results=body.max_results,
        request=request
    )

@router.post("/unified")
async def unified_query(
    request: Request,
    body: QueryRequest,
    user: User = Depends(get_current_user),
    chat_service = Depends(get_chat_service)
):
    """Execute query using the multi-agent system (ClavrAgent)."""
    answer = await chat_service.execute_unified_query(
        user=user,
        query_text=body.query,
        request=request
    )
    return {"answer": answer}

@router.post("/unified/stream")
async def unified_query_stream(
    request: Request,
    body: QueryRequest,
    user: User = Depends(get_current_user),
    chat_service = Depends(get_chat_service)
):
    """Execute query using the multi-agent system with streaming output."""
    async def event_generator():
        async for chunk in chat_service.execute_unified_query_stream(
            user=user,
            query_text=body.query,
            request=request
        ):
            # Format as SSE data
            yield f"data: {chunk}\n\n"
        
    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.post("/stream")
async def chat_stream_alias(
    request: Request,
    body: QueryRequest,
    user: User = Depends(get_current_user),
    chat_service = Depends(get_chat_service)
):
    """Alias for /api/chat/unified/stream - Direct chat streaming endpoint."""
    async def event_generator():
        async for chunk in chat_service.execute_unified_query_stream(
            user=user,
            query_text=body.query,
            request=request
        ):
            # Format as SSE data
            yield f"data: {chunk}\n\n"
        
    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# Create a separate router for /api/query endpoints (legacy/alias)
query_router = APIRouter(prefix="/api/query", tags=["query"])

@query_router.post("/stream")
async def query_stream_alias(
    request: Request,
    body: QueryRequest,
    user: User = Depends(get_current_user),
    chat_service = Depends(get_chat_service)
):
    """Alias for /api/chat/unified/stream - Legacy query streaming endpoint."""
    async def event_generator():
        async for chunk in chat_service.execute_unified_query_stream(
            user=user,
            query_text=body.query,
            request=request
        ):
            # Format as SSE data
            yield f"data: {chunk}\n\n"
        
    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

