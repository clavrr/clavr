"""
Admin Endpoints - User Management & Platform Administration
Admin-only access required for all endpoints
"""
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, desc, text, or_, select

from api.dependencies import get_current_user
from src.auth import get_admin_user, log_auth_event, AuditEventType
from src.database import get_async_db
from src.database.models import User, Session as DBSession, BlogPost, ConversationMessage
from src.utils.logger import setup_logger
from fastapi import Request

logger = setup_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ============================================
# REQUEST/RESPONSE MODELS
# ============================================

class UserSummary(BaseModel):
    """User summary for admin views"""
    id: int
    email: str
    name: Optional[str]
    is_admin: bool
    created_at: datetime
    email_indexed: bool
    indexing_status: str
    index_count: int
    
    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """Paginated user list response"""
    users: List[UserSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


class UserDetail(UserSummary):
    """Detailed user information"""
    picture_url: Optional[str]
    indexing_started_at: Optional[datetime]
    indexing_completed_at: Optional[datetime]
    last_email_synced_at: Optional[datetime]
    collection_name: Optional[str]
    active_sessions: int = 0


class PlatformStats(BaseModel):
    """Platform-wide statistics"""
    total_users: int
    active_users_30d: int
    admin_users: int
    total_blog_posts: int
    published_blog_posts: int
    total_conversations: int
    users_with_indexed_emails: int
    average_index_count: float


class AdminUserUpdate(BaseModel):
    """Schema for updating user admin status"""
    is_admin: bool


# ============================================
# USER MANAGEMENT ENDPOINTS
# ============================================

@router.get("/users", response_model=UserListResponse)
async def list_users(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by email or name (case-insensitive partial match)"),
    admin_only: bool = Query(False, description="Filter to admin users only"),
    db: AsyncSession = Depends(get_async_db),
    admin: User = Depends(get_admin_user)
):
    """
    List all users with pagination and search (admin only)
    """
    try:
        # Log admin activity
        await log_auth_event(
            db=db,
            event_type=AuditEventType.ADMIN_ACTION,
            user_id=admin.id,
            request=request,
            action="list_users",
            details={"page": page, "search": search, "admin_only": admin_only}
        )
        
        stmt = select(User)
        
        # Filter by admin status
        if admin_only:
            stmt = stmt.where(User.is_admin == True)
        
        # Search filter (case-insensitive partial match)
        if search and search.strip():
            search_term = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    User.email.ilike(search_term),
                    User.name.ilike(search_term)
                )
            )
            logger.debug(f"Applied search filter: '{search_term}'")
        
        # Get total count before pagination
        count_stmt = select(func.count()).select_from(User)
        if admin_only:
            count_stmt = count_stmt.where(User.is_admin == True)
        if search and search.strip():
            search_term = f"%{search.strip()}%"
            count_stmt = count_stmt.where(
                or_(
                    User.email.ilike(search_term),
                    User.name.ilike(search_term)
                )
            )
        result = await db.execute(count_stmt)
        total = result.scalar_one()
        
        # Calculate total pages
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        
        # Apply pagination and ordering
        stmt = stmt.order_by(desc(User.created_at))\
                    .offset((page - 1) * page_size)\
                    .limit(page_size)
        
        result = await db.execute(stmt)
        users = result.scalars().all()
        
        # Convert to response models
        user_summaries = [UserSummary.model_validate(user) for user in users]
        
        logger.info(f"Admin {admin.email} listed users: page={page}, total={total}, search='{search}', admin_only={admin_only}")
        
        return UserListResponse(
            users=user_summaries,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )
        
    except Exception as e:
        logger.error(f"Error listing users: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list users: {str(e)}"
        )


@router.get("/users/{user_id}", response_model=UserDetail)
async def get_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    admin: User = Depends(get_admin_user)
):
    """
    Get detailed user information (admin only)
    """
    try:
        # Log admin activity
        await log_auth_event(
            db=db,
            event_type=AuditEventType.ADMIN_ACTION,
            user_id=admin.id,
            request=request,
            action="get_user_details",
            target_user_id=user_id
        )
        
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found"
            )
        
        # Count active sessions
        count_stmt = select(func.count()).select_from(DBSession).where(
            DBSession.user_id == user_id,
            DBSession.expires_at > datetime.utcnow()
        )
        result = await db.execute(count_stmt)
        active_sessions = result.scalar_one()
        
        user_detail = UserDetail.model_validate(user)
        user_detail.active_sessions = active_sessions
        
        return user_detail
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user: {str(e)}"
        )


