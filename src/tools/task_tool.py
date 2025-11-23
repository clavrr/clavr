"""
Task Tool - Service Layer Integration

Orchestrates task operations using the TaskService business logic layer.

Architecture:
    TaskTool → TaskService → GoogleTasksClient/TaskManager → Tasks API

The service layer provides:
- Clean business logic interfaces
- Centralized error handling
- Shared code between tools and workers
- Better testability

For advanced features, specialized modules are used:
- tasks/email_integration.py: Email-to-task features
- tasks/calendar_integration.py: Calendar-to-task features
- tasks/ai_features.py: AI-powered extraction and enhancement
- tasks/summarize_integration.py: Task summarization
"""
from typing import Optional, Any, List, Dict
from datetime import datetime
from pydantic import BaseModel, Field

from .base_tool import ClavrBaseTool
from .constants import ToolConfig, ParserIntegrationConfig, ToolLimits
from .tasks.constants import (
    DEFAULT_PRIORITY,
    DEFAULT_STATUS,
    DEFAULT_ANALYTICS_DAYS,
    DEFAULT_DAYS_AHEAD,
    DEFAULT_DURATION_MINUTES
)
from ..integrations.google_tasks.service import TaskService
from ..integrations.google_tasks.exceptions import TaskServiceException
from ..utils.logger import setup_logger
from ..utils.config import Config
from ..ai.prompts import (
    TASK_CONVERSATIONAL_LIST,
    TASK_CONVERSATIONAL_EMPTY
)

logger = setup_logger(__name__)


class TaskActionInput(BaseModel):
    """Input schema for task operations"""
    action: str = Field(
        description="Action to perform: 'create', 'list', 'complete', 'delete', 'update', 'search', 'analytics', 'bulk_complete', 'bulk_delete', 'get_subtasks', 'get_reminders', 'get_overdue'"
    )
    description: Optional[str] = Field(default=None, description="Task description")
    due_date: Optional[str] = Field(default=None, description="Task due date (ISO format)")
    priority: Optional[str] = Field(default="medium", description="Priority: low, medium, high, critical")
    category: Optional[str] = Field(default=None, description="Task category (work, personal, etc.)")
    task_id: Optional[str] = Field(default=None, description="Task ID (for complete/delete)")
    status: Optional[str] = Field(default="pending", description="Task status filter for listing")
    tags: Optional[List[str]] = Field(default=None, description="Task tags")
    project: Optional[str] = Field(default=None, description="Project name")
    parent_id: Optional[str] = Field(default=None, description="Parent task ID for subtasks")
    subtasks: Optional[List[str]] = Field(default=None, description="List of subtask descriptions")
    notes: Optional[str] = Field(default=None, description="Task notes")
    recurrence: Optional[str] = Field(default=None, description="Recurrence pattern")
    reminder_days: Optional[int] = Field(default=None, description="Days before due date to send reminder")
    estimated_hours: Optional[float] = Field(default=None, description="Estimated hours to complete")
    query: Optional[str] = Field(default=None, description="Search query")
    task_ids: Optional[List[str]] = Field(default=None, description="List of task IDs for bulk operations")
    days: Optional[int] = Field(default=30, description="Number of days for analytics")


