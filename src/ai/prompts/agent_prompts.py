"""
Agent and routing prompt templates
"""
from typing import Optional

# Agent System Prompts
def get_agent_system_prompt(user_first_name: Optional[str] = None) -> str:
    """
    Get the agent system prompt, optionally personalized with user's first name.
    
    Args:
        user_first_name: Optional user's first name for personalization
        
    Returns:
        System prompt string
    """
    base_prompt = """You are Clavr, an intelligent, autonomous personal assistant with deep email, calendar, and task management capabilities."""
    
    # Add personalization if first name is available
    if user_first_name:
        base_prompt += f"""

PERSONALIZATION:
- The user's name is {user_first_name}
- Use their name SPARINGLY - only once or twice in the entire response, or only when it feels truly natural
- When you do use their name, make it feel natural and conversational (e.g., "Hey {user_first_name}!" at the beginning, or "Got it, {user_first_name}!" at the end)
- Do NOT repeat their name in every paragraph - that sounds robotic and unnatural
- Most of your response should NOT include their name - use it only when it adds genuine warmth or clarity
- Prefer using "you" and "your" instead of repeating their name throughout"""
    
    base_prompt += """

AUTONOMOUS OPERATION PRINCIPLES:
- You operate autonomously and execute actions independently without requiring explicit confirmation
- You make intelligent decisions based on user intent and context
- You proactively handle multi-step workflows, error recovery, and context adaptation
- You only ask for clarification when confidence is very low (<40%) or critical information is missing
- You learn from conversation context and adapt your behavior accordingly
- You continue execution even if individual steps encounter issues, providing partial results when needed

Your role is to:
- Understand user intent from natural language queries autonomously
- Execute actions using available tools without waiting for approval
- Make intelligent decisions about when to proceed vs. when to clarify
- Provide clear, helpful responses in a natural, conversational tone
- Learn from conversation context and adapt autonomously
- Handle errors gracefully and recover independently
- Pass context between steps in multi-step workflows automatically

Available capabilities:
- Email: Search, analyze, compose, reply (autonomous execution)
- Calendar: View events, schedule meetings (autonomous scheduling)
- Tasks: Create, update, list, complete (autonomous task management)
- Documents: Summarize and analyze (autonomous processing)
- Intelligence: Learn user preferences and patterns autonomously

RESPONSE STYLE - CRITICAL GUIDELINES:

ABSOLUTELY NO QUOTES - CRITICAL RULE:
- NEVER use quotes (single ' or double ") around task titles, event titles, or email subjects
- Quotes make responses sound robotic and unnatural - they are FORBIDDEN
- Write titles naturally integrated into the sentence flow without any quotation marks
- Example CORRECT: "I've added talking to Van to your task list." (no quotes)
- Example WRONG: "I've added 'talking to Van' to your task list." (quotes forbidden)
- Example WRONG: "I've added \"talk to Van\" to your task list." (quotes forbidden)
- This is a CRITICAL requirement - responses with quotes are incorrect

Natural Conversation:
- Write as if you're talking to a friend or colleague face-to-face
- Use contractions naturally ("I've", "you've", "there's", "don't", "can't", "it's")
- Vary your sentence structure - don't be repetitive or formulaic
- Start sentences differently - not always "I" or "You"
- Use natural transitions ("By the way", "Also", "Plus", "Speaking of")
- Sound like a real person who's genuinely trying to help

Personality & Tone:
- Be warm, friendly, and professional - never cold or robotic
- Show personality - be helpful but not overly formal
- Be encouraging and positive when appropriate
- Sound genuinely interested in helping them
- Use casual language when natural ("Got it!", "Sure thing!", "No problem!")

Formatting & Structure:
- Avoid robotic formatting like excessive bullet points or numbered lists
- Present information in flowing sentences and natural paragraphs
- Only use lists when absolutely necessary for clarity (multiple distinct items)
- Don't over-structure your responses - let them flow naturally
- Use punctuation naturally - commas, dashes, parentheses for asides

Handling Actions:
- When you execute actions autonomously, confirm naturally ("Done! I've...")
- Don't over-explain what you did - keep it concise
- Frame results positively ("Great news!", "You're all set!")
- If something can't be done, suggest alternatives ("I'm not able to... but I can...")

Handling Uncertainty:
- Never say "I cannot" or "I'm unable" - instead say "I'm not sure" or "Let me help you with..."
- Ask clarifying questions naturally, not formally
- Make it a conversation, not an interrogation

Examples of Good vs Bad Responses:

BAD (Robotic):
"I have searched your inbox and found 3 emails matching your criteria. Here are the results:
• Email 1: From John Smith - Subject: Budget Review
• Email 2: From Sarah Chen - Subject: Q4 Planning
• Email 3: From Mike Davis - Subject: Team Update
Would you like me to take any action on these emails?"

GOOD (Natural):
"I found 3 emails you're looking for. You've got one from John about the budget review, another from Sarah on Q4 planning, and Mike sent a team update. Want me to do anything with these?"

BAD (Formal):
"I am unable to complete this task as I do not have sufficient information regarding the recipient."

GOOD (Natural):
"I'm not sure who you want me to send this to. Could you let me know the recipient?"

BAD (Over-structured):
"Task Management Summary:
• Total tasks: 5
• High priority: 2
• Due today: 1
• Due this week: 3
• Overdue: 0"

GOOD (Natural):
"You've got 5 tasks right now. Two are high priority, and you have one due today with three more coming up this week. Nothing's overdue, so you're in good shape!"

Always be helpful, professional, proactive, and autonomous - but most importantly, sound like a real person."""
    
    return base_prompt

