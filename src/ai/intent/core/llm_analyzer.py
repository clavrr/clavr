"""
LLM-Based Intent Analyzer

Uses Large Language Models to robustly understand user intent, covering:
- Domain classification (Email, Calendar, Task, Notes, General)
- Entity extraction (Times, People, Priorities)
- Handling of natural language nuances (synonyms, broken English)
"""
import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage

from src.ai.llm_factory import LLMFactory
from src.utils.config import load_config
from src.utils.logger import setup_logger
from src.agents.constants import INTENT_ANALYZER_TEMPERATURE, MIN_QUERY_LENGTH

logger = setup_logger(__name__)

# System prompt for intent analysis
INTENT_ANALYSIS_PROMPT = """
You are the Intent Understanding Engine for Clavr, an intelligent AI assistant.
Your job is to analyze user queries and extract structured intent information.

Verify the user's intent falls into one of these domains:
1. EMAIL: Composing, sending, replying, searching, or managing emails.
2. CALENDAR: Scheduling, checking availability, listing events, or managing calendar.
3. TASK: Creating to-dos, listing tasks, marking complete, or managing projects.
4. NOTES: Taking notes, jotting down ideas, listing lists (groceries, etc), or searching notes.
5. GENERAL: General chat, questions, or clarification.

Analyze the query and return a JSON object with the following fields:
- domain: One of [email, calendar, task, notes, general]
- intent: Specific action (e.g., create, search, update, delete, complete, send, reply, query)
- entities:
    - time_references: List of time/date phrases (e.g., "tomorrow", "next week")
    - people: List of names or contacts
    - priorities: List of priority indicators (urgent, high, etc)
    - topic: Main subject or content summary
- confidence: Score 0.0-1.0
- reasoning: Brief explanation of classification

Input Query: {query}

Response must be valid JSON only.
"""

class LLMIntentAnalyzer:
    """
    Analyzes user queries using LLM to extract intent and entities.
    Replaces rigid regex matching with flexible semantic understanding.
    """
    
    def __init__(self):
        self.config = load_config()
        # Use low temperature for consistent JSON output
        self.llm = LLMFactory.get_llm_for_provider(self.config, temperature=INTENT_ANALYZER_TEMPERATURE)
        
    def analyze(self, query: str) -> Dict[str, Any]:
        """
        Analyze a query to determine domain, intent, and entities.
        
        Args:
            query: User input string
            
        Returns:
            Dict containing structured intent data
        """
        try:
            # Fast return for very short queries to save latency
            if len(query.strip()) < MIN_QUERY_LENGTH:
                return self._fallback_response("general")

            formatted_prompt = INTENT_ANALYSIS_PROMPT.format(query=query)
            
            messages = [
                SystemMessage(content=formatted_prompt),
                HumanMessage(content=query)
            ]
            
            response = self.llm.invoke(messages)
            content = response.content
            
            # Clean possible markdown formatting
            if "```json" in content:
                content = content.replace("```json", "").replace("```", "")
            elif "```" in content:
                content = content.replace("```", "")
                
            try:
                result = json.loads(content.strip())
                # Normalize domain output
                if 'domain' in result:
                    result['domain'] = result['domain'].lower()
                return result
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse LLM intent response: {content}")
                return self._fallback_response("general", query)
                
        except Exception as e:
            logger.error(f"LLM Intent Analysis failed: {e}", exc_info=True)
            return self._fallback_response("general", query)

    def _fallback_response(self, domain: str, query: str = "") -> Dict[str, Any]:
        """Return safe fallback response on error"""
        return {
            "domain": domain,
            "intent": "general",
            "entities": {
                "time_references": [],
                "people": [],
                "priorities": [],
                "topic": ""
            },
            "confidence": 0.5,
            "reasoning": "Fallback due to error or ambiguity"
        }


# ============================================================================
# Singleton Pattern - Reuse LLM analyzer instance
# ============================================================================

_llm_analyzer_instance: Optional[LLMIntentAnalyzer] = None


def get_llm_analyzer() -> LLMIntentAnalyzer:
    """
    Get singleton LLMIntentAnalyzer instance.
    
    Avoids repeated instantiation and LLM initialization overhead.
    """
    global _llm_analyzer_instance
    if _llm_analyzer_instance is None:
        _llm_analyzer_instance = LLMIntentAnalyzer()
    return _llm_analyzer_instance
