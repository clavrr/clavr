"""
Analytics API Router

Endpoints for memory graph analytics:
- Relationship analytics (who you communicate with most)
- Topic analytics (trending topics, clusters)
- Temporal patterns (activity over time)
- Cross-app insights (integration health, entity unification)

This complements the existing graph router with analytics-focused queries.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, Optional
from datetime import datetime

from api.dependencies import get_config
from api.auth import get_current_user_required
from src.database.models import User
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/relationships")
async def get_relationship_analytics(
    time_range_days: int = Query(default=30, ge=1, le=365),
    top_n: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user_required),
    config=Depends(get_config)
):
    """
    Get relationship analytics for the current user.
    
    Returns:
    - Top contacts by interaction frequency
    - Relationship strength distribution
    - New connections in the last week
    - Communication trends
    """
    from src.services.analytics import get_memory_analytics
    
    analytics = get_memory_analytics()
    if not analytics:
        raise HTTPException(
            status_code=503,
            detail="Analytics service not initialized"
        )
    
    return await analytics.get_relationship_analytics(
        user_id=current_user.id,
        time_range_days=time_range_days,
        top_n=top_n
    )


@router.get("/topics")
async def get_topic_analytics(
    time_range_days: int = Query(default=30, ge=1, le=365),
    top_n: int = Query(default=15, ge=1, le=50),
    current_user: User = Depends(get_current_user_required),
    config=Depends(get_config)
):
    """
    Get topic analytics for the current user.
    
    Returns:
    - Trending topics with velocity
    - Topic clusters (related topics)
    - Topic sources breakdown
    - Weekly topic activity
    """
    from src.services.analytics import get_memory_analytics
    
    analytics = get_memory_analytics()
    if not analytics:
        raise HTTPException(
            status_code=503,
            detail="Analytics service not initialized"
        )
    
    return await analytics.get_topic_analytics(
        user_id=current_user.id,
        time_range_days=time_range_days,
        top_n=top_n
    )


@router.get("/temporal")
async def get_temporal_patterns(
    time_range_days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(get_current_user_required),
    config=Depends(get_config)
):
    """
    Get temporal activity patterns for the current user.
    
    Returns:
    - Activity by hour of day
    - Activity by day of week
    - Peak hours and quiet periods
    - 14-day activity trend
    """
    from src.services.analytics import get_memory_analytics
    
    analytics = get_memory_analytics()
    if not analytics:
        raise HTTPException(
            status_code=503,
            detail="Analytics service not initialized"
        )
    
    return await analytics.get_temporal_activity_patterns(
        user_id=current_user.id,
        time_range_days=time_range_days
    )


@router.get("/cross-app")
async def get_cross_app_insights(
    time_range_days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(get_current_user_required),
    config=Depends(get_config)
):
    """
    Get cross-app activity insights for the current user.
    
    Returns:
    - Content distribution by source app
    - Cross-app person connections
    - Entity unification statistics
    - Integration health status
    """
    from src.services.analytics import get_memory_analytics
    
    analytics = get_memory_analytics()
    if not analytics:
        raise HTTPException(
            status_code=503,
            detail="Analytics service not initialized"
        )
    
    return await analytics.get_cross_app_insights(
        user_id=current_user.id,
        time_range_days=time_range_days
    )


@router.get("/report")
async def get_full_analytics_report(
    time_range_days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(get_current_user_required),
    config=Depends(get_config)
):
    """
    Get a comprehensive analytics report for the current user.
    
    Combines all analytics into a single response:
    - relationships: Contact and communication analysis
    - topics: Topic trends and clusters
    - temporal: Activity patterns over time
    - cross_app: Integration and unification insights
    """
    from src.services.analytics import get_memory_analytics
    
    analytics = get_memory_analytics()
    if not analytics:
        raise HTTPException(
            status_code=503,
            detail="Analytics service not initialized"
        )
    
    return await analytics.get_full_analytics_report(
        user_id=current_user.id,
        time_range_days=time_range_days
    )


@router.get("/health")
async def get_analytics_health(
    current_user: User = Depends(get_current_user_required)
):
    """
    Get the health status of analytics services.
    """
    from src.services.analytics import get_memory_analytics
    
    analytics = get_memory_analytics()
    
    return {
        "analytics_service": "healthy" if analytics else "not_initialized",
        "timestamp": datetime.utcnow().isoformat()
    }
