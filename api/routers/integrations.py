"""
Integrations Router - External service integrations (Slack, Notion, Asana, etc.)
"""
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional

from api.dependencies import get_db, get_integration_service, get_config, get_current_user
from src.database.models import User
from src.utils.logger import setup_logger
from src.utils.config import Config, get_frontend_url
from src.auth.audit import log_auth_event, AuditEventType
import hmac
import hashlib
import json

logger = setup_logger(__name__)
router = APIRouter(prefix="/integrations", tags=["integrations"])

@router.get("/{provider}/auth")
async def auth_provider(
    provider: str,
    redirect_to: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    integration_service = Depends(get_integration_service),
    db: Session = Depends(get_db),
    request: Request = None # Optional, will be populated by FastAPI
):
    """Initiate OAuth flow for a provider - redirects to OAuth consent screen."""
    try:
        # Log initiation (optional, but good for tracking intent)
        await log_auth_event(
            db=db,
            event_type=AuditEventType.ADMIN_ACTION,
            user_id=user.id,
            action="init_integration_auth",
            provider=provider
        )
        url = await integration_service.get_auth_url(provider, user.id, user.email, redirect_to=redirect_to)
        return RedirectResponse(url=url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{provider}/callback")
async def auth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
    integration_service = Depends(get_integration_service),
    config: Config = Depends(get_config),
    db: Session = Depends(get_db)
):
    """Handle OAuth callback for a provider."""
    try:
        real_provider, user_id = await integration_service.handle_callback(provider, code, state)
        
        # Log successful connection
        await log_auth_event(
            db=db,
            event_type=AuditEventType.INTEGRATION_CONNECTED,
            user_id=user_id,
            provider=real_provider
        )
        
        f_url = get_frontend_url(config)
        return RedirectResponse(url=f"{f_url}/integrations?success=true&provider={real_provider}")
    except Exception as e:
        logger.error(f"Integration callback failed for {provider}: {e}", exc_info=True)
        f_url = get_frontend_url(config)
        return RedirectResponse(url=f"{f_url}/integrations?error=auth_failed")

@router.post("/{provider}/disconnect")
async def disconnect_integration(
    provider: str,
    user: User = Depends(get_current_user),
    integration_service = Depends(get_integration_service),
    db: Session = Depends(get_db)
):
    """Disconnect an integration."""
    try:
        await integration_service.disconnect(user.id, provider)
        
        # Log disconnection
        await log_auth_event(
            db=db,
            event_type=AuditEventType.INTEGRATION_DISCONNECTED,
            user_id=user.id,
            provider=provider
        )
        
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{provider}/toggle")
async def toggle_integration(
    provider: str,
    user: User = Depends(get_current_user),
    integration_service = Depends(get_integration_service)
):
    """Toggle integration active status."""
    try:
        is_active = await integration_service.toggle(user.id, provider)
        return {"success": True, "is_active": is_active}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/status")
async def get_integrations_status(
    user: User = Depends(get_current_user),
    integration_service = Depends(get_integration_service)
):
    """Get status of all integrations for the user."""
    integrations = await integration_service.get_user_integrations(user.id)
    return {"integrations": integrations}

@router.post("/linear/webhook")
async def linear_webhook(
    request: Request,
    config: Config = Depends(get_config)
):
    """
    Handle incoming webhooks from Linear.
    URL: /api/integrations/linear/webhook
    """
    # 1. Get raw body for signature verification
    body = await request.body()
    signature = request.headers.get("Linear-Signature")
    
    # 2. Verify signature if secret is configured
    if config.linear_webhook_secret:
        if not signature:
            logger.warning("Missing Linear-Signature header")
            raise HTTPException(status_code=401, detail="Missing signature")
        
        expected_signature = hmac.new(
            config.linear_webhook_secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_signature):
            logger.warning("Invalid Linear signature")
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    # 3. Process payload
    try:
        payload = json.loads(body)
        action = payload.get("action")
        type_ = payload.get("type")
        
        logger.info(f"Received Linear webhook: {action} {type_}")
        
        # TODO: Implement specific event handlers (e.g. sync back to our DB)
        # For now, we just acknowledge receipt
        return {"success": True}
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
