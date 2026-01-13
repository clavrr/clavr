
"""
LLM Extraction Schemas for Drive Agent
"""

DRIVE_INTENT_SCHEMA = {
    "action": "One of: search, list, read, starred, extract_tasks. Default 'list' if unclear.",
    "search_term": "Specific keywords or filename to search for. If user says 'the report' and context mentions 'Apollo', infer 'Apollo Report'. Null for list/starred.",
    "file_id": "File ID if explicitly provided, else null",
    "days_ago": "Number of days for list/recent commands (e.g. 7 for 'this week'). Default 7."
}
