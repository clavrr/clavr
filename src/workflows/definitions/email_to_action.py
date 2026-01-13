"""
Email to Action Workflow

Processes an email and automatically:
- Extracts action items → creates tasks
- Detects meeting requests → creates calendar events
- Classifies and categorizes the email
"""
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..base.workflow import Workflow, WorkflowContext
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class EmailToActionWorkflow(Workflow):
    """
    Email processing workflow.
    
    Analyzes an email using AI and automatically creates
    tasks and calendar events from the content.
    """
    
    name = "email_to_action"
    description = "Process email and convert to tasks and calendar events"
    version = "2.0.0"
    
    def __init__(
        self,
        email_service: Any,
        calendar_service: Any,
        task_service: Any,
        email_ai_analyzer: Any
    ):
        """
        Initialize with required services.
        
        Args:
            email_service: Email service instance
            calendar_service: Calendar service instance
            task_service: Task service instance
            email_ai_analyzer: AI analyzer for email processing (required)
        """
        self.email_service = email_service
        self.calendar_service = calendar_service
        self.task_service = task_service
        self.email_ai_analyzer = email_ai_analyzer
    
    def get_required_params(self) -> List[str]:
        return ["email_id"]
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "required": ["email_id"],
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "Email message ID to process"
                },
                "auto_create_tasks": {
                    "type": "boolean",
                    "default": True,
                    "description": "Automatically create tasks from action items"
                },
                "auto_create_events": {
                    "type": "boolean",
                    "default": True,
                    "description": "Automatically create calendar events"
                },
                "auto_archive": {
                    "type": "boolean",
                    "default": False,
                    "description": "Archive email after processing"
                }
            }
        }
    
    async def execute(self, context: WorkflowContext) -> Dict[str, Any]:
        """Execute the email-to-action workflow"""
        params = context.params
        email_id = params['email_id']
        auto_create_tasks = params.get('auto_create_tasks', True)
        auto_create_events = params.get('auto_create_events', True)
        auto_archive = params.get('auto_archive', False)
        
        result = {
            "email_id": email_id,
            "tasks_created": [],
            "events_created": [],
            "email_classification": {},
            "action_items_found": [],
            "events_suggested": [],
            "archived": False,
            "errors": []
        }
        
        # Step 1: Get email
        email = await asyncio.to_thread(
            self.email_service.get_email,
            email_id
        )
        
        if not email:
            raise ValueError(f"Email not found: {email_id}")
        
        context.state['email_subject'] = email.get('subject', 'No subject')
        context.state['email_from'] = email.get('from', 'Unknown')
        
        # Step 2: Extract action items
        action_items = await asyncio.to_thread(
            self.email_ai_analyzer.extract_action_items,
            email_data=email,
            context={},
            auto_categorize=True
        )
        
        result['action_items_found'] = action_items
        context.state['action_items_count'] = len(action_items)
        
        # Step 3: Create tasks if enabled
        if auto_create_tasks and action_items:
            for task_data in action_items:
                try:
                    task = await asyncio.to_thread(
                        self.task_service.create_task,
                        title=task_data.get('title', 'Task from email'),
                        due_date=task_data.get('due_date'),
                        priority=task_data.get('priority', 'medium'),
                        category=task_data.get('category', 'work'),
                        notes=f"From email: {email.get('subject', 'No subject')}\nEmail ID: {email_id}",
                        tags=['email', 'auto-created']
                    )
                    result['tasks_created'].append({
                        "id": task.get('id'),
                        "title": task_data.get('title'),
                        "source": "email_action_item"
                    })
                    logger.info(f"[WORKFLOW] Created task: {task_data.get('title')}")
                except Exception as e:
                    error_msg = f"Failed to create task '{task_data.get('title')}': {e}"
                    result['errors'].append(error_msg)
                    logger.error(f"[WORKFLOW] {error_msg}")
        
        # Step 4: Detect calendar events
        event_suggestions = await asyncio.to_thread(
            self.email_ai_analyzer.suggest_calendar_events,
            email
        )
        
        result['events_suggested'] = event_suggestions
        context.state['events_suggested_count'] = len(event_suggestions)
        
        # Step 5: Create events if enabled
        if auto_create_events and event_suggestions:
            for event_data in event_suggestions:
                try:
                    event = await asyncio.to_thread(
                        self.calendar_service.create_event,
                        title=event_data.get('title', 'Event from email'),
                        start_time=event_data.get('start_time'),
                        duration_minutes=event_data.get('duration_minutes', 60),
                        description=f"From email: {email.get('subject', '')}\nEmail ID: {email_id}",
                        attendees=event_data.get('attendees', [])
                    )
                    result['events_created'].append({
                        "id": event.get('id'),
                        "title": event_data.get('title'),
                        "start_time": event_data.get('start_time'),
                        "source": "email_meeting_request"
                    })
                    logger.info(f"[WORKFLOW] Created event: {event_data.get('title')}")
                except Exception as e:
                    error_msg = f"Failed to create event '{event_data.get('title')}': {e}"
                    result['errors'].append(error_msg)
                    logger.error(f"[WORKFLOW] {error_msg}")
        
        # Step 6: Classify email
        urgency = await asyncio.to_thread(
            self.email_ai_analyzer.classify_urgency,
            email
        )
        
        category = await asyncio.to_thread(
            self.email_ai_analyzer.suggest_email_category,
            email
        )
        
        result['email_classification'] = {
            "urgency": urgency,
            "category": category,
            "has_action_items": len(action_items) > 0,
            "has_meeting_request": len(event_suggestions) > 0
        }
        
        # Step 7: Archive if requested
        if auto_archive:
            try:
                await asyncio.to_thread(
                    self.email_service.archive_email,
                    email_id
                )
                result['archived'] = True
                logger.info(f"[WORKFLOW] Archived email: {email_id}")
            except Exception as e:
                error_msg = f"Failed to archive email: {e}"
                result['errors'].append(error_msg)
                logger.error(f"[WORKFLOW] {error_msg}")
        
        # Summary
        result['summary'] = {
            "tasks_created_count": len(result['tasks_created']),
            "events_created_count": len(result['events_created']),
            "urgency": urgency,
            "category": category,
            "error_count": len(result['errors']),
            "success": len(result['errors']) == 0
        }
        
        return result


