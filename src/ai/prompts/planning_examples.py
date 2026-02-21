"""
Golden Planning Examples for Supervisor Few-Shot Learning.

These examples guide the Supervisor Agent on how to decompose complex, 
multi-step, and ambiguous queries into logical execution steps.
"""
from typing import List, TypedDict
import json
import random

class PlanningStep(TypedDict):
    step: int
    domain: str
    query: str

class PlanningExample(TypedDict):
    user_query: str
    plan: List[PlanningStep]
    reasoning: str

PLANNING_EXAMPLES: List[PlanningExample] = [
    {
        "user_query": "Check if I have any urgent emails from boss and if so, block out time this afternoon to handle them.",
        "plan": [
            {"step": 1, "domain": "email", "query": "Find emails from 'boss' that are urgent or high priority"},
            {"step": 2, "domain": "calendar", "query": "Check my availability for this afternoon"},
            {"step": 3, "domain": "calendar", "query": "Schedule a 1 hour focus block this afternoon to 'Handle Urgent Emails'"}
        ],
        "reasoning": "Standard dependency chain: Search -> Check -> Act."
    },
    {
        "user_query": "What's the weather like in Tokyo and what time is it there right now?",
        "plan": [
            {"step": 1, "domain": "weather", "query": "Current weather in Tokyo"},
            {"step": 2, "domain": "timezone", "query": "Current time in Tokyo"}
        ],
        "reasoning": "Parallel information retrieval. No dependency."
    },
    {
        "user_query": "Summarize the last 3 emails about the 'Project X' launch and create a task to review them.",
        "plan": [
            {"step": 1, "domain": "email", "query": "Find last 3 emails about 'Project X launch'"},
            {"step": 2, "domain": "tasks", "query": "Create a task 'Review Project X launch emails'"}
        ],
        "reasoning": "Retrieval followed by action. Summarization happens in the agent response or can be explicit if needed."
    },
    {
        "user_query": "How long does it take to drive to the airport and are there any flights in my calendar today?",
        "plan": [
            {"step": 1, "domain": "maps", "query": "Drive time to the airport"},
            {"step": 2, "domain": "calendar", "query": "Show flights or travel events for today"}
        ],
        "reasoning": "Two distinct domain queries combined."
    },
    {
        "user_query": "Prepare me for my meeting with Sarah.",
        "plan": [
            {"step": 1, "domain": "calendar", "query": "Find next meeting with Sarah"},
            {"step": 2, "domain": "email", "query": "Find recent emails to/from Sarah"},
            {"step": 3, "domain": "drive", "query": "Find documents related to Sarah"},
            {"step": 4, "domain": "notion", "query": "Find recent notes about Sarah"}
        ],
        "reasoning": "Vague 'prepare' intent requires gathering context from multiple sources (Calendar, Email, Drive, Notion)."
    },
    {
        "user_query": "Prepare me for my next meeting.",
        "plan": [
            {"step": 1, "domain": "calendar", "query": "Get details of my next meeting"},
            {"step": 2, "domain": "drive", "query": "Find documents related to the meeting found in the previous step"},
            {"step": 3, "domain": "email", "query": "Find emails related to the meeting found in the previous step"}
        ],
        "reasoning": "Identify the meeting first, then use that context to gather files and communications."
    },
    {
        "user_query": "If it's raining in Seattle tomorrow, remind me to pack an umbrella.",
        "plan": [
            {"step": 1, "domain": "weather", "query": "Forecast for Seattle tomorrow"},
            {"step": 2, "domain": "tasks", "query": "Create a reminder 'Pack umbrella' due tomorrow (conditional)"}
        ],
        "reasoning": "Conditional logic: Check first, then act."
    },
    {
        "user_query": "Find that file I was working on yesterday about the budget.",
        "plan": [
            {"step": 1, "domain": "drive", "query": "Find modified files from yesterday matching 'budget'"},
            {"step": 2, "domain": "notion", "query": "Find pages modified yesterday matching 'budget'"}
        ],
        "reasoning": "Ambiguous 'file' search across Drive and Notion."
    },
    # --- NEW DOMAIN EXAMPLES ---
    {
        "user_query": "How much did I spend on Uber last month and do I have enough in my budget?",
        "plan": [
            {"step": 1, "domain": "finance", "query": "Aggregate spending on Uber for last month"},
            {"step": 2, "domain": "notion", "query": "Find page 'Monthly Budget' or 'Financial Goals'"}
        ],
        "reasoning": "Finance query combined with knowledge retrieval."
    },
    {
        "user_query": "Research the latest advancements in solid state batteries and save the summary to my notes.",
        "plan": [
            {"step": 1, "domain": "research", "query": "Latest advancements in solid state batteries"},
            {"step": 2, "domain": "notes", "query": "Create a note 'Solid State Batteries Research' with content from step 1"}
        ],
        "reasoning": "Deep research followed by content creation in Notes (Keep)."
    },
    {
        "user_query": "Find a good Italian restaurant nearby, check if I have free time at 7pm, and book a table.",
        "plan": [
            {"step": 1, "domain": "maps", "query": "Italian restaurants nearby"},
            {"step": 2, "domain": "calendar", "query": "Check availability at 7pm today"},
            {"step": 3, "domain": "general", "query": "Book a table (Simulated)"} 
        ],
        "reasoning": "Maps -> Calendar -> Action. Booking might be general/unsupported but correctly planned."
    },
    # --- FOLLOW-UP REFERENCE RESOLUTION EXAMPLES ---
    # These teach the planner to resolve pronouns/references from conversation history
    {
        "user_query": "What does the email talk about",
        "_conversation_history": "USER: What new emails do I have? ASSISTANT: You have one new email: Google Developer forums Summary: A brief update on forum activity since January 23, 2026.",
        "plan": [
            {"step": 1, "domain": "email", "query": "Show full content of the email with subject 'Google Developer forums Summary'"}
        ],
        "reasoning": "Follow-up: 'the email' resolved to 'Google Developer forums Summary' from conversation history."
    },
    {
        "user_query": "Who's attending that meeting?",
        "_conversation_history": "USER: What's on my calendar today? ASSISTANT: You have 2 events: 1) Team Standup at 9:00 AM, 2) Product Review at 2:00 PM.",
        "plan": [
            {"step": 1, "domain": "calendar", "query": "Get attendee details for the 'Team Standup' meeting today"}
        ],
        "reasoning": "Follow-up: 'that meeting' resolved to the most recent/first meeting mentioned ('Team Standup'). If ambiguous, pick the most recently discussed one."
    },
    {
        "user_query": "Reply to it saying I'll be there",
        "_conversation_history": "USER: Show me emails from Sarah. ASSISTANT: Found 2 emails from Sarah: 1) 'Dinner plans Friday?' (today), 2) 'Q4 Report review' (yesterday).",
        "plan": [
            {"step": 1, "domain": "email", "query": "Reply to the email from Sarah with subject 'Dinner plans Friday?' saying 'I'll be there'"}
        ],
        "reasoning": "Follow-up: 'it' resolved to the most recent email from Sarah ('Dinner plans Friday?'). Reply intent detected."
    },
    # --- SCHEDULING WITH ATTENDEES ---
    # CRITICAL: Scheduling with a person's name is ALWAYS a single calendar step.
    # The calendar agent handles name-to-email resolution internally.
    {
        "user_query": "Schedule a meeting with Emmanuel tomorrow at 11am",
        "plan": [
            {"step": 1, "domain": "calendar", "query": "Schedule a meeting with Emmanuel tomorrow at 11am"}
        ],
        "reasoning": "SINGLE STEP. The calendar agent handles attendee name-to-email resolution internally. Do NOT decompose into email search + calendar."
    },
    {
        "user_query": "Set up a 1:1 with Sarah Chen next Tuesday at 3pm",
        "plan": [
            {"step": 1, "domain": "calendar", "query": "Schedule a 1:1 meeting with Sarah Chen next Tuesday at 3pm"}
        ],
        "reasoning": "Scheduling with a person's name is always a SINGLE calendar step. The calendar agent resolves the name to an email address internally."
    }
]

