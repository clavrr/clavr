"""
AI Features Endpoints
Auto-reply, email analysis, summarization, meeting prep
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

from api.dependencies import get_async_db, get_current_user
from src.database.models import User, UserWritingProfile
from src.features.auto_responder import EmailAutoResponder
from src.features.email_analyzer import EmailAnalyzer
from src.features.document_summarizer import DocumentSummarizer
from src.features.meeting_notes import MeetingNotesGenerator
from src.utils.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter(prefix="/api/ai", tags=["ai_features"])


# ============================================
# REQUEST/RESPONSE MODELS
# ============================================

class EmailAutoReplyRequest(BaseModel):
    """Request for auto-reply generation"""
    email_content: str
    email_subject: str
    sender_name: str
    sender_email: str
    num_options: int = 3


class EmailAnalysisRequest(BaseModel):
    """Request for email analysis"""
    subject: str
    body: str
    sender: str


class DocumentSummaryRequest(BaseModel):
    """Request for document summarization"""
    content: str
    title: Optional[str] = None
    doc_type: str = "text"


class MeetingPrepRequest(BaseModel):
    """Request for meeting prep brief"""
    meeting_title: str
    meeting_time: str  # ISO format
    attendees: List[str]
    calendar_description: Optional[str] = None


# ============================================
# ENDPOINTS
# ============================================

@router.post("/auto-reply")
async def generate_auto_reply(
    request: EmailAutoReplyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
) -> Dict[str, Any]:
    """
    Generate intelligent reply options for an email
    
    Returns 3 variations with different tones:
    - Professional
    - Friendly
    - Brief
    
    **Note:** If you have built a writing style profile, replies will be
    personalized to match your writing style. Build a profile at POST /api/profile/build
    
    Args:
        request: EmailAutoReplyRequest with email details
        
    Returns:
        Dictionary with success status and reply options
    """
    try:
        from sqlalchemy import select
        
        # Fetch user's writing profile if available
        user_style = None
        stmt = select(UserWritingProfile).where(
            UserWritingProfile.user_id == user.id
        )
        result = await db.execute(stmt)
        profile = result.scalar_one_or_none()
        
        if profile:
            user_style = profile.profile_data
            logger.info(f"Using writing profile for user {user.id} (sample_size={profile.sample_size}, confidence={profile.confidence_score})")
        else:
            logger.info(f"No writing profile found for user {user.id} - using generic responses")
        
        from src.utils.config import load_config
        config = load_config()
        responder = EmailAutoResponder(config)
        
        replies = await responder.generate_reply(
            email_content=request.email_content,
            email_subject=request.email_subject,
            sender_name=request.sender_name,
            sender_email=request.sender_email,
            user_style=user_style,
            num_options=request.num_options
        )
        
        return {
            "success": True,
            "replies": replies,
            "count": len(replies),
            "personalized": profile is not None
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating auto-reply: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-email")
async def analyze_email(
    request: EmailAnalysisRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
) -> Dict[str, Any]:
    """
    Analyze email for sentiment, priority, intent, and urgency
    
    Provides comprehensive analysis including:
    - Sentiment analysis (positive/negative/neutral)
    - Priority scoring (high/medium/low)
    - Intent detection (question/request/info/complaint)
    - Urgency indicators
    - Suggested actions
    
    Args:
        request: EmailAnalysisRequest with email details
        
    Returns:
        Dictionary with analysis results
    """
    try:
        from src.utils.config import load_config
        config = load_config()
        analyzer = EmailAnalyzer(config)
        
        analysis = await analyzer.analyze_email(
            subject=request.subject,
            body=request.body,
            sender=request.sender
        )
        
        return {
            "success": True,
            "analysis": {
                "sentiment": analysis.sentiment,
                "sentiment_score": analysis.sentiment_score,
                "priority": analysis.priority,
                "priority_score": analysis.priority_score,
                "intent": analysis.intent,
                "action_required": analysis.action_required,
                "is_urgent": analysis.is_urgent,
                "urgency_reasons": analysis.urgency_reasons,
                "category": analysis.category,
                "tags": analysis.tags,
                "estimated_response_time": analysis.estimated_response_time,
                "requires_human": analysis.requires_human,
                "key_points": analysis.key_points,
                "suggested_actions": analysis.suggested_actions
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing email: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/summarize")
async def summarize_document(
    request: DocumentSummaryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
) -> Dict[str, Any]:
    """
    Summarize any document or email
    
    Extracts:
    - Executive summary (2-3 sentences)
    - Key points (bullet format)
    - Main topics/themes
    - Action items
    - Important dates and numbers
    
    Args:
        request: DocumentSummaryRequest with content to summarize
        
    Returns:
        Dictionary with summary and extracted information
    """
    try:
        from src.utils.config import load_config
        config = load_config()
        summarizer = DocumentSummarizer(config)
        
        summary = await summarizer.summarize_document(
            content=request.content,
            title=request.title,
            doc_type=request.doc_type
        )
        
        return {
            "success": True,
            "summary": {
                "title": summary.title,
                "summary": summary.summary,
                "key_points": summary.key_points,
                "topics": summary.topics,
                "word_count": summary.word_count,
                "reading_time": summary.estimated_reading_time,
                "sentiment": summary.sentiment,
                "action_items": summary.action_items,
                "important_dates": summary.important_dates,
                "important_numbers": summary.important_numbers
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error summarizing document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/meeting-prep")
async def prepare_meeting_brief(
    request: MeetingPrepRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
) -> Dict[str, Any]:
    """
    Generate pre-meeting brief with preparation materials
    
    Creates comprehensive brief including:
    - Agenda items
    - Context summary from related emails
    - Talking points
    - Decisions needed
    - Preparation tasks
    
    Args:
        request: MeetingPrepRequest with meeting details
        
    Returns:
        Dictionary with meeting brief
    """
    try:
        from src.utils.config import load_config
        config = load_config()
        generator = MeetingNotesGenerator(config)
        
        meeting_time = datetime.fromisoformat(request.meeting_time.replace('Z', '+00:00'))
        
        brief = await generator.generate_pre_meeting_brief(
            meeting_title=request.meeting_title,
            meeting_time=meeting_time,
            attendees=request.attendees,
            calendar_description=request.calendar_description
        )
        
        return {
            "success": True,
            "brief": {
                "meeting_title": brief.meeting_title,
                "meeting_time": brief.meeting_time,
                "attendees": brief.attendees,
                "agenda_items": brief.agenda_items,
                "context_summary": brief.context_summary,
                "key_emails": brief.key_emails,
                "talking_points": brief.talking_points,
                "decisions_needed": brief.decisions_needed,
                "preparation_tasks": brief.preparation_tasks
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating meeting brief: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

