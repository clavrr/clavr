"""
Specialized summarizers for specific content types
Handles email threads, calendar events, conversations, etc.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
from .abstractive import AbstractiveSummarizer
from .extractive import ExtractiveSummarizer
from .constants import DEFAULT_FORMAT, DEFAULT_LENGTH
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class EmailThreadSummarizer:
    """Summarize email threads with context awareness"""
    
    def __init__(self, llm_client=None):
        """
        Initialize email thread summarizer
        
        Args:
            llm_client: LLM client instance
        """
        self.abstractive = AbstractiveSummarizer(llm_client)
        self.extractive = ExtractiveSummarizer()
    
    def summarize(
        self,
        emails: List[Dict[str, Any]],
        format_type: str = DEFAULT_FORMAT,
        length: str = DEFAULT_LENGTH,
        focus: Optional[str] = None
    ) -> str:
        """
        Summarize email thread
        
        Args:
            emails: List of email dictionaries with keys: subject, from, to, body, date
            format_type: Output format
            length: Summary length
            focus: Optional focus area
            
        Returns:
            Thread summary
        """
        if not emails:
            return "No emails to summarize."
        
        # Build context-aware content
        thread_content = self._build_thread_content(emails)
        
        # Extract metadata
        metadata = self._extract_thread_metadata(emails)
        
        # Try AI summarization first
        summary = self.abstractive.summarize(
            thread_content,
            format_type,
            length,
            focus,
            metadata={'source_type': 'email', **metadata}
        )
        
        # Fallback to extractive
        if not summary:
            summary = self.extractive.summarize(thread_content, format_type, length)
        
        # Add thread context
        return self._format_thread_summary(summary, metadata, emails)
    
    def _build_thread_content(self, emails: List[Dict[str, Any]]) -> str:
        """
        Build formatted content from email thread
        
        Args:
            emails: List of emails
            
        Returns:
            Formatted thread content
        """
        parts = []
        
        for i, email in enumerate(emails, 1):
            subject = email.get('subject', 'No Subject')
            sender = email.get('from', 'Unknown')
            body = email.get('body', '')
            
            parts.append(f"Email {i} - {subject}")
            parts.append(f"From: {sender}")
            parts.append(f"{body}\n")
        
        return "\n".join(parts)
    
    def _extract_thread_metadata(self, emails: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract metadata from email thread
        
        Args:
            emails: List of emails
            
        Returns:
            Metadata dictionary
        """
        metadata = {
            'email_count': len(emails),
            'participants': set(),
            'subjects': set()
        }
        
        for email in emails:
            # Collect participants
            if 'from' in email:
                metadata['participants'].add(email['from'])
            if 'to' in email:
                if isinstance(email['to'], list):
                    metadata['participants'].update(email['to'])
                else:
                    metadata['participants'].add(email['to'])
            
            # Collect subjects
            if 'subject' in email:
                metadata['subjects'].add(email['subject'])
        
        # Convert sets to lists for JSON serialization
        metadata['participants'] = list(metadata['participants'])
        metadata['subjects'] = list(metadata['subjects'])
        
        return metadata
    
    def _format_thread_summary(
        self,
        summary: str,
        metadata: Dict[str, Any],
        emails: List[Dict[str, Any]]
    ) -> str:
        """
        Format thread summary with context
        
        Args:
            summary: Generated summary
            metadata: Thread metadata
            emails: Original emails
            
        Returns:
            Formatted summary
        """
        parts = []
        
        # Add header
        email_count = metadata.get('email_count', 0)
        participant_count = len(metadata.get('participants', []))
        
        parts.append(f"📧 Email Thread Summary ({email_count} messages, {participant_count} participants)\n")
        
        # Add summary
        parts.append(summary)
        
        return "\n".join(parts)


