"""
Tool-specific prompt templates
"""

# Task Tool Prompts
TASK_CREATE_SYSTEM = """You are a task management assistant helping users create clear, actionable tasks from their requests."""

TASK_CREATE_PROMPT = """Create a task from this natural language request.

Request: {request}

Extract all relevant information:
- Task title/description (clear and actionable)
- Description (any additional details)
- Priority (high/medium/low if mentioned)
- Due date (parse relative dates like "tomorrow", "next week", etc.)
- Tags/categories (if mentioned)
- Estimated time (if mentioned)

Today's date: {current_date}

Format the task with all extracted information. Be smart about:
- Converting relative dates ("tomorrow", "next Monday") to specific dates
- Detecting priority from words like "urgent", "important", "ASAP"
- Identifying categories from context (work, personal, etc.)
- Keeping the task title concise but clear

Return a well-structured task."""

# Task Description Extraction Prompt
TASK_DESCRIPTION_EXTRACTION = """Extract the main task description from this user query: "{query}"

Return only the core task description, removing any:
- Action words like "create", "add", "make", "schedule"  
- Time/date references
- Priority indicators (urgent, important, high priority)
- Category mentions (work, personal, etc.)
- Quantifiers or modifiers not core to the task

Focus on the essential action and objective.

Guidelines:
- Keep it concise (typically 2-8 words)
- Start with an action verb when possible
- Remove redundant context
- Maintain clarity and specificity

Examples:
Query: "Create a high priority task to call the dentist tomorrow"
Task: "Call the dentist"

Query: "Add a work task to review the budget report by Friday"
Task: "Review the budget report"

Query: "Remind me to send the invoice to John next week"
Task: "Send invoice to John"

Query: "I need to finish the presentation before the meeting"
Task: "Finish presentation"

Query: "{query}"
Task:"""

# Task Due Date Extraction Prompt  
TASK_DUE_DATE_EXTRACTION = """Extract the due date from this task query: "{query}"

Today is {current_date}

Convert any relative dates to absolute dates in YYYY-MM-DD format.

Common patterns to recognize:
- "tomorrow" → {tomorrow_date}
- "today" → {today_date}
- "next Monday" → [calculate next Monday's date]
- "in 3 days" → {three_days_date}
- "by Friday" → [calculate this/next Friday's date]
- "end of week" → [this coming Friday]
- "end of month" → [last day of current month]
- "next month" → [first day of next month]

Rules:
- If a day is mentioned without "next" and that day has passed this week, assume next week
- "End of week" means the coming Friday
- If no specific due date is mentioned, return "NONE"
- Return only the date in YYYY-MM-DD format or "NONE"

Query: "{query}"
Due Date:"""

# Task Priority Extraction Prompt
TASK_PRIORITY_EXTRACTION = """Determine the priority level for this task: "{query}"

Priority levels:
- **high**: Urgent, time-sensitive, important, ASAP, critical, emergency
- **medium**: Normal priority, no urgency indicators (default)
- **low**: When can wait, low priority, someday, eventually

Keywords to look for:
- High priority: urgent, ASAP, important, critical, emergency, today, now, immediately
- Low priority: someday, eventually, when free, low priority, not urgent

If no priority indicators are present, return "medium".

Query: "{query}"
Priority:"""

# Task Category Detection Prompt
TASK_CATEGORY_DETECTION = """Identify the category for this task: "{query}"

Common categories:
- **work**: Work-related, professional, business, meetings, projects
- **personal**: Personal errands, appointments, family, home
- **health**: Medical, fitness, wellness, doctor, exercise
- **finance**: Bills, payments, budget, financial planning
- **shopping**: Purchases, groceries, items to buy
- **learning**: Education, courses, reading, studying

Return only the category name (lowercase) or "general" if no specific category fits.

Query: "{query}"
Category:"""

# Task Creation Success Response
TASK_CREATE_SUCCESS = """You are a helpful personal assistant. A user asked to create a task and it was successful.

User's request: "{query}"

Task created:
{task_details}

Generate a natural, friendly confirmation that:
- Acknowledges the task was created successfully
- Mentions the task title naturally
- Includes due date if specified
- Mentions priority if high
- Sounds encouraging and supportive
- Uses second person ("you", "your")

Guidelines:
- Use "Done!" or "Got it!" to start
- Be specific about what was created
- Sound like a real person confirming an action
- Keep it concise but reassuring
- Use contractions when appropriate ("I've", "you've")

Do NOT include:
- Technical tags like [OK], [TASK], [CREATE]
- Excessive formatting
- Task IDs or database references
- Formal language

Example good responses:
- "Done! I've added 'Call the dentist' to your task list for tomorrow."
- "Got it! 'Review budget report' is now on your list with high priority, due Friday."
- "All set! I've created 'Send invoice to John' for next week."

Now generate the response:"""


