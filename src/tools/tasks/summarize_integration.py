"""
Task Summarization Integration Module

Handles integration with SummarizeTool for task summaries and accomplishments.
"""
from typing import Optional, Any
from datetime import datetime, timedelta

from ...utils.logger import setup_logger
from .constants import DEFAULT_DAYS_AHEAD, PERIOD_DAYS

logger = setup_logger(__name__)


class SummarizeIntegration:
    """Handles task summarization features"""

    def __init__(self, task_tool):
        """
        Initialize summarize integration

        Args:
            task_tool: Reference to parent TaskTool instance
        """
        self.task_tool = task_tool

    def summarize_tasks(
        self,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        category: Optional[str] = None,
        days_ahead: int = DEFAULT_DAYS_AHEAD,
        summary_format: str = "bullet_points",
        summary_length: str = "medium",
        summarize_tool: Optional[Any] = None
    ) -> str:
        """
        Generate summary of tasks using SummarizeTool

        Args:
            status: Task status filter
            priority: Priority filter
            category: Category filter
            days_ahead: Number of days to look ahead
            summary_format: Format for summary
            summary_length: Length of summary
            summarize_tool: Reference to SummarizeTool

        Returns:
            Formatted summary string
        """
        try:
            from .core_operations import CoreOperations
            core = CoreOperations(self.task_tool)

            tasks_output = core.list_tasks(
                status=status or "pending",
                priority=priority,
                category=category
            )

            if not summarize_tool:
                return tasks_output

            context_text = f"""Task List Summary Request:
Status: {status or 'pending'}
Priority: {priority or 'all'}
Category: {category or 'all'}
Timeframe: Next {days_ahead} days

{tasks_output}

Please provide a concise overview highlighting:
- Most urgent/important tasks
- Key deadlines
- Project groupings
- Recommendations for prioritization"""

            summary = summarize_tool.run(
                content=context_text,
                format=summary_format,
                length=summary_length,
                focus="actionable insights and priorities"
            )

            logger.info("[TASK->SUMMARIZE] Generated task summary")
            return summary

        except Exception as e:
            logger.error(f"Error summarizing tasks: {e}")
            return f"[ERROR] Failed to summarize tasks: {str(e)}"

    def summarize_accomplishments(
        self,
        period: str = "week",
        summary_format: str = "bullet_points",
        summarize_tool: Optional[Any] = None
    ) -> str:
        """
        Summarize completed tasks for a period

        Args:
            period: Time period (day/week/month/quarter)
            summary_format: Format for summary
            summarize_tool: Reference to SummarizeTool

        Returns:
            Formatted accomplishment summary
        """
        try:
            from .core_operations import CoreOperations
            core = CoreOperations(self.task_tool)

            # Map period to days using constants
            days = PERIOD_DAYS.get(period, DEFAULT_DAYS_AHEAD)

            completed_tasks = core.list_tasks(status="completed")

            if not summarize_tool:
                return f"**Accomplishments ({period}):**\n\n{completed_tasks}"

            context_text = f"""Completed Tasks Summary ({period.title()}):

{completed_tasks}

Please summarize accomplishments, highlighting:
- Major achievements
- Projects completed
- Productivity patterns
- Areas of focus"""

            summary = summarize_tool.run(
                content=context_text,
                format=summary_format,
                length="medium",
                focus="achievements and productivity"
            )

            logger.info(f"[TASK->SUMMARIZE] Generated accomplishment summary for {period}")
            return summary

        except Exception as e:
            logger.error(f"Error summarizing accomplishments: {e}")
            return f"[ERROR] Failed to summarize accomplishments: {str(e)}"
