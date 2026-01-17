"""
Style Analyzer Service

Analyzes user's historical text (emails, documents) to determine their unique communication style.
This enables the agent to mirror the user's voice ("Day One Adaptation").
"""
import asyncio
import json
from typing import List, Dict, Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage

from ..utils.logger import setup_logger
from ..ai.llm_factory import LLMFactory
from api.dependencies import AppState
from src.ai.memory.semantic_memory import SemanticMemory

logger = setup_logger(__name__)

STYLE_ANALYSIS_PROMPT = """
You are an Expert Linguist and Profiler.
Your task is to analyze a sample of texts written by a User and construct a precise "Communication Style Profile".

The goal is to allow an AI to mimic this user's style seamlessly.

ANALYZE THE FOLLOWING DIMENSIONS:
1. FORMALITY (0-10): Is it strict formal (10) or text-speak casual (0)?
2. VERBOSITY (0-10): Do they write long paragraphs (10) or short bullets (0)?
3. TONE: Warm, Direct, Professional, Playful, Sarcastic, Urgent, etc.
4. FORMATTING: Use of bullets, bolding, emojis, capitalization.
5. VOCABULARY: Simple vs Complex, Technical jargon vs Plain English.
6. GREETINGS/SIGN-OFFS: "Hi X" vs "Dear X", "Best" vs "Cheers".

INPUT TEXT SAMPLES:
{text_samples}

OUTPUT FORMAT (JSON ONLY):
{{
  "formality_score": <int 0-10>,
  "verbosity_score": <int 0-10>,
  "tone_keywords": ["<adj>", "<adj>", ...],
  "formatting_preference": "<description>",
  "common_greetings": ["<ex>", ...],
  "common_signoffs": ["<ex>", ...],
  "style_guidelines": [
    "Use bullet points for lists > 3 items",
    "Never use emojis",
    "Start emails with 'Hey'",
    ... 3-5 specific rules ...
  ]
}}
"""

class StyleAnalyzer:
    """
    Analyzes user content to create a persistent User Style Profile.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.llm = None

    def _get_llm(self):
        if not self.llm:
            try:
                # Use a high-quality model for analysis (e.g. Gemini 1.5 Pro or Flash)
                self.llm = LLMFactory.get_llm_for_provider(self.config, temperature=0.1)
            except Exception as e:
                logger.error(f"[StyleAnalyzer] Failed to initialize LLM: {e}")
        return self.llm

    async def analyze_and_extract_style(
        self, 
        user_id: int, 
        texts: List[str],
        semantic_memory: Optional[SemanticMemory] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze a batch of user texts and save the profile to memory.
        
        Args:
            user_id: User ID
            texts: List of text samples (e.g. sent emails)
            semantic_memory: Optional memory instance to save findings directly
            
        Returns:
            The extracted style profile dict
        """
        if not texts:
            return None
            
        llm = self._get_llm()
        if not llm:
            return None

        # Truncate and join samples
        # Limit to first ~500 chars of each, max 20 samples to fit context
        samples = []
        for t in texts[:20]:
            clean = t.strip()
            if clean:
                samples.append(f"- {clean[:500]}")
        
        if not samples:
            return None
            
        combined_text = "\n".join(samples)

        try:
            messages = [
                SystemMessage(content="You are a Communication Style Analyzer."),
                HumanMessage(content=STYLE_ANALYSIS_PROMPT.format(text_samples=combined_text))
            ]
            
            # Execute LLM
            response = await asyncio.to_thread(llm.invoke, messages)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Clean JSON
            json_str = content.replace("```json", "").replace("```", "").strip()
            start = json_str.find("{")
            end = json_str.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = json_str[start:end]
            
            profile = json.loads(json_str)
            
            logger.info(f"[StyleAnalyzer] Extracted profile for user {user_id}: {profile.get('tone_keywords')}")
            
            # Save to Memory if provided
            if semantic_memory:
                await self._save_profile_to_memory(user_id, profile, semantic_memory)
                
            return profile

        except Exception as e:
            logger.error(f"[StyleAnalyzer] Analysis failed: {e}")
            return None

    async def _save_profile_to_memory(self, user_id: int, profile: Dict[str, Any], memory: SemanticMemory):
        """Save the profile components as discrete facts."""
        try:
            # 1. Save general summary
            tone_str = ", ".join(profile.get("tone_keywords", []))
            summary_fact = (
                f"User's communication style is {tone_str}. "
                f"Formality: {profile.get('formality_score')}/10. "
                f"Verbosity: {profile.get('verbosity_score')}/10."
            )
            await memory.learn_fact(user_id, summary_fact, "user_style", "style_analyzer")
            
            # 2. Save specific guidelines
            for rule in profile.get("style_guidelines", []):
                await memory.learn_fact(user_id, f"Style Rule: {rule}", "user_style", "style_analyzer")
                
            # 3. Save formatting prefs
            fmt = profile.get("formatting_preference")
            if fmt:
                await memory.learn_fact(user_id, f"Formatting Preference: {fmt}", "user_style", "style_analyzer")

        except Exception as e:
            logger.warning(f"[StyleAnalyzer] Failed to save facts: {e}")