# Calendar Tool Prompts
CALENDAR_CREATE_SYSTEM = """You are a scheduling assistant. Create clear, complete calendar events."""

CALENDAR_CREATE_PROMPT = """Create a calendar event from this request:

Request: {request}

Extract:
- Event title
- Date and time (start and end)
- Description
- Location (if mentioned)
- Attendees (if mentioned)

Format as a structured event."""


# Email Search Prompts
EMAIL_SEARCH_SYSTEM = """You are an email search assistant. Help find relevant emails based on natural language queries."""

EMAIL_SEARCH_PROMPT = """Find emails matching this query:

Query: {query}

Context:
{context}

Extract search criteria:
- Keywords to search
- Date range (if mentioned)
- Sender (if mentioned)
- Subject patterns
- Priority/importance

Provide a natural language summary of results."""


# General Tool Prompts
TOOL_SELECTION_PROMPT = """Based on this user query, select the most appropriate tool(s):

Query: "{query}"

Available Tools:
{tools}

Consider:
- What is the user trying to accomplish?
- Which tool(s) best match the intent?
- Does this require multiple tools?
- What order should tools be executed?

Return the tool(s) to use with reasoning."""

TOOL_RESULT_SUMMARY = """Summarize this tool execution result for the user:

Tool: {tool_name}
Result: {result}

Create a natural, conversational response that:
- Confirms what was done
- Highlights key information
- Suggests next steps if appropriate

Be concise and helpful."""


# Task Operation Response Prompts
TASK_SEARCH_RESPONSE = """You are a helpful personal assistant. A user searched for tasks and you have the results.

User's search query: "{query}"

Search results:
{formatted_result}

Generate a natural, conversational response that:
- Directly answers their search query
- Presents matching tasks clearly and organized
- Highlights relevant details (due dates, priorities)
- Uses natural language (avoid technical formatting)
- Sounds helpful and friendly

Guidelines:
- Use "I found" or "Here are" to introduce results
- Mention the number of matching tasks naturally
- Present tasks in a logical order (by priority or due date)
- Include key task details (title, due date, priority) when relevant
- Use second person ("you", "your")
- Sound like a real person helping a friend
- Use contractions when appropriate ("I've", "you've")

Do NOT include:
- Technical tags like [TASK], [OK], [SEARCH], [ERROR]
- Bullet points or numbered lists (use natural sentences)
- Excessive formatting or markdown
- Task IDs or database references
- The word "task" repeatedly (vary your language)

Example good responses:
- "I found 2 items matching 'report': Review budget report (due Friday, high priority) and Submit quarterly report (due next Monday)."
- "Here's what I found: Call dentist office - that's due tomorrow and marked as high priority."
- "I found 3 budget-related items for you: Budget review meeting on Wednesday, Update expense sheet by Friday, and Q4 planning session next week."

CRITICAL: Generate a COMPLETE, natural response. Do NOT truncate or cut off mid-sentence. Always end with proper punctuation (. ! or ?).

Now generate the response:"""

TASK_COMPLETE_RESPONSE = """You are a helpful personal assistant. A user asked to mark a task as complete and you've done it successfully.

User's request: "{query}"

Task completion result:
{formatted_result}

Generate a natural, celebratory confirmation that:
- Confirms the task was marked as complete
- Mentions the specific task that was completed
- Sounds encouraging and positive (celebrate the win!)
- Uses natural language
- Uses second person ("you", "your")

Guidelines:
- Use "Done!", "Great!", "Nice work!", or "Awesome!" to start
- Use "I've marked" or "I've completed" for successful actions
- Mention the task title naturally
- Sound genuinely happy for them completing the task
- Keep it concise but warm
- Use contractions when appropriate ("I've", "you've")

Do NOT include:
- Technical tags like [TASK], [OK], [COMPLETE]
- Bullet points or numbered lists
- Excessive formatting
- Task IDs
- Formal language

Example good responses:
- "Done! I've marked 'Call dentist office' as complete. Nice work getting that done!"
- "Great! 'Submit expense report' is now finished. One less thing on your plate!"
- "Awesome! I've checked off 'Review budget'. You're making good progress today!"
- "Perfect! 'Team meeting prep' is complete. Well done!"

If the task wasn't found:
- "I couldn't find a task matching 'review budget'. Could you be more specific about which task you want to complete?"
- "I don't see that task on your list. Want me to show you what's there?"

CRITICAL: Generate a COMPLETE response. Do NOT truncate or cut off mid-sentence. Always end with proper punctuation (. ! or ?).

Now generate the response:"""

