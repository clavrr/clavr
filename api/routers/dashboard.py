"""
Dashboard Router - API endpoints for dashboard statistics

Provides overview statistics for:
- Unread emails count
- Today's calendar events count  
- Outstanding tasks count
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
import asyncio
from concurrent.futures import ThreadPoolExecutor

from api.auth import get_current_user_required
from ..dependencies import get_config
from src.database import get_db, get_async_db
from src.core.async_credential_provider import AsyncCredentialFactory
from src.database.models import User
from src.utils.logger import setup_logger
from src.integrations.gmail.service import EmailService
from src.integrations.google_tasks.service import TaskService
from src.integrations.google_calendar.service import CalendarService

logger = setup_logger(__name__)

print("DEBUG: MODULE LOADED: dashboard.py")

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get dashboard statistics for the current user
    
    Returns:
        - unread_emails: Number of unread emails
        - todays_events: Number of events today (remaining today, not past)
        - outstanding_tasks: Number of incomplete tasks
        - last_updated: Timestamp of when stats were fetched
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    
    logger.info(f"[DASHBOARD] Fetching stats for user {current_user.id}")
    
    stats = {
        "unread_emails": 0,
        "todays_events": 0,
        "outstanding_tasks": 0,
        "last_updated": datetime.now().isoformat(),
        "errors": []
    }
    
    try:
        # Run blocking DB query in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        
        def get_credentials():
            from src.database.models import Session as DBSession
            from sqlalchemy import select
            from google.oauth2.credentials import Credentials
            from src.utils import decrypt_token
            import os
            
            stmt = select(DBSession).where(
                DBSession.user_id == current_user.id,
                DBSession.expires_at > datetime.utcnow()
            ).order_by(DBSession.created_at.desc()).limit(1)
            
            result = db.execute(stmt)
            session = result.scalar_one_or_none()
            
            if session and session.gmail_access_token:
                try:
                    return Credentials(
                        token=decrypt_token(session.gmail_access_token),
                        refresh_token=decrypt_token(session.gmail_refresh_token) if session.gmail_refresh_token else None,
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.getenv('GOOGLE_CLIENT_ID'),
                        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
                        scopes=[
                            'https://www.googleapis.com/auth/gmail.readonly',
                            'https://www.googleapis.com/auth/gmail.send',
                            'https://www.googleapis.com/auth/gmail.modify',
                            'https://www.googleapis.com/auth/calendar',
                            'https://www.googleapis.com/auth/tasks'
                        ]
                    )
                except Exception as e:
                    logger.error(f"[DASHBOARD] Token decryption failed in stats: {e}")
                    return None
            return None
        
        with ThreadPoolExecutor() as executor:
            credentials = await loop.run_in_executor(executor, get_credentials)
        
        if not credentials:
            logger.warning("[DASHBOARD] No valid credentials found")
            stats["errors"].append("No valid session - please re-authenticate")
            return stats
        
        logger.info("[DASHBOARD] Valid credentials obtained, fetching real stats")

        # Get REAL unread emails count
        try:
            email_service = EmailService(config, credentials)
            unread_emails = email_service.list_unread_emails(limit=100)
            stats["unread_emails"] = len(unread_emails) if unread_emails else 0
            logger.info(f"[DASHBOARD] Real unread emails: {stats['unread_emails']}")
        except Exception as e:
            stats["errors"].append(f"Email error: {str(e)}")
            logger.error(f"[DASHBOARD] Email service error: {e}")
        
        # Get REAL today's events count (only upcoming, not past)
        try:
            import pytz
            calendar_service = CalendarService(config, credentials)
            
            # Use user's local timezone (Pacific Time) for accurate event counting
            user_tz = pytz.timezone('America/Los_Angeles')
            now_local = datetime.now(user_tz)
            today_end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=0)
            
            logger.info(f"[DASHBOARD] Fetching events from {now_local.isoformat()} to {today_end_local.isoformat()}")
            
            events = calendar_service.list_events(
                start_date=now_local.isoformat(),
                end_date=today_end_local.isoformat(),
                days_back=0,
                days_ahead=0,
                max_results=50
            )
            
            stats["todays_events"] = len(events) if events else 0
            logger.info(f"[DASHBOARD] Real upcoming events today: {stats['todays_events']}")
        except Exception as e:
            stats["errors"].append(f"Calendar error: {str(e)}")
            logger.error(f"[DASHBOARD] Calendar service error: {e}", exc_info=True)
        
        # Get REAL outstanding tasks count
        try:
            task_service = TaskService(config, credentials)
            tasks = task_service.list_tasks(status='pending', limit=100)
            stats["outstanding_tasks"] = len(tasks) if tasks else 0
            logger.info(f"[DASHBOARD] Real outstanding tasks: {stats['outstanding_tasks']}")
        except Exception as e:
            stats["errors"].append(f"Task error: {str(e)}")
            logger.error(f"[DASHBOARD] Task service error: {e}")
        
        logger.info(f"[DASHBOARD] Stats completed: emails={stats['unread_emails']}, events={stats['todays_events']}, tasks={stats['outstanding_tasks']}")
        return stats
        
    except Exception as e:
        logger.error(f"[DASHBOARD] Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch dashboard stats: {str(e)}"
        )


@router.get("/overview")
async def get_dashboard_overview(
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get detailed dashboard overview with additional insights
    
    Returns extended stats including:
    - Basic counts (emails, events, tasks)
    - Recent activity summaries
    - Service availability status
    """
    logger.info(f"[DASHBOARD] Fetching overview for user {current_user.id}")
    
    overview = {
        "user_info": {
            "id": current_user.id,
            "email": current_user.email,
            "name": getattr(current_user, 'name', None)
        },
        "stats": {},
        "services": {
            "email": {"available": False, "last_sync": None},
            "calendar": {"available": False, "last_sync": None}, 
            "tasks": {"available": False, "last_sync": None}
        },
        "recent_activity": {
            "recent_emails": [],
            "upcoming_events": [],
            "urgent_tasks": []
        },
        "last_updated": datetime.now().isoformat()
    }
    
    try:
        # Get basic stats first
        stats = await get_dashboard_stats(current_user, config, db)
        overview["stats"] = stats
        
        # Initialize credential factory
        credential_factory = CredentialFactory(config)
        
        # Get service availability and recent activity
        try:
            email_service = credential_factory.create_service('email', user_id=current_user.id, db_session=db)
            if email_service and email_service.gmail_client and email_service.gmail_client.is_available():
                overview["services"]["email"]["available"] = True
                
                # Get recent emails (last 5)
                recent_emails = email_service.search_emails(limit=5, folder="inbox")
                overview["recent_activity"]["recent_emails"] = [
                    {
                        "subject": email.get("subject", "No subject"),
                        "sender": email.get("sender", "Unknown"),
                        "date": email.get("date", ""),
                        "is_unread": email.get("labels", []).count("UNREAD") > 0
                    }
                    for email in recent_emails[:3]  # Just first 3 for overview
                ]
        except Exception as e:
            logger.error(f"[DASHBOARD] Email overview error: {e}")
        
        try:
            calendar_service = credential_factory.create_service('calendar', user_id=current_user.id, db_session=db)
            if calendar_service and calendar_service.calendar_client and calendar_service.calendar_client.is_available():
                overview["services"]["calendar"]["available"] = True
                
                # Get upcoming events (next few hours)
                upcoming_events = calendar_service.get_todays_events()
                overview["recent_activity"]["upcoming_events"] = [
                    {
                        "title": event.get("summary", "No title"),
                        "start": event.get("start", {}),
                        "location": event.get("location", "")
                    }
                    for event in upcoming_events[:3]  # Just first 3 for overview
                ]
        except Exception as e:
            logger.error(f"[DASHBOARD] Calendar overview error: {e}")
        
        try:
            task_service = credential_factory.create_service('task', user_id=current_user.id, db_session=db)
            if task_service and task_service.tasks_client and task_service.tasks_client.is_available():
                overview["services"]["tasks"]["available"] = True
                
                # Get urgent/due tasks
                urgent_tasks = task_service.list_tasks(status="needsAction", limit=5)
                overview["recent_activity"]["urgent_tasks"] = [
                    {
                        "title": task.get("title", "No title"),
                        "due": task.get("due", ""),
                        "notes": task.get("notes", "")[:100] + "..." if len(task.get("notes", "")) > 100 else task.get("notes", "")
                    }
                    for task in urgent_tasks[:3]  # Just first 3 for overview
                ]
        except Exception as e:
            logger.error(f"[DASHBOARD] Task overview error: {e}")
        
        return overview
        
    except Exception as e:
        logger.error(f"[DASHBOARD] Overview error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch dashboard overview: {str(e)}"
        )
