"""
API Router for GDPR-Compliant Data Export

Endpoints:
- GET /api/export/request - Request data export (returns immediately with task ID)
- GET /api/export/download/{token} - Download generated export file
- GET /api/export/status/{task_id} - Check export generation status
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime, timedelta
import secrets
import json
import logging

from api.auth import get_current_user_required as get_current_user
from api.dependencies import get_config
from src.database import get_async_db as get_db
from src.database.models import User
from src.features.data_export import generate_export_for_user
from src.utils.config import Config
from src.auth.audit import log_auth_event, AuditEventType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["Data Export"])


# Store export tokens temporarily (in production, use Redis or database)
EXPORT_TOKENS = {}  # token -> (user_id, export_data, expires_at)


@router.post("/request")
async def request_data_export(
    request: Request,
    format: str = Query(default="zip", description="Export format: json, csv, or zip"),
    include_vectors: bool = Query(default=False, description="Include vector embeddings (large!)"),
    include_email_content: bool = Query(default=True, description="Include full email content"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: Config = Depends(get_config),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    Request a data export (GDPR Article 20 - Right to Data Portability)
    
    This endpoint initiates the export process. For large exports, the generation
    happens in the background and you'll receive a download token.
    
    **Export Formats:**
    - `json`: Complete data in JSON format
    - `csv`: Multiple CSV files (one per data type)
    - `zip`: ZIP archive containing JSON + CSV files + README
    
    **Response:**
    - For small exports: Immediate response with data
    - For large exports: Task ID to check status
    """
    # Validate format
    if format not in ["json", "csv", "zip"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid format: {format}. Must be one of: json, csv, zip"
        )
    
    logger.info(f"Data export requested by user {current_user.id} (format: {format})")
    
    # Log audit event
    await log_auth_event(
        db=db,
        event_type=AuditEventType.DATA_EXPORT_REQUEST,
        user_id=current_user.id,
        request=request,
        format=format,
        include_vectors=include_vectors
    )
    
    try:
        # For JSON/CSV, we can generate immediately if it's a small dataset
        # For ZIP or with vectors, use background task
        if format == "zip" or include_vectors:
            # Generate a secure token for download
            download_token = secrets.token_urlsafe(32)
            
            # Schedule background task
            background_tasks.add_task(
                _generate_export_background,
                user_id=current_user.id,
                db=db,
                config=config,
                format=format,
                include_vectors=include_vectors,
                download_token=download_token
            )
            
            return JSONResponse(
                status_code=202,  # Accepted
                content={
                    "status": "processing",
                    "message": "Export is being generated. Please use the download token to retrieve it.",
                    "download_token": download_token,
                    "download_url": f"/api/export/download/{download_token}",
                    "estimated_time_seconds": 30 if not include_vectors else 120,
                    "expires_in_minutes": 60
                }
            )
        else:
            # Generate immediately for small exports
            export_data = await generate_export_for_user(
                user_id=current_user.id,
                db=db,
                config=config,
                format=format,
                include_vectors=False
            )
            
            if format == "json":
                return JSONResponse(
                    content=export_data,
                    headers={
                        "Content-Disposition": f'attachment; filename="notely_export_{current_user.id}_{datetime.utcnow().strftime("%Y%m%d")}.json"'
                    }
                )
            elif format == "csv":
                # Return CSV files as JSON response with download links
                return JSONResponse(content={
                    "status": "success",
                    "format": "csv",
                    "files": export_data,
                    "note": "CSV files are returned as strings. Save each to a .csv file."
                })
    
    except Exception as e:
        logger.error(f"Error generating export for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate export: {str(e)}"
        )