class BatchEmailProcessorWorkflow(Workflow):
    """
    Process multiple emails in batch.
    
    Useful for processing all unread emails or a filtered set.
    """
    
    name = "batch_email_processor"
    description = "Process multiple emails and extract actions in batch"
    version = "1.0.0"
    
    def __init__(
        self,
        email_service: Any,
        calendar_service: Any,
        task_service: Any,
        email_ai_analyzer: Any
    ):
        self.email_service = email_service
        self.calendar_service = calendar_service
        self.task_service = task_service
        self.email_ai_analyzer = email_ai_analyzer
        
        # Create single email processor
        self.single_processor = EmailToActionWorkflow(
            email_service=email_service,
            calendar_service=calendar_service,
            task_service=task_service,
            email_ai_analyzer=email_ai_analyzer
        )
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "email_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of email IDs to process (optional)"
                },
                "query": {
                    "type": "string",
                    "default": "is:unread",
                    "description": "Gmail query to find emails (if email_ids not provided)"
                },
                "max_emails": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum emails to process"
                },
                "auto_create_tasks": {
                    "type": "boolean",
                    "default": True
                },
                "auto_create_events": {
                    "type": "boolean",
                    "default": True
                }
            }
        }
    
    async def execute(self, context: WorkflowContext) -> Dict[str, Any]:
        """Execute batch email processing"""
        params = context.params
        email_ids = params.get('email_ids', [])
        query = params.get('query', 'is:unread')
        max_emails = params.get('max_emails', 10)
        
        # Get email IDs if not provided
        if not email_ids:
            emails = await asyncio.to_thread(
                self.email_service.list_emails,
                max_results=max_emails,
                query=query
            )
            email_ids = [e.get('id') for e in emails if e.get('id')]
        
        results = {
            "processed_count": 0,
            "tasks_created_total": 0,
            "events_created_total": 0,
            "errors": [],
            "email_results": []
        }
        
        # Process each email
        for email_id in email_ids[:max_emails]:
            try:
                # Create sub-context
                sub_context = WorkflowContext.create(
                    workflow_name="email_to_action",
                    user_id=context.user_id,
                    params={
                        "email_id": email_id,
                        "auto_create_tasks": params.get('auto_create_tasks', True),
                        "auto_create_events": params.get('auto_create_events', True),
                        "auto_archive": False  # Don't archive in batch
                    }
                )
                
                email_result = await self.single_processor.execute(sub_context)
                results['email_results'].append({
                    "email_id": email_id,
                    "success": True,
                    "summary": email_result.get('summary', {})
                })
                
                results['processed_count'] += 1
                results['tasks_created_total'] += len(email_result.get('tasks_created', []))
                results['events_created_total'] += len(email_result.get('events_created', []))
                
            except Exception as e:
                results['errors'].append({
                    "email_id": email_id,
                    "error": str(e)
                })
                results['email_results'].append({
                    "email_id": email_id,
                    "success": False,
                    "error": str(e)
                })
        
        results['summary'] = {
            "total_emails": len(email_ids),
            "processed": results['processed_count'],
            "failed": len(results['errors']),
            "tasks_created": results['tasks_created_total'],
            "events_created": results['events_created_total']
        }
        
        return results
