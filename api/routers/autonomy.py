"""
Autonomy API Router

Endpoints for managing autonomy settings and autonomous actions.
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.database import get_async_db as get_db
from src.database.models import User, AutonomySettings, AutonomousAction
from src.ai.autonomy.action_executor import ActionExecutor, ExecutionResult
from src.ai.autonomy.autonomy_defaults import (
    ActionType,
    AutonomyLevel, 
    DEFAULT_AUTONOMY_LEVELS,
    get_default_autonomy_level,
)
from src.utils.logger import setup_logger
from api.dependencies import get_current_user_required

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/autonomy", tags=["autonomy"])


# ==================== Request/Response Models ====================

class AutonomySettingUpdate(BaseModel):
    """Request model for updating autonomy settings."""
    autonomy_level: str = Field(..., description="One of: high, medium, low")
    require_notification: bool = True
    require_confirmation: bool = False


class AutonomySettingResponse(BaseModel):
    """Response model for autonomy setting."""
    action_type: str
    autonomy_level: str
    require_notification: bool
    require_confirmation: bool
    is_default: bool = False  # True if using system default
    
    class Config:
        from_attributes = True


class AutonomousActionResponse(BaseModel):
    """Response model for autonomous action."""
    id: int
    action_type: str
    description: Optional[str]
    status: str
    autonomy_level_used: Optional[str]
    created_at: datetime
    executed_at: Optional[datetime]
    undo_available: bool = False
    requires_approval: bool = False
    
    class Config:
        from_attributes = True


class ActionApprovalRequest(BaseModel):
    """Request model for approving/rejecting action."""
    reason: Optional[str] = None


# ==================== Settings Endpoints ====================

@router.get("/settings", response_model=List[AutonomySettingResponse])
async def get_autonomy_settings(
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all autonomy settings for the current user.
    
    Returns both user-configured settings and defaults for unconfigured action types.
    """
    # Get user's configured settings
    stmt = select(AutonomySettings).where(AutonomySettings.user_id == user.id)
    result = await db.execute(stmt)
    user_settings = {s.action_type: s for s in result.scalars().all()}
    
    # Build response with defaults for missing types
    response = []
    for action_type in ActionType:
        if action_type.value in user_settings:
            setting = user_settings[action_type.value]
            response.append(AutonomySettingResponse(
                action_type=action_type.value,
                autonomy_level=setting.autonomy_level,
                require_notification=setting.require_notification,
                require_confirmation=setting.require_confirmation,
                is_default=False,
            ))
        else:
            # Return default setting
            response.append(AutonomySettingResponse(
                action_type=action_type.value,
                autonomy_level=get_default_autonomy_level(action_type.value),
                require_notification=True,
                require_confirmation=False,
                is_default=True,
            ))
    
    return response


@router.get("/settings/{action_type}", response_model=AutonomySettingResponse)
async def get_autonomy_setting(
    action_type: str,
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Get autonomy setting for a specific action type."""
    # Validate action type
    valid_types = [a.value for a in ActionType]
    if action_type not in valid_types:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid action type. Valid types: {valid_types}"
        )
    
    # Get user's setting
    stmt = select(AutonomySettings).where(
        AutonomySettings.user_id == user.id,
        AutonomySettings.action_type == action_type
    )
    result = await db.execute(stmt)
    setting = result.scalar_one_or_none()
    
    if setting:
        return AutonomySettingResponse(
            action_type=action_type,
            autonomy_level=setting.autonomy_level,
            require_notification=setting.require_notification,
            require_confirmation=setting.require_confirmation,
            is_default=False,
        )
    
    # Return default
    return AutonomySettingResponse(
        action_type=action_type,
        autonomy_level=get_default_autonomy_level(action_type),
        require_notification=True,
        require_confirmation=False,
        is_default=True,
    )


@router.put("/settings/{action_type}", response_model=AutonomySettingResponse)
async def update_autonomy_setting(
    action_type: str,
    update: AutonomySettingUpdate,
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Update autonomy setting for a specific action type."""
    # Validate action type
    valid_types = [a.value for a in ActionType]
    if action_type not in valid_types:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid action type. Valid types: {valid_types}"
        )
    
    # Validate autonomy level
    valid_levels = [l.value for l in AutonomyLevel]
    if update.autonomy_level not in valid_levels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid autonomy level. Valid levels: {valid_levels}"
        )
    
    # Get or create setting
    stmt = select(AutonomySettings).where(
        AutonomySettings.user_id == user.id,
        AutonomySettings.action_type == action_type
    )
    result = await db.execute(stmt)
    setting = result.scalar_one_or_none()
    
    if setting:
        setting.autonomy_level = update.autonomy_level
        setting.require_notification = update.require_notification
        setting.require_confirmation = update.require_confirmation
    else:
        setting = AutonomySettings(
            user_id=user.id,
            action_type=action_type,
            autonomy_level=update.autonomy_level,
            require_notification=update.require_notification,
            require_confirmation=update.require_confirmation,
        )
        db.add(setting)
    
    await db.commit()
    await db.refresh(setting)
    
    logger.info(f"[AutonomyAPI] Updated {action_type} to {update.autonomy_level} for user {user.id}")
    
    return AutonomySettingResponse(
        action_type=action_type,
        autonomy_level=setting.autonomy_level,
        require_notification=setting.require_notification,
        require_confirmation=setting.require_confirmation,
        is_default=False,
    )


