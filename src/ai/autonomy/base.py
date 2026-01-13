"""
Autonomy Base Components

Provides foundational classes for all autonomy services, ensuring consistent
configuration, logging, and LLM interaction patterns.
"""
import asyncio
import logging
from typing import Optional, Callable, Dict, Any, List

from langchain_core.messages import SystemMessage, HumanMessage

from ...utils.logger import setup_logger
from ...utils.config import Config
from ..llm_factory import LLMFactory

class AutonomyComponent:
    """
    Base class for all autonomy components (Planner, Evaluator, Learner).
    Standardizes configuration and logging.
    """
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_logger(self.__class__.__module__)

class NarrativeGenerator(AutonomyComponent):
    """
    Base class for generating LLM-powered narratives (briefings, summaries).
    """

    async def _generate_narrative(
        self,
        system_prompt: str,
        user_context: str,
        temperature: float = 0.7,
        fallback_message: str = "Unable to generate narrative."
    ) -> str:
        """
        Generate generic text narrative using LLM.
        """
        try:
            llm = LLMFactory.get_llm_for_provider(self.config, temperature=temperature)
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_context)
            ]
            
            # Simple retry logic could go here
            result = await asyncio.to_thread(llm.invoke, messages)
            return result.content
            
        except Exception as e:
            self.logger.error(f"Narrative generation failed: {e}")
            return fallback_message
    
    def _format_list(self, items: List[Any], formatter: Callable[[Any], str], empty_message: str = "None.") -> str:
        """
        Helper to format a list of items into a string.
        """
        if not items:
            return empty_message
        return "\n".join([f"- {formatter(item)}" for item in items])

class StructuredGenerator(AutonomyComponent):
    """
    Base class for generating structured JSON outputs (Plans, Decisions).
    """
    
    async def _generate_structured(
        self,
        system_prompt: str,
        user_context: str,
        temperature: float = 0.2
    ) -> Dict[str, Any]:
        """
        Generate and parse JSON output.
        Uses native JSON mode for Google Gemini.
        """
        try:
            # We use a lower temperature for structured tasks
            llm = LLMFactory.get_llm_for_provider(self.config, temperature=temperature)
            
            # Force JSON output via generation_config (Native Gemini 1.5 feature)
            # This ensures the model outputs strictly valid JSON without markdown fences
            structured_llm = llm.bind(generation_config={"response_mime_type": "application/json"})
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_context)
            ]
            
            result = await asyncio.to_thread(structured_llm.invoke, messages)
            
            # Parse JSON directly
            import json
            content = result.content.strip()
            return json.loads(content)
            
        except Exception as e:
            self.logger.error(f"Structured generation failed: {e}")
            return {}
