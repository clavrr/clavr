"""
Workflow Tool for Automated Productivity Workflows

This tool provides automated workflows that combine Email, Calendar, and Task tools
to create intelligent productivity assistance.

Architecture:
    WorkflowTool → ProductivityWorkflows → Multiple Services
"""
from typing import Optional, Any
from pydantic import BaseModel, Field, PrivateAttr

from .base_tool import ClavrBaseTool
from .constants import ToolLimits
from ..workflows import ProductivityWorkflows
from ..integrations.gmail.service import EmailService
from ..integrations.google_calendar.service import CalendarService
from ..integrations.google_tasks.service import TaskService
from .email.ai_analyzer import EmailAIAnalyzer
from ..utils.logger import setup_logger
from ..utils.config import Config

logger = setup_logger(__name__)


class WorkflowActionInput(BaseModel):
    """Input schema for workflow operations"""
    action: str = Field(
        description="Workflow to run: 'morning_briefing', 'email_to_action', 'weekly_planning', 'end_of_day_review'"
    )
    email_id: Optional[str] = Field(default=None, description="Email ID for email-to-action workflow")
    auto_create_tasks: Optional[bool] = Field(default=True, description="Auto-create tasks in email-to-action")
    auto_create_events: Optional[bool] = Field(default=True, description="Auto-create events in email-to-action")
    auto_archive: Optional[bool] = Field(default=False, description="Auto-archive email after processing")
    include_weather: Optional[bool] = Field(default=False, description="Include weather in morning briefing")
    include_last_week: Optional[bool] = Field(default=True, description="Include last week review in weekly planning")
    max_emails: Optional[int] = Field(default=ToolLimits.MAX_EMAILS_DISPLAY, description="Max emails in briefing")
    max_tasks: Optional[int] = Field(default=ToolLimits.MAX_TASKS_DISPLAY, description="Max tasks in briefing")


