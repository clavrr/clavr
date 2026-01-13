
"""
LLM Extraction Schemas for Keep Agent
"""

CREATE_NOTE_SCHEMA = {
    "title": "Title of the note, else null",
    "body": "Body content of the note",
    "items": "List of items (for checklists), else null"
}

SEARCH_NOTE_SCHEMA = {
    "search_query": "What to search for in notes"
}

DELETE_NOTE_SCHEMA = {
    "note_identifier": "Title or ID of the note to delete"
}
