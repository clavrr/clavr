"""
Email Integration Module for Task Tool

Handles all email-related task operations including:
- Creating tasks from emails
- AI-powered email task extraction
- Linking tasks to emails
- Searching tasks by email metadata
"""
from typing import Dict, Any, Optional, List
from langchain_core.messages import SystemMessage, HumanMessage

from .constants import (
    DEFAULT_PRIORITY,
    AI_TASK_EXTRACTION_PROMPT,
    URGENCY_KEYWORDS,
    EMAIL_BODY_PREVIEW_LENGTH,
    EMAIL_BODY_MAX_LENGTH_FOR_PROMPT,
)
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class EmailIntegration:
    """Handles email-related task operations"""
    
    def __init__(self, task_tool):
        """
        Initialize email integration
        
        Args:
            task_tool: Reference to parent TaskTool instance
        """
        self.task_tool = task_tool
    
    def create_task_from_email(
        self,
        email_id: str,
        email_data: Dict[str, Any],
        extract_action_items: bool = True,
        auto_prioritize: bool = True
    ) -> str:
        """
        Create task(s) from email content
        
        Args:
            email_id: Email ID for linking
            email_data: Email metadata (subject, body, from, date)
            extract_action_items: Use AI to extract multiple tasks
            auto_prioritize: Automatically set priority based on content
            
        Returns:
            Success message with created task IDs
        """
        try:
            subject = email_data.get('subject', 'Email Task')
            body = email_data.get('body', '')
            sender = email_data.get('from', 'Unknown')
            email_date = email_data.get('date', '')
            
            # Use AI extraction if enabled and available
            if extract_action_items and self.task_tool.llm_client:
                return self._extract_tasks_from_email_ai(email_id, email_data)
            
            # Simple extraction: use subject as task description
            description = f"{subject}"
            if body and len(body) > 0:
                first_line = body.split('\n')[0][:EMAIL_BODY_PREVIEW_LENGTH]
                notes = f"From email: {first_line}..."
            else:
                notes = f"Created from email from {sender}"
            
            # Auto-prioritize based on keywords
            priority = DEFAULT_PRIORITY
            if auto_prioritize:
                priority = self._determine_priority_from_text(subject)
            
            # Extract due date from subject if possible
            due_date = None
            if self.task_tool.date_parser:
                try:
                    parsed = self.task_tool.date_parser.parse_flexible_date(subject)
                    if parsed:
                        due_date = parsed.get('iso_datetime') or parsed.get('iso_date')
                except:
                    pass
            
            # Create task
            result = self.task_tool._create_task(
                description=description,
                due_date=due_date,
                priority=priority,
                tags=['email', 'inbox'],
                notes=notes
            )
            
            logger.info(f"[EMAIL->TASK] Created task from email {email_id}: {description}")
            return result
            
        except Exception as e:
            return self.task_tool._handle_error(e, "creating task from email")
    
    def _extract_tasks_from_email_ai(
        self,
        email_id: str,
        email_data: Dict[str, Any]
    ) -> str:
        """
        Use AI to extract multiple action items from email
        
        Args:
            email_id: Email ID
            email_data: Email content
            
        Returns:
            Success message with all created tasks
        """
        try:
            subject = email_data.get('subject', '')
            body = email_data.get('body', '')
            sender = email_data.get('from', '')
            
            user_msg = f"""Extract action items from this email:

Subject: {subject}
From: {sender}
Body: {body[:EMAIL_BODY_MAX_LENGTH_FOR_PROMPT]}

Extract all actionable tasks. Be specific and clear."""
            
            messages = [
                SystemMessage(content=AI_TASK_EXTRACTION_PROMPT),
                HumanMessage(content=user_msg)
            ]
            
            response = self.task_tool.llm_client.invoke(messages)
            ai_output = response.content
            
            # Parse AI response and create tasks
            tasks_created = []
            task_blocks = ai_output.split('---')
            
            for block in task_blocks:
                if 'TASK:' not in block:
                    continue
                
                task_data = self._parse_task_block(block)
                if task_data['description']:
                    self.task_tool._create_task(
                        description=task_data['description'],
                        due_date=task_data.get('due_date'),
                        priority=task_data.get('priority', DEFAULT_PRIORITY),
                        tags=task_data.get('tags', ['email', 'ai-extracted']),
                        notes=f"Extracted from email: {subject}"
                    )
                    tasks_created.append(task_data['description'])
            
            if tasks_created:
                output = f"**Created {len(tasks_created)} tasks from email:**\n\n"
                for i, task in enumerate(tasks_created, 1):
                    output += f"{i}. {task}\n"
                output += f"\nAll tasks linked to email '{subject}'"
                return self.task_tool._format_success(output)
            else:
                return "[INFO] No actionable tasks found in email"
                
        except Exception as e:
            logger.error(f"AI task extraction failed: {e}")
            # Fallback to simple extraction
            return self.create_task_from_email(email_id, email_data, extract_action_items=False)
    
    def link_task_to_email(
        self,
        task_id: str,
        email_id: str,
        email_subject: Optional[str] = None
    ) -> str:
        """
        Link existing task to an email
        
        Args:
            task_id: Task ID to link
            email_id: Email ID to link to
            email_subject: Optional email subject for reference
            
        Returns:
            Success message
        """
        try:
            result = self.task_tool._update_task(
                task_id=task_id,
                notes=f"Linked to email: {email_subject or email_id}"
            )
            
            logger.info(f"[TASK<->EMAIL] Linked task {task_id} to email {email_id}")
            return result
            
        except Exception as e:
            return self.task_tool._handle_error(e, "linking task to email")
    
    def search_tasks_by_email(
        self,
        email_id: Optional[str] = None,
        sender: Optional[str] = None,
        subject_keyword: Optional[str] = None
    ) -> str:
        """
        Find tasks related to emails using hybrid metadata search
        
        Args:
            email_id: Specific email ID
            sender: Email sender address
            subject_keyword: Keyword in email subject
            
        Returns:
            List of matching tasks
        """
        try:
            metadata_filters = {}
            if email_id:
                metadata_filters['email_id'] = email_id
            if sender:
                metadata_filters['email_sender'] = sender
            if subject_keyword:
                metadata_filters['email_subject'] = subject_keyword
            
            # Import here to avoid circular dependency
            from .utils import search_tasks_with_metadata
            return search_tasks_with_metadata(
                self.task_tool,
                metadata_filters=metadata_filters,
                tags=['email']
            )
            
        except Exception as e:
            return self.task_tool._handle_error(e, "searching tasks by email")
    
    def _determine_priority_from_text(self, text: str) -> str:
        """Determine priority based on urgency keywords in text"""
        text_lower = text.lower()
        
        for priority, keywords in URGENCY_KEYWORDS.items():
            if any(word in text_lower for word in keywords):
                return priority
        
        return DEFAULT_PRIORITY
    
    def _parse_task_block(self, block: str) -> Dict[str, Any]:
        """Parse a task block from AI output"""
        lines = block.strip().split('\n')
        task_data = {
            'description': None,
            'priority': DEFAULT_PRIORITY,
            'due_date': None,
            'tags': ['email', 'ai-extracted']
        }
        
        for line in lines:
            if line.startswith('TASK:'):
                task_data['description'] = line.replace('TASK:', '').strip()
            elif line.startswith('PRIORITY:'):
                task_data['priority'] = line.replace('PRIORITY:', '').strip().lower()
            elif line.startswith('DUE:'):
                task_data['due_date'] = line.replace('DUE:', '').strip()
            elif line.startswith('TAGS:'):
                tags_str = line.replace('TAGS:', '').strip()
                task_data['tags'].extend([t.strip() for t in tags_str.split(',')])
        
        return task_data
