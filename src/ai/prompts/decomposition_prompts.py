"""
Query decomposition prompts
"""

QUERY_DECOMPOSITION_PROMPT = """Decompose this query into sequential execution steps: "{query}"

Return JSON list with objects containing: id, query, intent, action, dependencies

IMPORTANT ACTION MAPPING:
- For task queries like "what tasks do I have", "show my tasks", "list tasks", use action="list" NOT "search"
- For task creation queries like "add a task", "create a task", "please add a task about X", use action="create" NOT "search" or "list"
- For bulk operations like "mark all tasks as done", "complete all tasks", "clear all", use action="bulk_complete"
- Use "search" only when the user is searching for specific existing tasks by keyword or criteria

Example format:
[
  {{"id": "step_1", "query": "what tasks do I have", "intent": "task", "action": "list", "dependencies": []}},
  {{"id": "step_2", "query": "please add a task about calling mom", "intent": "task", "action": "create", "dependencies": []}},
  {{"id": "step_3", "query": "mark all my tasks as done", "intent": "task", "action": "bulk_complete", "dependencies": []}},
  {{"id": "step_4", "query": "find tasks about project X", "intent": "task", "action": "search", "dependencies": []}},
  {{"id": "step_5", "query": "schedule a meeting", "intent": "calendar", "action": "create", "dependencies": ["step_1"]}}
]"""

