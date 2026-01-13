"""
Prompt templates for AI operations

Centralized prompt management with consistent formatting and validation.
"""

from .agent_prompts import (
    get_agent_system_prompt,
    INTENT_CLASSIFICATION_PROMPT,
    ENTITY_EXTRACTION_PROMPT,
    CLARIFICATION_PROMPT,
    MULTI_INTENT_PROMPT,
    PARAMETER_EXTRACTION_SYSTEM_PROMPT
)

from .supervisor_prompts import (
    SUPERVISOR_PLANNING_SYSTEM_PROMPT,
    SUPERVISOR_ROUTING_SYSTEM_PROMPT,
    SUPERVISOR_GENERAL_SYSTEM_PROMPT
)

from .conversational_prompts import (
    get_orchestrator_conversational_prompt,
    get_conversational_enhancement_prompt
)

from .voice_prompts import (
    VOICE_SYSTEM_INSTRUCTION,
    get_voice_conversational_prompt
)

from .financial_prompts import (
    FINANCIAL_ANALYSIS_SYSTEM_PROMPT
)

from .autonomy_prompts import (
    AUTONOMOUS_GOAL_SELECTION_SYSTEM_PROMPT,
    AUTONOMOUS_PLANNING_SYSTEM_PROMPT,
    AUTONOMOUS_REFLECTION_SYSTEM_PROMPT,
    AUTONOMOUS_LOOP_SYSTEM_PROMPT,
    MORNING_BRIEFING_SYSTEM_PROMPT,
    MEETING_BRIEFING_SYSTEM_PROMPT
)

__all__ = [
    # Agent System Prompts
    "get_agent_system_prompt",
    "PARAMETER_EXTRACTION_SYSTEM_PROMPT",
    
    # NLP & Intent Prompts
    "INTENT_CLASSIFICATION_PROMPT",
    "ENTITY_EXTRACTION_PROMPT",
    "CLARIFICATION_PROMPT",
    "MULTI_INTENT_PROMPT",
    
    # Supervisor Prompts
    "SUPERVISOR_PLANNING_SYSTEM_PROMPT",
    "SUPERVISOR_ROUTING_SYSTEM_PROMPT",
    "SUPERVISOR_GENERAL_SYSTEM_PROMPT",
    
    # Conversational & Response Prompts
    get_orchestrator_conversational_prompt,
    get_conversational_enhancement_prompt,
    
    # Voice Prompts
    "VOICE_SYSTEM_INSTRUCTION",
    "get_voice_conversational_prompt",
    
    # Financial Analysis Prompts
    "FINANCIAL_ANALYSIS_SYSTEM_PROMPT",

    # Autonomy Prompts
    "AUTONOMOUS_GOAL_SELECTION_SYSTEM_PROMPT",
    "AUTONOMOUS_PLANNING_SYSTEM_PROMPT",
    "AUTONOMOUS_REFLECTION_SYSTEM_PROMPT",
    "AUTONOMOUS_LOOP_SYSTEM_PROMPT"
]