@router.get("/download/{token}")
async def download_export(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Download a generated data export using a secure token
    
    The token expires after 1 hour for security.
    """
    if token not in EXPORT_TOKENS:
        raise HTTPException(
            status_code=404,
            detail="Export not found or token expired. Please request a new export."
        )
    
    user_id, export_data, expires_at = EXPORT_TOKENS[token]
    
    # Check expiration
    if datetime.utcnow() > expires_at:
        del EXPORT_TOKENS[token]
        raise HTTPException(
            status_code=410,  # Gone
            detail="Export token has expired. Please request a new export."
        )
    
    logger.info(f"User {user_id} downloading export with token {token[:10]}...")
    
    # Log audit event
    await log_auth_event(
        db=db,
        event_type=AuditEventType.DATA_EXPORT_DOWNLOAD,
        user_id=user_id,
        request=request,
        token_prefix=token[:8]
    )
    
    # Determine content type and filename
    if isinstance(export_data, bytes):
        # ZIP file
        content_type = "application/zip"
        filename = f"notely_export_{user_id}_{datetime.utcnow().strftime('%Y%m%d')}.zip"
    else:
        # JSON
        content_type = "application/json"
        filename = f"notely_export_{user_id}_{datetime.utcnow().strftime('%Y%m%d')}.json"
        export_data = json.dumps(export_data, indent=2, default=str).encode('utf-8')
    
    # Clean up token after download
    del EXPORT_TOKENS[token]
    
    return Response(
        content=export_data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.delete("/request")
async def cancel_data_export(
    current_user: User = Depends(get_current_user)
):
    """
    Cancel any pending data export requests
    
    This will invalidate any active export tokens for the current user.
    """
    # Remove all tokens for this user
    tokens_to_remove = [
        token for token, (user_id, _, _) in EXPORT_TOKENS.items()
        if user_id == current_user.id
    ]
    
    for token in tokens_to_remove:
        del EXPORT_TOKENS[token]
    
    logger.info(f"Cancelled {len(tokens_to_remove)} export(s) for user {current_user.id}")
    
    return JSONResponse(content={
        "status": "success",
        "message": f"Cancelled {len(tokens_to_remove)} pending export(s)"
    })


@router.get("/info")
async def get_export_info(current_user: User = Depends(get_current_user)):
    """
    Get information about available data export options
    
    Returns details about what data can be exported and in what formats.
    """
    return JSONResponse(content={
        "available_formats": ["json", "csv", "zip"],
        "data_categories": [
            {
                "name": "user_profile",
                "description": "Your account information and settings",
                "included_by_default": True
            },
            {
                "name": "emails",
                "description": "Your email data from Gmail",
                "included_by_default": True,
                "optional_full_content": True
            },
            {
                "name": "calendar",
                "description": "Your calendar events",
                "included_by_default": True
            },
            {
                "name": "conversations",
                "description": "Your chat history with the AI assistant",
                "included_by_default": True
            },
            {
                "name": "sessions",
                "description": "Your login session history",
                "included_by_default": True
            },
            {
                "name": "vector_embeddings",
                "description": "AI/ML embeddings of your data (very large)",
                "included_by_default": False,
                "requires_special_request": True
            }
        ],
        "gdpr_compliance": {
            "regulation": "GDPR Article 20",
            "right": "Right to Data Portability",
            "description": "You have the right to receive your personal data in a structured, commonly used, and machine-readable format."
        },
        "export_limits": {
            "max_emails": 10000,
            "max_calendar_events": 5000,
            "token_expiry_minutes": 60
        },
        "recommended_format": "zip",
        "estimated_generation_time": {
            "json": "5-10 seconds",
            "csv": "5-10 seconds",
            "zip": "15-30 seconds",
            "with_vectors": "1-2 minutes"
        }
    })


async def _generate_export_background(
    user_id: int,
    db: AsyncSession,
    config: Config,
    format: str,
    include_vectors: bool,
    download_token: str
):
    """
    Background task to generate export file
    
    This runs asynchronously so the user doesn't have to wait.
    """
    try:
        logger.info(f"Starting background export generation for user {user_id}")
        
        # Generate export
        export_data = await generate_export_for_user(
            user_id=user_id,
            db=db,
            config=config,
            format=format,
            include_vectors=include_vectors
        )
        
        # Store in temporary cache (expires in 1 hour)
        expires_at = datetime.utcnow() + timedelta(hours=1)
        EXPORT_TOKENS[download_token] = (user_id, export_data, expires_at)
        
        logger.info(f"Export generated successfully for user {user_id}, token: {download_token[:10]}...")
        
    except Exception as e:
        logger.error(f"Background export failed for user {user_id}: {e}", exc_info=True)
        # Store error in token so user can see what went wrong
        expires_at = datetime.utcnow() + timedelta(minutes=10)
        EXPORT_TOKENS[download_token] = (
            user_id,
            {"error": str(e), "status": "failed"},
            expires_at
        )
