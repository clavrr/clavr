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

logger = setup_logger(__name__)
router = APIRouter(prefix="/integrations", tags=["integrations"])

@router.get("/{provider}/auth")
async def auth_provider(
    provider: str,
    redirect_to: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    integration_service = Depends(get_integration_service)
):
    """Initiate OAuth flow for a provider - redirects to OAuth consent screen."""
    try:
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
    config: Config = Depends(get_config)
):
    """Handle OAuth callback for a provider."""
    try:
        real_provider, _ = await integration_service.handle_callback(provider, code, state)
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
    integration_service = Depends(get_integration_service)
):
    """Disconnect an integration."""
    try:
        await integration_service.disconnect(user.id, provider)
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
