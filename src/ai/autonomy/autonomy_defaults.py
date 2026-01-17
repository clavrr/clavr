"""
Autonomy Defaults

Sensible default autonomy levels for new users.
These can be overridden per-user in AutonomySettings.
"""
from enum import Enum
from typing import Dict


class ActionType(str, Enum):
    """Supported autonomous action types."""
    # Calendar actions
    CALENDAR_BLOCK = "calendar_block"     # Block focus time
    CALENDAR_EVENT = "calendar_event"     # Create events with attendees
    CALENDAR_RESCHEDULE = "calendar_reschedule"  # Reschedule existing events
    
    # Email actions
    EMAIL_DRAFT = "email_draft"           # Draft email (doesn't send)
    EMAIL_SEND = "email_send"             # Send email
    EMAIL_REPLY = "email_reply"           # Reply to email
    EMAIL_FORWARD = "email_forward"       # Forward email
    
    # Task actions
    TASK_CREATE = "task_create"           # Create task
    TASK_COMPLETE = "task_complete"       # Mark task complete
    
    # Integration actions
    LINEAR_ISSUE = "linear_issue"         # Create Linear issue
    SLACK_MESSAGE = "slack_message"       # Post Slack message
    SLACK_STATUS = "slack_status"         # Set Slack status (Deep Work Shield)
    NOTION_PAGE = "notion_page"           # Create Notion page
    
    # Document actions  
    DOCUMENT_SHARE = "document_share"     # Share document



class AutonomyLevel(str, Enum):
    """Autonomy levels for action execution."""
    HIGH = "high"      # Execute immediately, notify after
    MEDIUM = "medium"  # Execute immediately, notify before
    LOW = "low"        # Queue for user approval


# Default autonomy levels per action type
# Organized by risk level:
# - HIGH: Safe, read-only, or easily reversible
# - MEDIUM: Creates data, visible to user, reversible
# - LOW: Potentially harmful, irreversible, or external-facing

DEFAULT_AUTONOMY_LEVELS: Dict[str, str] = {
    # HIGH autonomy (safe, easily reversible)
    ActionType.CALENDAR_BLOCK.value: AutonomyLevel.HIGH.value,
    ActionType.EMAIL_DRAFT.value: AutonomyLevel.HIGH.value,
    ActionType.TASK_CREATE.value: AutonomyLevel.HIGH.value,
    
    # MEDIUM autonomy (creates data but user can see immediately)
    ActionType.CALENDAR_EVENT.value: AutonomyLevel.MEDIUM.value,
    ActionType.TASK_COMPLETE.value: AutonomyLevel.MEDIUM.value,
    ActionType.LINEAR_ISSUE.value: AutonomyLevel.MEDIUM.value,
    ActionType.NOTION_PAGE.value: AutonomyLevel.MEDIUM.value,
    ActionType.SLACK_STATUS.value: AutonomyLevel.MEDIUM.value,  # Deep Work Shield
    
    # LOW autonomy (potentially harmful or irreversible)
    ActionType.EMAIL_SEND.value: AutonomyLevel.LOW.value,
    ActionType.EMAIL_REPLY.value: AutonomyLevel.LOW.value,
    ActionType.EMAIL_FORWARD.value: AutonomyLevel.LOW.value,
    ActionType.SLACK_MESSAGE.value: AutonomyLevel.LOW.value,
    ActionType.DOCUMENT_SHARE.value: AutonomyLevel.LOW.value,
    ActionType.CALENDAR_RESCHEDULE.value: AutonomyLevel.LOW.value,
}


# Undo configuration
UNDO_WINDOW_MINUTES = 5  # Actions can be undone within this window

# Which action types support undo
UNDOABLE_ACTIONS = {
    ActionType.CALENDAR_BLOCK.value,
    ActionType.CALENDAR_EVENT.value,
    ActionType.TASK_CREATE.value,
    ActionType.LINEAR_ISSUE.value,
    ActionType.NOTION_PAGE.value,
    ActionType.EMAIL_DRAFT.value,
    ActionType.SLACK_STATUS.value,  # Can reset status
}

# Actions that CANNOT be undone
NON_UNDOABLE_ACTIONS = {
    ActionType.EMAIL_SEND.value,
    ActionType.EMAIL_REPLY.value,
    ActionType.EMAIL_FORWARD.value,
    ActionType.SLACK_MESSAGE.value,
    ActionType.DOCUMENT_SHARE.value,
}


def get_default_autonomy_level(action_type: str) -> str:
    """Get the default autonomy level for an action type."""
    return DEFAULT_AUTONOMY_LEVELS.get(action_type, AutonomyLevel.LOW.value)


def is_action_undoable(action_type: str) -> bool:
    """Check if an action type supports undo."""
    return action_type in UNDOABLE_ACTIONS


# Icon mapping for action types (used in notifications)
ACTION_TYPE_ICONS: Dict[str, str] = {
    ActionType.CALENDAR_BLOCK.value: "calendar",
    ActionType.CALENDAR_EVENT.value: "calendar",
    ActionType.CALENDAR_RESCHEDULE.value: "calendar",
    ActionType.EMAIL_DRAFT.value: "mail",
    ActionType.EMAIL_SEND.value: "send",
    ActionType.EMAIL_REPLY.value: "reply",
    ActionType.EMAIL_FORWARD.value: "forward",
    ActionType.TASK_CREATE.value: "check-square",
    ActionType.TASK_COMPLETE.value: "check-circle",
    ActionType.LINEAR_ISSUE.value: "git-pull-request",
    ActionType.SLACK_MESSAGE.value: "message-circle",
    ActionType.SLACK_STATUS.value: "shield",  # Deep Work Shield
    ActionType.NOTION_PAGE.value: "file-text",
    ActionType.DOCUMENT_SHARE.value: "share-2",
}