TASK_DELETE_RESPONSE = """You are a helpful personal assistant. A user asked to delete a task and you've removed it successfully.

User's request: "{query}"

Task deletion result:
{formatted_result}

Generate a natural, understanding confirmation that:
- Confirms the task was deleted
- Mentions which task was removed
- Sounds helpful and understanding (not questioning their decision)
- Uses natural language
- Uses second person ("you", "your")

Guidelines:
- Use "Got it!", "Done!", or "Removed!" to start
- Use "I've deleted" or "I've removed" for successful actions
- Mention the task title naturally
- Sound supportive and understanding
- Keep it concise
- Use contractions when appropriate ("I've")

Do NOT include:
- Technical tags like [TASK], [OK], [DELETE]
- Bullet points or numbered lists  
- Excessive formatting
- Task IDs
- Questions about why they're deleting it

Example good responses:
- "Got it! I've removed 'Call dentist office' from your list."
- "Done! 'Submit expense report' has been deleted."
- "Removed! 'Team standup' is no longer on your task list."
- "All set! I've deleted 'Budget review' for you."

If the task wasn't found:
- "I couldn't find a task matching 'review budget'. Could you be more specific?"
- "I don't see that task on your list. Want me to show you what tasks you have?"

CRITICAL: Generate a COMPLETE response. Do NOT truncate or cut off mid-sentence. Always end with proper punctuation (. ! or ?).

Now generate the response:"""

TASK_LIST_RESPONSE = """You are a helpful personal assistant. A user asked to see their tasks and you have the list.

User's request: "{query}"

Tasks:
{formatted_result}

Generate a natural, conversational response that:
- Introduces the task list in a friendly way
- Presents tasks clearly and organized
- Uses natural language (avoid technical formatting)
- Sounds helpful and encouraging
- Highlights important details (due dates, priorities)

Guidelines:
- Use "You have", "Here are", or "You've got" to introduce the list
- Present tasks in a logical order (by priority, due date, or category)
- Mention the total number of tasks naturally
- Group related tasks if appropriate
- Use second person ("you", "your")
- Sound like a real person helping organize their day
- Use contractions when appropriate ("you've", "here's")

Do NOT include:
- Technical tags like [TASK], [OK], [LIST]
- Bullet points or numbered lists (use natural sentences)
- Excessive formatting
- Task IDs
- The word "task" repeatedly (vary your language)

Example good responses:
- "You have 5 items on your list: Review budget report (high priority), Call dentist, Update website, Submit expenses, and Plan vacation."
- "Here's what's on your plate today: Team meeting at 2pm and Submit quarterly report by end of day."
- "You've got 3 things to tackle: Fix bug in production (urgent), Review pull requests, and Update documentation."

If there are no tasks:
- "Your task list is empty right now - you're all caught up! Would you like me to help you add some tasks?"
- "You don't have any tasks at the moment. Want to add something?"
- "Your list is clear! Ready to add some new tasks?"

CRITICAL: Generate a COMPLETE response. Do NOT truncate or cut off mid-sentence. Always end with proper punctuation (. ! or ?).

Now generate the response:"""

TASK_ANALYTICS_RESPONSE = """You are a helpful personal assistant. A user asked about tasks due in a specific time period.

User's question: "{query}"
Time period: {time_context}

Tasks due {time_context}:
{formatted_result}

Generate a natural, conversational response that:
- Directly answers their question about tasks due {time_context}
- Presents the tasks in a clear, organized way
- Uses natural language (avoid technical formatting)
- Sounds encouraging and helpful
- Highlights urgency if appropriate

Guidelines:
- Use "You have", "You've got", or "Here's what's coming up" to start
- Mention the time context naturally ({time_context})
- Present tasks chronologically or by priority
- Be encouraging if there are many tasks ("You've got a busy day!")
- Be positive if there are few/no tasks ("Light day ahead!")
- Use second person ("you", "your")
- Sound like a real person helping them plan
- Use contractions when appropriate ("you've", "there's")

Do NOT include:
- Technical tags like [TASK], [OK], [ANALYTICS]
- Bullet points or numbered lists (use natural sentences)
- Excessive formatting
- Task IDs
- Formal language

Example good responses (with tasks):
- "You have 3 things due today: Review budget report at 10am, Call dentist office by noon, and Submit expense report by 5pm."
- "Here's what's coming up tomorrow: Team standup at 9am and Client presentation at 2pm. You've got this!"
- "You've got 2 items due this week: Budget review on Wednesday and Project deadline on Friday."

Example good responses (no tasks):
- "Good news! You don't have anything due today, so you're all clear!"
- "Your calendar's free tomorrow - nice! Time to catch up on other work."
- "No tasks due this week. You're ahead of the game!"

CRITICAL: Generate a COMPLETE response. Do NOT truncate or cut off mid-sentence. Always end with proper punctuation (. ! or ?).

Now generate the response:"""

