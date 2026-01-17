"""
Detection Package

Contains services for detecting conflicts and patterns.
"""
from .conflict_detector import (
    ConflictDetector,
    ConflictInfo,
    check_calendar_event_for_conflicts,
)

__all__ = [
    "ConflictDetector",
    "ConflictInfo",
    "check_calendar_event_for_conflicts",
]