@router.delete("/settings/{action_type}")
async def reset_autonomy_setting(
    action_type: str,
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Reset autonomy setting to default for a specific action type."""
    stmt = select(AutonomySettings).where(
        AutonomySettings.user_id == user.id,
        AutonomySettings.action_type == action_type
    )
    result = await db.execute(stmt)
    setting = result.scalar_one_or_none()
    
    if setting:
        await db.delete(setting)
        await db.commit()
        
    return {"message": f"Reset {action_type} to default", "default_level": get_default_autonomy_level(action_type)}


# ==================== Actions Endpoints ====================

@router.get("/actions", response_model=List[AutonomousActionResponse])
async def get_actions(
    status: Optional[str] = Query(None, description="Filter by status: pending, executed, rejected, failed, undone"),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Get autonomous actions for the current user."""
    stmt = select(AutonomousAction).where(
        AutonomousAction.user_id == user.id
    )
    
    if status:
        stmt = stmt.where(AutonomousAction.status == status)
    
    stmt = stmt.order_by(AutonomousAction.created_at.desc()).limit(limit)
    
    result = await db.execute(stmt)
    actions = result.scalars().all()
    
    response = []
    for action in actions:
        response.append(AutonomousActionResponse(
            id=action.id,
            action_type=action.action_type,
            description=action.plan_data.get('description') if action.plan_data else None,
            status=action.status,
            autonomy_level_used=action.autonomy_level_used,
            created_at=action.created_at,
            executed_at=action.executed_at,
            undo_available=action.is_undo_available() if hasattr(action, 'is_undo_available') else False,
            requires_approval=action.requires_approval,
        ))
    
    return response


@router.get("/actions/pending", response_model=List[AutonomousActionResponse])
async def get_pending_actions(
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Get actions pending user approval."""
    stmt = select(AutonomousAction).where(
        AutonomousAction.user_id == user.id,
        AutonomousAction.status == 'pending',
        AutonomousAction.requires_approval == True
    ).order_by(AutonomousAction.created_at.desc())
    
    result = await db.execute(stmt)
    actions = result.scalars().all()
    
    return [
        AutonomousActionResponse(
            id=a.id,
            action_type=a.action_type,
            description=a.plan_data.get('description') if a.plan_data else None,
            status=a.status,
            autonomy_level_used=a.autonomy_level_used,
            created_at=a.created_at,
            executed_at=a.executed_at,
            undo_available=False,
            requires_approval=True,
        ) for a in actions
    ]


@router.post("/actions/{action_id}/approve")
async def approve_action(
    action_id: int,
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Approve a pending action for execution."""
    from src.core.credential_provider import CredentialFactory
    from src.utils.config import load_config
    
    config = load_config()
    factory = CredentialFactory(config)
    
    executor = ActionExecutor(db, config, factory)
    result = await executor.approve_action(action_id, user.id)
    
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error or "Failed to approve action")
    
    return {
        "message": "Action approved and executed",
        "action_id": action_id,
        "status": result.status,
        "result": result.result_data,
    }


@router.post("/actions/{action_id}/reject")
async def reject_action(
    action_id: int,
    body: ActionApprovalRequest = None,
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Reject a pending action."""
    from src.utils.config import load_config
    
    config = load_config()
    executor = ActionExecutor(db, config)
    
    reason = body.reason if body else None
    success = await executor.reject_action(action_id, user.id, reason)
    
    if not success:
        raise HTTPException(status_code=404, detail="Action not found or not pending")
    
    return {"message": "Action rejected", "action_id": action_id}


@router.post("/actions/{action_id}/undo")
async def undo_action(
    action_id: int,
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Undo an executed action (if within 5-minute window)."""
    from src.core.credential_provider import CredentialFactory
    from src.utils.config import load_config
    
    config = load_config()
    factory = CredentialFactory(config)
    
    executor = ActionExecutor(db, config, factory)
    success = await executor.undo_action(action_id, user.id)
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail="Cannot undo action. It may not exist, already undone, or undo window expired."
        )
    
    return {"message": "Action undone", "action_id": action_id}


# ==================== Stats Endpoint ====================

@router.get("/stats")
async def get_autonomy_stats(
    user: User = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """Get autonomy statistics for the current user."""
    from sqlalchemy import func
    
    # Count by status
    stmt = select(
        AutonomousAction.status,
        func.count(AutonomousAction.id)
    ).where(
        AutonomousAction.user_id == user.id
    ).group_by(AutonomousAction.status)
    
    result = await db.execute(stmt)
    status_counts = {row[0]: row[1] for row in result.all()}
    
    # Count pending approvals
    pending_approvals = status_counts.get('pending', 0)
    
    # Recent actions count (last 24h)
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(hours=24)
    stmt = select(func.count(AutonomousAction.id)).where(
        AutonomousAction.user_id == user.id,
        AutonomousAction.created_at >= cutoff
    )
    result = await db.execute(stmt)
    recent_count = result.scalar() or 0
    
    return {
        "by_status": status_counts,
        "pending_approvals": pending_approvals,
        "actions_last_24h": recent_count,
        "total_executed": status_counts.get('executed', 0),
    }
