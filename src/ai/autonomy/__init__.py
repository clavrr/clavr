"""
AI Autonomy Module

Provides autonomous behavior capabilities:
- BehaviorLearner: Mine sequential patterns from user actions
- BriefingGenerator: Generate morning briefings and meeting dossiers
- ContextEvaluator: Evaluate context to trigger proactive actions  
- ProactivePlanner: Goal-driven planning for autonomous actions
- NarrativeGenerator: Base class for LLM-powered narratives
"""

from .behavior_learner import BehaviorLearner
from .briefing import BriefingGenerator, MeetingBriefGenerator
from .evaluator import ContextEvaluator
from .planner import ProactivePlanner, ActionPlan
from .base import NarrativeGenerator

# Re-export config for convenience
from .autonomy_config import (
    LEARNING_INITIAL_DELAY_SECONDS,
    LEARNING_INTERVAL_SECONDS,
    MORNING_BRIEF_HOURS,
    EOD_SUMMARY_HOURS,
    MEETING_PREP_MINUTES,
)

__all__ = [
    'BehaviorLearner',
    'BriefingGenerator',
    'MeetingBriefGenerator',
    'ContextEvaluator',
    'ProactivePlanner',
    'ActionPlan',
    'NarrativeGenerator',
]