@router.get("/users/count", response_model=dict)
async def get_user_count(
    db: AsyncSession = Depends(get_async_db),
    admin: User = Depends(get_admin_user)
):
    """
    Get user count statistics (admin only)
    """
    try:
        # Total users
        total_stmt = select(func.count()).select_from(User)
        result = await db.execute(total_stmt)
        total_users = result.scalar_one()
        
        # Admin users
        admin_stmt = select(func.count()).select_from(User).where(User.is_admin == True)
        result = await db.execute(admin_stmt)
        admin_users = result.scalar_one()
        
        regular_users = total_users - admin_users
        
        # Active users (logged in within last 30 days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        active_stmt = select(func.count(func.distinct(DBSession.user_id)))\
                        .select_from(DBSession)\
                        .where(DBSession.created_at >= thirty_days_ago)
        result = await db.execute(active_stmt)
        active_users = result.scalar_one()
        
        # Users with indexed emails
        indexed_stmt = select(func.count()).select_from(User).where(User.email_indexed == True)
        result = await db.execute(indexed_stmt)
        users_with_indexed = result.scalar_one()
        
        return {
            "total_users": total_users,
            "admin_users": admin_users,
            "regular_users": regular_users,
            "active_users_30d": active_users,
            "users_with_indexed_emails": users_with_indexed
        }
        
    except Exception as e:
        logger.error(f"Error getting user count: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user count: {str(e)}"
        )


@router.put("/users/{user_id}/admin", response_model=UserSummary)
async def update_user_admin_status(
    user_id: int,
    update: AdminUserUpdate,
    db: AsyncSession = Depends(get_async_db),
    admin: User = Depends(get_admin_user)
):
    """
    Update user admin status (admin only)
    
    **WARNING**: Use with caution. Granting admin access gives full platform control.
    """
    try:
        # Prevent self-demotion (at least one admin must remain)
        if user_id == admin.id and not update.is_admin:
            # Check if there are other admins
            other_admins_stmt = select(func.count()).select_from(User).where(
                User.is_admin == True,
                User.id != user_id
            )
            result = await db.execute(other_admins_stmt)
            other_admins = result.scalar_one()
            
            if other_admins == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot remove admin status: At least one admin must exist"
                )
        
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found"
            )
        
        user.is_admin = update.is_admin
        await db.commit()
        await db.refresh(user)
        
        # Log critical admin action
        await log_auth_event(
            db=db,
            event_type=AuditEventType.ADMIN_ACTION,
            user_id=admin.id,
            request=request,
            action="update_admin_status",
            target_user_id=user_id,
            target_user_email=user.email,
            new_status=update.is_admin
        )
        
        logger.warning(f"Admin {admin.email} updated admin status for user {user.email}: {update.is_admin}")
        
        return UserSummary.model_validate(user)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user admin status: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user admin status: {str(e)}"
        )


@router.delete("/users/{user_id}/sessions", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_user_sessions(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    admin: User = Depends(get_admin_user)
):
    """
    Revoke all sessions for a user (force logout) (admin only)
    """
    try:
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found"
            )
        
        sessions_stmt = select(DBSession).where(DBSession.user_id == user_id)
        result = await db.execute(sessions_stmt)
        sessions = result.scalars().all()
        count = len(sessions)
        
        for session in sessions:
            await db.delete(session)
        
        await db.commit()
        
        # Log critical admin action
        await log_auth_event(
            db=db,
            event_type=AuditEventType.ADMIN_ACTION,
            user_id=admin.id,
            request=request,
            action="revoke_sessions",
            target_user_id=user_id,
            target_user_email=user.email,
            session_count=count
        )
        
        logger.warning(f"Admin {admin.email} revoked {count} sessions for user {user.email}")
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error revoking user sessions: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revoke user sessions: {str(e)}"
        )


# ============================================
# PLATFORM STATISTICS ENDPOINTS
# ============================================

@router.get("/stats", response_model=PlatformStats)
async def get_platform_stats(
    db: AsyncSession = Depends(get_async_db),
    admin: User = Depends(get_admin_user)
):
    """
    Get platform-wide statistics (admin only)
    
    Returns comprehensive platform metrics including:
    - User counts and activity
    - Blog post statistics
    - Email indexing metrics
    - Conversation counts
    """
    try:
        # User statistics
        total_users_stmt = select(func.count()).select_from(User)
        result = await db.execute(total_users_stmt)
        total_users = result.scalar_one()
        
        admin_users_stmt = select(func.count()).select_from(User).where(User.is_admin == True)
        result = await db.execute(admin_users_stmt)
        admin_users = result.scalar_one()
        
        # Active users (sessions in last 30 days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        active_users_stmt = select(func.count(func.distinct(DBSession.user_id)))\
                            .select_from(DBSession)\
                            .where(DBSession.created_at >= thirty_days_ago)
        result = await db.execute(active_users_stmt)
        active_users_30d = result.scalar_one()
        
        # Email indexing statistics
        indexed_stmt = select(func.count()).select_from(User).where(User.email_indexed == True)
        result = await db.execute(indexed_stmt)
        users_with_indexed_emails = result.scalar_one()
        
        avg_stmt = select(func.avg(User.index_count))
        result = await db.execute(avg_stmt)
        avg_index_count = result.scalar() or 0.0
        
        # Blog statistics
        total_blog_stmt = select(func.count()).select_from(BlogPost)
        result = await db.execute(total_blog_stmt)
        total_blog_posts = result.scalar_one()
        
        published_blog_stmt = select(func.count()).select_from(BlogPost).where(BlogPost.is_published == True)
        result = await db.execute(published_blog_stmt)
        published_blog_posts = result.scalar_one()
        
        # Conversation statistics
        conv_stmt = select(func.count(func.distinct(ConversationMessage.session_id)))\
                    .select_from(ConversationMessage)
        result = await db.execute(conv_stmt)
        total_conversations = result.scalar_one()
        
        return PlatformStats(
            total_users=total_users,
            active_users_30d=active_users_30d,
            admin_users=admin_users,
            total_blog_posts=total_blog_posts,
            published_blog_posts=published_blog_posts,
            total_conversations=total_conversations,
            users_with_indexed_emails=users_with_indexed_emails,
            average_index_count=round(float(avg_index_count), 2)
        )
        
    except Exception as e:
        logger.error(f"Error getting platform stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get platform stats: {str(e)}"
        )


