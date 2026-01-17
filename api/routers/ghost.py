from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime

from api.dependencies import get_db, get_current_user_required, get_config
from src.database.models import User, GhostDraft
from src.integrations.linear.service import LinearService
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/ghost", tags=["ghost"])

@router.get("/drafts", response_model=List[Dict[str, Any]])
async def list_drafts(
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    """List all pending drafts for the Ghost Collaborator."""
    drafts = db.query(GhostDraft).filter(
        GhostDraft.user_id == current_user.id,
        GhostDraft.status == "draft"
    ).order_by(GhostDraft.created_at.desc()).all()
    
    return [
        {
            "id": d.id,
            "title": d.title,
            "description": d.description,
            "status": d.status,
            "integration_type": d.integration_type,
            "confidence": d.confidence,
            "source": f"#{d.source_channel}",
            "created_at": d.created_at.isoformat()
        } for d in drafts
    ]

@router.post("/drafts/{draft_id}/approve")
async def approve_draft(
    draft_id: int,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
    config=Depends(get_config)
):
    """Approve a draft and post it to the respective integration (e.g., Linear)."""
    draft = db.query(GhostDraft).filter(
        GhostDraft.id == draft_id,
        GhostDraft.user_id == current_user.id
    ).first()
    
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    if draft.status != "draft":
        raise HTTPException(status_code=400, detail=f"Draft in status '{draft.status}' cannot be approved")

    try:
        if draft.integration_type == "linear":
            linear = LinearService(config)
            # Find the first team available for the user or use a default from config
            # For now, let's assume we have a helper to get the team
            # In a real app, this would be part of user settings
            issue_data = await linear.create_issue(
                title=draft.title,
                description=draft.description,
                priority="urgent" if draft.confidence > 0.8 else "high"
            )
            
            draft.status = "posted"
            draft.resolved_entity_id = issue_data.get("id")
            db.commit()
            
            return {"status": "success", "entity_id": draft.resolved_entity_id, "message": "Issue posted to Linear"}
        
        else:
            raise HTTPException(status_code=501, detail=f"Integration '{draft.integration_type}' not yet supported for Ghost")

    except Exception as e:
        logger.error(f"[Ghost] Failed to approve draft {draft_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to post issue: {str(e)}")

@router.post("/drafts/{draft_id}/dismiss")
async def dismiss_draft(
    draft_id: int,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    """Dismiss a draft suggestion."""
    draft = db.query(GhostDraft).filter(
        GhostDraft.id == draft_id,
        GhostDraft.user_id == current_user.id
    ).first()
    
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    draft.status = "dismissed"
    db.commit()
    
    return {"status": "success", "message": "Draft dismissed"}
