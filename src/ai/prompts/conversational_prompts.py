"""
Conversational response prompt templates

These prompts generate natural, conversational responses to user queries
based on search results, operations, and system state. All prompts are
designed to sound like a helpful friend, not a robotic assistant.
"""

from .utils import BasePromptBuilder



# Orchestrator Conversational Response Prompt
def get_orchestrator_conversational_prompt(query: str, raw_results: str) -> str:
    """
    Get the conversational prompt for orchestrator response generation.
    """
    instruction = "Generate a natural response based on the tool results below."
    
    # Use builder for base guidelines
    base_prompt = BasePromptBuilder.build_conversational_prompt(
        instruction=instruction,
        context=f"User Query: {query}\nTool Results:\n{raw_results}"
    )
    
    # Add orchestrator-specific refinement rules
    specific_rules = """
ORCHESTRATOR RULES:
- PARAPHRASE naturally: "Going to the Gym" -> "hitting the gym".
- PRESERVE EXACT TITLES for creation actions (Created task: [TITLE]). Use verbatim WITHOUT quotes.
- REALTIME AWARENESS: Use 'Current Time' to calculate gaps or countdowns.
- COMPLETE RESPONSES: Never truncate; finish all sentences.
"""
    return base_prompt + specific_rules


def get_conversational_enhancement_prompt(query: str, response: str, current_time: str = None, user_name: str = None, is_voice: bool = False) -> str:
    """
    Get a compact prompt for enhancing robotic responses.
    """
    time_context = f"Current time: {current_time}" if current_time else ""
    name_hint = f"User: {user_name}" if user_name else ""
    
    instruction = f"Transform the robotic agent output into a natural, friendly response. {time_context} {name_hint}"
    
    grounding_rules = """
STRICT GROUNDING RULES:
1. Do NOT claim an action (create, send, update, delete) was successful unless the Agent Output explicitly confirms it (e.g., "Event created", "Email sent").
2. If the Agent Output just lists items or information, do NOT state that you have scheduled, sent, or changed anything.
3. If the Agent Output contains an error or "not found" message, reflect that accurately but politely.
4. NEVER hallucinate tool results that aren't in the Agent Output.
"""
    
    return BasePromptBuilder.build_conversational_prompt(
        instruction=instruction,
        context=f"Query: {query}\nAgent output:\n{response}\n\n{grounding_rules}",
        is_voice=is_voice
    )


