"""
Utility functions for prompt management.
"""
from typing import Any, Dict, List, Optional
from .constants import (
    CORE_PERSONA, 
    TONE_STYLE_GUIDELINES, 
    OPERATIONAL_PRINCIPLES, 
    MEMORY_INSTRUCTIONS
)

def format_prompt(template: str, **kwargs: Any) -> str:
    """
    Format a prompt template with the provided variables.
    """
    try:
        return template.format(**kwargs)
    except KeyError as e:
        raise ValueError(f"Missing key for prompt format: {e}")


class BasePromptBuilder:
    """
    Assembles modular prompts from reusable components.
    
    Ensures that Clavr's persona and critical rules are 
    consistently applied across all agents and domains.
    """
    
    @staticmethod
    def build_system_prompt(
        agent_role: str,
        capabilities: List[str],
        specific_rules: Optional[List[str]] = None,
        include_memory: bool = True
    ) -> str:
        """Assembles a full system prompt for an agent."""
        components = [
            CORE_PERSONA,
            f"\nAGENT ROLE:\n{agent_role}",
            "\nCAPABILITIES:\n- " + "\n- ".join(capabilities),
            TONE_STYLE_GUIDELINES,
            OPERATIONAL_PRINCIPLES
        ]
        
        if include_memory:
            components.append(MEMORY_INSTRUCTIONS)
            
        if specific_rules:
            components.append("\nSPECIFIC DOMAIN RULES:\n- " + "\n- ".join(specific_rules))
            
        return "\n".join(components)

    @staticmethod
    def build_conversational_prompt(
        instruction: str,
        context: Optional[str] = None,
        is_voice: bool = False
    ) -> str:
        """Assembles a conversational response prompt."""
        components = [
            f"You are Clavr. {instruction}",
            TONE_STYLE_GUIDELINES
        ]
        
        if context:
            components.append(f"\nCONTEXT:\n{context}")
            
        if is_voice:
            components.append("\nVOICE CONSTRAINTS:\n- NO MARKDOWN\n- NO EMOJIS\n- STRICT BREVITY")
            
        return "\n".join(components)

