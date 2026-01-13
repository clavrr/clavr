"""
Agent and routing prompt templates
"""
from typing import Optional
from .utils import BasePromptBuilder

# --- AGENT SYSTEM PROMPTS (MASTER & SPECIALIZED) ---

def get_agent_system_prompt(user_first_name: Optional[str] = None) -> str:
    """Get the master orchestrator system prompt."""
    agent_role = "You are the master orchestrator, coordinating between multiple specialized agents."
    capabilities = [
        "Email: Search, analyze, compose, reply",
        "Calendar: View events, schedule meetings, resolve conflicts",
        "Tasks: Create, update, list, complete",
        "Drive: Search, read, and organize files",
        "Keep: Manage notes and lists",
        "Notion: Manage workspace pages and databases",
        "Maps: search places and get directions",
        "Weather: Check current weather and forecasts",
        "Finance: Track spending and analyze transactions",
        "Timezone: Convert times and check world clocks",
        "Research: Deep analysis and web searching",
        "Intelligence: Learn user preferences and patterns autonomously"
    ]
    
    prompt = BasePromptBuilder.build_system_prompt(
        agent_role=agent_role,
        capabilities=capabilities,
    )
    
    if user_first_name:
        prompt = f"USER NAME: {user_first_name}\n\n" + prompt
        
    return prompt

# --- NLP & ROUTING PROMPTS ---

_INTENT_CLASSIFICATION_ROLE = """You are a high-precision intent classification engine.
Analyze the user query and extract structured intent, entities, and steps for execution."""

_INTENT_CLASSIFICATION_RULES = [
    "Distinguish clearly between SINGLE-STEP and MULTI-STEP queries.",
    "Use 'multi_step' intent ONLY if there are DISTINCT actions on DIFFERENT objects.",
    "Search/List results from tools do NOT count as 'summarize' intent unless the user specifically asked for a summary.",
    "MEMORY AWARENESS: Use the [RELEVANT MEMORY CONTEXT] to resolve ambiguous entities like 'boss', 'partner', or 'the team'.",
    "Identify 'operation_type' as 'read' for info gathering and 'write' for state-changing actions."
]

INTENT_CLASSIFICATION_PROMPT = BasePromptBuilder.build_system_prompt(
    agent_role=_INTENT_CLASSIFICATION_ROLE,
    capabilities=[
        "Natural language intent parsing",
        "Memory-aware entity resolution",
        "Workflow decomposition"
    ],
    specific_rules=_INTENT_CLASSIFICATION_RULES
) + """

OUTPUT FORMAT (JSON ONLY):
{
    "intent": "list|search|send|reply|schedule|create_task|multi_step|analyze|summarize|mark_read|none",
    "confidence": 0.0-1.0,
    "is_multi_step": boolean,
    "entities": {
        "recipients": [], "subjects": [], "senders": [], 
        "date_range": null, "keywords": [], "location": null, "urgency": "low|med|high"
    },
    "steps": [], # Required if is_multi_step is true
    "limit": 10,
    "reasoning": "short explanation"
}

QUERY: "{query}"
RELEVANT MEMORY CONTEXT:
{context}
"""

PARAMETER_EXTRACTION_SYSTEM_PROMPT = BasePromptBuilder.build_system_prompt(
    agent_role="You are a precise parameter extraction engine.",
    capabilities=[
        "Extracting specific fields from natural language into JSON",
        "Resolving relative dates/times using current context",
        "Mapping named entities to structured parameters"
    ],
    specific_rules=[
        "Return ONLY valid JSON.",
        "Do not include markdown or explanations.",
        "If a field cannot be found, use null.",
        "Handle ambiguous dates (e.g., 'next Friday') relative to the Current Context."
    ]
) + """

CURRENT CONTEXT: Today is {current_time_str}.
SCHEMA:
{schema_str}

RELEVANT MEMORY CONTEXT:
{memory_context}
"""

ENTITY_EXTRACTION_PROMPT = BasePromptBuilder.build_system_prompt(
    agent_role="You are a structured entity extraction engine.",
    capabilities=[
        "Extracting names, emails, dates, times, topics, and locations.",
        "Assigning confidence scores to extracted entities."
    ],
    specific_rules=["Format as JSON only."]
) + """

QUERY: "{query}"
"""

CLARIFICATION_PROMPT = BasePromptBuilder.build_system_prompt(
    agent_role="You are a helpful assistant seeking clarification.",
    capabilities=["Identifying missing or ambiguous information in user queries."],
    specific_rules=["Generate a natural, friendly, non-interrogative question."]
) + """

QUERY: "{query}"
ISSUE: {issue}
"""

MULTI_INTENT_PROMPT = BasePromptBuilder.build_system_prompt(
    agent_role="You are a multi-intent detection system.",
    capabilities=["Analyzing complex queries for sequential or parallel actions."],
    specific_rules=["Identify priority and dependencies between intents.", "Format as JSON."]
) + """

QUERY: "{query}"
"""
