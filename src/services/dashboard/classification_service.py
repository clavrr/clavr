"""
Message Classification Service

LLM-powered classification of messages from all sources (email, Slack, Linear)
to determine priority, urgency, and required actions.
"""
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import asyncio

from sqlalchemy import select, and_, or_

from src.utils.logger import setup_logger
from src.utils.config import Config, load_config
from src.ai.llm_factory import LLMFactory
from src.database import get_db_context, MessageClassification, User

logger = setup_logger(__name__)

# Classification prompt template
CLASSIFICATION_PROMPT = """You are an intelligent message classifier. Analyze the following messages and determine which ones require the user's attention.

For each message, determine:
1. **needs_response**: Does this message require a response or action from the user? (true/false)
2. **urgency**: How urgent is this? (high, medium, low)
3. **reason**: Brief explanation of why this needs attention (1 sentence)
4. **suggested_action**: What should the user do? (reply, schedule, delegate, review, none)

IMPORTANT CRITERIA FOR needs_response=true:
- Someone asks a direct question
- Money, investment, or business opportunity mentioned
- Deadline or time-sensitive request
- Personal or professional relationship building
- Someone offers help or expresses interest
- Action items or commitments mentioned

OUTPUT FORMAT (JSON array):
[
  {"id": "msg_1", "needs_response": true, "urgency": "high", "reason": "Alexandra offers $50k investment opportunity", "suggested_action": "reply"},
  {"id": "msg_2", "needs_response": false, "urgency": "low", "reason": "Newsletter, no action needed", "suggested_action": "none"}
]

MESSAGES TO CLASSIFY:
{messages_json}

Return ONLY the JSON array, no other text."""


class MessageClassificationService:
    """
    Service for LLM-based message classification.
    
    Analyzes messages from email, Slack, Linear and determines:
    - Whether user needs to respond
    - Urgency level
    - Suggested action
    """
    
    def __init__(self, config: Optional[Config] = None):
        self.config = config or load_config()
        self.llm_factory = LLMFactory()
    
    async def classify_messages(
        self, 
        user_id: int, 
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Classify a batch of messages using Gemini.
        
        Args:
            user_id: User ID for context
            messages: List of message dicts with 'id', 'source_type', 'title', 'sender', 'snippet'
            
        Returns:
            List of classification results
        """
        if not messages:
            return []
        
        logger.info(f"[ClassificationService] Classifying {len(messages)} messages for user {user_id}")
        
        # Prepare messages for LLM
        messages_for_llm = []
        for i, msg in enumerate(messages):
            messages_for_llm.append({
                "id": msg.get('id', f'msg_{i}'),
                "source": msg.get('source_type', 'email'),
                "from": msg.get('sender', 'Unknown'),
                "subject": msg.get('title', 'No Subject'),
                "preview": msg.get('snippet', '')[:500]  # Limit snippet length
            })
        
        # Create prompt
        prompt = CLASSIFICATION_PROMPT.format(
            messages_json=json.dumps(messages_for_llm, indent=2)
        )
        
        try:
            # Get LLM and invoke
            llm = self.llm_factory.get_llm_for_provider(
                self.config, 
                temperature=0.1  # Low temp for consistent classification
            )
            
            # Run in thread for async compatibility
            response = await asyncio.to_thread(llm.invoke, prompt)
            
            # Parse response
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Extract JSON from response
            try:
                # Try to find JSON array in response
                start_idx = response_text.find('[')
                end_idx = response_text.rfind(']') + 1
                if start_idx != -1 and end_idx > start_idx:
                    json_str = response_text[start_idx:end_idx]
                    classifications = json.loads(json_str)
                else:
                    logger.warning(f"[ClassificationService] No JSON array found in response")
                    classifications = []
            except json.JSONDecodeError as e:
                logger.error(f"[ClassificationService] Failed to parse LLM response: {e}")
                classifications = []
            
            logger.info(f"[ClassificationService] Classified {len(classifications)} messages")
            return classifications
            
        except Exception as e:
            logger.error(f"[ClassificationService] LLM classification failed: {e}")
            return []
    
    def store_classifications(
        self,
        user_id: int,
        messages: List[Dict[str, Any]],
        classifications: List[Dict[str, Any]]
    ) -> int:
        """
        Store classification results in database.
        
        Args:
            user_id: User ID
            messages: Original message list
            classifications: LLM classification results
            
        Returns:
            Number of classifications stored
        """
        # Build lookup from classifications by ID
        classification_map = {c.get('id'): c for c in classifications}
        
        stored_count = 0
        
        with get_db_context() as session:
            for msg in messages:
                msg_id = msg.get('id', '')
                classification = classification_map.get(msg_id, {})
                
                # Skip if no classification or doesn't need response
                needs_response = classification.get('needs_response', False)
                if not needs_response:
                    continue
                
                # Check if already exists (upsert)
                existing = session.query(MessageClassification).filter(
                    and_(
                        MessageClassification.user_id == user_id,
                        MessageClassification.source_type == msg.get('source_type', 'email'),
                        MessageClassification.source_id == msg_id
                    )
                ).first()
                
                if existing:
                    # Update existing
                    existing.needs_response = needs_response
                    existing.urgency = classification.get('urgency', 'low')
                    existing.classification_reason = classification.get('reason', '')
                    existing.suggested_action = classification.get('suggested_action', 'review')
                    existing.classified_at = datetime.utcnow()
                else:
                    # Create new
                    new_classification = MessageClassification(
                        user_id=user_id,
                        source_type=msg.get('source_type', 'email'),
                        source_id=msg_id,
                        needs_response=needs_response,
                        urgency=classification.get('urgency', 'low'),
                        classification_reason=classification.get('reason', ''),
                        suggested_action=classification.get('suggested_action', 'review'),
                        title=msg.get('title', 'No Title'),
                        sender=msg.get('sender', 'Unknown'),
                        snippet=msg.get('snippet', '')[:500],
                        source_date=msg.get('date'),
                        created_at=datetime.utcnow(),
                        classified_at=datetime.utcnow()
                    )
                    session.add(new_classification)
                
                stored_count += 1
            
            session.commit()
        
        logger.info(f"[ClassificationService] Stored {stored_count} classifications for user {user_id}")
        return stored_count
    
    def get_pending_reminders(
        self, 
        user_id: int, 
        hours: int = 48,
        limit: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Get pending reminders from classifications.
        
        Args:
            user_id: User ID
            hours: Time window in hours
            limit: Maximum results
            
        Returns:
            List of reminder dicts for BriefService
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        with get_db_context() as session:
            results = session.query(MessageClassification).filter(
                and_(
                    MessageClassification.user_id == user_id,
                    MessageClassification.needs_response == True,
                    MessageClassification.is_dismissed == False,
                    MessageClassification.classified_at >= cutoff
                )
            ).order_by(
                # High urgency first
                MessageClassification.urgency.asc(),  # 'high' < 'low' alphabetically
                MessageClassification.classified_at.desc()
            ).limit(limit).all()
            
            reminders = []
            for r in results:
                reminders.append({
                    "title": r.title,
                    "subtitle": f"from {r.sender}" if r.sender else r.classification_reason,
                    "type": r.source_type,
                    "urgency": r.urgency,
                    "due_date": r.source_date.isoformat() if r.source_date else None,
                    "id": f"classification_{r.id}",
                    "suggested_action": r.suggested_action,
                    "reason": r.classification_reason
                })
            
            return reminders
