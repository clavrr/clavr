"""
Email Action Handlers

Handles core email actions: send, reply, mark_read, mark_unread, delete, archive, schedule, extract_tasks, auto_process.
This module centralizes action handling logic to keep the main EmailTool class clean.
"""
from typing import Optional, Dict, Any

from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class EmailActionHandlers:
    """
    Handles core email actions.
    
    This class centralizes action handling to improve maintainability
    and keep the main EmailTool class focused on orchestration.
    """
    
    def __init__(self, email_tool):
        """
        Initialize action handlers.
        
        Args:
            email_tool: Parent EmailTool instance for accessing services, config, etc.
        """
        self.email_tool = email_tool
        self.email_service = email_tool.email_service if hasattr(email_tool, 'email_service') else None
    
    def handle_send(
        self,
        to: Optional[str],
        subject: Optional[str],
        body: Optional[str],
        **kwargs
    ) -> str:
        """Handle send email action"""
        if not to or not subject or not body:
            return "[ERROR] Please provide 'to', 'subject', and 'body' for send action"
        
        # Emit high-level action event
        workflow_emitter = kwargs.get('workflow_emitter')
        if workflow_emitter:
            self.email_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr sending email...",
                data={'to': to, 'subject': subject}
            )
        
        result = self.email_service.send_email(to=to, subject=subject, body=body)
        return f"Done! I've sent an email to {to} with subject '{subject}'."
    
    def handle_reply(
        self,
        message_id: Optional[str],
        body: Optional[str],
        **kwargs
    ) -> str:
        """Handle reply to email action"""
        if not message_id or not body:
            return "[ERROR] Please provide 'message_id' and 'body' for reply action"
        
        # Emit high-level action event
        workflow_emitter = kwargs.get('workflow_emitter')
        if workflow_emitter:
            self.email_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr replying...",
                data={'message_id': message_id}
            )
        
        # Get original email subject for better response
        try:
            original_email = self.email_service.get_email(message_id)
            original_subject = original_email.get('subject', 'that email')
        except:
            original_subject = "that email"
        result = self.email_service.reply_to_email(message_id=message_id, body=body)
        return f"Done! I've sent your reply to '{original_subject}'."
    
    def handle_mark_read(
        self,
        message_id: Optional[str],
        query: Optional[str],
        **kwargs
    ) -> str:
        """Handle mark email as read action"""
        # SMART MARK READ HANDLER: Uses context, handles follow-ups, auto-acts when obvious
        if not message_id:
            # Check if this is a follow-up query (e.g., "the first one", "the second one")
            selected_email = self.email_tool._handle_follow_up_selection(query, "mark_read")
            if selected_email:
                message_id = selected_email.get('id')
                email_subject = selected_email.get('subject', 'that email')
                logger.info(f"[EMAIL] Resolved follow-up selection for mark_read: {email_subject}")
            else:
                # Try to find email by subject or query
                if query:
                    emails = self.email_service.search_emails(query=query, limit=10)
                    if not emails:
                        return f"I couldn't find any emails matching '{query}'."
                    elif len(emails) == 1:
                        message_id = emails[0].get('id')
                        email_subject = emails[0].get('subject', 'that email')
                        logger.info(f"[EMAIL] Auto-marking single matching email as read: {email_subject}")
                    else:
                        # Multiple matches - show list and store for follow-up
                        self.email_tool._last_email_list = emails
                        self.email_tool._last_email_list_query = query
                        
                        email_list_parts = []
                        for i, e in enumerate(emails[:5], 1):
                            email_subject = e.get('subject', 'Untitled')
                            sender = e.get('from', e.get('sender', 'Unknown'))
                            email_desc = f"{i}. **{email_subject}** (from {sender})"
                            email_list_parts.append(email_desc)
                        
                        email_list = "\n".join(email_list_parts)
                        return f"I found {len(emails)} emails matching '{query}'. Which one should I mark as read?\n\n{email_list}\n\nJust say 'the first one', 'the second one', or 'the one from [sender]' and I'll mark it as read!"
                else:
                    return "I need to know which email to mark as read. You can say something like 'mark email X as read' or 'mark the email about Y as read'."
        
        if not message_id:
            return "I couldn't identify which email to mark as read. Please try again with more details."
        
        # Get email subject for better response
        try:
            email = self.email_service.get_email(message_id)
            email_subject = email.get('subject', 'that email')
        except:
            email_subject = "that email"
        
        result = self.email_service.mark_as_read([message_id])
        # Clear the stored list since we marked an email
        self.email_tool._last_email_list = None
        self.email_tool._last_email_list_query = None
        return f"Done! I've marked '{email_subject}' as read."
    
    def handle_mark_unread(
        self,
        message_id: Optional[str],
        query: Optional[str],
        **kwargs
    ) -> str:
        """Handle mark email as unread action"""
        # SMART MARK UNREAD HANDLER: Uses context, handles follow-ups, auto-acts when obvious
        if not message_id:
            selected_email = self.email_tool._handle_follow_up_selection(query, "mark_unread")
            if selected_email:
                message_id = selected_email.get('id')
                email_subject = selected_email.get('subject', 'that email')
                logger.info(f"[EMAIL] Resolved follow-up selection for mark_unread: {email_subject}")
            else:
                if query:
                    emails = self.email_service.search_emails(query=query, limit=10)
                    if not emails:
                        return f"I couldn't find any emails matching '{query}'."
                    elif len(emails) == 1:
                        message_id = emails[0].get('id')
                        email_subject = emails[0].get('subject', 'that email')
                        logger.info(f"[EMAIL] Auto-marking single matching email as unread: {email_subject}")
                    else:
                        self.email_tool._last_email_list = emails
                        self.email_tool._last_email_list_query = query
                        
                        email_list_parts = []
                        for i, e in enumerate(emails[:5], 1):
                            email_subject = e.get('subject', 'Untitled')
                            sender = e.get('from', e.get('sender', 'Unknown'))
                            email_desc = f"{i}. **{email_subject}** (from {sender})"
                            email_list_parts.append(email_desc)
                        
                        email_list = "\n".join(email_list_parts)
                        return f"I found {len(emails)} emails matching '{query}'. Which one should I mark as unread?\n\n{email_list}\n\nJust say 'the first one', 'the second one', or 'the one from [sender]' and I'll mark it as unread!"
                else:
                    return "I need to know which email to mark as unread. You can say something like 'mark email X as unread'."
        
        if not message_id:
            return "I couldn't identify which email to mark as unread. Please try again with more details."
        
        try:
            email = self.email_service.get_email(message_id)
            email_subject = email.get('subject', 'that email')
        except:
            email_subject = "that email"
        
        result = self.email_service.mark_as_unread([message_id])
        self.email_tool._last_email_list = None
        self.email_tool._last_email_list_query = None
        return f"Done! I've marked '{email_subject}' as unread."
    
    def handle_delete(
        self,
        message_id: Optional[str],
        query: Optional[str],
        **kwargs
    ) -> str:
        """Handle delete email action"""
        # Get workflow_emitter from kwargs if available
        workflow_emitter = kwargs.get('workflow_emitter')
        
        # Emit workflow event for deleting email
        if workflow_emitter:
            self.email_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr deleting email...",
                data={'action': 'delete'}
            )
        
        # SMART DELETE HANDLER: Uses context, handles follow-ups, auto-deletes when obvious
        if not message_id:
            selected_email = self.email_tool._handle_follow_up_selection(query, "delete")
            if selected_email:
                message_id = selected_email.get('id')
                email_subject = selected_email.get('subject', 'that email')
                logger.info(f"[EMAIL] Resolved follow-up selection for delete: {email_subject}")
            else:
                if query:
                    emails = self.email_service.search_emails(query=query, limit=10)
                    if not emails:
                        return f"I couldn't find any emails matching '{query}'."
                    elif len(emails) == 1:
                        message_id = emails[0].get('id')
                        email_subject = emails[0].get('subject', 'that email')
                        logger.info(f"[EMAIL] Auto-deleting single matching email: {email_subject}")
                    else:
                        self.email_tool._last_email_list = emails
                        self.email_tool._last_email_list_query = query
                        
                        email_list_parts = []
                        for i, e in enumerate(emails[:5], 1):
                            email_subject = e.get('subject', 'Untitled')
                            sender = e.get('from', e.get('sender', 'Unknown'))
                            email_desc = f"{i}. **{email_subject}** (from {sender})"
                            email_list_parts.append(email_desc)
                        
                        email_list = "\n".join(email_list_parts)
                        return f"I found {len(emails)} emails matching '{query}'. Which one should I delete?\n\n{email_list}\n\nJust say 'the first one', 'the second one', or 'the one from [sender]' and I'll delete it!"
                else:
                    return "I need to know which email to delete. You can say something like 'delete email X' or 'delete the email about Y'."
        
        if not message_id:
            return "I couldn't identify which email to delete. Please try again with more details."
        
        try:
            email = self.email_service.get_email(message_id)
            email_subject = email.get('subject', 'that email')
        except:
            email_subject = "that email"
        
        result = self.email_service.delete_emails([message_id])
        self.email_tool._last_email_list = None
        self.email_tool._last_email_list_query = None
        return f"Done! I've deleted '{email_subject}'."
    
    def handle_archive(
        self,
        message_id: Optional[str],
        query: Optional[str],
        **kwargs
    ) -> str:
        """Handle archive email action"""
        # SMART ARCHIVE HANDLER: Uses context, handles follow-ups, auto-archives when obvious
        if not message_id:
            selected_email = self.email_tool._handle_follow_up_selection(query, "archive")
            if selected_email:
                message_id = selected_email.get('id')
                email_subject = selected_email.get('subject', 'that email')
                logger.info(f"[EMAIL] Resolved follow-up selection for archive: {email_subject}")
            else:
                if query:
                    emails = self.email_service.search_emails(query=query, limit=10)
                    if not emails:
                        return f"I couldn't find any emails matching '{query}'."
                    elif len(emails) == 1:
                        message_id = emails[0].get('id')
                        email_subject = emails[0].get('subject', 'that email')
                        logger.info(f"[EMAIL] Auto-archiving single matching email: {email_subject}")
                    else:
                        self.email_tool._last_email_list = emails
                        self.email_tool._last_email_list_query = query
                        
                        email_list_parts = []
                        for i, e in enumerate(emails[:5], 1):
                            email_subject = e.get('subject', 'Untitled')
                            sender = e.get('from', e.get('sender', 'Unknown'))
                            email_desc = f"{i}. **{email_subject}** (from {sender})"
                            email_list_parts.append(email_desc)
                        
                        email_list = "\n".join(email_list_parts)
                        return f"I found {len(emails)} emails matching '{query}'. Which one should I archive?\n\n{email_list}\n\nJust say 'the first one', 'the second one', or 'the one from [sender]' and I'll archive it!"
                else:
                    return "I need to know which email to archive. You can say something like 'archive email X' or 'archive the email about Y'."
        
        if not message_id:
            return "I couldn't identify which email to archive. Please try again with more details."
        
        try:
            email = self.email_service.get_email(message_id)
            email_subject = email.get('subject', 'that email')
        except:
            email_subject = "that email"
        
        result = self.email_service.archive_emails([message_id])
        self.email_tool._last_email_list = None
        self.email_tool._last_email_list_query = None
        return f"Done! I've archived '{email_subject}'."
    
    def handle_schedule(
        self,
        to: Optional[str],
        subject: Optional[str],
        body: Optional[str],
        schedule_time: Optional[str],
        **kwargs
    ) -> str:
        """Handle schedule email action"""
        if not to or not subject or not body or not schedule_time:
            return "[ERROR] Please provide 'to', 'subject', 'body', and 'schedule_time' for schedule action"
        return f"[INFO] Email scheduling feature coming soon"
    
    def handle_extract_tasks(
        self,
        message_id: Optional[str],
        auto_create_tasks: bool = False,
        **kwargs
    ) -> str:
        """Handle extract tasks from email action"""
        if not message_id:
            return "[ERROR] Please provide 'message_id' for extract_tasks action"
        
        # Get email
        email = self.email_service.get_email(message_id)
        
        # Extract tasks using AI
        tasks = self.email_tool.ai_analyzer.extract_action_items(email)
        
        if not tasks:
            return f"No action items found in email"
        
        # If auto_create_tasks is True and task_service available, create tasks
        if auto_create_tasks and hasattr(self.email_tool, '_task_service') and self.email_tool._task_service:
            from ...integrations.google_tasks.service import TaskService
            task_service: TaskService = self.email_tool._task_service
            
            created_tasks = []
            for task_data in tasks:
                try:
                    result = task_service.create_task(
                        title=task_data.get('title'),
                        due_date=task_data.get('due_date'),
                        priority=task_data.get('priority', 'medium'),
                        category=task_data.get('category', 'work'),
                        notes=task_data.get('notes', '')
                    )
                    created_tasks.append(result)
                except Exception as e:
                    logger.warning(f"Failed to create task: {e}")
            
            return f"Extracted and created {len(created_tasks)}/{len(tasks)} tasks from email:\n\n" + \
                   "\n".join([f"- {t.get('title')} (Priority: {t.get('priority', 'medium')})" for t in created_tasks])
        else:
            # Just return extracted tasks
            output = f"**Extracted {len(tasks)} action items from email:**\n\n"
            for i, task in enumerate(tasks, 1):
                output += f"{i}. **{task.get('title')}**\n"
                output += f"   Priority: {task.get('priority', 'medium')}\n"
                if task.get('due_date'):
                    output += f"   Due: {task.get('due_date')}\n"
                if task.get('category'):
                    output += f"   Category: {task.get('category')}\n"
                if task.get('notes'):
                    output += f"   Notes: {task.get('notes')}\n"
                output += "\n"
            
            if not auto_create_tasks:
                output += "\nTip: Use `auto_create_tasks=true` to automatically create these tasks"
            
            return output
    
    def handle_auto_process(
        self,
        message_id: Optional[str],
        **kwargs
    ) -> str:
        """Handle auto process email action"""
        if not message_id:
            return "[ERROR] Please provide 'message_id' for auto_process action"
        
        # Get email
        email = self.email_service.get_email(message_id)
        
        results = []
        
        # 1. Extract and create tasks
        tasks = self.email_tool.ai_analyzer.extract_action_items(email)
        if tasks and hasattr(self.email_tool, '_task_service') and self.email_tool._task_service:
            task_count = 0
            for task_data in tasks:
                try:
                    self.email_tool._task_service.create_task(
                        title=task_data.get('title'),
                        due_date=task_data.get('due_date'),
                        priority=task_data.get('priority', 'medium'),
                        category=task_data.get('category', 'work'),
                        notes=f"From email: {email.get('subject', '')} | {task_data.get('notes', '')}"
                    )
                    task_count += 1
                except Exception as e:
                    logger.warning(f"Failed to create task: {e}")
            
            if task_count > 0:
                results.append(f"Created {task_count} tasks")
        
        # 2. Detect calendar events
        events = self.email_tool.ai_analyzer.suggest_calendar_events(email)
        if events:
            results.append(f"Found {len(events)} potential calendar events (auto-creation coming soon)")
        
        # 3. Classify and label email
        urgency = self.email_tool.ai_analyzer.classify_urgency(email)
        category = self.email_tool.ai_analyzer.suggest_email_category(email)
        results.append(f"Classified as: {category} ({urgency} urgency)")
        
        # 4. Archive/label based on processing
        if tasks or events:
            # Only archive if we extracted something useful
            try:
                self.email_service.archive_emails([message_id])
                results.append("Email archived")
            except Exception as e:
                logger.warning(f"Failed to archive email: {e}")
        
        return "**Email Auto-Processing Complete**\n\n" + "\n".join(results)


