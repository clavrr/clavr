"""
Authentication Audit Logging Service

Provides comprehensive audit logging for all authentication events
to support security monitoring, compliance, and forensic analysis.
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import Request

from ..database.models import AuditLog
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


# Event type constants
class AuditEventType:
    """Standard audit event types"""
    # Authentication events
    LOGIN_ATTEMPT = "login_attempt"
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGOUT = "logout"
    
    # Session events
    SESSION_CREATED = "session_created"
    SESSION_EXPIRED = "session_expired"
    SESSION_REVOKED = "session_revoked"
    SESSION_TOKEN_ROTATED = "session_token_rotated"
    
    # Token events
    TOKEN_REFRESH_SUCCESS = "token_refresh_success"
    TOKEN_REFRESH_FAILURE = "token_refresh_failure"
    
    # OAuth events
    OAUTH_CALLBACK_SUCCESS = "oauth_callback_success"
    OAUTH_CALLBACK_FAILURE = "oauth_callback_failure"
    
    # Admin events
    ADMIN_ACTION = "admin_action"
    USER_SETTINGS_UPDATED = "user_settings_updated"
    
    # Security events
    UNAUTHORIZED_ACCESS_ATTEMPT = "unauthorized_access_attempt"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"


async def log_auth_event(
    db,  # Can be Session or AsyncSession
    event_type: str,
    user_id: Optional[int] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    request: Optional[Request] = None,
    **extra_data
) -> AuditLog:
    """
    Log an authentication or security event
    
    Args:
        db: Database session
        event_type: Type of event (use AuditEventType constants)
        user_id: User ID (None for events before authentication)
        success: Whether the event was successful
        error_message: Error message if event failed
        request: FastAPI request object (to extract IP and user-agent)
        **extra_data: Additional event-specific data
        
    Returns:
        Created AuditLog record
        
    Example:
        >>> log_auth_event(
        ...     db=db,
        ...     event_type=AuditEventType.LOGIN_SUCCESS,
        ...     user_id=1,
        ...     success=True,
        ...     request=request,
        ...     oauth_provider='google'
        ... )
    """
    # Extract request metadata
    ip_address = None
    user_agent = None
    
    if request:
        ip_address = request.client.host if hasattr(request, 'client') else None
        user_agent = request.headers.get('user-agent') if hasattr(request, 'headers') else None
    
    # Create audit log entry
    audit_log = AuditLog(
        user_id=user_id,
        event_type=event_type,
        event_data=extra_data if extra_data else None,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
        error_message=error_message
    )
    
    db.add(audit_log)
    
    # Handle both sync and async sessions
    try:
        await db.commit()
        await db.refresh(audit_log)
    except TypeError:
        # Sync session - commit/refresh not awaitable
        db.commit()
        db.refresh(audit_log)
    
    # Also log to application logs
    log_level = logging.INFO if success else logging.WARNING
    logger.log(
        log_level,
        f"[AUDIT] {event_type} - user_id={user_id}, success={success}, "
        f"ip={ip_address}, data={extra_data}"
    )
    
    return audit_log


def get_user_audit_logs(
    db: Session,
    user_id: int,
    event_type: Optional[str] = None,
    limit: int = 100
) -> list:
    """
    Get audit logs for a specific user
    
    Args:
        db: Database session
        user_id: User ID
        event_type: Filter by event type (optional)
        limit: Maximum number of records to return
        
    Returns:
        List of AuditLog records
    """
    query = db.query(AuditLog).filter(AuditLog.user_id == user_id)
    
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)
    
    return query.order_by(AuditLog.created_at.desc()).limit(limit).all()


def get_failed_login_attempts(
    db: Session,
    ip_address: Optional[str] = None,
    user_id: Optional[int] = None,
    hours: int = 1
) -> list:
    """
    Get failed login attempts within a time window
    
    Useful for detecting brute force attacks
    
    Args:
        db: Database session
        ip_address: Filter by IP address (optional)
        user_id: Filter by user ID (optional)
        hours: Time window in hours
        
    Returns:
        List of AuditLog records for failed logins
    """
    from datetime import timedelta
    
    cutoff_time = datetime.utcnow() - timedelta(hours=hours)
    
    query = db.query(AuditLog).filter(
        AuditLog.event_type == AuditEventType.LOGIN_FAILURE,
        AuditLog.created_at >= cutoff_time
    )
    
    if ip_address:
        query = query.filter(AuditLog.ip_address == ip_address)
    
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    
    return query.order_by(AuditLog.created_at.desc()).all()


def get_security_summary(db: Session, hours: int = 24) -> Dict[str, Any]:
    """
    Get security event summary for the last N hours
    
    Args:
        db: Database session
        hours: Time window in hours
        
    Returns:
        Dictionary with security metrics
    """
    from datetime import timedelta
    from sqlalchemy import func
    
    cutoff_time = datetime.utcnow() - timedelta(hours=hours)
    
    # Count events by type
    event_counts = db.query(
        AuditLog.event_type,
        AuditLog.success,
        func.count(AuditLog.id).label('count')
    ).filter(
        AuditLog.created_at >= cutoff_time
    ).group_by(
        AuditLog.event_type,
        AuditLog.success
    ).all()
    
    # Count failed logins by IP
    failed_by_ip = db.query(
        AuditLog.ip_address,
        func.count(AuditLog.id).label('count')
    ).filter(
        AuditLog.event_type == AuditEventType.LOGIN_FAILURE,
        AuditLog.created_at >= cutoff_time,
        AuditLog.ip_address.isnot(None)
    ).group_by(
        AuditLog.ip_address
    ).order_by(
        func.count(AuditLog.id).desc()
    ).limit(10).all()
    
    return {
        'time_window_hours': hours,
        'event_counts': [
            {'event_type': e[0], 'success': e[1], 'count': e[2]}
            for e in event_counts
        ],
        'failed_logins_by_ip': [
            {'ip_address': ip, 'count': count}
            for ip, count in failed_by_ip
        ]
    }
