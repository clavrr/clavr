"""
Insights Service Package

Provides proactive insight surfacing from the knowledge graph.
"""
from .insight_service import (
    InsightService,
    get_insight_service,
    init_insight_service,
)

__all__ = [
    "InsightService",
    "get_insight_service", 
    "init_insight_service",
]