@router.get("/health/detailed", response_model=dict)
async def get_detailed_health(
    db: AsyncSession = Depends(get_async_db),
    admin: User = Depends(get_admin_user)
):
    """
    Get detailed platform health information (admin only)
    
    Includes database connectivity, user activity, and system status.
    """
    try:
        from src.utils.config import load_config, Config
        from src.ai.rag import RAGEngine
        from ..dependencies import AppState
        
        config = load_config("config/config.yaml")
        rag_available = False
        
        try:
            # Use cached RAG engine from AppState
            rag = AppState.get_rag_engine()
            rag_available = True
        except Exception:
            pass
        
        # Database health
        db_healthy = False
        try:
            await db.execute(text("SELECT 1"))
            db_healthy = True
        except Exception:
            pass
        
        # Recent activity (last 24 hours)
        twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
        
        recent_sessions_stmt = select(func.count()).select_from(DBSession).where(
            DBSession.created_at >= twenty_four_hours_ago
        )
        result = await db.execute(recent_sessions_stmt)
        recent_sessions = result.scalar_one()
        
        recent_conv_stmt = select(func.count()).select_from(ConversationMessage).where(
            ConversationMessage.timestamp >= twenty_four_hours_ago
        )
        result = await db.execute(recent_conv_stmt)
        recent_conversations = result.scalar_one()
        
        # Total counts
        total_users_stmt = select(func.count()).select_from(User)
        result = await db.execute(total_users_stmt)
        total_users = result.scalar_one()
        
        total_sessions_stmt = select(func.count()).select_from(DBSession)
        result = await db.execute(total_sessions_stmt)
        total_sessions = result.scalar_one()
        
        return {
            "status": "healthy" if db_healthy and rag_available else "degraded",
            "database": {
                "connected": db_healthy,
                "total_users": total_users,
                "total_sessions": total_sessions
            },
            "rag": {
                "available": rag_available
            },
            "activity_24h": {
                "new_sessions": recent_sessions,
                "conversations": recent_conversations
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting detailed health: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get detailed health: {str(e)}"
        )


# ============================================
# PROFILE SERVICE MONITORING
# ============================================

@router.get("/profile-service/stats")
async def get_profile_service_stats(
    admin: User = Depends(get_admin_user)
):
    """
    Get profile update service statistics (admin only)
    
    **Returns:**
    - Service status (running/stopped)
    - Total profiles count
    - Stale profiles count
    - Profiles needing refresh
    - Service configuration
    
    **Use Cases:**
    - Monitor background service health
    - Identify profiles needing attention
    - Tune service parameters
    """
    try:
        from src.services.profile_service import get_profile_service
        
        service = get_profile_service()
        stats = await service.get_service_stats()
        
        return {
            "success": True,
            "stats": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting profile service stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get profile service stats: {str(e)}"
        )


@router.post("/profile-service/trigger-update")
async def trigger_profile_update(
    admin: User = Depends(get_admin_user)
):
    """
    Manually trigger profile update cycle (admin only)
    
    **Action:**
    Immediately starts a profile update cycle, updating up to
    max_updates_per_run stale profiles.
    
    **Returns:**
    - Number of profiles updated
    - Update results
    """
    try:
        from src.services.profile_service import get_profile_service
        
        service = get_profile_service()
        updated_count = await service.update_stale_profiles()
        
        return {
            "success": True,
            "updated_count": updated_count,
            "message": f"Updated {updated_count} profiles",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error triggering profile update: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger profile update: {str(e)}"
        )


@router.post("/profile-service/mark-refresh/{user_id}")
async def mark_user_profile_for_refresh(
    user_id: int,
    admin: User = Depends(get_admin_user)
):
    """
    Mark a specific user's profile for refresh (admin only)
    
    **Args:**
    - user_id: ID of user whose profile should be refreshed
    
    **Action:**
    Sets the needs_refresh flag on the profile, which will cause it
    to be updated in the next update cycle.
    
    **Returns:**
    - Success status
    - Confirmation message
    """
    try:
        from src.services.profile_service import get_profile_service
        
        service = get_profile_service()
        success = await service.mark_profile_for_refresh(user_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No profile found for user {user_id}"
            )
        
        return {
            "success": True,
            "message": f"Profile for user {user_id} marked for refresh",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking profile for refresh: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark profile for refresh: {str(e)}"
        )

