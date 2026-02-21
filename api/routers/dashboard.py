"""
Dashboard Router - API endpoints for dashboard statistics

Provides overview statistics for:
- Unread emails count
- Today's calendar events count  
- Outstanding tasks count
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, Optional
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

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


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
            unread_emails = await asyncio.to_thread(email_service.list_unread_emails, limit=100)
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
            
            events = await asyncio.to_thread(
                calendar_service.list_events,
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
            tasks = await asyncio.to_thread(task_service.list_tasks, status='pending', limit=100)
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


# ============================================
# REVENUE DASHBOARD ROUTES
# ============================================

@router.get("/pipeline")
async def get_pipeline(
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Get active deal pipeline for the current user."""
    from api.dependencies import AppState

    try:
        pipeline_svc = AppState.get_pipeline_service(db_session=db)
        deals = await pipeline_svc.get_pipeline(current_user.id)
        return {
            "success": True,
            "deals": [d.to_dict() for d in deals],
            "total": len(deals),
        }
    except Exception as e:
        logger.error(f"[PIPELINE] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pipeline/stale")
async def get_stale_deals(
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config),
    db: Session = Depends(get_db),
    days: int = 7
) -> Dict[str, Any]:
    """Get deals with no activity in the last N days."""
    from api.dependencies import AppState

    try:
        pipeline_svc = AppState.get_pipeline_service(db_session=db)
        stale = await pipeline_svc.get_stale_deals(current_user.id, stale_days=days)
        return {
            "success": True,
            "stale_deals": [d.to_dict() for d in stale],
            "total": len(stale),
        }
    except Exception as e:
        logger.error(f"[PIPELINE] Stale deals error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pipeline/{deal_name}")
async def get_deal_detail(
    deal_name: str,
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Get deep detail for a specific deal with cross-stack context."""
    from api.dependencies import AppState

    try:
        pipeline_svc = AppState.get_pipeline_service(db_session=db)
        detail = await pipeline_svc.get_deal_detail(deal_name, current_user.id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Deal '{deal_name}' not found")
        return {"success": True, **detail}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[PIPELINE] Deal detail error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/accounts")
async def get_customer_health(
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config),
    db: Session = Depends(get_db),
    threshold: float = 40.0
) -> Dict[str, Any]:
    """Get customer health scores, filtered to at-risk accounts."""
    from api.dependencies import AppState

    try:
        health_svc = AppState.get_customer_health_service(db_session=db)
        at_risk = await health_svc.get_at_risk_accounts(current_user.id, threshold=threshold)
        return {
            "success": True,
            "at_risk_accounts": [h.to_dict() for h in at_risk],
            "total_at_risk": len(at_risk),
            "threshold": threshold,
        }
    except Exception as e:
        logger.error(f"[HEALTH] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/meeting-roi")
async def get_meeting_roi(
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config),
    db: Session = Depends(get_db),
    date: Optional[str] = None
) -> Dict[str, Any]:
    """Get meeting ROI scores for a given day."""
    from api.dependencies import AppState

    try:
        roi_svc = AppState.get_meeting_roi_service(db_session=db)
        summary = await roi_svc.score_day(current_user.id, date)
        return {"success": True, **summary.to_dict()}
    except Exception as e:
        logger.error(f"[MEETING_ROI] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/meeting-roi/declines")
async def get_decline_suggestions(
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config),
    db: Session = Depends(get_db),
    date: Optional[str] = None
) -> Dict[str, Any]:
    """Get low-ROI meetings that could be declined."""
    from api.dependencies import AppState

    try:
        roi_svc = AppState.get_meeting_roi_service(db_session=db)
        suggestions = await roi_svc.suggest_declines(current_user.id, date)
        return {
            "success": True,
            "suggestions": [s.to_dict() for s in suggestions],
            "total": len(suggestions),
        }
    except Exception as e:
        logger.error(f"[MEETING_ROI] Decline suggestions error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/follow-ups")
async def get_follow_ups(
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config),
) -> Dict[str, Any]:
    """Get active follow-up tracked threads and stats."""
    from api.dependencies import AppState

    try:
        tracker = AppState.get_follow_up_tracker()
        active = tracker.get_active(current_user.id)
        stats = tracker.get_stats(current_user.id)
        return {
            "success": True,
            "active_threads": [t.to_dict() for t in active],
            "stats": stats,
        }
    except Exception as e:
        logger.error(f"[FOLLOW_UP] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/time-allocation")
async def get_time_allocation(
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config),
    db: Session = Depends(get_db),
    week_start: Optional[str] = None
) -> Dict[str, Any]:
    """Get time allocation report for a given week."""
    from api.dependencies import AppState

    try:
        from src.services.time_allocation import TimeAllocationService
        time_svc = TimeAllocationService(config=config, db_session=db)
        report = await time_svc.analyze_week(current_user.id, week_start)
        return {"success": True, **report.to_dict()}
    except Exception as e:
        logger.error(f"[TIME_ALLOC] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/velocity")
async def get_sprint_velocity(
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config),
) -> Dict[str, Any]:
    """Get sprint velocity trend and recommendations."""
    from src.services.sprint_velocity import SprintVelocityService

    try:
        velocity_svc = SprintVelocityService(config=config)
        trend = velocity_svc.get_velocity_trend(current_user.id)
        recs = velocity_svc.get_recommendations(current_user.id)
        return {
            "success": True,
            "trend": trend.to_dict(),
            "recommendations": recs,
        }
    except Exception as e:
        logger.error(f"[VELOCITY] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

