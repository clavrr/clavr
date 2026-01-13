"""
Fact Extractor (Observer)

Automatically analyzes conversation turns to extract persistent facts and preferences.
Runs in the background to populate Semantic Memory.
"""
import json
import asyncio
from typing import List, Dict, Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage

from ...utils.logger import setup_logger
from .semantic_memory import SemanticMemory
from ..llm_factory import LLMFactory
from api.dependencies import AppState

logger = setup_logger(__name__)

ExtractionSchema = {
    "facts": [
        {
            "content": "User lives in New York",
            "category": "personal_detail",
            "confidence": 0.9
        },
        {
            "content": "User prefers concise emails",
            "category": "preference",
            "confidence": 0.95
        }
    ]
}

SYSTEM_PROMPT = """
You are an intelligent Observer monitoring a conversation between a User and an AI Assistant.
Your goal is to extract new, persistent FACTS or PREFERENCES about the User.

Ignore:
- Temporary context (e.g. "I'm hungry now", "Schedule a meeting for tomorrow")
- Questions asked by the user
- General chit-chat

Extract:
- Explicit favorites/dislikes (e.g. "I hate early meetings", "I accept invites from X")
- personal details (e.g. "My wife's name is Sarah", "I live in Seattle")
- Work context (e.g. "I use Asana for tasks", "My boss is John")

Return a JSON object with a list of 'facts'. If nothing worth learning is found, return {"facts": []}.
"""

class FactExtractor:
    """
    Observer that uses LLM to extract facts from conversation.
    """
    
    def __init__(self):
        self.llm = None
        
    def _get_llm(self):
        if not self.llm:
            try:
                config = AppState.get_config()
                # Use a cheaper/faster model if available, or standard one
                self.llm = LLMFactory.get_llm_for_provider(config, temperature=0.0)
            except Exception as e:
                logger.error(f"Failed to initialize LLM for FactExtractor: {e}")
        return self.llm

    async def extract_and_learn(self, 
                                messages: List[Dict[str, Any]], 
                                user_id: int, 
                                semantic_memory: SemanticMemory):
        """
        Analyze recent messages and learn new facts.
        
        Args:
            messages: List of recent message dicts
            user_id: User ID
            semantic_memory: Semantic Memory instance to save to
        """
        llm = self._get_llm()
        if not llm:
            return

        # Format conversation for LLM
        # We only look at the last few turns to save tokens
        text_lines = []
        for msg in messages[-4:]: # Analyze last 2 rounds
            role = msg.get('role', 'unknown').upper()
            content = msg.get('content', '')
            text_lines.append(f"{role}: {content}")
            
        convo_text = "\n".join(text_lines)
        
        try:
            # Prepare Prompt
            prompt_msgs = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=f"Analyze this conversation:\n\n{convo_text}")
            ]
            
            # Call LLM
            # Run in thread to avoid blocking if LLM client is sync
            result = await asyncio.to_thread(llm.invoke, prompt_msgs)
            response_text = result.content if hasattr(result, 'content') else str(result)
            
            # Extract JSON
            # Simple cleanup for markdown code blocks
            clean_text = response_text.replace("```json", "").replace("```", "").strip()
            if not clean_text.startswith("{"):
                # Try simple regex if chatty
                import re
                match = re.search(r'\{.*\}', clean_text, re.DOTALL)
                if match:
                    clean_text = match.group(0)
                else:
                    # If still not JSON, maybe it's just raw text or malformed
                    logger.warning(f"Failed to find JSON object in LLM response: {clean_text[:100]}...")
                    return

            try:
                data = json.loads(clean_text)
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode failed for fact extraction: {e}")
                return

            facts = data.get("facts", [])
            
            if not facts:
                return

            # Save facts to memory
            for fact in facts:
                if isinstance(fact, dict):
                    content = fact.get("content")
                    category = fact.get("category", "general")
                elif isinstance(fact, str):
                    content = fact
                    category = "general"
                else:
                    continue

                # Deduplicate check is done inside learn_fact
                if content:
                    await semantic_memory.learn_fact(
                        user_id=user_id, 
                        content=content, 
                        category=category, 
                        source="observer"
                    )
                    
        except Exception as e:
            logger.warning(f"Fact extraction failed: {e}")
            # Non-critical, just log and continue
