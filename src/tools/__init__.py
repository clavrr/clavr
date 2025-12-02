"""
Tools Module - LangChain-compatible tools for email, calendar, tasks, and more

These tools wrap the parsers and provide a unified interface for the orchestrator.
"""
from typing import Optional, Any, Dict
from langchain.tools import BaseTool
from pydantic import Field

from ..utils.logger import setup_logger
from ..utils.config import Config

logger = setup_logger(__name__)


class EmailTool(BaseTool):
    """Email management tool wrapping EmailParser"""
    name: str = "email"
    description: str = "Email management (search, send, reply, organize). Use this for any email-related queries."
    
    config: Optional[Config] = Field(default=None)
    rag_engine: Optional[Any] = Field(default=None)
    user_id: int = Field(default=1)
    credentials: Optional[Any] = Field(default=None)
    user_first_name: Optional[str] = Field(default=None)
    _parser: Optional[Any] = None
    
    def __init__(self, config: Optional[Config] = None, rag_engine: Optional[Any] = None, 
                 user_id: int = 1, credentials: Optional[Any] = None, user_first_name: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.rag_engine = rag_engine
        self.user_id = user_id
        self.credentials = credentials
        self.user_first_name = user_first_name
        self._parser = None
    
    def _initialize_parser(self):
        """Lazy initialization of parser"""
        if self._parser is None:
            try:
                from ..agent.parsers.email_parser import EmailParser
                from ..services.rag_service import RAGService
                
                # Create RAG service 
                rag_service = None
                if self.config:
                    rag_service = RAGService(config=self.config, collection_name="email-knowledge")
                    # Use provided rag_engine 
                    if self.rag_engine:
                        rag_service.rag_engine = self.rag_engine
                
                self._parser = EmailParser(
                    rag_service=rag_service,
                    memory=None,
                    config=self.config,
                    user_first_name=self.user_first_name
                )
                
                # Set google_client if credentials available
                if self.credentials:
                    from ..core.email.google_client import GoogleGmailClient
                    self._parser.google_client = GoogleGmailClient(
                        config=self.config,
                        credentials=self.credentials
                    )
            except Exception as e:
                logger.error(f"Failed to initialize EmailParser: {e}")
                raise
    
    def _run(self, action: str = "search", query: str = "", **kwargs) -> str:
        """Execute email tool action"""
        workflow_emitter = kwargs.get('workflow_emitter')
        
        self._initialize_parser()
        if self._parser is None:
            return "Error: Email parser not initialized"
        
        # Set workflow_emitter on parser so handlers can emit events
        if workflow_emitter and hasattr(self._parser, 'workflow_emitter'):
            self._parser.workflow_emitter = workflow_emitter
        
        try:
            # Emit action executing event
            if workflow_emitter:
                self._emit_action_event(workflow_emitter, 'executing', f"Processing email {action}", action=action)
            
            # CRITICAL: Handle empty queries before processing
            # Some actions don't require a query, others should default to inbox
            if not query or not query.strip():
                if action == "unread":
                    # Unread action doesn't need a query - route directly
                    result = self._parser.action_handlers.handle_list_action(self, "is:unread")
                elif action == "list":
                    # List action doesn't need a query - route directly to inbox
                    result = self._parser.action_handlers.handle_list_action(self, "in:inbox")
                elif action == "search":
                    # Search with empty query should default to inbox search
                    result = self._parser.action_handlers.handle_search_action(self, "in:inbox")
                else:
                    # For other actions with empty query, default to inbox list
                    logger.debug(f"[EMAIL] Empty query for action '{action}', defaulting to inbox list")
                    result = self._parser.action_handlers.handle_list_action(self, "in:inbox")
            # CRITICAL: If query is already a Gmail search query (starts with "in:", "from:", "after:", etc.),
            # execute it directly to avoid infinite recursion. Otherwise, use parse_query to route properly.
            elif query and (query.startswith("in:") or query.startswith("from:") or 
                         query.startswith("after:") or query.startswith("before:") or
                         query.startswith("is:") or query.startswith("has:") or
                         query.startswith("subject:") or query.startswith("label:")):
                # Direct Gmail query - execute directly using action handlers
                if action == "search":
                    result = self._parser.action_handlers.handle_search_action(self, query)
                elif action == "list":
                    result = self._parser.action_handlers.handle_list_action(self, query)
                elif action == "unread":
                    result = self._parser.action_handlers.handle_list_action(self, f"{query} is:unread" if query else "is:unread")
                else:
                    # For other actions, use parse_query
                    result = self._parser.parse_query(query, self, user_id=self.user_id)
            else:
                # Natural language query - use parse_query to route properly
                result = self._parser.parse_query(query, self, user_id=self.user_id)
            
            # Emit action complete event
            if workflow_emitter:
                result_summary = result[:100] if result else "completed"
                self._emit_action_event(workflow_emitter, 'complete', f"Email {action} completed", action=action, result=result_summary)
            
            return result
        except Exception as e:
            logger.error(f"EmailTool error: {e}", exc_info=True)
            # Emit error event
            if workflow_emitter:
                self._emit_action_event(workflow_emitter, 'error', f"Email {action} failed: {str(e)}", action=action, error=str(e))
            return f"Error: {str(e)}"
    
    def _emit_action_event(self, workflow_emitter, event_type: str, message: str, **kwargs):
        """Helper to emit workflow action events (handles async safely)"""
        try:
            import asyncio
            # Try to get the running event loop
            try:
                loop = asyncio.get_running_loop()
                # If loop is running, schedule the coroutine as a task
                # This is safe because the orchestrator runs in an async context
                asyncio.create_task(self._emit_async(workflow_emitter, event_type, message, **kwargs))
            except RuntimeError:
                # No running loop - this shouldn't happen in normal operation
                # but if it does, we'll skip the event rather than creating a new loop
                logger.debug(f"No running event loop for workflow event emission (this is expected in some contexts)")
        except Exception as e:
            logger.debug(f"Failed to emit workflow event: {e}")
    
    async def _emit_async(self, workflow_emitter, event_type: str, message: str, **kwargs):
        """Async helper to emit workflow events"""
        try:
            if event_type == 'executing':
                await workflow_emitter.emit_action_executing(kwargs.get('action', 'email_operation'), data=kwargs)
            elif event_type == 'complete':
                await workflow_emitter.emit_action_complete(
                    kwargs.get('action', 'email_operation'),
                    result=kwargs.get('result', ''),
                    data=kwargs
                )
            elif event_type == 'error':
                await workflow_emitter.emit_error('action', message, data=kwargs)
        except Exception as e:
            logger.debug(f"Error emitting workflow event: {e}")
    
    async def _arun(self, action: str = "search", query: str = "", **kwargs) -> str:
        """Async execution"""
        return self._run(action=action, query=query, **kwargs)


class CalendarTool(BaseTool):
    """Calendar management tool wrapping CalendarParser"""
    name: str = "calendar"
    description: str = "Calendar management (create events, find free time, check conflicts). Use this for scheduling and calendar queries."
    
    config: Optional[Config] = Field(default=None)
    user_id: Optional[int] = Field(default=None)
    credentials: Optional[Any] = Field(default=None)
    rag_engine: Optional[Any] = Field(default=None)
    _parser: Optional[Any] = None
    
    def __init__(self, config: Optional[Config] = None, user_id: Optional[int] = None,
                 credentials: Optional[Any] = None, rag_engine: Optional[Any] = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.user_id = user_id
        self.credentials = credentials
        self.rag_engine = rag_engine
        self._parser = None
    
    def _initialize_parser(self):
        """Lazy initialization of parser"""
        if self._parser is None:
            try:
                from ..agent.parsers.calendar_parser import CalendarParser
                from ..services.rag_service import RAGService
                
                # Create RAG service if config provided
                rag_service = None
                if self.config:
                    rag_service = RAGService(config=self.config, collection_name="email-knowledge")
                    # Use provided rag_engine if available
                    if self.rag_engine:
                        rag_service.rag_engine = self.rag_engine
                
                self._parser = CalendarParser(
                    rag_service=rag_service,
                    memory=None,
                    config=self.config
                )
                
                # Set google_client if credentials available
                if self.credentials:
                    from ..core.calendar.google_client import GoogleCalendarClient
                    self._parser.google_client = GoogleCalendarClient(
                        config=self.config,
                        credentials=self.credentials
                    )
            except Exception as e:
                logger.error(f"Failed to initialize CalendarParser: {e}")
                raise
    
    def _run(self, action: str = "create", query: str = "", **kwargs) -> str:
        """Execute calendar tool action"""
        workflow_emitter = kwargs.get('workflow_emitter')
        
        self._initialize_parser()
        if self._parser is None:
            return "Error: Calendar parser not initialized"
        
        # Set workflow_emitter on parser so handlers can emit events
        if workflow_emitter and hasattr(self._parser, 'workflow_emitter'):
            self._parser.workflow_emitter = workflow_emitter
        
        try:
            # Emit action executing event
            if workflow_emitter:
                self._emit_action_event(workflow_emitter, 'executing', f"Processing calendar {action}", action=action)
            
            # If called with specific event parameters (from event handler), create event directly
            if kwargs.get('title') and kwargs.get('start_time'):
                # Direct event creation - called from event handler with parsed parameters
                if not hasattr(self._parser, 'google_client') or not self._parser.google_client:
                    return "Error: Google Calendar client not initialized"
                
                result = self._parser.google_client.create_event(
                    title=kwargs.get('title'),
                    start_time=kwargs.get('start_time'),
                    end_time=kwargs.get('end_time'),
                    duration_minutes=kwargs.get('duration_minutes', 60),
                    description=kwargs.get('description', ''),
                    location=kwargs.get('location', ''),
                    attendees=kwargs.get('attendees'),
                    recurrence=kwargs.get('recurrence')
                )
                
                if result:
                    event_title = result.get('summary') or kwargs.get('title')
                    logger.info(f"[CalendarTool] Created event: {event_title}")
                    result_str = f"Created event: {event_title}"
                    
                    # Emit action complete event
                    if workflow_emitter:
                        self._emit_action_event(workflow_emitter, 'complete', f"Calendar event created: {event_title}", action=action, result=event_title)
                    
                    return result_str
                else:
                    error_msg = "Error: Failed to create calendar event"
                    if workflow_emitter:
                        self._emit_action_event(workflow_emitter, 'error', error_msg, action=action)
                    return error_msg
            
            # Otherwise, route through parse_query to handle query parsing and execution
            # This handles queries like "schedule a meeting today at 6 PM"
            if query:
                result = self._parser.parse_query(query, self, user_id=self.user_id)
                
                # Emit action complete event
                if workflow_emitter:
                    result_summary = result[:100] if result else "completed"
                    self._emit_action_event(workflow_emitter, 'complete', f"Calendar {action} completed", action=action, result=result_summary)
                
                return result
            else:
                error_msg = "Error: No query or event parameters provided"
                if workflow_emitter:
                    self._emit_action_event(workflow_emitter, 'error', error_msg, action=action)
                return error_msg
        except Exception as e:
            logger.error(f"CalendarTool error: {e}", exc_info=True)
            # Emit error event
            if workflow_emitter:
                self._emit_action_event(workflow_emitter, 'error', f"Calendar {action} failed: {str(e)}", action=action, error=str(e))
            return f"Error: {str(e)}"
    
    def _emit_action_event(self, workflow_emitter, event_type: str, message: str, **kwargs):
        """Helper to emit workflow action events (handles async safely)"""
        try:
            import asyncio
            # Try to get the running event loop
            try:
                loop = asyncio.get_running_loop()
                # If loop is running, schedule the coroutine as a task
                # This is safe because the orchestrator runs in an async context
                asyncio.create_task(self._emit_async(workflow_emitter, event_type, message, **kwargs))
            except RuntimeError:
                # No running loop - this shouldn't happen in normal operation
                # but if it does, we'll skip the event rather than creating a new loop
                logger.debug(f"No running event loop for workflow event emission (this is expected in some contexts)")
        except Exception as e:
            logger.debug(f"Failed to emit workflow event: {e}")
    
    async def _emit_async(self, workflow_emitter, event_type: str, message: str, **kwargs):
        """Async helper to emit workflow events"""
        try:
            if event_type == 'executing':
                await workflow_emitter.emit_action_executing(kwargs.get('action', 'calendar_operation'), data=kwargs)
            elif event_type == 'complete':
                await workflow_emitter.emit_action_complete(
                    kwargs.get('action', 'calendar_operation'),
                    result=kwargs.get('result', ''),
                    data=kwargs
                )
            elif event_type == 'error':
                await workflow_emitter.emit_error('action', message, data=kwargs)
        except Exception as e:
            logger.debug(f"Error emitting workflow event: {e}")
    
    async def _arun(self, action: str = "create", query: str = "", **kwargs) -> str:
        """Async execution"""
        return self._run(action=action, query=query, **kwargs)


class TaskTool(BaseTool):
    """Task management tool wrapping TaskService for Google Tasks API"""
    name: str = "tasks"
    description: str = "Task management (create, list, complete, search). Use this for task-related queries."
    
    storage_path: str = Field(default="./data/tasks.json")
    config: Optional[Config] = Field(default=None)
    user_id: int = Field(default=1)
    credentials: Optional[Any] = Field(default=None)
    user_first_name: Optional[str] = Field(default=None)
    _parser: Optional[Any] = None
    _task_service: Optional[Any] = None
    
    def __init__(self, storage_path: str = "./data/tasks.json", config: Optional[Config] = None,
                 user_id: int = 1, credentials: Optional[Any] = None, user_first_name: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.storage_path = storage_path
        self.config = config
        self.user_id = user_id
        self.credentials = credentials
        self.user_first_name = user_first_name
        self._parser = None
        self._task_service = None
    
    @property
    def task_service(self) -> Optional[Any]:
        """Lazy initialization of task service for Google Tasks API access"""
        if self._task_service is None and self.credentials and self.config:
            try:
                from ..integrations.google_tasks.service import TaskService
                self._task_service = TaskService(
                    config=self.config,
                    credentials=self.credentials
                )
                logger.info("[TaskTool] TaskService initialized successfully")
            except Exception as e:
                logger.warning(f"[TaskTool] Failed to initialize TaskService: {e}")
        return self._task_service
    
    def _initialize_parser(self):
        """Lazy initialization of parser"""
        if self._parser is None:
            try:
                from ..agent.parsers.task_parser import TaskParser
                
                self._parser = TaskParser(
                    rag_service=None,
                    memory=None,
                    config=self.config,
                    user_first_name=self.user_first_name
                )
                
                # Set google_client if credentials available
                if self.credentials:
                    from ..core.tasks.google_client import GoogleTasksClient
                    self._parser.google_client = GoogleTasksClient(
                        config=self.config,
                        credentials=self.credentials
                    )
            except Exception as e:
                logger.error(f"Failed to initialize TaskParser: {e}")
                raise
    
    def _run(self, action: str = "create", query: str = "", **kwargs) -> str:
        """Execute task tool action - CRITICAL: Must return actual task data, not metadata"""
        workflow_emitter = kwargs.get('workflow_emitter')
        
        # Initialize parser early so extraction methods are available
        self._initialize_parser()
        
        # Set workflow_emitter on parser so handlers can emit events
        if workflow_emitter and self._parser and hasattr(self._parser, 'workflow_emitter'):
            self._parser.workflow_emitter = workflow_emitter
        
        try:
            # CRITICAL FIX: For list/search actions, fetch ACTUAL tasks from Google Tasks API
            # The old code returned parse metadata like "{'action': 'list'}" causing LLM hallucination
            
            if action == "list" and self.task_service:
                # Fetch actual tasks from Google Tasks API
                status = kwargs.get('status', 'pending')
                limit = kwargs.get('limit', 100)
                tasks = self.task_service.list_tasks(status=status, limit=limit)
                
                if not tasks:
                    return "You don't have any pending tasks right now."
                
                # Format tasks for natural response
                task_lines = []
                for i, task in enumerate(tasks[:20], 1):  # Limit to 20 for response
                    title = task.get('title', task.get('description', 'Untitled'))
                    due = task.get('due')
                    status_str = task.get('status', 'needsAction')
                    
                    line = f"{i}. {title}"
                    if due:
                        line += f" (due: {due})"
                    if status_str == 'completed':
                        line += " [DONE]"
                    task_lines.append(line)
                
                result = f"Your tasks ({len(tasks)} total):\n" + "\n".join(task_lines)
                if len(tasks) > 20:
                    result += f"\n... and {len(tasks) - 20} more tasks"
                return result
                
            elif action == "search" and self.task_service:
                # Search tasks
                search_terms = kwargs.get('search_terms', query)
                tasks = self.task_service.list_tasks(status='all', limit=100)
                
                # Filter by search terms
                search_lower = search_terms.lower()
                matching = [t for t in tasks if search_lower in t.get('title', '').lower() 
                           or search_lower in t.get('notes', '').lower()]
                
                if not matching:
                    return f"I couldn't find any tasks matching '{search_terms}'."
                
                task_lines = []
                for i, task in enumerate(matching[:10], 1):
                    title = task.get('title', 'Untitled')
                    task_lines.append(f"{i}. {title}")
                
                return f"Found {len(matching)} tasks matching '{search_terms}':\n" + "\n".join(task_lines)
            
            elif action == "complete" and self.task_service:
                task_desc = kwargs.get('task_description', query)
                # Find and complete the task
                tasks = self.task_service.list_tasks(status='pending', limit=100)
                task_lower = task_desc.lower()
                
                for task in tasks:
                    title = task.get('title', '').lower()
                    if task_lower in title or title in task_lower:
                        task_id = task.get('id')
                        if task_id:
                            self.task_service.complete_task(task_id)
                            return f"Done! I've marked '{task.get('title')}' as complete."
                
                return f"I couldn't find a task matching '{task_desc}' to complete."
            
            elif action == "create" and self.task_service:
                # CRITICAL: Use parser's rich extraction architecture - never use raw query
                # The parser has sophisticated extraction methods that understand natural language
                
                # If parser already extracted description (from classification path), use it
                extracted_description = kwargs.get('description') or kwargs.get('title')
                
                # If no description provided, use parser's extraction methods
                if not extracted_description or extracted_description.strip() == "":
                    if self._parser and query:
                        # Use parser's rich extraction architecture
                        logger.info(f"[TaskTool] Extracting task description from query using parser: '{query}'")
                        try:
                            # Use the parser's extraction methods directly
                            extracted_description = self._parser.creation_handlers._extract_task_description(
                                query, ["create", "add", "make", "new", "task"]
                            )
                            
                            # If LLM extraction failed, try LLM-specific extraction
                            if not extracted_description or len(extracted_description.strip()) < 3:
                                extracted_description = self._parser.creation_handlers._extract_task_description_llm(query)
                            
                            # If still no description, use cleaned query (last resort)
                            if not extracted_description or len(extracted_description.strip()) < 3:
                                cleaned = self._parser.query_processing_handlers.extract_actual_query(query)
                                # Remove action words manually as final fallback
                                cleaned = cleaned.replace("please", "").replace("create", "").replace("add", "").replace("make", "").replace("task", "").replace("about", "").strip()
                                if cleaned and len(cleaned) >= 3:
                                    extracted_description = cleaned
                        except Exception as e:
                            logger.warning(f"[TaskTool] Parser extraction failed: {e}, will use query as fallback")
                    
                    # Final fallback: use query if extraction completely failed
                    if not extracted_description or len(extracted_description.strip()) < 3:
                        logger.warning(f"[TaskTool] Extraction failed, using query as fallback: '{query}'")
                        extracted_description = query
                
                # Map description -> title (parser uses "description", TaskService uses "title")
                title = extracted_description.strip()
                
                # Extract other parameters from kwargs (parser may have extracted these)
                notes = kwargs.get('notes', '')
                due_date = kwargs.get('due_date') or kwargs.get('due')
                priority = kwargs.get('priority', 'medium')
                category = kwargs.get('category')
                tags = kwargs.get('tags')
                project = kwargs.get('project')
                reminder_days = kwargs.get('reminder_days')
                estimated_hours = kwargs.get('estimated_hours')
                
                # If parser didn't extract these, try extracting from query
                if self._parser and query and not due_date:
                    try:
                        due_date = self._parser.creation_handlers._extract_due_date(query)
                    except:
                        pass
                
                if self._parser and query and priority == 'medium':
                    try:
                        extracted_priority = self._parser.creation_handlers._extract_priority(query)
                        if extracted_priority:
                            priority = extracted_priority
                    except:
                        pass
                
                logger.info(f"[TaskTool] Creating task with extracted title: '{title}' (from query: '{query}')")
                
                if not title or title.strip() == "":
                    return "[ERROR] Could not extract task description from query. Please try rephrasing."
                
                try:
                    result = self.task_service.create_task(
                        title=title,
                        notes=notes,
                        due_date=due_date,
                        priority=priority,
                        category=category,
                        tags=tags,
                        project=project,
                        reminder_days=reminder_days,
                        estimated_hours=estimated_hours
                    )
                    task_title = result.get('title', title)
                    # Return with clear format so orchestrator can extract exact title
                    return f"Created task: {task_title}"
                except Exception as e:
                    logger.error(f"Failed to create task: {e}", exc_info=True)
                    return f"[ERROR] Failed to create task: {str(e)}"
            
            # Fallback to parser for complex operations
            if self._parser:
                return self._parser.parse_query(query, self)
            
            return f"Error: Unable to execute task action '{action}'"
            
        except Exception as e:
            logger.error(f"TaskTool error: {e}", exc_info=True)
            return f"Error: {str(e)}"
    
    async def _arun(self, action: str = "create", query: str = "", **kwargs) -> str:
        """Async execution"""
        return self._run(action=action, query=query, **kwargs)


class SummarizeTool(BaseTool):
    """Summarization tool"""
    name: str = "summarize"
    description: str = "Summarize content (emails, documents, conversations). Use this for summarization requests."
    
    config: Optional[Config] = Field(default=None)
    
    def __init__(self, config: Optional[Config] = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config
    
    def _run(self, content: str = "", **kwargs) -> str:
        """Execute summarization"""
        try:
            from ..agent.roles.synthesizer_role import SynthesizerRole
            
            synthesizer = SynthesizerRole(config=self.config)
            result = synthesizer.summarize(content)
            return result
        except Exception as e:
            logger.error(f"SummarizeTool error: {e}")
            return f"Error: {str(e)}"
    
    async def _arun(self, content: str = "", **kwargs) -> str:
        """Async execution"""
        return self._run(content=content, **kwargs)


class NotionTool(BaseTool):
    """Notion integration tool wrapping NotionParser"""
    name: str = "notion"
    description: str = "Notion database management (query, create, update). Use this for Notion-related queries."
    
    config: Optional[Config] = Field(default=None)
    graph_manager: Optional[Any] = Field(default=None)
    rag_engine: Optional[Any] = Field(default=None)
    _parser: Optional[Any] = None
    
    def __init__(self, config: Optional[Config] = None, graph_manager: Optional[Any] = None,
                 rag_engine: Optional[Any] = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.graph_manager = graph_manager
        self.rag_engine = rag_engine
        self._parser = None
    
    def _initialize_parser(self):
        """Lazy initialization of parser"""
        if self._parser is None:
            try:
                from ..agent.parsers.notion_parser import NotionParser
                from ..services.rag_service import RAGService
                
                # Create RAG service if config provided
                rag_service = None
                if self.config:
                    rag_service = RAGService(config=self.config, collection_name="email-knowledge")
                    # Use provided rag_engine if available
                    if self.rag_engine:
                        rag_service.rag_engine = self.rag_engine
                
                self._parser = NotionParser(
                    rag_service=rag_service,
                    memory=None,
                    config=self.config
                )
                
                # Set graph_manager if provided
                if self.graph_manager:
                    self._parser.graph_manager = self.graph_manager
            except Exception as e:
                logger.error(f"Failed to initialize NotionParser: {e}")
                raise
    
    def _run(self, action: str = "query", query: str = "", **kwargs) -> str:
        """Execute Notion tool action"""
        self._initialize_parser()
        if self._parser is None:
            return "Error: Notion parser not initialized"
        
        try:
            result = self._parser.parse_query_to_params(query)
            if hasattr(self._parser, action):
                return getattr(self._parser, action)(**result)
            return str(result)
        except Exception as e:
            logger.error(f"NotionTool error: {e}")
            return f"Error: {str(e)}"
    
    async def _arun(self, action: str = "query", query: str = "", **kwargs) -> str:
        """Async execution"""
        return self._run(action=action, query=query, **kwargs)


__all__ = ['EmailTool', 'CalendarTool', 'TaskTool', 'SummarizeTool', 'NotionTool']

