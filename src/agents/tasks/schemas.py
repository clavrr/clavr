
"""
LLM Extraction Schemas for Task Agent
"""

CREATE_TASK_SCHEMA = {
    "title": "The main task description or title",
    "due_date": "Due date/time if specified (iso format or relative like 'tomorrow'), else null",
    "priority": "Priority level if specified (high, medium, low), else null",
    "project_name": "Project name if specified (especially for Asana), else null",
    "notes": "Additional notes/details for the task, else null"
}

COMPLETE_TASK_SCHEMA = {
    "task_title": "The exact title or keywords of the task to complete",
}