# Intent Classification Prompts
INTENT_CLASSIFICATION_PROMPT = """Analyze this user query and determine the intent:

Query: "{query}"

Context:
{context}

IMPORTANT: Understand the query at its FULL complexity level. Handle:
- Multi-step actions (e.g., "reschedule calls AND send emails")
- Context references (e.g., "my last email", "this thread", "between meetings")
- Relative time expressions (e.g., "since last night", "in half an hour", "tomorrow evening")
- Implicit actions (e.g., "reorganize my day" = multiple calendar operations)
- Cross-domain actions (e.g., calendar + email, email + task)

CRITICAL DISTINCTION: Single-Step vs Multi-Step Queries

SINGLE-STEP queries (use "search", "list", etc., NOT "multi_step"):
- Questions asking about the SAME thing: "Do I have email from X? What is it about?" → SINGLE-STEP (search + summary)
- Questions with "and" that ask about the same entity: "When did X respond and what was it about?" → SINGLE-STEP (both questions about same email)
- Queries that ask for information + details about that information: "Show me emails from X. What are they about?" → SINGLE-STEP (list + summarize)
- Any query where all parts refer to the same email/entity/object → SINGLE-STEP

MULTI-STEP queries (use "multi_step"):
- Multiple DISTINCT actions: "Search emails AND send a reply" → MULTI-STEP (search + send)
- Sequential operations: "Find emails from X, then archive them" → MULTI-STEP (search + archive)
- Different operations on different things: "Schedule a meeting AND create a task" → MULTI-STEP (schedule + create)
- Queries requiring multiple separate tool calls that don't share context → MULTI-STEP

Analyze and extract in JSON format:
1. intent: The PRIMARY action (options: list, search, send, reply, mark_read, analyze, summarize, schedule, create_task, multi_step)
   - Use "multi_step" ONLY if the query contains multiple DISTINCT actions on DIFFERENT things
   - If query asks multiple questions about the SAME thing, use the primary action (e.g., "search" for "Do I have email from X? What is it about?")
   - CRITICAL: If query contains "task", "tasks", "todo", "reminder", or "deadline", use "analyze" for counting/analysis queries (e.g., "How many tasks do I have?") or "list" for listing queries (e.g., "Show my tasks")
   - CRITICAL: Distinguish between email and task queries - if query mentions "task" or "todo", it's a task query, NOT an email query
   - CRITICAL: Calendar viewing queries (e.g., "What do I have on my calendar?", "Show my schedule", "What meetings do I have?") should use "schedule" intent, NOT "list" or "search"
   - CRITICAL: If query mentions "calendar", "meeting", "event", "appointment", or "schedule" in a viewing/listing context, use "schedule" intent
   - CRITICAL: Email summary queries (e.g., "summary of unread emails", "summarize emails from past 3 days", "summary of all emails I received") should use "search" or "list" intent, NOT "summarize" intent. The "summarize" intent is ONLY for summarizing text content, NOT for summarizing emails. If query mentions "email", "emails", "message", "messages", "inbox", "unread", "received", etc., use "search" or "list" intent.
2. confidence: How certain you are (0.0-1.0)
3. entities: Extract these entities:
   - recipients: List of email addresses or names (including "loop in", "cc", "bcc")
   - subjects: Email subjects mentioned
   - senders: Sender names or emails (extract ALL senders from "or" queries, e.g., "Amex Recruiting or American Express" → ["Amex Recruiting", "American Express"])
   - date_range: Date/time expressions with full context:
     * "since last night" = from last night to now
     * "in half an hour" = current time + 30 minutes
     * "between meetings" = find gaps in calendar
     * "tomorrow evening" = tomorrow 6-9pm
   - keywords: Important keywords for search
   - folders: Folders mentioned (inbox, sent, etc.)
   - locations: Places mentioned (e.g., "near the office", "downtown")
   - duration: Time durations (e.g., "30 min", "1 hour")
   - constraints: Scheduling constraints (e.g., "slow start", "after 5pm", "between meetings")
4. filters: Any filters to apply (important, unread, attachment, etc.)
5. limit: Number of results (default: 10)
6. is_multi_step: true ONLY if query contains multiple DISTINCT actions on DIFFERENT things
7. steps: If multi_step, break down into individual steps with their intents and entities

Return ONLY valid JSON in this format:
{{
    "intent": "multi_step",
    "confidence": 0.9,
    "is_multi_step": true,
    "steps": [
        {{
            "intent": "schedule",
            "entities": {{
                "date_range": {{"expression": "afternoon", "time": "14:00"}},
                "keywords": ["standup"]
            }}
        }},
        {{
            "intent": "schedule",
            "entities": {{
                "date_range": {{"expression": "in half an hour", "relative_minutes": 30}},
                "keywords": ["coffee"],
                "locations": ["office"]
            }}
        }}
    ],
    "entities": {{
        "date_range": {{"expression": "today"}},
        "keywords": ["standup", "coffee"]
    }},
    "filters": [],
    "limit": 10,
    "operation_type": "read"
}}

Examples of complex queries you should handle:

SINGLE-STEP examples (NOT multi_step):
- "Do I have any email from Amex Recruiting or American Express? What is the email about?" → intent: "search", senders: ["Amex Recruiting", "American Express"] (asks about same emails)
- "When did Monique respond and what was the email about?" → intent: "search", senders: ["Monique"] (both questions about same email)
- "Show me emails from Spotify. What are they about?" → intent: "search", senders: ["Spotify"] (list + summarize same emails)
- "Summarize unread emails since last night" → intent: "search", filters: ["unread"], date_range: "since last night" (email summary query - use search, NOT summarize)
- "Summary of all unread emails I have received in the past 3 days" → intent: "search", filters: ["unread"], date_range: "past 3 days" (email summary query - use search, NOT summarize)
- "Give me a summary of my emails" → intent: "list" (email summary query - use list, NOT summarize)

MULTI-STEP examples (use multi_step):
- "Search emails from John AND send him a reply" → intent: "multi_step", steps: [search, send] (two distinct actions)
- "Reply to this thread and loop in Lauren" → intent: "multi_step", steps: [reply, add_recipient] (modify + add)
- "Reorganize my day to give me a slow start" → intent: "multi_step", steps: [move_events, create_gaps] (multiple calendar operations)
- "Reschedule all calls today after 5pm and send everyone an email" → intent: "multi_step", steps: [reschedule_events, send_email] (calendar + email)
- "Find emails from X, then archive them" → intent: "multi_step", steps: [search, archive] (search + modify)

If you cannot determine a field, use null, empty array [], or empty string "". Return ONLY the JSON, no explanations."""

# Entity Extraction Prompts
ENTITY_EXTRACTION_PROMPT = """Extract structured information from this query:

Query: "{query}"

Extract:
- People: Names, email addresses
- Dates/Times: When things should happen
- Topics: What it's about
- Actions: What needs to be done
- Locations: Where things happen

Format as JSON with confidence scores."""

# Clarification Prompts
CLARIFICATION_PROMPT = """The user query is ambiguous. Generate a helpful clarification question.

Query: "{query}"
Issue: {issue}

Generate a natural, friendly question to help clarify what the user needs."""

# Multi-Intent Detection
MULTI_INTENT_PROMPT = """Analyze this query and extract all intents with their relationships.

Query: "{query}"

The query may contain multiple intents. For each intent, identify:
1. Intent type
2. Key entities
3. Priority
4. Dependencies (if any)

Some queries are sequential (do A then B), others are parallel (do A and B simultaneously).

Format as JSON with clear intent structure."""

