"""
Intelligent Email Parser with LLM-based Intent Extraction

This parser doesn't just extract text from emails - it understands them.
It uses an LLM to extract:
- Action items ("send me the report")
- Intents (schedule_meeting, request_info)  
- Entities (people, dates, companies, topics)
- Questions asked
"""
import json
import re
from typing import Dict, Any, List, Optional
from datetime import datetime

from .base import BaseParser, ParsedNode, Relationship, Entity, ExtractedIntents
from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class EmailParser(BaseParser):
    """
    Multi-stage email parser that creates a rich knowledge graph node
    
    Stages:
    1. Extract metadata (from, to, subject, date)
    2. Detect and classify attachments
    3. Extract intents and entities from body using LLM
    4. Build relationships (FROM Contact, TO Contact, etc)
    """
    
    def __init__(self, llm_client=None):
        """
        Initialize email parser
        
        Args:
            llm_client: LLM client for intent extraction (optional)
        """
        self.llm_client = llm_client
        self.use_llm = llm_client is not None
    
    async def parse(self, email_data: Dict[str, Any]) -> ParsedNode:
        """
        Parse email into structured knowledge graph node
        
        Args:
            email_data: Raw email data from Gmail API
            
        Returns:
            ParsedNode with email data, intents, and relationships
        """
        try:
            # Stage 1: Extract metadata
            metadata = self._extract_metadata(email_data)
            
            # Stage 2: Classify attachments
            attachment_info = self._classify_attachments(email_data)
            
            # Stage 3: Extract intents and entities (LLM-based)
            intents = await self._extract_intents(email_data.get('body', ''), email_data.get('subject', ''))
            
            # Stage 4: Build relationships
            relationships = self._build_relationships(email_data, intents)
            
            # Create node
            # Serialize complex types to JSON strings for schema compliance
            attachment_info_str = json.dumps(attachment_info) if attachment_info else "[]"
            intents_dict = intents.to_dict() if intents else {}
            intents_str = json.dumps(intents_dict) if intents_dict else "{}"
            
            node = ParsedNode(
                node_id=self.generate_node_id('Email', email_data.get('id', '')),
                node_type='Email',
                properties={
                    **metadata,
                    'attachment_info': attachment_info_str,  # JSON string
                    'intents': intents_str,  # JSON string
                    'has_action_items': len(intents.action_items) > 0 if intents else False,
                    'has_questions': len(intents.questions) > 0 if intents else False,
                },
                relationships=relationships,
                searchable_text=self._build_searchable_text(metadata, email_data)
            )
            
            logger.debug(f"Parsed email: {node.node_id} with {len(relationships)} relationships")
            return node
            
        except Exception as e:
            logger.error(f"Failed to parse email: {e}", exc_info=True)
            raise
    
    def _extract_metadata(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract structured metadata from email"""
        # Extract email address from sender string (handles "Name <email@domain.com>" format)
        sender_raw = email_data.get('sender', '')
        sender_email = self._extract_email_address(sender_raw)
        
        # Parse date - extract date only (YYYY-MM-DD format for schema validation)
        date_raw = email_data.get('date', '')
        parsed_date = self._parse_date_to_date_only(date_raw)
        
        # Extract body (required property) - truncate if too long, handle empty
        body = email_data.get('body', '') or ''
        body_cleaned = self.clean_text(body)
        
        # Handle empty body (required by schema - use placeholder)
        if not body_cleaned or len(body_cleaned.strip()) == 0:
            body_cleaned = "[No body content]"
        
        # Truncate body to max 10000 characters (schema limit)
        # Must be exactly <= 10000 (not 10000 + "... [truncated]")
        MAX_BODY_LENGTH = 10000
        if len(body_cleaned) > MAX_BODY_LENGTH:
            # Reserve space for truncation marker
            truncate_marker = "... [truncated]"
            max_content_length = MAX_BODY_LENGTH - len(truncate_marker)
            body_cleaned = body_cleaned[:max_content_length] + truncate_marker
            logger.debug(f"Truncated email body from {len(body)} to {len(body_cleaned)} characters")
        
        # Final safety check - ensure it's exactly <= 10000
        if len(body_cleaned) > MAX_BODY_LENGTH:
            body_cleaned = body_cleaned[:MAX_BODY_LENGTH]
            logger.warning(f"Body still exceeded limit after truncation, hard-capped to {MAX_BODY_LENGTH}")
        
        return {
            'subject': self.clean_text(email_data.get('subject', '')),
            'sender': sender_email,  # Use extracted email, not full string
            'date': parsed_date,  # Use date-only format (YYYY-MM-DD) for schema
            'body': body_cleaned,  # Required property (truncated if needed)
            # Optional metadata (not in schema but useful)
            'email_id': email_data.get('id', ''),
            'thread_id': email_data.get('threadId', ''),
            'sender_domain': self._extract_domain(sender_email),
            'recipients': self._extract_emails_from_string(email_data.get('to', '')),
            'cc': self._extract_emails_from_string(email_data.get('cc', '')),
            'timestamp': self._parse_date(date_raw),  # Full ISO datetime for internal use
            'labels': email_data.get('labels', []),
            'is_unread': 'UNREAD' in email_data.get('labels', []),
            'is_important': 'IMPORTANT' in email_data.get('labels', []),
            'is_starred': 'STARRED' in email_data.get('labels', []),
            'has_attachments': email_data.get('has_attachments', False),
            'folder': email_data.get('folder', 'inbox'),
        }
    
    def _extract_email_address(self, sender_string: str) -> str:
        """Extract email address from sender string like 'Name <email@domain.com>'"""
        if not sender_string:
            return ''
        
        # Pattern to match email address
        email_pattern = r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
        match = re.search(email_pattern, sender_string)
        
        if match:
            return match.group(1).lower().strip()
        
        # If no match, return original (might already be just an email)
        return sender_string.strip()
    
    def _extract_emails_from_string(self, email_string: str) -> List[str]:
        """Extract email addresses from comma-separated string"""
        if not email_string:
            return []
        
        emails = []
        for part in email_string.split(','):
            email = self._extract_email_address(part.strip())
            if email:
                emails.append(email)
        
        return emails
    
    def _classify_attachments(self, email_data: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Classify attachments by type
        
        Returns list of {filename, type, parser_hint}
        type can be: receipt, document, image, pdf, other
        parser_hint suggests which parser to use
        """
        attachments = []
        
        if not email_data.get('has_attachments'):
            return attachments
        
        for filename in email_data.get('attachment_names', '').split(','):
            filename = filename.strip()
            if not filename:
                continue
            
            # Classify by filename and keywords
            att_type = 'other'
            parser_hint = 'attachment_parser'
            
            # Receipt detection
            if any(kw in filename.lower() for kw in ['receipt', 'invoice', 'statement', 'bill']):
                att_type = 'receipt'
                parser_hint = 'receipt_parser'
            
            # Document detection
            elif filename.lower().endswith(('.pdf', '.doc', '.docx', '.txt')):
                att_type = 'document'
                parser_hint = 'attachment_parser'
            
            # Image detection
            elif filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                att_type = 'image'
                parser_hint = 'image_parser'
            
            attachments.append({
                'filename': filename,
                'type': att_type,
                'parser_hint': parser_hint
            })
        
        return attachments
    
    async def _extract_intents(self, body: str, subject: str) -> Optional[ExtractedIntents]:
        """
        Use LLM to extract intents and entities from email
        
        This is the "intelligence" - we understand what the email is about,
        not just what words it contains.
        """
        if not self.use_llm or not body:
            return None
        
        try:
            prompt = self._build_intent_extraction_prompt(body, subject)
            response = await self.llm_client.ainvoke(prompt)
            
            # Parse LLM response
            intents = self._parse_llm_response(response)
            return intents
            
        except Exception as e:
            logger.warning(f"Intent extraction failed: {e}")
            # Fallback to simple regex-based extraction
            return self._fallback_intent_extraction(body, subject)
    
    def _build_intent_extraction_prompt(self, body: str, subject: str) -> str:
        """Build prompt for LLM intent extraction"""
        return f"""You are a productivity assistant analyzing an email. Extract structured information.

Subject: {subject}
Body: {body[:2000]}  

Extract the following in JSON format:
{{
    "action_items": ["list of tasks or requests mentioned"],
    "intents": ["intent types: schedule_meeting, request_info, share_update, ask_question, etc"],
    "entities": [
        {{"entity_type": "person|date|company|topic|location", "value": "entity value", "confidence": 0.0-1.0}}
    ],
    "topics": ["main topics discussed"],
    "questions": ["questions asked in the email"]
}}

Focus on:
- Action items: Things to do ("send me", "can you", "please review")
- Intents: What sender wants (schedule, inform, request)
- Entities: Who, what, when, where mentioned
- Topics: Key subjects (not generic words)
- Questions: Actual questions asked

Respond ONLY with the JSON, no other text."""
    
    def _parse_llm_response(self, response) -> ExtractedIntents:
        """Parse LLM JSON response into ExtractedIntents"""
        try:
            # Extract JSON from response
            if hasattr(response, 'content'):
                text = response.content
            else:
                text = str(response)
            
            # Clean markdown code blocks
            json_match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
            if json_match:
                text = json_match.group(1)
            
            data = json.loads(text)
            
            # Convert entities to Entity objects
            entities = [
                Entity(
                    entity_type=e.get('entity_type', 'unknown'),
                    value=e.get('value', ''),
                    confidence=e.get('confidence', 1.0)
                )
                for e in data.get('entities', [])
            ]
            
            return ExtractedIntents(
                action_items=data.get('action_items', []),
                intents=data.get('intents', []),
                entities=entities,
                topics=data.get('topics', []),
                questions=data.get('questions', [])
            )
            
        except Exception as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return ExtractedIntents()
    
    def _fallback_intent_extraction(self, body: str, subject: str) -> ExtractedIntents:
        """Simple regex-based fallback when LLM is unavailable"""
        intents = ExtractedIntents()
        
        text = f"{subject} {body}".lower()
        
        # Detect action items
        action_patterns = [
            r'please\s+(.+?)[\.\,]',
            r'can\s+you\s+(.+?)[\.\,]',
            r'could\s+you\s+(.+?)[\.\,]',
            r'send\s+me\s+(.+?)[\.\,]',
        ]
        for pattern in action_patterns:
            matches = re.findall(pattern, text)
            intents.action_items.extend(matches[:3])  # Limit to 3
        
        # Detect intents
        if any(word in text for word in ['meet', 'schedule', 'calendar']):
            intents.intents.append('schedule_meeting')
        if any(word in text for word in ['?', 'can you', 'could you']):
            intents.intents.append('request_info')
        
        # Detect questions
        questions = re.findall(r'([^\.]+\?)', body)
        intents.questions = questions[:3]  # Limit to 3
        
        return intents
    
    def _build_relationships(self, email_data: Dict[str, Any], intents: Optional[ExtractedIntents]) -> List[Relationship]:
        """
        Build relationships from email to other nodes
        
        Relationships created:
        - Email FROM Contact
        - Email TO Contact(s)
        - Email CONTAINS ActionItem (for each action)
        - Email MENTIONS Company/Topic
        """
        relationships = []
        
        # FROM relationship - extract email from sender string
        sender_raw = email_data.get('sender', '')
        sender_email = self._extract_email_address(sender_raw)
        if sender_email:
            relationships.append(Relationship(
                from_node=self.generate_node_id('Email', email_data.get('id', '')),
                to_node=self.generate_node_id('Contact', sender_email),
                rel_type='FROM'
            ))
        
        # TO relationships - extract emails from recipient strings
        recipients_raw = email_data.get('to', '')
        recipients = self._extract_emails_from_string(recipients_raw)
        for recipient_email in recipients:
            if recipient_email:
                relationships.append(Relationship(
                    from_node=self.generate_node_id('Email', email_data.get('id', '')),
                    to_node=self.generate_node_id('Contact', recipient_email),
                    rel_type='TO'
                ))
        
        # CONTAINS ActionItem relationships
        if intents and intents.action_items:
            for i, action in enumerate(intents.action_items):
                action_id = f"{email_data.get('id', '')}_{i}"
                relationships.append(Relationship(
                    from_node=self.generate_node_id('Email', email_data.get('id', '')),
                    to_node=self.generate_node_id('ActionItem', action_id),
                    rel_type='CONTAINS',
                    properties={'action_description': action}
                ))
        
        # MENTIONS Topic relationships
        if intents and intents.topics:
            for topic in intents.topics[:5]:  # Limit to top 5 topics
                relationships.append(Relationship(
                    from_node=self.generate_node_id('Email', email_data.get('id', '')),
                    to_node=self.generate_node_id('Topic', topic.lower()),
                    rel_type='DISCUSSES'
                ))
        
        return relationships
    
    def _build_searchable_text(self, metadata: Dict[str, Any], email_data: Dict[str, Any]) -> str:
        """Build text for vector embedding"""
        parts = []
        
        if metadata.get('subject'):
            parts.append(f"Subject: {metadata['subject']}")
        
        if metadata.get('sender'):
            parts.append(f"From: {metadata['sender']}")
        
        body = email_data.get('body', '')
        if body:
            # Limit body length
            body_snippet = body[:1500] if len(body) > 1500 else body
            parts.append(f"Body: {body_snippet}")
        
        return "\n\n".join(parts)
    
    def _extract_domain(self, email: str) -> Optional[str]:
        """Extract domain from email address"""
        if '@' in email:
            return email.split('@')[1]
        return None
    
    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse date string to ISO format (with time)"""
        if not date_str:
            return None
        try:
            # Try to parse various formats
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)
            return dt.isoformat()
        except:
            return date_str
    
    def _parse_date_to_date_only(self, date_str: str) -> Optional[str]:
        """Parse date string to date-only format (YYYY-MM-DD) for schema validation"""
        if not date_str:
            return None
        try:
            # Try to parse various formats
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)
            # Return date only in YYYY-MM-DD format
            return dt.strftime('%Y-%m-%d')
        except:
            # Fallback: try to extract date from string
            try:
                # Try ISO format first
                from datetime import datetime
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return dt.strftime('%Y-%m-%d')
            except:
                # Last resort: return as-is (might fail validation)
                return date_str[:10] if len(date_str) >= 10 else date_str
