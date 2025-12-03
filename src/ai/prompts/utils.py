"""
Prompt Utilities - Helper functions for prompt formatting and validation

Provides consistent prompt formatting, validation, and template management.
"""
from typing import Dict, Any, Optional, List
import re

from ...utils.logger import setup_logger

logger = setup_logger(__name__)


def format_prompt(template: str, **kwargs) -> str:
    """
    Format a prompt template with validation.
    
    Args:
        template: Prompt template string with {placeholders}
        **kwargs: Values to fill in placeholders
        
    Returns:
        Formatted prompt string
        
    Raises:
        ValueError: If required placeholders are missing
    """
    # Extract all placeholders from template
    placeholders = set(re.findall(r'\{(\w+)\}', template))
    
    # Check for missing required placeholders
    missing = placeholders - set(kwargs.keys())
    if missing:
        logger.warning(f"Missing placeholders in prompt: {missing}. Using empty strings.")
        # Fill missing placeholders with empty strings
        for placeholder in missing:
            kwargs[placeholder] = ""
    
    # Check for extra kwargs (not necessarily an error, but worth logging)
    extra = set(kwargs.keys()) - placeholders
    if extra:
        logger.debug(f"Extra kwargs provided (not used in template): {extra}")
    
    try:
        return template.format(**kwargs)
    except KeyError as e:
        logger.error(f"Error formatting prompt: {e}")
        raise ValueError(f"Missing required placeholder: {e}")


def build_system_user_prompt(system_prompt: str, user_prompt: str) -> List[Dict[str, str]]:
    """
    Build a standard system/user message pair for LLM calls.
    
    Args:
        system_prompt: System prompt
        user_prompt: User prompt
        
    Returns:
        List of message dictionaries in LangChain format
    """
    from langchain_core.messages import SystemMessage, HumanMessage
    
    return [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]


def validate_template_variables(template: str, provided_vars: Dict[str, Any]) -> Dict[str, bool]:
    """
    Validate that all template variables are provided.
    
    Args:
        template: Prompt template
        provided_vars: Variables provided
        
    Returns:
        Dictionary mapping variable names to whether they're provided
    """
    placeholders = set(re.findall(r'\{(\w+)\}', template))
    return {var: var in provided_vars for var in placeholders}


def extract_template_variables(template: str) -> List[str]:
    """
    Extract all variable names from a template.
    
    Args:
        template: Prompt template string
        
    Returns:
        List of variable names found in template
    """
    return list(set(re.findall(r'\{(\w+)\}', template)))