@router.get("/briefs")
async def get_briefs(
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get dashboard briefs (Emails, Todos, Meetings, Reminders).
    
    Aggregates:
    - Emails: Unread & Important (summarized)
    - Todos: High priority from Tasks/Notion
    - Meetings: Today's schedule
    - Reminders: Proactive bills/appointments
    """
    from src.services.dashboard.brief_service import BriefService
    from src.core.credential_provider import CredentialFactory
    
    logger.info(f"[BRIEFS] Fetching briefs for user {current_user.id}")
    
    try:
        # Helper to initialize services via factory in a thread (since it involves sync DB ops)
        def init_services():
            factory = CredentialFactory(config)
            
            # Create services using factory (prioritizes UserIntegration -> falls back to Session)
            try:
                e_svc = factory.create_service('email', user_id=current_user.id, db_session=db)
            except Exception as e:
                logger.error(f"[BRIEFS] Failed to init EmailService: {e}")
                e_svc = None
                
            try:
                t_svc = factory.create_service('task', user_id=current_user.id, db_session=db)
            except Exception as e:
                logger.error(f"[BRIEFS] Failed to init TaskService: {e}")
                t_svc = None
                
            try:
                c_svc = factory.create_service('calendar', user_id=current_user.id, db_session=db)
            except Exception as e:
                logger.error(f"[BRIEFS] Failed to init CalendarService: {e}")
                c_svc = None
                
            return e_svc, t_svc, c_svc

        # Run sync initialization in thread pool
        loop = asyncio.get_event_loop()
        email_svc, task_svc, cal_svc = await loop.run_in_executor(None, init_services)

        # 3. Aggregation
        brief_service = BriefService(
            config=config,
            email_service=email_svc,
            task_service=task_svc,
            calendar_service=cal_svc
        )
        logger.info(f"[BRIEFS] BriefService created. Calendar Svc available: {cal_svc is not None}")
        
        briefs = await brief_service.get_dashboard_briefs(
            user_id=current_user.id,
            user_name=current_user.name or current_user.email.split('@')[0] if current_user.email else "there"
        )
        return briefs
        
    except Exception as e:
        logger.error(f"[BRIEFS] Error fetching briefs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch briefs: {str(e)}"
        )


from pydantic import BaseModel

class DraftReplyRequest(BaseModel):
    """Request for generating a draft reply"""
    email_id: str
    email_content: str
    email_subject: str
    sender_name: str
    sender_email: str


class AnalyzeEmailRequest(BaseModel):
    """Request for analyzing an email"""
    email_id: str
    email_content: str
    email_subject: str
    sender_name: str


@router.post("/draft-reply")
async def generate_draft_reply(
    request: DraftReplyRequest,
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Generate AI draft reply for an email.
    
    Returns a personalized draft reply in the user's writing style.
    """
    try:
        from src.features.auto_responder import EmailAutoResponder
        from src.database.models import UserWritingProfile
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession
        
        logger.info(f"[DRAFT] Generating draft reply for email {request.email_id}")
        
        # Get user's writing profile if available
        user_style = None
        try:
            from src.database import get_async_db_context
            async with get_async_db_context() as async_db:
                stmt = select(UserWritingProfile).where(
                    UserWritingProfile.user_id == current_user.id
                )
                result = await async_db.execute(stmt)
                profile = result.scalar_one_or_none()
                if profile:
                    user_style = profile.profile_data
                    logger.info(f"[DRAFT] Using writing profile for user {current_user.id}")
        except Exception as e:
            logger.warning(f"[DRAFT] Could not load writing profile: {e}")
        
        # Generate reply
        responder = EmailAutoResponder(config)
        replies = await responder.generate_reply(
            email_content=request.email_content,
            email_subject=request.email_subject,
            sender_name=request.sender_name,
            sender_email=request.sender_email,
            user_style=user_style,
            num_options=1  # Just one primary draft
        )
        
        primary_reply = replies[0] if replies else {"tone": "friendly", "content": ""}
        
        return {
            "success": True,
            "draft": primary_reply.get("content", ""),
            "tone": primary_reply.get("tone", "friendly"),
            "style_match_score": primary_reply.get("style_match_score"),
            "email_id": request.email_id
        }
        
    except Exception as e:
        logger.error(f"[DRAFT] Error generating draft: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate draft: {str(e)}"
        )


@router.post("/analyze-email")
async def analyze_email(
    request: AnalyzeEmailRequest,
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config)
) -> Dict[str, Any]:
    """
    Analyze an email for sentiment, priority, and suggested actions.
    """
    try:
        from src.ai.llm_factory import LLMFactory
        
        logger.info(f"[ANALYZE] Analyzing email {request.email_id}")
        
        llm = LLMFactory.create_chat_model(config)
        
        prompt = f"""Analyze this email and provide a JSON response with:
- sentiment: "positive", "negative", or "neutral"
- priority: "high", "medium", or "low"
- requires_reply: true/false
- summary: 1-2 sentence summary
- suggested_action: what the user should do

EMAIL:
Subject: {request.email_subject}
From: {request.sender_name}
Content: {request.email_content}

Respond with valid JSON only:"""

        response = await llm.ainvoke(prompt)
        content = response.content if hasattr(response, 'content') else str(response)
        
        # Try to parse as JSON
        import json
        try:
            analysis = json.loads(content)
        except json.JSONDecodeError:
            # Fallback analysis
            analysis = {
                "sentiment": "neutral",
                "priority": "medium",
                "requires_reply": True,
                "summary": "Email from " + request.sender_name,
                "suggested_action": "Review and respond if needed"
            }
        
        return {
            "success": True,
            "email_id": request.email_id,
            "analysis": analysis
        }
        
    except Exception as e:
        logger.error(f"[ANALYZE] Error analyzing email: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze email: {str(e)}"
        )
