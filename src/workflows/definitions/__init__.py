"""
Workflow Definitions Package

Contains all workflow implementations.
"""
from .morning_briefing import MorningBriefingWorkflow
from .email_to_action import EmailToActionWorkflow, BatchEmailProcessorWorkflow
from .weekly_planning import WeeklyPlanningWorkflow
from .end_of_day import EndOfDayReviewWorkflow

__all__ = [
    'MorningBriefingWorkflow',
    'EmailToActionWorkflow',
    'BatchEmailProcessorWorkflow',
    'WeeklyPlanningWorkflow',
    'EndOfDayReviewWorkflow'
]
