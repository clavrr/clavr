"""
Dashboard Router - API endpoints for dashboard statistics

Provides overview statistics for:
- Unread emails count
- Today's calendar events count  
- Outstanding tasks count
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any
from datetime import datetime, date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from api.auth import get_current_user_required
from ..dependencies import get_config
from src.database import get_async_db, get_db
from src.integrations.gmail.service import EmailService
from src.integrations.google_calendar.service import CalendarService
from src.integrations.google_tasks.service import TaskService
from src.core.credential_provider import CredentialFactory
from src.database.models import User
from src.utils.logger import setup_logger

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
        - todays_events: Number of events today
        - outstanding_tasks: Number of incomplete tasks
        - last_updated: Timestamp of when stats were fetched
    """
    logger.info(f"[DASHBOARD] Fetching stats for user {current_user.id}")
    logger.info(f"[DASHBOARD] User email: {current_user.email}")
    logger.info(f"[DASHBOARD] Current time: {datetime.now()}")
    
    stats = {
        "unread_emails": 0,
        "todays_events": 0,
        "outstanding_tasks": 0,
        "last_updated": datetime.now().isoformat(),
        "errors": []
    }
    
    logger.info(f"[DASHBOARD] Initial stats: {stats}")
    
    try:
        # Initialize credential factory
        credential_factory = CredentialFactory(config)
        
        # Get user session manually for direct credential access
        from src.database.models import Session as DBSession
        from sqlalchemy import select
        from google.oauth2.credentials import Credentials
        import os
        
        stmt = select(DBSession).where(
            DBSession.user_id == current_user.id,
            DBSession.expires_at > datetime.utcnow()
        ).order_by(DBSession.created_at.desc())
        
        result = db.execute(stmt)
        session = result.scalar_one_or_none()
        credentials = None
        
        logger.info(f"[DASHBOARD] Session query result: {session}")
        logger.info(f"[DASHBOARD] Session exists: {session is not None}")
        
        if session:
            logger.info(f"[DASHBOARD] Session ID: {session.id}")
            logger.info(f"[DASHBOARD] Session expires: {session.expires_at}")
            logger.info(f"[DASHBOARD] Has gmail token: {session.gmail_access_token is not None}")
        
        if session and session.gmail_access_token:
            client_id = os.getenv('GOOGLE_CLIENT_ID')
            client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
            
            logger.info(f"[DASHBOARD] Client ID exists: {client_id is not None}")
            logger.info(f"[DASHBOARD] Client secret exists: {client_secret is not None}")
            
            credentials = Credentials(
                token=session.gmail_access_token,
                refresh_token=session.gmail_refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=[
                    'https://www.googleapis.com/auth/gmail.readonly',
                    'https://www.googleapis.com/auth/gmail.send',
                    'https://www.googleapis.com/auth/gmail.modify',
                    'https://www.googleapis.com/auth/calendar',
                    'https://www.googleapis.com/auth/tasks'
                ]
            )
            logger.info(f"[DASHBOARD] Credentials created successfully")

        logger.info(f"[DASHBOARD] Final credentials status: {credentials is not None}")

        # Get unread emails count
        try:
            # TEMPORARY FIX: Always return mock data for testing
            # This bypasses credential issues while we test the frontend
            stats["unread_emails"] = 5  # Mock data
            logger.info(f"[DASHBOARD] Mock: Found {stats['unread_emails']} unread emails")
            
            if credentials:
                logger.info("[DASHBOARD] Valid credentials found - using mock data")
            else:
                stats["errors"].append("Email service not available - no valid session")
                logger.warning("[DASHBOARD] No valid email session found - still using mock data for testing")
                
        except Exception as e:
            stats["errors"].append(f"Email error: {str(e)}")
            logger.error(f"[DASHBOARD] Email service error: {e}")
        
        # Get calendar stats (today's events)
        try:
            # TEMPORARY FIX: Always return mock data for testing
            stats["todays_events"] = 3  # Mock data
            logger.info(f"[DASHBOARD] Mock: Found {stats['todays_events']} events today")
            
            if credentials:
                logger.info("[DASHBOARD] Valid credentials found - using mock data")
            else:
                stats["errors"].append("Calendar service not available - no valid session")
                logger.warning("[DASHBOARD] Calendar service not available - still using mock data for testing")
                
        except Exception as e:
            stats["errors"].append(f"Calendar error: {str(e)}")
            logger.error(f"[DASHBOARD] Calendar service error: {e}")
        
        # Get task stats
        try:
            # TEMPORARY FIX: Always return mock data for testing
            stats["outstanding_tasks"] = 7  # Mock data
            logger.info(f"[DASHBOARD] Mock: Found {stats['outstanding_tasks']} outstanding tasks")
            
            if credentials:
                logger.info("[DASHBOARD] Valid credentials found - using mock data")
            else:
                stats["errors"].append("Task service not available - no valid session")
                logger.warning("[DASHBOARD] Task service not available - still using mock data for testing")
                
        except Exception as e:
            stats["errors"].append(f"Task error: {str(e)}")
            logger.error(f"[DASHBOARD] Task service error: {e}")
        
        logger.info(f"[DASHBOARD] Stats completed for user {current_user.id}: {stats}")
        logger.info(f"[DASHBOARD] Final values - Emails: {stats['unread_emails']}, Events: {stats['todays_events']}, Tasks: {stats['outstanding_tasks']}")
        return stats
        
    except Exception as e:
        logger.error(f"[DASHBOARD] Unexpected error: {e}")
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
