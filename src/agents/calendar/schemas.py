
"""
LLM Extraction Schemas for Calendar Agent
"""

SCHEDULE_SCHEMA = {
    "summary": "Title or summary of the event. Do NOT include attendee names here — extract them into attendees instead. E.g. 'Schedule meeting with John' → summary='Meeting', attendees=['John']",
    "start_time": "Start time in ISO format or relative (e.g. 'tomorrow at 3pm')",
    "end_time": "End time or duration (e.g. '1 hour'), else null",
    "attendees": "List of attendee names or email addresses. Extract ANY person mentioned with 'with [name]' here. Names will be resolved to emails automatically. E.g. 'meeting with Emmanuel and Sarah' → ['Emmanuel', 'Sarah']",
    "location": "Location of the event, else null",
    "description": "Description of the event, else null",
    "timezone_reference": "If user mentions a specific timezone or city for time (e.g. '9am London time', '3pm Tokyo'), extract it here. null otherwise.",
    "check_conflicts": "Boolean. True if user implies checking availability or preventing overlaps. Default True unless user says 'double book' or 'force'."
}

LIST_SCHEMA = {
    "start_time": "Start date/time (ISO format). For 'yesterday', use YESTERDAY's date at 00:00:00. For 'today'/'now', use TODAY at 00:00:00. For 'tomorrow', use tomorrow at 00:00:00. For 'last week', use 7 days ago.",
    "end_time": "End date/time (ISO format). For 'yesterday', use yesterday at 23:59:59. If 'next month', use last day of next month.",
    "days_ahead": "Number of days to list. Use 1 for a specific day. Use NEGATIVE values for past dates: -1 for yesterday, -7 for last week. Default 1 for today, 7 for 'week', 30 for 'month'.",
    "looking_at_past": "Boolean. True if user asks about past events (yesterday, last week, what did I do). False if asking about future or today."
}

UPDATE_SCHEMA = {
    "search_criteria": "The phrase used to identify the CURRENT event (e.g. 'meeting with Dan', '10am meeting').",
    "new_start_time": "The NEW start time desired (ISO format or relative). Null if not changing.",
    "new_title": "The NEW title desired. Null if not changing."
}

AVAILABILITY_SCHEMA = {
    "start_time": "Time to check availability for (ISO format). Default 'now'.",
    "duration_minutes": "Duration to check for (defaults to 30 mins if not specified).",
    "action": "One of: 'check_specific' (Am I free at X?), 'find_gap' (When am I free?)"
}
