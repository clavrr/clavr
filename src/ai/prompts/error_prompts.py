"""
Error handling and validation prompt templates

Prompts for error messages, validation, and edge case handling.
"""

# Error Message Prompts
ERROR_MESSAGE_PROMPT = """You are a helpful AI assistant. An error occurred while processing a user's query.

User's question: "{query}"
Error: {error_msg}

Generate a natural, friendly, and conversational error message. The response should:
- Be warm and apologetic
- Not sound robotic or technical
- Explain the issue in simple terms
- Suggest what the user can do
- Use second person ("you", "your")
- Sound like a real person

Do NOT include:
- Technical error details
- Technical tags like [ERROR], [OK]
- Excessive formatting
- The exact error message verbatim

Generate the COMPLETE response:"""


# No Results Prompts
NO_RESULTS_PROMPT = """You are a helpful AI assistant. A user asked about {query_type}, but no matching results were found.

User's question: "{query}"

Generate a natural, friendly, and conversational response explaining that no results were found. The response should:
- Be warm and personable (like talking to a friend)
- Not sound robotic or formal
- Be reassuring when appropriate
- Use second person ("you", "your")
- Sound like a real person answering a question
- Mention what was checked or filtered

Do NOT include:
- Technical tags like [EMAIL], [OK], [ERROR]
- Excessive formatting or structure
- Bullet points or numbered lists (use natural sentences instead)
- The phrase "No results found" verbatim (rephrase naturally)
- The prefix "[OK]" or any technical markers

CRITICAL: Generate a COMPLETE response. Do NOT truncate or cut off mid-sentence. Always end with proper punctuation (. ! or ?). Do NOT start with "[OK]" or any technical prefix.

Now generate the COMPLETE response for this user:"""


# Validation Prompts
VALIDATION_PROMPT = """You are validating a query classification.

Original query: "{query}"
Proposed action: {action}
Original classification: {classification}

Is this classification correct? Consider:
1. Does the action match what the user is asking for?
2. Are there any critical misclassifications (e.g., "show emails" classified as "send")?

Respond with ONLY valid JSON:
{{
    "is_correct": true/false,
    "corrected_action": "action_name" (only if is_correct is false),
    "reasoning": "brief explanation"
}}"""


# Multi-Step Detection Prompt
MULTI_STEP_DETECTION_PROMPT = """Analyze this query and determine if it requires MULTIPLE DISTINCT ACTIONS or if it's asking MULTIPLE QUESTIONS ABOUT THE SAME THING.

Query: "{query}"

CRITICAL DISTINCTION:
- MULTIPLE QUESTIONS ABOUT THE SAME THING = SINGLE-STEP (e.g., "Do I have email from X? What is it about?")
- MULTIPLE DISTINCT ACTIONS = MULTI-STEP (e.g., "Search emails AND send a reply")

Return ONLY a JSON object with:
{{
    "is_multi_step": true or false,
    "reasoning": "brief explanation"
}}

Examples:
- "Do I have any email from Amex? What is the email about?" → {{"is_multi_step": false, "reasoning": "Both questions about same email"}}
- "Search emails from John AND send him a reply" → {{"is_multi_step": true, "reasoning": "Two distinct actions: search and send"}}
- "When did X respond and what was it about?" → {{"is_multi_step": false, "reasoning": "Both questions about same email"}}
- "Find emails from X, then archive them" → {{"is_multi_step": true, "reasoning": "Two distinct actions: find and archive"}}

Return ONLY the JSON, no explanations."""


# Query Decomposition Prompt
QUERY_DECOMPOSITION_PROMPT = """Break this email query into sequential steps:

Query: "{query}"

{operations_context}

Decompose into individual steps, each with:
- Step number
- Intent (what action to take)
- Entities (what to act on)
- Dependencies (if this step depends on previous steps)

Format as JSON array of step objects."""


# Calendar Error Prompts
CALENDAR_UNAVAILABLE_PROMPT = """You are a helpful AI assistant. A user tried to use a calendar feature, but there was a technical issue with the calendar tool.

Generate a natural, friendly response letting them know there's a temporary issue. Be helpful and suggest they try again in a moment. Keep it concise and conversational."""

CALENDAR_TASK_MISROUTE_PROMPT = """You are a helpful AI assistant. A user asked about tasks, but their query was accidentally routed to the calendar system.

Query: {query}

Generate a natural, helpful response redirecting them to the task system and offering to help with their task query. Be friendly and seamless about the correction."""

