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
    name_hint = f"User's name: {user_name}" if user_name else ""
    
    instruction = f"Rewrite the agent output as a natural co-worker response. {time_context} {name_hint}"
    
    grounding_rules = """
STRICT RULES:
1. GROUNDING: Only confirm actions (created, sent, scheduled) if the Agent Output explicitly says so. Never hallucinate results.
2. If the output lists items or info, present them naturally — don't claim you did something you didn't.
3. If there's an error, reflect it honestly but conversationally.
4. For emails: rephrase covering ALL important details (names, dates, numbers, key points).
5. ANTI-REPETITION:
   - Do NOT start with {user_name or 'the user name'} as the first word.
   - Do NOT use the same opening phrase (e.g., "Here's what I found") that you've used before.
   - For action confirmations: lead with the confirmation, not a greeting. Example: "Done — Clavr Sprint Meeting is on the calendar for tomorrow at 11." NOT "Hey! Here's what I've done — I've scheduled..."
   - Vary your delivery. Sometimes be brief, sometimes add a useful observation.
6. CONCISENESS: Don't pad the response. If the answer is short, keep it short.
7. NATURAL FORMATTING: When listing tasks, reminders, or items, weave them into a natural sentence instead of bullet points. Use bullet points ONLY for 5+ items. For example, instead of "• Laundry • Dishes • Shopping", say "You've got laundry, dishes, and shopping to take care of."
"""
    
    return BasePromptBuilder.build_conversational_prompt(
        instruction=instruction,
        context=f"Query: {query}\nAgent output:\n{response}\n\n{grounding_rules}",
        is_voice=is_voice
    )


