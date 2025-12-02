"""
Knowledge Graph API Endpoints

Exposes the knowledge graph system for queries, analytics, and visualization.
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from src.database import get_async_db
from src.utils.config import load_config
from src.utils.logger import setup_logger
from ..auth import get_current_user_required
from ..dependencies import get_config
from src.database.models import User
from src.services.graph_search_service import GraphSearchService

logger = setup_logger(__name__)
router = APIRouter(prefix="/api/graph", tags=["knowledge_graph"])


# ============================================
# REQUEST/RESPONSE MODELS
# ============================================

class GraphSearchRequest(BaseModel):
    """Request for graph-enhanced search"""
    query: str = Field(..., min_length=1, max_length=1000)
    use_graph: bool = Field(True, description="Enable graph traversal")
    use_vector: bool = Field(True, description="Enable vector search")
    max_results: int = Field(10, ge=1, le=100)


class EntitySearchRequest(BaseModel):
    """Request for entity-based search"""
    entity_type: str = Field(..., description="Entity type (PERSON, VENDOR, etc.)")
    entity_name: str = Field(..., min_length=1)
    relationship_type: Optional[str] = Field(None, description="Optional relationship filter")
    max_results: int = Field(10, ge=1, le=100)


class SpendingAnalysisRequest(BaseModel):
    """Request for spending analysis"""
    time_period: Optional[str] = Field(None, description="Time period (e.g., '30d', '6m')")
    vendor_filter: Optional[str] = Field(None, description="Vendor name filter")


class GraphVisualizationRequest(BaseModel):
    """Request for graph visualization data"""
    center_node: Optional[str] = Field(None, description="Center node ID")
    depth: int = Field(2, ge=1, le=5, description="Traversal depth")
    max_nodes: int = Field(50, ge=10, le=200)


class InsightsRequest(BaseModel):
    """Request for AI insights"""
    insight_type: str = Field('general', description="Type: general, spending, contacts")


# ============================================
# ENDPOINTS
# ============================================

@router.post("/search")
async def graph_search(
    request: GraphSearchRequest,
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config)
) -> Dict[str, Any]:
    """
    Graph-enhanced search combining knowledge graph + vector search
    
    Provides richer results than vector-only search by:
    - Traversing relationships between entities
    - Finding related documents through graph connections
    - Providing structured reasoning paths
    
    Examples:
        - "Find all receipts from Amazon"
        - "Show emails mentioning both John and Project X"
        - "What meetings do I have about the Q4 budget?"
    """
    try:
        logger.info(f"Graph search request from user {current_user.id}: '{request.query}'")
        
        # Initialize graph search service
        search_service = GraphSearchService(
            config=config,
            user_id=current_user.id
        )
        
        # Execute search
        results = await search_service.search(
            query=request.query,
            use_graph=request.use_graph,
            use_vector=request.use_vector,
            max_results=request.max_results
        )
        
        return {
            'success': True,
            'query': request.query,
            'results': results,
            'user_id': current_user.id
        }
        
    except Exception as e:
        logger.error(f"Graph search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Graph search failed: {str(e)}")


@router.post("/entity/search")
async def search_by_entity(
    request: EntitySearchRequest,
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config)
) -> Dict[str, Any]:
    """
    Find all items related to a specific entity
    
    Use cases:
        - Find all emails from a specific person
        - Find all receipts from a vendor
        - Find all documents mentioning a project
    
    Example:
        POST /api/graph/entity/search
        {
            "entity_type": "VENDOR",
            "entity_name": "Amazon",
            "relationship_type": "HAS_RECEIPT"
        }
    """
    try:
        logger.info(
            f"Entity search: {request.entity_type}/{request.entity_name} "
            f"(user={current_user.id})"
        )
        
        search_service = GraphSearchService(
            config=config,
            user_id=current_user.id
        )
        
        results = await search_service.find_by_entity(
            entity_type=request.entity_type,
            entity_name=request.entity_name,
            relationship_type=request.relationship_type,
            max_results=request.max_results
        )
        
        return {
            'success': True,
            'entity_type': request.entity_type,
            'entity_name': request.entity_name,
            'count': len(results),
            'results': results
        }
        
    except Exception as e:
        logger.error(f"Entity search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analytics/spending")
async def analyze_spending(
    request: SpendingAnalysisRequest,
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config)
) -> Dict[str, Any]:
    """
    GraphRAG-powered spending analysis
    
    Analyzes spending patterns from receipts in the knowledge graph:
    - Total spending by vendor
    - Spending trends over time
    - Unusual spending patterns
    - AI-generated insights
    
    Example:
        POST /api/graph/analytics/spending
        {
            "time_period": "30d",
            "vendor_filter": "Amazon"
        }
    """
    try:
        logger.info(f"Spending analysis request (user={current_user.id})")
        
        search_service = GraphSearchService(
            config=config,
            user_id=current_user.id
        )
        
        analysis = await search_service.analyze_spending(
            time_period=request.time_period,
            vendor_filter=request.vendor_filter
        )
        
        return {
            'success': True,
            'user_id': current_user.id,
            'time_period': request.time_period,
            'analysis': analysis
        }
        
    except Exception as e:
        logger.error(f"Spending analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/insights")
async def get_insights(
    request: InsightsRequest,
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config)
) -> Dict[str, Any]:
    """
    Get AI-generated insights from your knowledge graph
    
    Types of insights:
        - general: Overall patterns and trends
        - spending: Financial insights
        - contacts: Communication patterns
    
    Example:
        POST /api/graph/insights
        {
            "insight_type": "spending"
        }
    """
    try:
        logger.info(f"Insights request: {request.insight_type} (user={current_user.id})")
        
        search_service = GraphSearchService(
            config=config,
            user_id=current_user.id
        )
        
        insights = await search_service.get_insights(
            insight_type=request.insight_type
        )
        
        return {
            'success': True,
            'insight_type': request.insight_type,
            'insights': insights
        }
        
    except Exception as e:
        logger.error(f"Insights generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/visualize")
async def visualize_graph(
    request: GraphVisualizationRequest,
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config)
) -> Dict[str, Any]:
    """
    Get graph visualization data
    
    Returns nodes and edges for visualization in the frontend.
    Can be centered on a specific node or show an overview.
    
    Example:
        POST /api/graph/visualize
        {
            "center_node": "email_12345",
            "depth": 2,
            "max_nodes": 50
        }
    """
    try:
        logger.info(f"Graph visualization request (user={current_user.id})")
        
        search_service = GraphSearchService(
            config=config,
            user_id=current_user.id
        )
        
        viz_data = await search_service.visualize_graph(
            center_node=request.center_node,
            depth=request.depth,
            max_nodes=request.max_nodes
        )
        
        return {
            'success': True,
            'visualization': viz_data
        }
        
    except Exception as e:
        logger.error(f"Graph visualization failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_graph_stats(
    current_user: User = Depends(get_current_user_required),
    config = Depends(get_config)
) -> Dict[str, Any]:
    """
    Get knowledge graph statistics
    
    Returns:
        - Total nodes by type
        - Total relationships by type
        - Graph coverage metrics
    """
    try:
        logger.info(f"Graph stats request (user={current_user.id})")
        
        search_service = GraphSearchService(
            config=config,
            user_id=current_user.id
        )
        
        stats = await search_service.graph.get_statistics()
        
        return {
            'success': True,
            'stats': stats,
            'user_id': current_user.id
        }
        
    except Exception as e:
        logger.error(f"Graph stats failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