class CalendarEventSummarizer:
    """Summarize calendar events and meetings"""
    
    def __init__(self, llm_client=None):
        """
        Initialize calendar event summarizer
        
        Args:
            llm_client: LLM client instance
        """
        self.abstractive = AbstractiveSummarizer(llm_client)
        self.extractive = ExtractiveSummarizer()
    
    def summarize(
        self,
        events: List[Dict[str, Any]],
        format_type: str = DEFAULT_FORMAT,
        length: str = DEFAULT_LENGTH,
        focus: Optional[str] = None
    ) -> str:
        """
        Summarize calendar events
        
        Args:
            events: List of event dictionaries with keys: title, start, end, description, attendees
            format_type: Output format
            length: Summary length
            focus: Optional focus area
            
        Returns:
            Events summary
        """
        if not events:
            return "No events to summarize."
        
        # Build content from events
        events_content = self._build_events_content(events)
        
        # Extract metadata
        metadata = self._extract_events_metadata(events)
        
        # Try AI summarization first
        summary = self.abstractive.summarize(
            events_content,
            format_type,
            length,
            focus,
            metadata={'source_type': 'calendar', **metadata}
        )
        
        # Fallback to extractive
        if not summary:
            summary = self.extractive.summarize(events_content, format_type, length)
        
        # Add events context
        return self._format_events_summary(summary, metadata, events)
    
    def _build_events_content(self, events: List[Dict[str, Any]]) -> str:
        """
        Build formatted content from events
        
        Args:
            events: List of events
            
        Returns:
            Formatted events content
        """
        parts = []
        
        for event in events:
            title = event.get('title', 'Untitled Event')
            description = event.get('description', '')
            start = event.get('start', '')
            
            parts.append(f"Event: {title}")
            if start:
                parts.append(f"Time: {start}")
            if description:
                parts.append(f"{description}\n")
        
        return "\n".join(parts)
    
    def _extract_events_metadata(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract metadata from events
        
        Args:
            events: List of events
            
        Returns:
            Metadata dictionary
        """
        metadata = {
            'event_count': len(events),
            'attendees': set(),
            'titles': []
        }
        
        for event in events:
            # Collect attendees
            if 'attendees' in event:
                if isinstance(event['attendees'], list):
                    metadata['attendees'].update(event['attendees'])
            
            # Collect titles
            if 'title' in event:
                metadata['titles'].append(event['title'])
        
        # Convert sets to lists
        metadata['attendees'] = list(metadata['attendees'])
        
        return metadata
    
    def _format_events_summary(
        self,
        summary: str,
        metadata: Dict[str, Any],
        events: List[Dict[str, Any]]
    ) -> str:
        """
        Format events summary with context
        
        Args:
            summary: Generated summary
            metadata: Events metadata
            events: Original events
            
        Returns:
            Formatted summary
        """
        parts = []
        
        # Add header
        event_count = metadata.get('event_count', 0)
        parts.append(f"📅 Calendar Summary ({event_count} events)\n")
        
        # Add summary
        parts.append(summary)
        
        return "\n".join(parts)


class ConversationSummarizer:
    """Summarize conversations and chat threads"""
    
    def __init__(self, llm_client=None):
        """
        Initialize conversation summarizer
        
        Args:
            llm_client: LLM client instance
        """
        self.abstractive = AbstractiveSummarizer(llm_client)
        self.extractive = ExtractiveSummarizer()
    
    def summarize(
        self,
        messages: List[Dict[str, Any]],
        format_type: str = DEFAULT_FORMAT,
        length: str = DEFAULT_LENGTH,
        focus: Optional[str] = None
    ) -> str:
        """
        Summarize conversation
        
        Args:
            messages: List of message dictionaries with keys: speaker, content, timestamp
            format_type: Output format
            length: Summary length
            focus: Optional focus area
            
        Returns:
            Conversation summary
        """
        if not messages:
            return "No messages to summarize."
        
        # Build conversation content
        conversation_content = self._build_conversation_content(messages)
        
        # Extract metadata
        metadata = self._extract_conversation_metadata(messages)
        
        # Try AI summarization first
        summary = self.abstractive.summarize(
            conversation_content,
            format_type,
            length,
            focus,
            metadata={'source_type': 'conversation', **metadata}
        )
        
        # Fallback to extractive
        if not summary:
            summary = self.extractive.summarize(conversation_content, format_type, length)
        
        # Add conversation context
        return self._format_conversation_summary(summary, metadata, messages)
    
    def _build_conversation_content(self, messages: List[Dict[str, Any]]) -> str:
        """
        Build formatted content from conversation
        
        Args:
            messages: List of messages
            
        Returns:
            Formatted conversation content
        """
        parts = []
        
        for msg in messages:
            speaker = msg.get('speaker', 'Unknown')
            content = msg.get('content', '')
            
            parts.append(f"{speaker}: {content}")
        
        return "\n".join(parts)
    
    def _extract_conversation_metadata(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract metadata from conversation
        
        Args:
            messages: List of messages
            
        Returns:
            Metadata dictionary
        """
        metadata = {
            'message_count': len(messages),
            'participants': set()
        }
        
        for msg in messages:
            if 'speaker' in msg:
                metadata['participants'].add(msg['speaker'])
        
        # Convert sets to lists
        metadata['participants'] = list(metadata['participants'])
        
        return metadata
    
    def _format_conversation_summary(
        self,
        summary: str,
        metadata: Dict[str, Any],
        messages: List[Dict[str, Any]]
    ) -> str:
        """
        Format conversation summary with context
        
        Args:
            summary: Generated summary
            metadata: Conversation metadata
            messages: Original messages
            
        Returns:
            Formatted summary
        """
        parts = []
        
        # Add header
        message_count = metadata.get('message_count', 0)
        participant_count = len(metadata.get('participants', []))
        
        parts.append(f"💬 Conversation Summary ({message_count} messages, {participant_count} participants)\n")
        
        # Add summary
        parts.append(summary)
        
        return "\n".join(parts)
