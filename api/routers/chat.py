"""
Chat Router - Smart chat, RAG search, and agent orchestration.
"""
from fastapi import APIRouter, Depends, Request, HTTPException, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, model_validator

from api.dependencies import get_db, get_chat_service, get_config, get_current_user
from src.database.models import User
from src.utils.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

# Shared SSE streaming headers
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no"
}


class QueryRequest(BaseModel):
    query: Optional[str] = None
    message: Optional[str] = None  # Frontend sends 'message' instead of 'query'
    max_results: Optional[int] = 5
    conversationId: Optional[str] = None
    userId: Optional[str] = None

    @model_validator(mode="after")
    def _resolve_query(self):
        """Accept either 'query' or 'message' — normalize to query."""
        if not self.query and self.message:
            self.query = self.message
        if not self.query:
            raise ValueError("Either 'query' or 'message' must be provided")
        return self


def _create_streaming_response(user: User, query: str, request: Request, chat_service, conversation_id: str = None) -> StreamingResponse:
    """
    Create a streaming SSE response for chat queries.
    
    Extracted helper to avoid code duplication across streaming endpoints.
    """
    async def event_generator():
        async for chunk in chat_service.execute_unified_query_stream(
            user=user,
            query_text=query,
            request=request,
            conversation_id=conversation_id
        ):
            yield f"data: {chunk}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS
    )


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
    return _create_streaming_response(user, body.query, request, chat_service, conversation_id=body.conversationId)


@router.post("/stream")
async def chat_stream_alias(
    request: Request,
    body: QueryRequest,
    user: User = Depends(get_current_user),
    chat_service = Depends(get_chat_service)
):
    """Alias for /api/chat/unified/stream - Direct chat streaming endpoint."""
    return _create_streaming_response(user, body.query, request, chat_service, conversation_id=body.conversationId)


# Legacy /api/query router
query_router = APIRouter(prefix="/query", tags=["query"])


@query_router.post("/stream")
async def query_stream_alias(
    request: Request,
    body: QueryRequest,
    user: User = Depends(get_current_user),
    chat_service = Depends(get_chat_service)
):
    """Alias for /api/chat/unified/stream - Legacy query streaming endpoint."""
    return _create_streaming_response(user, body.query, request, chat_service, conversation_id=body.conversationId)
