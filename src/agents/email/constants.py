
"""
Constants for Email Agent
"""

# Intent related constants
# Note: INTENT_KEYWORDS is globally defined in src/agents/constants.py, so we don't redefine it here unless it's specific to the agent internal logic.
# These local lists are used for keyword routing within the agent.

COUNT_KEYWORDS = ["how many", "count", "number of", "total"]

ACTION_DESCRIPTIONS = {
    "archive": "archiving email",
    "delete": "deleting email",
    "mark_read": "marking email as read",
    "mark_unread": "marking email as unread",
    "mark_spam": "marking email as spam",
}
