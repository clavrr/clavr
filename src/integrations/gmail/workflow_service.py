"""
Email Workflow Service - Logic for email workflows (creating tasks/events from emails)
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import re
import json
from src.utils.logger import setup_logger
from .exceptions import EmailIntegrationException

logger = setup_logger(__name__)

class EmailWorkflowService:
    """
    Specialized service for email-based workflows (tasks, events)
    """
    
    def __init__(self, parent):
        """
        Initialize with parent EmailService
        """
        self.parent = parent
        self.config = parent.config
        self.credentials = parent.credentials
    
    def create_event_from_email(
        self,
        email_id: str,
        email_subject: str,
        email_body: str,
        calendar_service: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Create a calendar event from an email"""
        try:
            logger.info(f"[EMAIL_WORKFLOW] Creating event from email: {email_id}")
            
            if not calendar_service:
                from .calendar_service import CalendarService
                calendar_service = CalendarService(
                    config=self.config,
                    credentials=self.credentials
                )
            
            from langchain_core.messages import HumanMessage
            
            # Use intelligent parsers from parent if available
            date_parser = self.parent.date_parser
            llm_client = self.parent.llm_client
            
            # Fallback initialization if needed
            if not date_parser:
                try:
                    from ..utils import FlexibleDateParser
                    date_parser = FlexibleDateParser(self.config)
                except Exception: pass
            
            if not llm_client:
                try:
                    from ..ai.llm_factory import LLMFactory
                    llm_client = LLMFactory.get_llm_for_provider(self.config, temperature=0.1)
                except Exception: pass
            
            event_title = email_subject
            start_time = None
            end_time = None
            location = None
            attendees = []
            
            if llm_client:
                try:
                    extraction_prompt = f"""Extract meeting/event details from this email. 
Subject: {email_subject}
Body: {email_body[:2000]}

Extract the following in JSON format:
{{
    "event_title": "Cleaned meeting title",
    "date_time": "Date/time expression",
    "location": "Location",
    "attendees": ["emails/names"],
    "duration_hours": 1.0,
    "confidence": 0.5
}}"""
                    response = llm_client.invoke([HumanMessage(content=extraction_prompt)])
                    response_text = response.content if hasattr(response, 'content') else str(response)
                    
                    if response_text:
                        json_match = re.search(r'\{[\s\S]*\}', response_text)
                        if json_match:
                            extracted = json.loads(json_match.group(0))
                            if extracted.get('event_title'):
                                event_title = extracted['event_title'].strip()
                            
                            date_time_expr = extracted.get('date_time')
                            if date_time_expr and date_parser:
                                date_range = date_parser.parse_date_expression(date_time_expr, prefer_future=True)
                                if date_range:
                                    start_time = date_range['start']
                                    duration_hours = extracted.get('duration_hours', 1.0)
                                    end_time = start_time + timedelta(hours=duration_hours)
                            
                            location = extracted.get('location')
                            attendees = extracted.get('attendees') or []
                except Exception as e:
                    logger.warning(f"[EMAIL_WORKFLOW] LLM extraction failed: {e}")
            
            if not start_time and date_parser:
                try:
                    combined_text = f"{email_subject} {email_body[:500]}"
                    date_range = date_parser.parse_date_expression(combined_text, prefer_future=True)
                    if date_range:
                        start_time = date_range['start']
                        end_time = date_range.get('end', start_time + timedelta(hours=1))
                except Exception: pass
            
            if not start_time:
                start_time = datetime.now() + timedelta(hours=1)
                end_time = start_time + timedelta(hours=1)
            
            event_data = {
                'summary': event_title,
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'description': f"Created from email: {email_id}\n\n{email_body[:500]}..."
            }
            if location: event_data['location'] = location
            if attendees: event_data['attendees'] = attendees
            
            return calendar_service.create_event(**event_data)
        except Exception as e:
            logger.error(f"[EMAIL_WORKFLOW] Failed to create event: {e}")
            raise EmailIntegrationException(f"Failed to create event: {e}", service_name="email")

    def create_task_from_email(
        self,
        email_id: str,
        email_subject: str,
        email_body: Optional[str] = None,
        auto_extract: bool = False,
        task_service: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Create a task from an email"""
        try:
            logger.info(f"[EMAIL_WORKFLOW] Creating task from email: {email_id}")
            if not task_service:
                from .task_service import TaskService
                task_service = TaskService(config=self.config, credentials=self.credentials)
            
            return task_service.create_task_from_email(
                email_id=email_id,
                email_subject=email_subject,
                email_body=email_body,
                auto_extract=auto_extract
            )
        except Exception as e:
            logger.error(f"[EMAIL_WORKFLOW] Failed to create task: {e}")
            raise EmailIntegrationException(f"Failed to create task: {e}", service_name="email")
