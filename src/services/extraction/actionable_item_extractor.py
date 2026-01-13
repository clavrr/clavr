"""
Actionable Item Extractor Service.

Uses LLM to analyze text (emails, messages) and extract structured actionable items
like bills, appointments, and deadlines for proactive reminders.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass
import json
import re

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.ai.llm_factory import LLMFactory

logger = setup_logger(__name__)

@dataclass
class ExtractedItem:
    """Structured actionable item extracted from text."""
    title: str
    item_type: str  # bill, appointment, deadline, task
    due_date: Optional[str] = None
    amount: Optional[float] = None
    urgency: str = "medium"
    suggested_action: str = "Review"

class ActionableItemExtractor:
    """
    Extracts actionable items (bills, appointments, deadlines) from text
    using LLM-based analysis.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.llm = LLMFactory.get_llm_for_provider(config)
        
    async def extract_from_email(self, email_prop: Dict[str, Any]) -> List[ExtractedItem]:
        """Extract actionable items from an email object."""
        content = f"Subject: {email_prop.get('subject', '')}\n\n{email_prop.get('body', '')}"
        source_id = f"email:{email_prop.get('id')}"
        return await self.extract_from_text(content, source_id)

    async def extract_from_text(self, text: str, source_id: str) -> List[ExtractedItem]:
        """Core extraction logic using LLM."""
        if not text or len(text) < 10:
            return []
            
        # Quick keyword check to avoid expensive LLM calls
        triggers = ["due", "invoice", "bill", "appointment", "schedule", "deadline", "payment", "expire", "by EOD", "meeting", "meet"]
        if not any(t in text.lower() for t in triggers):
            return []
            
        prompt = f"""
        Analyze the following text and extract any ACTIONABLE items that require user attention.
        Focus specifically on:
        1. Bills/Invoices (amounts, due dates)
        2. Appointments/Meetings (dates, times)
        3. Hard Deadlines (due dates)
        4. Forms/Signatures required
        
        Text:
        {text[:2500]}
        
        Return a JSON array of objects with these fields:
        - title: Concise summary (e.g., "Pay $450 daycare invoice")
        - item_type: "bill", "appointment", "deadline", "task"
        - due_date: ISO 8601 datetime string (YYYY-MM-DDTHH:MM:SS) if identifiable, else null
        - amount: Float value if it's a bill, else null
        - urgency: "high", "medium", "low"
        - suggested_action: "Pay", "RSVP", "Sign", "Book", "Review"
        
        If no actionable items are found, return empty array [].
        ONLY return the JSON array.
        """
        
        try:
            try:
                # Use invoke in thread to avoid blocking loop if sync
                import asyncio
                response_msg = await asyncio.to_thread(self.llm.invoke, prompt)
            except AttributeError:
                # Fallback if invoke missing
                response_msg = await self.llm.generate_content_async(prompt)
                
            if hasattr(response_msg, 'content'):
                response = response_msg.content
            else:
                response = str(response_msg)
            data = self._parse_json_response(response)
            
            items = []
            for item in data:
                # Basic validation
                if not item.get("title"):
                    continue
                    
                items.append(ExtractedItem(
                    title=item.get("title", ""),
                    item_type=item.get("item_type", "task"),
                    due_date=item.get("due_date"),
                    amount=item.get("amount"),
                    urgency=item.get("urgency", "medium"),
                    suggested_action=item.get("suggested_action", "Review")
                ))
            
            if items:
                logger.info(f"[Extractor] Found {len(items)} actionable items in {source_id}")
                
            return items
            
        except Exception as e:
            logger.error(f"[Extractor] Extraction failed for {source_id}: {e}")
            return []

    def _parse_json_response(self, response: str) -> List[Dict]:
        """Helper to parse LLM JSON output robustly."""
        try:
            # Strip markdown code blocks if present
            clean = response.replace("```json", "").replace("```", "").strip()
            # Handle potential leading/trailing non-json text
            start = clean.find('[')
            end = clean.rfind(']') + 1
            if start >= 0 and end > start:
                clean = clean[start:end]
                return json.loads(clean)
            return []
        except json.JSONDecodeError:
            return []
