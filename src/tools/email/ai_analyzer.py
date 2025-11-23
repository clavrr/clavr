"""
AI-powered email analysis for task extraction and intelligent processing

This module uses LLM to:
- Extract actionable tasks from email content
- Detect meeting requests and calendar events
- Classify email urgency and priority
- Suggest appropriate categories and tags
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import json
import re

from ...utils.logger import setup_logger
from .constants import LIMITS, URGENT_PATTERNS
from ..constants import ToolConfig
from ...core.calendar.utils import DEFAULT_DURATION_MINUTES

logger = setup_logger(__name__)

# Constants for AI analyzer
LLM_TEMPERATURE_TASK_EXTRACTION = 0.3  # Lower temperature for consistent extraction
LLM_MAX_TOKENS_TASK_EXTRACTION = 1000
MAX_BODY_LENGTH_FOR_PROMPT = 1500
MIN_TASK_TEXT_LENGTH = 10
MAX_TASK_TITLE_LENGTH = 200
MAX_SUBJECT_PREVIEW_LENGTH = 50
MAX_TASKS_EXTRACTED = 10
MAX_TAGS_SUGGESTED = 5
HIGH_PRIORITY_DEADLINE_DAYS = 3  # Deadlines within this many days are high priority

# Task duration estimates (in hours)
TASK_DURATION_SHORT = 0.25  # 15 minutes
TASK_DURATION_MEDIUM = 0.5  # 30 minutes
TASK_DURATION_STANDARD = 1.0  # 1 hour
TASK_DURATION_LONG = 2.0  # 2 hours

# Word count thresholds for duration estimation
WORD_COUNT_SHORT = 5
WORD_COUNT_MEDIUM = 10
WORD_COUNT_STANDARD = 20


class EmailAIAnalyzer:
    """Extract actionable insights from emails using AI"""
    
    def __init__(self, llm_client: Optional[Any] = None):
        """
        Initialize email AI analyzer
        
        Args:
            llm_client: LLM client for AI analysis (OpenAI, Anthropic, etc.)
        """
        self.llm_client = llm_client
        logger.info("[EMAIL_AI] EmailAIAnalyzer initialized")
    
    def extract_action_items(
        self,
        email_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        auto_categorize: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Extract actionable tasks from email using AI
        
        Args:
            email_data: Email data with subject, body, sender, etc.
            context: Additional context (user preferences, project info, etc.)
            auto_categorize: Automatically categorize and prioritize tasks
            
        Returns:
            List of tasks with:
                - title: Task description
                - priority: Inferred priority (low/medium/high/critical)
                - due_date: Suggested due date (if mentioned)
                - category: Suggested category (work/personal/etc.)
                - notes: Additional context from email
                - email_id: Link back to source email
        """
        logger.info(f"[EMAIL_AI] Extracting action items from email: {email_data.get('subject', 'No subject')}")
        
        # Extract email content
        subject = email_data.get('subject', '')
        body = email_data.get('body', email_data.get('snippet', ''))
        sender = email_data.get('from', email_data.get('sender', 'Unknown'))
        email_id = email_data.get('id', '')
        
        # If no LLM client, use rule-based extraction
        if not self.llm_client:
            return self._rule_based_task_extraction(email_data)
        
        # Build AI prompt
        prompt = self._build_task_extraction_prompt(subject, body, sender, context)
        
        try:
            # Call LLM
            response = self.llm_client.complete(
                prompt=prompt,
                temperature=LLM_TEMPERATURE_TASK_EXTRACTION,
                max_tokens=LLM_MAX_TOKENS_TASK_EXTRACTION
            )
            
            # Parse response
            tasks = self._parse_task_extraction_response(response, email_id)
            
            logger.info(f"[EMAIL_AI] Extracted {len(tasks)} action items")
            return tasks
            
        except Exception as e:
            logger.error(f"[EMAIL_AI] Failed to extract tasks with LLM: {e}")
            # Fallback to rule-based
            return self._rule_based_task_extraction(email_data)
    
    def _build_task_extraction_prompt(
        self,
        subject: str,
        body: str,
        sender: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build prompt for task extraction"""
        
        context_str = ""
        if context:
            if 'user_projects' in context:
                context_str += f"\nUser's active projects: {', '.join(context['user_projects'])}"
            if 'user_categories' in context:
                context_str += f"\nUser's task categories: {', '.join(context['user_categories'])}"
        
        prompt = f"""Analyze this email and extract all actionable tasks or to-do items.

Email Details:
Subject: {subject}
From: {sender}
Body:
{body[:MAX_BODY_LENGTH_FOR_PROMPT]}
{context_str}

Instructions:
1. Identify all explicit and implicit action items
2. For each task, provide:
   - title: Clear, actionable task description (start with verb)
   - priority: low, medium, high, or critical (based on urgency indicators)
   - due_date: Suggested due date in ISO format (if mentioned or inferable)
   - category: work, personal, finance, travel, shopping, or other
   - notes: Brief context or additional details

3. Priority guidelines:
   - critical: Urgent deadlines, legal/compliance, critical issues
   - high: Deadlines within {HIGH_PRIORITY_DEADLINE_DAYS} days, important stakeholders
   - medium: Standard tasks, normal deadlines
   - low: Optional tasks, long-term items

4. Return ONLY a valid JSON array of tasks:
[
  {{
    "title": "Review Q4 budget proposal",
    "priority": "high",
    "due_date": "2025-11-20",
    "category": "work",
    "notes": "Mentioned in paragraph 2, deadline is Friday"
  }},
  ...
]

If no action items found, return empty array: []
"""
        return prompt
    
    def _parse_task_extraction_response(
        self,
        response: str,
        email_id: str
    ) -> List[Dict[str, Any]]:
        """Parse LLM response into task list"""
        try:
            # Extract JSON from response
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                tasks = json.loads(json_str)
                
                # Add email_id to each task
                for task in tasks:
                    task['email_id'] = email_id
                    task['source'] = 'email_ai'
                
                return tasks
            else:
                logger.warning("[EMAIL_AI] No JSON array found in LLM response")
                return []
                
        except json.JSONDecodeError as e:
            logger.error(f"[EMAIL_AI] Failed to parse JSON response: {e}")
            return []
    
    def _rule_based_task_extraction(
        self,
        email_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Fallback: Extract tasks using rule-based patterns
        
        Looks for common patterns:
        - "TODO:", "TO DO:", "Action item:"
        - "Please [verb]", "Can you [verb]", "Could you [verb]"
        - "Need to [verb]", "Don't forget to [verb]"
        - Bullet points with action verbs
        """
        logger.info("[EMAIL_AI] Using rule-based task extraction")
        
        tasks = []
        subject = email_data.get('subject', '')
        body = email_data.get('body', email_data.get('snippet', ''))
        email_id = email_data.get('id', '')
        
        # Combine subject and body
        text = f"{subject}\n{body}"
        
        # Pattern 1: Explicit task markers
        explicit_patterns = [
            r'TODO:?\s*(.+?)(?:\n|$)',
            r'TO DO:?\s*(.+?)(?:\n|$)',
            r'Action item:?\s*(.+?)(?:\n|$)',
            r'Task:?\s*(.+?)(?:\n|$)',
        ]
        
        for pattern in explicit_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                task_text = match.group(1).strip()
                if len(task_text) > MIN_TASK_TEXT_LENGTH:
                    tasks.append({
                        'title': task_text[:MAX_TASK_TITLE_LENGTH],
                        'priority': 'medium',
                        'category': 'work',
                        'notes': f'Extracted from email: {subject[:MAX_SUBJECT_PREVIEW_LENGTH]}',
                        'email_id': email_id,
                        'source': 'rule_based'
                    })
        
        # Pattern 2: Request patterns
        request_patterns = [
            r'(?:please|can you|could you|would you)\s+(.{10,100}?)(?:\.|,|\n|$)',
            r'(?:need to|needs to|must)\s+(.{10,100}?)(?:\.|,|\n|$)',
            r'(?:don\'t forget to|remember to)\s+(.{10,100}?)(?:\.|,|\n|$)',
        ]
        
        for pattern in request_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                task_text = match.group(1).strip()
                if len(task_text) > MIN_TASK_TEXT_LENGTH:
                    tasks.append({
                        'title': task_text[:MAX_TASK_TITLE_LENGTH],
                        'priority': 'medium',
                        'category': 'work',
                        'notes': f'Request from: {email_data.get("from", "Unknown")}',
                        'email_id': email_id,
                        'source': 'rule_based'
                    })
        
        # Remove duplicates
        unique_tasks = []
        seen_titles = set()
        for task in tasks:
            title_lower = task['title'].lower()
            if title_lower not in seen_titles:
                seen_titles.add(title_lower)
                unique_tasks.append(task)
        
        logger.info(f"[EMAIL_AI] Rule-based extraction found {len(unique_tasks)} tasks")
        return unique_tasks[:MAX_TASKS_EXTRACTED]
    
    def suggest_calendar_events(
        self,
        email_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Detect meeting requests/invitations in emails
        
        Returns:
            List of suggested calendar events with:
                - title: Meeting title
                - start_time: Suggested start time
                - duration_minutes: Suggested duration
                - attendees: List of attendees
                - location: Meeting location (if mentioned)
                - description: Meeting description
        """
        logger.info(f"[EMAIL_AI] Detecting calendar events from email")
        
        subject = email_data.get('subject', '')
        body = email_data.get('body', email_data.get('snippet', ''))
        
        # Common meeting patterns
        meeting_keywords = [
            'meeting', 'call', 'discussion', 'sync', 'standup',
            'review', 'presentation', 'demo', 'workshop', 'session'
        ]
        
        events = []
        
        # Check if email mentions meetings
        text_lower = f"{subject} {body}".lower()
        is_meeting_related = any(keyword in text_lower for keyword in meeting_keywords)
        
        if not is_meeting_related:
            return []
        
        # Extract time mentions (simplified - could use LLM for better extraction)
        time_patterns = [
            r'(?:tomorrow|next week|next month)\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)',
            r'(\d{1,2}(?::\d{2})?\s*(?:am|pm))\s+(?:tomorrow|next week)',
            r'(?:on\s+)?(\w+day)\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)',
        ]
        
        for pattern in time_patterns:
            matches = re.finditer(pattern, body, re.IGNORECASE)
            for match in matches:
                # Create suggested event
                event = {
                    'title': subject if 'meeting' in subject.lower() else f"Meeting: {subject[:MAX_SUBJECT_PREVIEW_LENGTH]}",
                    'start_time': None,  # Would need date parsing
                    'duration_minutes': DEFAULT_DURATION_MINUTES,
                    'description': f"Suggested from email",
                    'notes': f"Extracted from email: {email_data.get('from', 'Unknown')}"
                }
                events.append(event)
                break  # One event per email for now
        
        logger.info(f"[EMAIL_AI] Found {len(events)} potential calendar events")
        return events
    
    def classify_urgency(
        self,
        email_data: Dict[str, Any]
    ) -> str:
        """
        Classify email urgency: urgent, normal, low
        
        Args:
            email_data: Email data
            
        Returns:
            'urgent', 'normal', or 'low'
        """
        subject = email_data.get('subject', '').lower()
        body = email_data.get('body', email_data.get('snippet', '')).lower()
        
        # Urgent indicators - use patterns from constants
        urgent_keywords = URGENT_PATTERNS.ACTION_KEYWORDS
        
        # Low priority indicators
        low_keywords = [
            'fyi', 'for your information', 'no action needed',
            'optional', 'at your convenience', 'when you have time'
        ]
        
        text = f"{subject} {body}"
        
        # Check for urgent indicators
        if any(keyword in text for keyword in urgent_keywords):
            return 'urgent'
        
        # Check for low priority indicators
        if any(keyword in text for keyword in low_keywords):
            return 'low'
        
        # Default to normal
        return 'normal'
    
    def suggest_email_category(
        self,
        email_data: Dict[str, Any]
    ) -> str:
        """
        Suggest email category based on content
        
        Returns:
            Category: work, personal, finance, travel, shopping, etc.
        """
        subject = email_data.get('subject', '').lower()
        body = email_data.get('body', email_data.get('snippet', '')).lower()
        sender = email_data.get('from', '').lower()
        
        text = f"{subject} {body} {sender}"
        
        # Category keywords
        categories = {
            'finance': ['invoice', 'payment', 'bill', 'receipt', 'bank', 'credit card', 'transaction'],
            'travel': ['flight', 'hotel', 'booking', 'reservation', 'itinerary', 'trip'],
            'shopping': ['order', 'shipping', 'delivery', 'purchase', 'amazon', 'ebay'],
            'work': ['project', 'meeting', 'deadline', 'review', 'proposal', 'report'],
            'personal': ['family', 'friend', 'personal'],
        }
        
        # Count matches for each category
        category_scores: Dict[str, int] = {}
        for category, keywords in categories.items():
            score = sum(1 for keyword in keywords if keyword in text)
            if score > 0:
                category_scores[category] = score
        
        # Return highest scoring category
        if category_scores:
            # Use lambda to make type checker happy
            return max(category_scores.items(), key=lambda x: x[1])[0]
        
        return 'other'
    
    def auto_enhance_task(
        self,
        task_description: str,
        email_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Use AI to enhance task with additional metadata
        
        Args:
            task_description: Task description
            email_context: Email context for better enhancement
            
        Returns:
            Enhanced task data with suggested improvements
        """
        logger.info(f"[EMAIL_AI] Auto-enhancing task: {task_description[:MAX_SUBJECT_PREVIEW_LENGTH]}")
        
        # Basic enhancement without LLM
        enhancements = {
            'original_title': task_description,
            'suggested_title': task_description,  # Could use LLM to improve
            'estimated_hours': self._estimate_task_duration(task_description),
            'suggested_tags': self._suggest_tags(task_description),
            'suggested_project': None,
        }
        
        # If email context provided, add more context
        if email_context:
            enhancements['context'] = {
                'from_email': email_context.get('from', 'Unknown'),
                'email_subject': email_context.get('subject', ''),
                'email_id': email_context.get('id', '')
            }
        
        return enhancements
    
    def _estimate_task_duration(self, task_description: str) -> float:
        """Estimate task duration in hours based on description"""
        # Simple heuristic based on word count
        length = len(task_description.split())
        
        if length < WORD_COUNT_SHORT:
            return TASK_DURATION_SHORT
        elif length < WORD_COUNT_MEDIUM:
            return TASK_DURATION_MEDIUM
        elif length < WORD_COUNT_STANDARD:
            return TASK_DURATION_STANDARD
        else:
            return TASK_DURATION_LONG
    
    def _suggest_tags(self, task_description: str) -> List[str]:
        """Suggest tags based on task description"""
        tags = []
        desc_lower = task_description.lower()
        
        tag_keywords = {
            'urgent': ['urgent', 'asap', 'immediately', 'critical'],
            'review': ['review', 'check', 'verify', 'approve'],
            'email': ['email', 'send', 'reply', 'forward'],
            'meeting': ['meeting', 'call', 'discussion', 'sync'],
            'research': ['research', 'investigate', 'explore', 'analyze'],
            'create': ['create', 'build', 'develop', 'design'],
        }
        
        for tag, keywords in tag_keywords.items():
            if any(keyword in desc_lower for keyword in keywords):
                tags.append(tag)
        
        return tags[:MAX_TAGS_SUGGESTED]
