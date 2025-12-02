"""
Email Composition Handlers - Email composition, scheduling, and body generation

This module handles:
- Email composition and sending
- Email scheduling  
- Email body generation (with LLM support)
- Recipient/subject/body extraction
- Email personalization
"""

from typing import Optional
import re
from langchain.tools import BaseTool

from ....utils.logger import setup_logger
from .constants import EmailParserConfig

logger = setup_logger(__name__)

# Constants for composition handlers
BODY_PREVIEW_LENGTH = 100
MAX_SUBJECT_LENGTH = 50


class EmailCompositionHandlers:
    """Handles email composition, scheduling, and generation"""
    
    def __init__(self, parser):
        self.parser = parser
        self.llm_client = parser.llm_client
        self.classifier = parser.classifier
    
    def extract_schedule_time(self, query: str) -> Optional[str]:
        """Extract schedule time from query using natural language parsing"""
        query_lower = query.lower()
        patterns = [
            r'schedule.*?(?:for|at|on)\s+(.+?)(?:\s+to|\s+about|$)',
            r'send\s+(?:later|at|on|tomorrow|next)\s+(.+?)(?:\s+to|\s+about|$)',
            r'send\s+(?:email|message).*?(?:at|on|tomorrow|next)\s+(.+?)(?:\s+to|\s+about|$)',
            r'(?:tomorrow|next\s+\w+).*?(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)',
            r'in\s+(\d+\s+(?:hour|hours|minute|minutes|day|days|week|weeks))',
        ]
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                schedule_str = match.group(1).strip()
                logger.info(f"[EMAIL] Extracted schedule time: '{schedule_str}'")
                return schedule_str
        if 'tomorrow' in query_lower:
            time_match = re.search(r'tomorrow(?:\s+at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?', query_lower)
            if time_match:
                time_part = time_match.group(1) if time_match.group(1) else '9am'
                return f"tomorrow at {time_part}"
            return "tomorrow"
        if 'next' in query_lower:
            day_match = re.search(r'next\s+(\w+)', query_lower)
            if day_match:
                return f"next {day_match.group(1)}"
        return None
    
    def parse_and_schedule_email(self, tool: BaseTool, query: str) -> str:
        """Handle email scheduling action"""
        schedule_time = self.extract_schedule_time(query)
        if not schedule_time:
            return "[ERROR] I couldn't determine when to schedule the email. Please specify a time like 'tomorrow at 3pm' or 'next Monday'."
        return self.parse_and_send_email(tool, query, schedule_time=schedule_time)
    
    def parse_and_send_email(self, tool: BaseTool, query: str, schedule_time: Optional[str] = None) -> str:
        """Parse email sending with intelligent extraction"""
        logger.info(f"[EMAIL] Parsing email send for query: {query}")
        to = self.extract_email_recipient(query)
        logger.info(f"[EMAIL] Extracted recipient: {to}")
        subject = self.extract_email_subject(query)
        logger.info(f"[EMAIL] Extracted subject: {subject}")
        body = self.extract_email_body(query, to)
        logger.info(f"[EMAIL] Extracted body: {body[:BODY_PREVIEW_LENGTH]}...")
        action = "schedule" if schedule_time else "send"
        return tool._run(action=action, to=to, subject=subject, body=body, schedule_time=schedule_time)
    
    def extract_email_recipient(self, query: str) -> Optional[str]:
        """Extract email recipient from query"""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, query)
        return emails[0] if emails else None
    
    def extract_email_subject(self, query: str) -> str:
        """Extract email subject from query - clean, professional, no emojis"""
        logger.info(f"Extracting subject from query: {query}")
        subject_patterns = [
            r'subject[:\s]+([^,]+)',
            r'with subject[:\s]+([^,]+)',
            r'subject[:\s]+([^,]+?)(?:\s+and|\s+body|\s+with|$)',
        ]
        for pattern in subject_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                subject = match.group(1).strip()
                subject = re.sub(r'\s+', ' ', subject)
                logger.info(f"Found explicit subject: {subject}")
                return subject if subject else "New Message"
        query_lower = query.lower()
        if 'product hunt' in query_lower and 'launch' in query_lower:
            return "Product Hunt Launch - Exciting News!"
        elif 'product launch' in query_lower or ('launch' in query_lower and 'product' in query_lower):
            return "Product Launch Update"
        elif 'project update' in query_lower or ('project' in query_lower and 'update' in query_lower):
            return "Project Update - Great Progress"
        elif 'meeting' in query_lower and 'tomorrow' in query_lower:
            return "Meeting Tomorrow - Quick Check-in"
        elif 'meeting' in query_lower:
            return "Meeting Discussion"
        elif 'discussion' in query_lower:
            return "Quick Discussion"
        elif 'update' in query_lower:
            return "Status Update"
        elif 'exciting' in query_lower:
            return "Exciting News"
        else:
            main_topic = query
            remove_words = ["send", "email", "to", "about", "an", "the", "our", "and", "how", "it", "is", "for", "first", "time", "discussion"]
            for word in remove_words:
                main_topic = re.sub(rf'\b{word}\b', '', main_topic, flags=re.IGNORECASE)
            main_topic = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', main_topic)
            main_topic = re.sub(r'\s+', ' ', main_topic).strip()
            main_topic = re.sub(r'^(with|about|for)\s+', '', main_topic, flags=re.IGNORECASE)
            if main_topic and len(main_topic) > 3:
                if len(main_topic) > MAX_SUBJECT_LENGTH:
                    main_topic = main_topic[:MAX_SUBJECT_LENGTH - 3] + "..."
                return main_topic.title()
            else:
                return "Quick Update"
    
    def extract_email_body(self, query: str, recipient: str = None) -> str:
        """Generate intelligent, well-structured email body using LLM when available"""
        logger.info(f"Generating email body for query: {query}")
        body_patterns = [
            r'body[:\s]+(.+)',
            r'with body[:\s]+(.+)',
            r'message[:\s]+(.+)',
        ]
        for pattern in body_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                body = match.group(1).strip()
                logger.info(f"Found explicit body: {body}")
                return self.personalize_email_body(body if body else "No message content", recipient)
        if self.llm_client:
            try:
                entities = {}
                if self.classifier:
                    try:
                        classification = self.classifier.classify_query(query)
                        entities = classification.get('entities', {})
                    except (AttributeError, KeyError, Exception):
                        pass
                return self.parser._generate_email_with_llm(query, recipient or "the recipient", entities)
            except Exception as e:
                logger.warning(f"LLM email generation failed: {e}")
                return self.generate_simple_email(query, recipient)
        return self.generate_simple_email(query, recipient)
    
    def generate_email_with_template(self, query: str, recipient: str = None) -> str:
        """LLM-based email generation"""
        return self.generate_simple_email(query, recipient)
    
    def generate_simple_email(self, query: str, recipient: str = None) -> str:
        """Generate a simple email when LLM is not available"""
        recipient_name = ""
        if recipient and '@' in recipient:
            recipient_name = recipient.split('@')[0].split('.')[0].title()
        greeting = f"Hi {recipient_name}," if recipient_name else "Hi there,"
        context = query
        action_words = ["send", "email", "to", "compose", "write"]
        for word in action_words:
            context = re.sub(rf'\b{word}\b', '', context, flags=re.IGNORECASE)
        context = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', context)
        context = re.sub(r'\s+', ' ', context).strip()
        return f"""{greeting}

{context if context else "I wanted to reach out to you about something important."}

Best regards,
Anthony"""
    
    def extract_meaningful_context(self, query: str) -> str:
        """Extract meaningful context from the query for email body"""
        context = query
        action_words = ["send", "compose", "write", "draft", "email", "message", "to", "about"]
        for word in action_words:
            context = re.sub(rf'\b{word}\b', '', context, flags=re.IGNORECASE)
        context = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', context)
        context = re.sub(r'\s+', ' ', context).strip()
        context = re.sub(r'^(with|about|for)\s+', '', context, flags=re.IGNORECASE)
        if context:
            context = context[0].lower() + context[1:]
            return context
        else:
            return "something important"
    
    def personalize_email_body(self, body: str, recipient: str = None) -> str:
        """Personalize email body with recipient name and user signature"""
        recipient_name = ""
        if recipient and '@' in recipient:
            recipient_name = recipient.split('@')[0].split('.')[0].title()
        if recipient_name:
            body = re.sub(r'Hi there,?', f'Hi {recipient_name},', body, flags=re.IGNORECASE)
            body = re.sub(r'Hello there,?', f'Hello {recipient_name},', body, flags=re.IGNORECASE)
            body = re.sub(r'Hey there,?', f'Hey {recipient_name},', body, flags=re.IGNORECASE)
            body = re.sub(r'Good morning,?', f'Good morning {recipient_name},', body, flags=re.IGNORECASE)
            body = re.sub(r'Good afternoon,?', f'Good afternoon {recipient_name},', body, flags=re.IGNORECASE)
        return body
    
    def extract_search_query(self, query: str, keywords: list) -> str:
        """Extract search query from user input"""
        query_lower = query.lower()
        from_patterns = [
            r'from\s+([a-zA-Z][a-zA-Z0-9@._-]+)',
            r'email+\s+from\s+([a-zA-Z][a-zA-Z0-9@._-]+)',
            r'have\s+from\s+([a-zA-Z][a-zA-Z0-9@._-]+)',
            r'got\s+from\s+([a-zA-Z][a-zA-Z0-9@._-]+)',
        ]
        for pattern in from_patterns:
            match = re.search(pattern, query_lower)
            if match:
                sender = match.group(1).strip()
                skip_words = ['did', 'does', 'do', 'when', 'what', 'who', 'where', 'why', 'how', 'the', 'my', 'me', 'i', 'was', 'were', 'are', 'is', 'about', 'any', 'have', 'has', 'had', 'been', 'being', 'get', 'got', 'new', 'recent']
                # Check if sender is just skip words or combinations of them
                sender_words = sender.lower().split()
                if sender.lower() not in skip_words and not all(word in skip_words for word in sender_words):
                    logger.info(f"[EMAIL] extract_search_query found sender '{sender}' via pattern '{pattern}'")
                    return f"from:{sender}"
        if "emails from" in query_lower:
            pattern = r'emails from\s+(.+)'
            match = re.search(pattern, query_lower)
            if match:
                return f"from:{match.group(1).strip()}"
        if "show me emails from" in query_lower:
            pattern = r'show me emails from\s+(.+)'
            match = re.search(pattern, query_lower)
            if match:
                return f"from:{match.group(1).strip()}"
        for keyword in keywords:
            if keyword in query_lower:
                pattern = rf'{keyword}\s+(.+)'
                match = re.search(pattern, query_lower)
                if match:
                    extracted = match.group(1).strip()
                    from_match = re.search(r'from\s+([a-zA-Z][a-zA-Z0-9@._-]+)', extracted.lower())
                    if from_match:
                        sender = from_match.group(1).strip()
                        skip_words = ['did', 'does', 'when', 'what', 'who', 'where', 'why', 'how', 'the', 'my', 'me', 'i', 'was', 'about', 'new', 'recent']
                        if sender.lower() not in skip_words:
                            return f"from:{sender}"
                    return extracted
        return query