class WorkflowTool(ClavrBaseTool):
    """Tool for automated productivity workflows"""
    
    name: str = "workflow_tool"
    description: str = """Automated productivity workflows that combine email, calendar, and tasks.
    
    Available workflows:
    - morning_briefing: Daily overview with events, tasks, and important emails
    - email_to_action: Process email into tasks and calendar events
    - weekly_planning: Weekly overview with planning suggestions
    - end_of_day_review: Daily completion summary and tomorrow preview
    
    Examples:
    - "Give me my morning briefing"
    - "Process this email into tasks: abc123"
    - "Show me my weekly plan"
    - "End of day summary"
    """
    
    args_schema: type[BaseModel] = WorkflowActionInput
    config: Optional[Config] = None
    _user_id: Optional[str] = PrivateAttr(default=None)
    _credentials: Optional[Any] = PrivateAttr(default=None)
    
    # Services
    _email_service: Optional[EmailService] = PrivateAttr(default=None)
    _calendar_service: Optional[CalendarService] = PrivateAttr(default=None)
    _task_service: Optional[TaskService] = PrivateAttr(default=None)
    
    # Workflows engine
    _workflows: Optional[ProductivityWorkflows] = PrivateAttr(default=None)
    
    # AI analyzer for email intelligence
    _email_ai_analyzer: Optional[EmailAIAnalyzer] = PrivateAttr(default=None)
    _llm_client: Optional[Any] = PrivateAttr(default=None)
    
    def __init__(
        self,
        config: Optional[Config] = None,
        user_id: Optional[str] = None,
        credentials: Optional[Any] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._set_attr('config', config)
        self._set_attr('_user_id', user_id)
        self._set_attr('_credentials', credentials)
        
        logger.info(f"[WORKFLOW_TOOL] Initializing for user: {user_id}")
    
    @property
    def email_service(self) -> EmailService:
        """Lazy-load email service"""
        if self._email_service is None:
            self._set_attr(
                '_email_service',
                EmailService(
                    config=self.config,
                    credentials=self._credentials
                )
            )
        return self._email_service
    
    @property
    def calendar_service(self) -> CalendarService:
        """Lazy-load calendar service"""
        if self._calendar_service is None:
            self._set_attr(
                '_calendar_service',
                CalendarService(
                    config=self.config,
                    credentials=self._credentials
                )
            )
        return self._calendar_service
    
    @property
    def task_service(self) -> TaskService:
        """Lazy-load task service"""
        if self._task_service is None:
            self._set_attr(
                '_task_service',
                TaskService(
                    config=self.config,
                    credentials=self._credentials
                )
            )
        return self._task_service
    
    @property
    def email_ai_analyzer(self) -> EmailAIAnalyzer:
        """Lazy-load email AI analyzer"""
        if self._email_ai_analyzer is None:
            self._set_attr(
                '_email_ai_analyzer',
                EmailAIAnalyzer(llm_client=self._llm_client)
            )
        return self._email_ai_analyzer
    
    @property
    def workflows(self) -> ProductivityWorkflows:
        """Lazy-load workflows engine"""
        if self._workflows is None:
            self._set_attr(
                '_workflows',
                ProductivityWorkflows(
                    email_service=self.email_service,
                    calendar_service=self.calendar_service,
                    task_service=self.task_service,
                    email_ai_analyzer=self.email_ai_analyzer
                )
            )
        return self._workflows
    
    def set_llm_client(self, llm_client: Any):
        """Set LLM client for AI features"""
        self._set_attr('_llm_client', llm_client)
    
    def _run(self, action: str, **kwargs) -> str:
        """
        Execute workflow action
        
        Args:
            action: Workflow to run
            **kwargs: Workflow-specific parameters
            
        Returns:
            Formatted workflow results
        """
        try:
            logger.info(f"[WORKFLOW_TOOL] Running workflow: {action}")
            
            if action == "morning_briefing":
                return self._run_morning_briefing(**kwargs)
            
            elif action == "email_to_action":
                return self._run_email_to_action(**kwargs)
            
            elif action == "weekly_planning":
                return self._run_weekly_planning(**kwargs)
            
            elif action == "end_of_day_review":
                return self._run_end_of_day_review(**kwargs)
            
            else:
                return f"[ERROR] Unknown workflow: {action}"
        
        except Exception as e:
            return self._handle_error(e, f"workflow '{action}'")
    
    def _run_morning_briefing(
        self,
        include_weather: bool = False,
        max_emails: int = 10,
        max_tasks: int = 10,
        **kwargs
    ) -> str:
        """Run morning briefing workflow"""
        logger.info("[WORKFLOW_TOOL] Generating morning briefing")
        
        briefing = self.workflows.morning_briefing(
            include_weather=include_weather,
            max_emails=max_emails,
            max_tasks=max_tasks
        )
        
        # Format as readable text
        return self.workflows.format_briefing_text(briefing)
    
    def _run_email_to_action(
        self,
        email_id: Optional[str] = None,
        auto_create_tasks: bool = True,
        auto_create_events: bool = True,
        auto_archive: bool = False,
        **kwargs
    ) -> str:
        """Run email-to-action workflow"""
        if not email_id:
            return "[ERROR] Please provide 'email_id' for email_to_action workflow"
        
        logger.info(f"[WORKFLOW_TOOL] Processing email {email_id}")
        
        result = self.workflows.email_to_action_workflow(
            email_id=email_id,
            auto_create_tasks=auto_create_tasks,
            auto_create_events=auto_create_events,
            auto_archive=auto_archive
        )
        
        # Format results
        lines = []
        lines.append(f"✅ Email {email_id} processed successfully!")
        lines.append("")
        
        # Tasks created
        if result.get('tasks_created'):
            lines.append(f"📝 Created {len(result['tasks_created'])} tasks:")
            for task in result['tasks_created']:
                priority = task.get('priority', 'medium').upper()
                lines.append(f"  • [{priority}] {task.get('title', 'Untitled')}")
            lines.append("")
        
        # Events created
        if result.get('events_created'):
            lines.append(f"📅 Created {len(result['events_created'])} calendar events:")
            for event in result['events_created']:
                lines.append(f"  • {event.get('summary', 'Untitled')}")
                if event.get('start', {}).get('dateTime'):
                    lines.append(f"    {event['start']['dateTime']}")
            lines.append("")
        
        # Classification
        classification = result.get('email_classification', {})
        if classification:
            lines.append(f"🏷️ Email Classification:")
            lines.append(f"  • Urgency: {classification.get('urgency', 'unknown')}")
            lines.append(f"  • Category: {classification.get('category', 'unknown')}")
            lines.append(f"  • Action Items Found: {classification.get('action_items_found', 0)}")
            lines.append("")
        
        # Archive status
        if result.get('archived'):
            lines.append("📥 Email archived")
        
        return "\n".join(lines)
    
    def _run_weekly_planning(
        self,
        include_last_week: bool = True,
        **kwargs
    ) -> str:
        """Run weekly planning workflow"""
        logger.info("[WORKFLOW_TOOL] Generating weekly planning")
        
        planning = self.workflows.weekly_planning_workflow(
            include_last_week_review=include_last_week
        )
        
        # Format as readable text
        lines = []
        lines.append("📅 WEEKLY PLANNING")
        lines.append("=" * 50)
        lines.append("")
        
        # This week
        this_week = planning.get('this_week', {})
        calendar_data = this_week.get('calendar', {})
        
        lines.append(f"📊 THIS WEEK OVERVIEW")
        lines.append(f"• Total Events: {calendar_data.get('total_events', 0)}")
        lines.append(f"• Busiest Day: {calendar_data.get('busiest_day', 'N/A')}")
        
        tasks_data = this_week.get('tasks', {})
        lines.append(f"• Total Tasks: {tasks_data.get('total_tasks', 0)}")
        
        by_priority = tasks_data.get('by_priority', {})
        lines.append(f"  - Urgent: {by_priority.get('urgent', 0)}")
        lines.append(f"  - High: {by_priority.get('high', 0)}")
        lines.append(f"  - Medium: {by_priority.get('medium', 0)}")
        lines.append("")
        
        # Last week
        if include_last_week:
            last_week = planning.get('last_week', {})
            if last_week:
                lines.append("📈 LAST WEEK REVIEW")
                lines.append(f"• Events: {last_week.get('total_events', 0)}")
                lines.append(f"• Tasks Completed: {last_week.get('tasks_completed', 0)}")
                lines.append(f"• Productivity Score: {last_week.get('productivity_score', 0)}/100")
                lines.append("")
        
        # Recommendations
        recommendations = planning.get('recommendations', [])
        if recommendations:
            lines.append("💡 RECOMMENDATIONS")
            for rec in recommendations:
                lines.append(f"  {rec.get('message', '')}")
            lines.append("")
        
        return "\n".join(lines)
    
    def _run_end_of_day_review(self, **kwargs) -> str:
        """Run end-of-day review workflow"""
        logger.info("[WORKFLOW_TOOL] Generating end-of-day review")
        
        review = self.workflows.end_of_day_review()
        
        # Format as readable text
        lines = []
        lines.append("🌙 END OF DAY REVIEW")
        lines.append("=" * 50)
        lines.append("")
        
        # Today's accomplishments
        today = review.get('today', {})
        lines.append("✅ TODAY'S ACCOMPLISHMENTS")
        lines.append(f"• Events Attended: {today.get('events_attended', 0)}")
        lines.append(f"• Tasks Completed: {today.get('tasks_completed', 0)}")
        
        if today.get('completed_task_list'):
            lines.append("")
            lines.append("Completed Tasks:")
            for task in today['completed_task_list'][:5]:
                lines.append(f"  ✓ {task.get('title', 'Untitled')}")
        lines.append("")
        
        # Tomorrow's preview
        tomorrow = review.get('tomorrow', {})
        lines.append("📅 TOMORROW'S PREVIEW")
        lines.append(f"• Scheduled Events: {tomorrow.get('scheduled_events', 0)}")
        lines.append(f"• Tasks Due: {tomorrow.get('tasks_due', 0)}")
        
        if tomorrow.get('event_list'):
            lines.append("")
            lines.append("Tomorrow's Events:")
            for event in tomorrow['event_list'][:3]:
                time = event.get('start', {}).get('dateTime', '')
                if time:
                    time = time[11:16]  # Extract HH:MM
                lines.append(f"  • {time} - {event.get('summary', 'Untitled')}")
        lines.append("")
        
        # Summary
        summary = review.get('summary', {})
        lines.append("📊 SUMMARY")
        lines.append(f"• Productivity Score: {summary.get('productivity_score', 0)}/100")
        lines.append(f"• Overdue Tasks: {summary.get('overdue_tasks', 0)}")
        lines.append("")
        
        return "\n".join(lines)
    
    async def _arun(self, **kwargs) -> str:
        """Async execution (calls sync version)"""
        return self._run(**kwargs)
    
    def _handle_error(self, error: Exception, context: str) -> str:
        """Handle and format errors"""
        logger.error(f"[WORKFLOW_TOOL] Error in {context}: {error}", exc_info=True)
        return f"[ERROR] Failed to run {context}: {str(error)}"