def get_planning_examples_str(count: int = 3) -> str:
    """
    Get a formatted string of random planning examples.
    Always includes at least one follow-up reference resolution example.
    """
    # Separate follow-up examples from standalone examples
    followup_examples = [ex for ex in PLANNING_EXAMPLES if "_conversation_history" in ex]
    standalone_examples = [ex for ex in PLANNING_EXAMPLES if "_conversation_history" not in ex]
    
    # Always include 1 follow-up example, fill rest with standalone
    selected_followup = random.sample(followup_examples, min(1, len(followup_examples)))
    remaining = max(0, count - len(selected_followup))
    selected_standalone = random.sample(standalone_examples, min(remaining, len(standalone_examples)))
    
    selected = selected_standalone + selected_followup
    random.shuffle(selected)
    
    output = []
    output.append("FEW-SHOT EXAMPLES:")
    for i, ex in enumerate(selected):
        output.append(f"Example {i+1}:")
        
        # Include conversation history for follow-up examples
        if "_conversation_history" in ex:
            output.append(f"(Conversation history: {ex['_conversation_history']})")
        
        output.append(f'User: "{ex["user_query"]}"')
        
        # Aligned with SUPERVISOR_PLANNING_SYSTEM_PROMPT format
        output.append("Result (JSON list ONLY):")
        
        plan_str = json.dumps(ex["plan"], indent=2)
        output.append(plan_str)
        output.append("")
        
    return "\n".join(output)
