
"""
LLM Extraction Schemas for Email Agent
"""

SEARCH_SCHEMA = {
    "sender": "Name or email of the sender (the person who sent the email). Extract from phrases like 'from X', 'sent by X', 'email from X'.",
    "subject_contains": "Keywords to search for in the subject line. Null if not specified.",
    "content_contains": "Keywords to search for in the email body. Null if not specified.",
    "is_unread": "Boolean. True if user wants only unread emails. False or null otherwise."
}

SEND_SCHEMA = {
    "recipient": "Email address or name of recipient",
    "subject": "Subject of the email",
    "body": "Body content of the email"
}

MANAGEMENT_SCHEMA = {
    "email_identifier": "Keywords to find the email (sender name, subject, or content). Required.",
    "label_name": "Label to apply (if labeling). Null if not a label action."
}

REPLY_SCHEMA = {
    "target_person": "Name or email of the person to reply to / or whose email to follow up on.",
    "topic_filter": "Keywords to identify the specific email thread (e.g. 'project x', 'meeting').",
    "intent_instruction": "Instructions for the reply body (e.g. 'ask for status', 'say yes').",
    "is_follow_up": "Boolean. True if user says 'follow up', implying finding a previous thread."
}