class TaskTool(ClavrBaseTool):
    """
    Task/To-Do management tool with service layer integration

    Architecture:
        TaskTool → TaskService → GoogleTasksClient/TaskManager → Tasks API

    Capabilities:
    - Create, update, delete tasks
    - List and search tasks with advanced filtering
    - Mark tasks as complete
    - Bulk operations
    - Email integration (create tasks from emails)
    - Calendar integration (schedule task time, create prep/follow-up tasks)
    - AI-powered task extraction from text
    - AI-powered task enhancement
    - Task summarization and analytics

    Examples:
    "Create a task to review budget by Friday"
    "Show me my high priority tasks"
    "Extract tasks from this email"
    "Schedule time for task XYZ"
    """

    name: str = "tasks"
    description: str = (
        "Manage tasks and to-do items. "
        "Can create tasks, list pending items, mark as complete, and delete. "
        "Supports email integration, calendar integration, and AI-powered features. "
        "Use this tool for comprehensive task management."
    )
    args_schema: type[BaseModel] = TaskActionInput
    config: Optional[Config] = Field(default=None, exclude=True)

    def __init__(
        self,
        config: Optional[Config] = None,
        user_id: Optional[int] = None,
        credentials: Optional[Any] = None,
        **kwargs
    ):
        """
        Initialize task tool with service layer integration

        Args:
            config: Configuration object for Google Tasks integration
            user_id: User ID for loading credentials from session
            credentials: OAuth credentials (if provided, will be used directly)
        """
        super().__init__(config=config, **kwargs)
        self._set_attr('_user_id', user_id)
        self._set_attr('_credentials', credentials)
        self._set_attr('_task_service', None)
        
        # Lazy-loaded modular components (for advanced features)
        self._set_attr('_email_integration', None)
        self._set_attr('_calendar_integration', None)
        self._set_attr('_ai_features', None)
        self._set_attr('_summarize_integration', None)
        
        # Parser for intelligent query understanding
        self._set_attr('_parser', None)
        
        # Context tracking for follow-up queries (stores last shown task list)
        self._set_attr('_last_task_list', None)
        self._set_attr('_last_task_list_query', None)

        # Initialize handlers (use _set_attr to bypass Pydantic validation)
        from .tasks.formatting_handlers import TaskFormattingHandlers
        from .tasks.action_handlers import TaskActionHandlers
        from .tasks.query_handlers import TaskQueryHandlers
        
        self._set_attr('formatting_handlers', TaskFormattingHandlers(self))
        self._set_attr('action_handlers', TaskActionHandlers(self))
        self._set_attr('query_handlers', TaskQueryHandlers(self))

        # Override date_parser with config if needed
        if config and self.date_parser is None:
            try:
                from ..utils import FlexibleDateParser
                self._set_attr('date_parser', FlexibleDateParser(config))
            except Exception as e:
                logger.debug(f"FlexibleDateParser with config not available: {e}")

    # ===================================================================
    # PROPERTIES - Task Service
    # ===================================================================

    @property
    def task_service(self) -> TaskService:
        """Get or create Task service with user credentials"""
        if self._task_service is None:
            logger.info(f"[TASKS] Initializing TaskService - user_id={self._user_id}")

            # Get credentials if not already provided
            credentials = self._credentials
            if not credentials and self._user_id:
                logger.info(f"[TASKS] Loading credentials from session for user_id={self._user_id}")
                credentials = self._get_credentials_from_session(self._user_id, service_name="TASKS")
            
            # Create task service with credentials
            # Note: storage_path removed in v3.0.0 - TaskService now requires Google Tasks API
            self._task_service = TaskService(
                config=self.config,
                credentials=credentials
            )

            logger.info(f"[OK] TaskService initialized (user_id={self._user_id})")
        
        return self._task_service

    # ===================================================================
    # PROPERTIES - Modular Components (for advanced features)
    # ===================================================================

    @property
    def email_integration(self):
        """Get or create EmailIntegration module"""
        if self._email_integration is None:
            from .tasks.email_integration import EmailIntegration
            self._email_integration = EmailIntegration(self)
            logger.debug("[MODULE] EmailIntegration loaded")
        return self._email_integration

    @property
    def calendar_integration(self):
        """Get or create CalendarIntegration module"""
        if self._calendar_integration is None:
            from .tasks.calendar_integration import CalendarIntegration
            self._calendar_integration = CalendarIntegration(self)
            logger.debug("[MODULE] CalendarIntegration loaded")
        return self._calendar_integration

    @property
    def ai_features(self):
        """Get or create AIFeatures module"""
        if self._ai_features is None:
            from .tasks.ai_features import AIFeatures
            self._ai_features = AIFeatures(self)
            logger.debug("[MODULE] AIFeatures loaded")
        return self._ai_features

    @property
    def summarize_integration(self):
        """Get or create SummarizeIntegration module"""
        if self._summarize_integration is None:
            from .tasks.summarize_integration import SummarizeIntegration
            self._summarize_integration = SummarizeIntegration(self)
            logger.debug("[MODULE] SummarizeIntegration loaded")
        return self._summarize_integration
    
    @property
    def parser(self):
        """
        Get or create TaskParser for intelligent query understanding
        
        Lazily initializes the parser on first use. Parser provides:
        - Action classification (create, list, complete, delete, etc.)
        - Entity extraction (description, due_date, priority, category)
        - Confidence scoring for parsed entities
        - Suggestions for ambiguous queries
        
        Returns None if config is not available (parser requires config).
        """
        if self._parser is None and self.config:
            try:
                from ..agent.parsers.task_parser import TaskParser
                parser_instance = TaskParser(
                    rag_service=None,
                    memory=None,
                    config=self.config
                )
                self._parser = parser_instance
                logger.info("[TASK] TaskParser initialized for intelligent query understanding")
            except Exception as e:
                logger.warning(f"[TASK] TaskParser initialization failed (queries will use fallback parsing): {e}")
                self._parser = None
        return self._parser

    # ===================================================================
    # CROSS-TOOL INTEGRATION - EMAIL
    # ===================================================================

    def create_task_from_email(
        self,
        email_id: str,
        email_data: Dict[str, Any],
        extract_action_items: bool = True,
        auto_prioritize: bool = True
    ) -> str:
        """Create task(s) from email content"""
        return self.email_integration.create_task_from_email(
            email_id, email_data, extract_action_items, auto_prioritize
        )

    def link_task_to_email(
        self,
        task_id: str,
        email_id: str,
        email_subject: Optional[str] = None
    ) -> str:
        """Link existing task to an email"""
        return self.email_integration.link_task_to_email(task_id, email_id, email_subject)

    def search_tasks_by_email(
        self,
        email_id: Optional[str] = None,
        sender: Optional[str] = None,
        subject_keyword: Optional[str] = None
    ) -> str:
        """Find tasks related to emails"""
        return self.email_integration.search_tasks_by_email(email_id, sender, subject_keyword)

    # ===================================================================
    # CROSS-TOOL INTEGRATION - CALENDAR
    # ===================================================================

    def create_task_from_event(
        self,
        event_id: str,
        event_data: Dict[str, Any],
        task_type: str = "preparation"
    ) -> str:
        """Create task from calendar event (preparation or follow-up)"""
        return self.calendar_integration.create_task_from_event(event_id, event_data, task_type)

    def schedule_task_time(
        self,
        task_id: str,
        preferred_time: Optional[str] = None,
        duration_minutes: int = DEFAULT_DURATION_MINUTES,
        calendar_tool: Optional[Any] = None
    ) -> str:
        """Schedule time in calendar for working on task"""
        return self.calendar_integration.schedule_task_time(
            task_id, preferred_time, duration_minutes, calendar_tool
        )

    # ===================================================================
    # CROSS-TOOL INTEGRATION - SUMMARIZE
    # ===================================================================

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
        """Generate summary of tasks using SummarizeTool"""
        return self.summarize_integration.summarize_tasks(
            status, priority, category, days_ahead, summary_format, summary_length, summarize_tool
        )

    def summarize_accomplishments(
        self,
        period: str = "week",
        summary_format: str = "bullet_points",
        summarize_tool: Optional[Any] = None
    ) -> str:
        """Summarize completed tasks for a period"""
        return self.summarize_integration.summarize_accomplishments(period, summary_format, summarize_tool)

    # ===================================================================
    # AI-POWERED FEATURES
    # ===================================================================

    def extract_tasks_from_text(
        self,
        text: str,
        source_type: str = "text",
        auto_create: bool = False,
        default_priority: str = "medium"
    ) -> str:
        """Extract action items from arbitrary text using AI"""
        return self.ai_features.extract_tasks_from_text(text, source_type, auto_create, default_priority)

    def auto_enhance_task(
        self,
        task_description: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Use AI to suggest task enhancements"""
        return self.ai_features.auto_enhance_task(task_description, context)

    # ===================================================================
    # MAIN EXECUTION METHOD
    # ===================================================================

    def _run(
        self,
        action: str,
        description: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: str = DEFAULT_PRIORITY,
        category: Optional[str] = None,
        task_id: Optional[str] = None,
        status: Optional[str] = DEFAULT_STATUS,
        tags: Optional[List[str]] = None,
        project: Optional[str] = None,
        parent_id: Optional[str] = None,
        subtasks: Optional[List[str]] = None,
        notes: Optional[str] = None,
        recurrence: Optional[str] = None,
        reminder_days: Optional[int] = None,
        estimated_hours: Optional[float] = None,
        query: Optional[str] = None,
        task_ids: Optional[List[str]] = None,
        days: Optional[int] = DEFAULT_ANALYTICS_DAYS,
        **kwargs
    ) -> str:
        """
        Main execution method - uses TaskService for core operations
        
        Routes to TaskService for CRUD operations and specialized modules
        for advanced features (email/calendar integration, AI features).
        
        PARSER INTEGRATION: If a query is provided, the parser enhances
        parameter extraction and action classification.
        """
        self._log_execution(action, description=description, task_id=task_id)
        
        # === PARSER INTEGRATION (Priority 1 Fix) ===
        # Use parser to enhance parameter extraction if query is provided
        if query and self.parser:
            try:
                parsed = self.parser.parse_query_to_params(
                    query=query,
                    user_id=self._user_id,
                    session_id=None
                )
                
                logger.info(f"[TASK] Parser result: action={parsed['action']}, confidence={parsed['confidence']}")
                
                # CRITICAL: Always use parser-detected action if it's a critical action (create, complete, delete, etc.)
                # These actions should NEVER be misclassified as list/search
                parsed_action = parsed['action']
                critical_actions = ['create', 'complete', 'delete', 'bulk_complete', 'update']
                is_critical_action = parsed_action in critical_actions
                
                # Use parsed action if:
                # 1. It's a critical action (always override)
                # 2. Confidence is high AND current action is overridable (search/list/default)
                # 3. Current action is None or empty
                is_overridable_action = action in ParserIntegrationConfig.OVERRIDABLE_ACTIONS or action == ParserIntegrationConfig.DEFAULT_ACTION_FALLBACK
                has_high_confidence = parsed['confidence'] >= ParserIntegrationConfig.USE_PARSED_ACTION_THRESHOLD
                
                if is_critical_action or (has_high_confidence and (not action or is_overridable_action)):
                    old_action = action
                    action = parsed_action
                    logger.info(f"[TASK] Using parser-detected action: {old_action} → {action} (confidence: {parsed['confidence']:.2f})")
                    
                    # If parser detected 'create' but we had 'list' or 'search', log a warning
                    if parsed_action == 'create' and old_action in ['list', 'search']:
                        logger.warning(f"[TASK] CRITICAL: Parser corrected misclassification: '{old_action}' → 'create' for query: '{query}'")
                
                # Enhance parameters with parsed entities (only if not already provided)
                entities = parsed.get('entities', {})
                if not description and 'description' in entities:
                    description = entities['description']
                    logger.info(f"[TASK] Using parser-extracted description: {description}")
                if not due_date and 'due_date' in entities:
                    due_date = str(entities['due_date'])
                    logger.info(f"[TASK] Using parser-extracted due_date: {due_date}")
                if priority == DEFAULT_PRIORITY and 'priority' in entities:  # Only override default
                    priority = entities['priority']
                    logger.info(f"[TASK] Using parser-extracted priority: {priority}")
                if not category and 'category' in entities:
                    category = entities['category']
                    logger.info(f"[TASK] Using parser-extracted category: {category}")
                
                # Log low-confidence warnings
                if parsed['confidence'] < ParserIntegrationConfig.LOW_CONFIDENCE_WARNING_THRESHOLD:
                    logger.warning(f"[TASK] Low confidence parse ({parsed['confidence']}). Suggestions: {parsed.get('metadata', {}).get('suggestions', [])}")
                    
            except Exception as e:
                logger.warning(f"[TASK] Parser enhancement failed (continuing with original params): {e}")

        try:
            # === CORE OPERATIONS (via TaskService) ===
            if action == "create":
                return self.action_handlers.handle_create(
                    description=description,
                    due_date=due_date,
                    priority=priority,
                    category=category,
                    tags=tags,
                    project=project,
                    parent_id=parent_id,
                    notes=notes,
                    recurrence=recurrence,
                    reminder_days=reminder_days,
                    estimated_hours=estimated_hours,
                    subtasks=subtasks,
                    query=query,
                    **kwargs
                )
            
            elif action == "list":
                return self.query_handlers.handle_list(
                    status=status,
                    priority=priority,
                    category=category,
                    tags=tags,
                    project=project,
                    description=description,
                    due_date=due_date,
                    query=query,
                    **kwargs
                )
            
            elif action == "complete":
                return self.action_handlers.handle_complete(
                    task_id=task_id,
                    description=description,
                    query=query,
                    **kwargs
                )
            
            elif action == "delete":
                return self.action_handlers.handle_delete(
                    task_id=task_id,
                    description=description,
                    query=query,
                    **kwargs
                )
            
            elif action == "update":
                return self.action_handlers.handle_update(
                    task_id=task_id,
                    description=description,
                        due_date=due_date,
                        priority=priority,
                        category=category,
                        tags=tags,
                        notes=notes,
                    status=status,
                    query=query,
                    **kwargs
                )
            
            elif action == "search" or action == "search_tasks":
                # Handle both "search" and "search_tasks" actions
                # If query contains "today", convert to list action with today filter
                if query and "today" in query.lower():
                    logger.info(f"[TASK] Converting 'search'/'search_tasks' to 'list' for 'today' query: {query}")
                    return self.query_handlers.handle_list(
                        status=status,
                        priority=priority,
                        category=category,
                        tags=tags,
                        project=project,
                        description=description,
                        due_date=due_date,
                        query=query,
                        **kwargs
                    )
                return self.query_handlers.handle_search(
                    query=query,
                    description=description,
                    tags=tags,
                    category=category,
                    priority=priority,
                    status=status,
                    due_date=due_date,
                    **kwargs
                )
            
            elif action == "analytics":
                return self.query_handlers.handle_analytics(
                    days=days,
                    **kwargs
                )
            
            elif action == "get_overdue":
                return self.query_handlers.handle_get_overdue(
                    query=query,
                    **kwargs
                )
            
            elif action == "get_due_today":
                return self.query_handlers.handle_get_due_today(
                    query=query,
                    **kwargs
                )
            
            elif action == "get_completed":
                return self.query_handlers.handle_get_completed(
                    query=query,
                    **kwargs
                )
            
            elif action == "get_by_priority":
                return self.query_handlers.handle_get_by_priority(
                    priority=priority,
                    query=query,
                    **kwargs
                )
            
            elif action == "bulk_complete":
                # If task_ids not provided, get all pending tasks
                if not task_ids:
                    # Get all pending tasks
                    all_pending_tasks = self.task_service.list_tasks(status="pending", show_completed=False, limit=1000)
                    task_ids = [task_id for task in all_pending_tasks if (task_id := task.get('id')) is not None]
                    
                    if not task_ids:
                        return "You don't have any pending tasks to complete."
                
                result = self.task_service.bulk_complete(task_ids)
                # bulk_complete returns 'success' and 'total', not 'success_count' and 'total_count'
                success_count = result.get('success', result.get('success_count', 0))
                total_count = result.get('total', result.get('total_count', len(task_ids)))
                failed_count = result.get('failed', 0)
                
                if success_count == total_count:
                    return f"Successfully completed all {success_count} task{'s' if success_count != 1 else ''}!"
                elif success_count > 0:
                    return f"Completed {success_count} out of {total_count} tasks. {failed_count} task{'s' if failed_count != 1 else ''} failed."
                else:
                    return f"[ERROR] Failed to complete any tasks. {result.get('error', 'Unknown error')}"
            
            elif action == "bulk_delete":
                if not task_ids:
                    return "[ERROR] Please provide 'task_ids' for bulk_delete action"
                
                result = self.task_service.bulk_delete(task_ids)
                return f"Deleted {result['success_count']} tasks"
            
            elif action == "get_subtasks":
                if not (parent_id or task_id):
                    return "[ERROR] Please provide 'parent_id' or 'task_id' for get_subtasks action"
                
                # Note: This feature may need to be implemented in TaskService
                return "[INFO] Subtasks feature in development"
            
            elif action == "get_reminders":
                # Note: This feature may need to be implemented in TaskService
                return "[INFO] Reminders feature in development"
            
            else:
                return f"[ERROR] Unknown action: {action}"

        except TaskServiceException as e:
            return f"[ERROR] Task service error: {str(e)}"
        except Exception as e:
            return self._handle_error(e, f"executing action '{action}'")

    async def _arun(self, action: str, **kwargs) -> str:
        """Async execution (delegates to sync version for now)"""
        return self._run(action=action, **kwargs)
    
    # ===================================================================
    # HELPER METHODS
    # ===================================================================
    
    
    def _handle_error(self, error: Exception, context: str) -> str:
        """Handle and format errors"""
        error_msg = f"[ERROR] Failed {context}: {str(error)}"
        logger.error(error_msg, exc_info=True)
        return error_msg
    
    def _log_execution(self, action: str, **kwargs) -> None:
        """Log execution details"""
        logger.info(f"[TASKS] Executing action '{action}' with params: {kwargs}")
    
    def _extract_task_description_from_complete_query(self, query: str) -> str:
        """Extract task description from complete queries like 'mark task X done'"""
        query_lower = query.lower()
        
        # Handle patterns like "mark task calling mom tonight done"
        for pattern in ["mark task", "mark the task", "mark my task", "mark task about"]:
            if pattern in query_lower:
                start_idx = query_lower.find(pattern) + len(pattern)
                end_idx = query_lower.find(" done", start_idx)
                if end_idx == -1:
                    end_idx = len(query)
                description = query[start_idx:end_idx].strip()
                if description:
                    return description
        
        # Remove common action words
        words_to_remove = ['please', 'mark', 'task', 'tasks', 'done', 'complete', 'finish', 'as', 'the', 'my']
        words = [w for w in query.split() if w.lower() not in words_to_remove]
        return ' '.join(words) if words else query
    
    def _handle_follow_up_selection(self, query: str, description: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Handle follow-up selections like "the first one", "the second one", "the one due tonight"
        
        Uses stored context from previous task list, or uses parser/memory to understand context.
        """
        query_lower = query.lower().strip()
        tasks = self._last_task_list
        
        # If no stored list, try to get recent tasks that might match
        if not tasks:
            # Check if this is clearly a follow-up (has ordinal words)
            has_ordinal = any(word in query_lower for word in ['first', 'second', 'third', 'one', 'two', 'three', '1', '2', '3'])
            if has_ordinal:
                # Get all pending tasks as context
                try:
                    tasks = self.task_service.list_tasks(status="pending", limit=10)
                    logger.info(f"[TASK] No stored list, using all pending tasks as context ({len(tasks)} tasks)")
                except:
                    return None
            else:
                return None
        
        # Handle ordinal references: "first", "second", "third", "1st", "2nd", etc.
        ordinal_patterns = {
            'first': 0, '1st': 0, 'one': 0, '1': 0,
            'second': 1, '2nd': 1, 'two': 1, '2': 1,
            'third': 2, '3rd': 2, 'three': 2, '3': 2,
            'fourth': 3, '4th': 3, 'four': 3, '4': 3,
            'fifth': 4, '5th': 4, 'five': 4, '5': 4,
        }
        
        for pattern, index in ordinal_patterns.items():
            if pattern in query_lower and index < len(tasks):
                logger.info(f"[TASK] Resolved ordinal reference '{pattern}' to index {index}")
                return tasks[index]
        
        # Handle date-based references: "the one due tonight", "the one due tomorrow", etc.
        if "due" in query_lower:
            # Try to extract date reference
            date_keywords = ['tonight', 'today', 'tomorrow', 'yesterday']
            for keyword in date_keywords:
                if keyword in query_lower:
                    # Find task with matching due date
                    from datetime import datetime, timedelta
                    today = datetime.now().date()
                    
                    if keyword == 'tonight' or keyword == 'today':
                        target_date = today
                    elif keyword == 'tomorrow':
                        target_date = today + timedelta(days=1)
                    elif keyword == 'yesterday':
                        target_date = today - timedelta(days=1)
                    else:
                        continue
                    
                    for task in tasks:
                        due_date = task.get('due_date', task.get('due', None))
                        if due_date:
                            try:
                                if isinstance(due_date, str):
                                    task_date = datetime.fromisoformat(due_date.replace('Z', '+00:00')).date()
                                else:
                                    task_date = due_date.date() if hasattr(due_date, 'date') else None
                                
                                if task_date == target_date:
                                    logger.info(f"[TASK] Resolved date reference '{keyword}' to task due {target_date}")
                                    return task
                            except:
                                continue
        
        # Handle "not done" or "pending" references
        if any(phrase in query_lower for phrase in ["not done", "pending", "not completed", "still pending"]):
            pending_tasks = [t for t in tasks if t.get('status', 'pending') != 'completed']
            if len(pending_tasks) == 1:
                logger.info(f"[TASK] Resolved 'not done' reference to single pending task")
                return pending_tasks[0]
        
        # Handle "already done" or "completed" references
        if any(phrase in query_lower for phrase in ["already done", "completed", "done already"]):
            completed_tasks = [t for t in tasks if t.get('status', 'pending') == 'completed']
            if len(completed_tasks) == 1:
                logger.info(f"[TASK] Resolved 'already done' reference to single completed task")
                return completed_tasks[0]
        
        # If description provided, try to match by description
        if description:
            matching = [t for t in tasks if description.lower() in t.get('title', '').lower()]
            if len(matching) == 1:
                logger.info(f"[TASK] Resolved description reference '{description}'")
                return matching[0]
        
        return None
