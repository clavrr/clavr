"""
Evaluation Test Datasets

Comprehensive test cases for evaluating agent capabilities.
"""
from typing import List
from .base import TestCase


# Intent Classification Test Cases
INTENT_TEST_CASES: List[TestCase] = [
    # Email intents
    TestCase(
        query="What new emails do I have?",
        expected_intent="email_operation",
        expected_tool="email"
    ),
    TestCase(
        query="Search for emails from John",
        expected_intent="email_operation",
        expected_tool="email",
        expected_entities={"senders": ["John"]}
    ),
    TestCase(
        query="Send an email to Sarah about the meeting",
        expected_intent="email_operation",
        expected_tool="email",
        expected_entities={"recipients": ["Sarah"], "keywords": ["meeting"]}
    ),
    TestCase(
        query="Who have I been emailing the most?",
        expected_intent="email_management",
        expected_tool="email"
    ),
    
    # Calendar intents
    TestCase(
        query="What's on my calendar today?",
        expected_intent="calendar_query",
        expected_tool="calendar",
        expected_entities={"date_range": "today"}
    ),
    TestCase(
        query="Schedule a meeting with Nick tomorrow at 10pm",
        expected_intent="calendar_management",
        expected_tool="calendar",
        expected_entities={"attendees": ["Nick"], "date_range": "tomorrow", "time": "10pm"}
    ),
    TestCase(
        query="What do I have next week Monday?",
        expected_intent="calendar_query",
        expected_tool="calendar",
        expected_entities={"date_range": "next week Monday"}
    ),
    
    # Task intents
    TestCase(
        query="What tasks do I have?",
        expected_intent="task_listing",
        expected_tool="tasks"
    ),
    TestCase(
        query="Create a task to review the proposal",
        expected_intent="task_creation",
        expected_tool="tasks",
        expected_entities={"keywords": ["review", "proposal"]}
    ),
    TestCase(
        query="How many tasks do I have?",
        expected_intent="task_analysis",
        expected_tool="tasks"
    ),
    
    # Multi-step intents
    TestCase(
        query="Find emails from John and send him a reply",
        expected_intent="multi_step",
        expected_tool=None  # Multi-step uses multiple tools
    ),
]


# Entity Extraction Test Cases
ENTITY_TEST_CASES: List[TestCase] = [
    TestCase(
        query="Schedule a meeting with Anthony tomorrow at 3pm",
        expected_entities={
            "attendees": ["Anthony"],
            "date_range": "tomorrow",
            "time": "3pm"
        }
    ),
    TestCase(
        query="Send email to john@example.com and sarah@example.com about the project",
        expected_entities={
            "recipients": ["john@example.com", "sarah@example.com"],
            "keywords": ["project"]
        }
    ),
    TestCase(
        query="Create a task to review the budget proposal by Friday",
        expected_entities={
            "keywords": ["review", "budget", "proposal"],
            "date_range": "Friday"
        }
    ),
    TestCase(
        query="What emails do I have from Amex Recruiting or American Express?",
        expected_entities={
            "senders": ["Amex Recruiting", "American Express"]
        }
    ),
]


# Tool Selection Test Cases
TOOL_SELECTION_TEST_CASES: List[TestCase] = [
    TestCase(
        query="What new emails do I have?",
        expected_tool="email"
    ),
    TestCase(
        query="Show my calendar for today",
        expected_tool="calendar"
    ),
    TestCase(
        query="List my tasks",
        expected_tool="tasks"
    ),
    TestCase(
        query="Schedule a meeting tomorrow",
        expected_tool="calendar"
    ),
    TestCase(
        query="Create a task to follow up",
        expected_tool="tasks"
    ),
]


# Response Quality Test Cases
RESPONSE_QUALITY_TEST_CASES: List[TestCase] = [
    TestCase(
        query="What's on my calendar today?",
        expected_response_contains=["calendar", "today"],
        expected_response_excludes=["error", "failed", "unable"]
    ),
    TestCase(
        query="What tasks do I have?",
        expected_response_contains=["task"],
        expected_response_excludes=["error"]
    ),
]


# Preset Functionality Test Cases
PRESET_TEST_CASES: List[TestCase] = [
    TestCase(
        query="Create a meeting preset called 'standup' with duration 30 minutes",
        expected_response_contains=["preset", "standup", "created"],
        metadata={"preset_type": "calendar", "preset_name": "standup"}
    ),
    TestCase(
        query="List my meeting presets",
        expected_response_contains=["preset"],
        expected_response_excludes=["error"]
    ),
    TestCase(
        query="Use the standup preset to schedule a meeting tomorrow",
        expected_response_contains=["standup", "preset"],
        metadata={"preset_name": "standup"}
    ),
]


# Contact Resolution Test Cases
CONTACT_RESOLUTION_TEST_CASES: List[TestCase] = [
    TestCase(
        query="Schedule a meeting with Anthony tomorrow",
        expected_entities={"attendees": ["Anthony"]},
        metadata={"expected_email": "manikoanthony@gmail.com"}
    ),
    TestCase(
        query="Send email to Nick",
        expected_entities={"recipients": ["Nick"]},
        metadata={"expected_email": "twumn@whitman.edu"}
    ),
]


# Conversation Memory Test Cases
MEMORY_TEST_CASES: List[TestCase] = [
    TestCase(
        query="What did I ask you about earlier?",
        context={"previous_query": "What's on my calendar today?"},
        expected_response_contains=["calendar"]
    ),
]


# End-to-End Test Cases
E2E_TEST_CASES: List[TestCase] = [
    TestCase(
        query="Schedule a meeting with Nick tomorrow at 10pm",
        expected_intent="calendar_management",
        expected_tool="calendar",
        expected_entities={"attendees": ["Nick"], "date_range": "tomorrow", "time": "10pm"},
        expected_response_contains=["created", "meeting", "Nick"],
        expected_response_excludes=["error", "failed"]
    ),
    TestCase(
        query="Create a task to review the proposal",
        expected_intent="task_creation",
        expected_tool="tasks",
        expected_entities={"keywords": ["review", "proposal"]},
        expected_response_contains=["created", "task"],
        expected_response_excludes=["error"]
    ),
    TestCase(
        query="What new emails do I have?",
        expected_intent="email_operation",
        expected_tool="email",
        expected_response_contains=["email"],
        expected_response_excludes=["error"]
    ),
]


# Multi-Step Query Test Cases
MULTISTEP_TEST_CASES: List[TestCase] = [
    # Simple 2-step queries (same domain)
    TestCase(
        query="Find emails from John and send him a reply",
        expected_intent="multi_step",
        expected_step_count=2,
        expected_domains=["email"],
        expected_response_contains=["email", "John"],
        expected_response_excludes=["error", "failed"],
        metadata={
            "expected_steps": [
                {"tool": "email", "action": "search", "entities": {"senders": ["John"]}},
                {"tool": "email", "action": "send", "entities": {"recipients": ["John"]}}
            ]
        }
    ),
    TestCase(
        query="Search for emails from Sarah, then archive them",
        expected_intent="multi_step",
        expected_step_count=2,
        expected_domains=["email"],
        expected_response_contains=["email", "Sarah"],
        expected_response_excludes=["error"],
        metadata={
            "expected_steps": [
                {"tool": "email", "action": "search", "entities": {"senders": ["Sarah"]}},
                {"tool": "email", "action": "archive"}
            ]
        }
    ),
    
    # Cross-domain 2-step queries
    TestCase(
        query="Find budget emails from last week and schedule a review meeting with the team",
        expected_intent="multi_step",
        expected_step_count=2,
        expected_domains=["email", "calendar"],
        expected_response_contains=["email", "meeting"],
        expected_response_excludes=["error"],
        metadata={
            "expected_steps": [
                {"tool": "email", "action": "search", "entities": {"keywords": ["budget"], "date_range": "last week"}},
                {"tool": "calendar", "action": "schedule", "entities": {"keywords": ["review", "meeting"]}}
            ]
        }
    ),
    TestCase(
        query="Check my calendar for tomorrow and create tasks for any prep work needed",
        expected_intent="multi_step",
        expected_step_count=2,
        expected_domains=["calendar", "tasks"],
        expected_response_contains=["calendar", "task"],
        expected_response_excludes=["error"],
        metadata={
            "expected_steps": [
                {"tool": "calendar", "action": "list", "entities": {"date_range": "tomorrow"}},
                {"tool": "tasks", "action": "create"}
            ]
        }
    ),
    TestCase(
        query="Send a summary of today's meetings to my manager and create a follow-up task",
        expected_intent="multi_step",
        expected_step_count=3,
        expected_domains=["calendar", "email", "tasks"],
        expected_response_contains=["meeting", "email", "task"],
        expected_response_excludes=["error"],
        metadata={
            "expected_steps": [
                {"tool": "calendar", "action": "list", "entities": {"date_range": "today"}},
                {"tool": "email", "action": "send"},
                {"tool": "tasks", "action": "create"}
            ]
        }
    ),
    
    # 3+ step queries
    TestCase(
        query="Find emails from John, send him a reply, and create a task to follow up next week",
        expected_intent="multi_step",
        expected_step_count=3,
        expected_domains=["email", "tasks"],
        expected_response_contains=["email", "John", "task"],
        expected_response_excludes=["error"],
        metadata={
            "expected_steps": [
                {"tool": "email", "action": "search", "entities": {"senders": ["John"]}},
                {"tool": "email", "action": "send", "entities": {"recipients": ["John"]}},
                {"tool": "tasks", "action": "create", "entities": {"keywords": ["follow up"], "date_range": "next week"}}
            ]
        }
    ),
    TestCase(
        query="Reschedule all meetings today after 5pm and send everyone an email notification",
        expected_intent="multi_step",
        expected_step_count=2,
        expected_domains=["calendar", "email"],
        expected_response_contains=["meeting", "email"],
        expected_response_excludes=["error"],
        metadata={
            "expected_steps": [
                {"tool": "calendar", "action": "reschedule", "entities": {"date_range": "today", "time": "after 5pm"}},
                {"tool": "email", "action": "send"}
            ]
        }
    ),
    
    # Sequential with dependencies
    TestCase(
        query="Find emails about the project, summarize them, then schedule a meeting to discuss",
        expected_intent="multi_step",
        expected_step_count=3,
        expected_domains=["email", "calendar"],
        expected_response_contains=["email", "meeting"],
        expected_response_excludes=["error"],
        metadata={
            "expected_steps": [
                {"tool": "email", "action": "search", "entities": {"keywords": ["project"]}},
                {"tool": "email", "action": "summarize"},
                {"tool": "calendar", "action": "schedule", "entities": {"keywords": ["discuss"]}}
            ],
            "dependencies": [
                {"step": 1, "depends_on": 0},
                {"step": 2, "depends_on": 1}
            ]
        }
    ),
    
    # Parallel execution opportunities
    TestCase(
        query="Search emails from John and search emails from Sarah",
        expected_intent="multi_step",
        expected_step_count=2,
        expected_domains=["email"],
        expected_response_contains=["email", "John", "Sarah"],
        expected_response_excludes=["error"],
        metadata={
            "expected_steps": [
                {"tool": "email", "action": "search", "entities": {"senders": ["John"]}},
                {"tool": "email", "action": "search", "entities": {"senders": ["Sarah"]}}
            ],
            "parallel_execution": True
        }
    ),
]


# Autonomy Test Cases
AUTONOMY_TEST_CASES: List[TestCase] = [
    # High confidence - should execute autonomously
    TestCase(
        query="Schedule a meeting with John tomorrow at 3pm",
        expected_autonomous_execution=True,
        expected_clarification_request=False,
        expected_confidence_level="high",
        expected_response_contains=["meeting", "John", "tomorrow"],
        expected_response_excludes=["error", "clarify", "who", "what"],
        metadata={"confidence_threshold": 0.8}
    ),
    TestCase(
        query="Send an email to sarah@example.com about the project",
        expected_autonomous_execution=True,
        expected_clarification_request=False,
        expected_confidence_level="high",
        expected_response_contains=["email", "sarah"],
        expected_response_excludes=["error", "clarify"],
        metadata={"confidence_threshold": 0.8}
    ),
    
    # Medium confidence - should execute with minimal context
    TestCase(
        query="Schedule something with that person we met last week",
        expected_autonomous_execution=True,
        expected_clarification_request=False,  # Should use context/memory
        expected_confidence_level="medium",
        expected_response_contains=["meeting", "schedule"],
        expected_response_excludes=["error"],
        metadata={"confidence_threshold": 0.5, "requires_context": True}
    ),
    TestCase(
        query="Send a follow-up email about our conversation",
        expected_autonomous_execution=True,
        expected_clarification_request=False,  # Should use conversation context
        expected_confidence_level="medium",
        expected_response_contains=["email"],
        expected_response_excludes=["error"],
        metadata={"confidence_threshold": 0.5, "requires_context": True}
    ),
    
    # Low confidence - should ask for clarification
    TestCase(
        query="Do that thing we talked about",
        expected_autonomous_execution=False,
        expected_clarification_request=True,
        expected_confidence_level="low",
        expected_response_contains=["clarify", "what", "which"],
        metadata={"confidence_threshold": 0.3}
    ),
    TestCase(
        query="Send it to them",
        expected_autonomous_execution=False,
        expected_clarification_request=True,
        expected_confidence_level="low",
        expected_response_contains=["who", "what", "clarify"],
        metadata={"confidence_threshold": 0.3}
    ),
    
    # Error recovery scenarios
    TestCase(
        query="Schedule meetings with John, Sarah, and invalid@email.com",
        expected_error_recovery=True,
        expected_partial_success=True,
        expected_autonomous_execution=True,
        expected_response_contains=["meeting", "John", "Sarah"],
        expected_response_excludes=["error", "failed"],
        metadata={"has_invalid_input": True}
    ),
    TestCase(
        query="Find emails from John and send replies to all of them",
        expected_error_recovery=True,
        expected_partial_success=True,
        expected_autonomous_execution=True,
        expected_response_contains=["email", "John"],
        expected_response_excludes=["error"],
        metadata={"may_have_partial_failures": True}
    ),
    
    # Context awareness
    TestCase(
        query="Send him a reply about the meeting",
        expected_context_usage={"previous_reference": True},
        expected_autonomous_execution=True,
        expected_response_contains=["email", "reply"],
        expected_response_excludes=["error", "who"],
        context={"previous_query": "Find emails from John"},
        metadata={"requires_context_resolution": True}
    ),
    TestCase(
        query="Schedule a meeting like last time",
        expected_context_usage={"previous_reference": True},
        expected_autonomous_execution=True,
        expected_response_contains=["meeting", "schedule"],
        expected_response_excludes=["error"],
        metadata={"requires_memory_retrieval": True}
    ),
    
    # Adaptive planning
    TestCase(
        query="Find a time to meet with John this week",
        expected_plan_adaptation=True,
        expected_autonomous_execution=True,
        expected_response_contains=["meeting", "John", "week"],
        expected_response_excludes=["error"],
        metadata={"requires_dynamic_planning": True}
    ),
    TestCase(
        query="Reorganize my day to give me a slow start",
        expected_plan_adaptation=True,
        expected_autonomous_execution=True,
        expected_response_contains=["calendar", "schedule"],
        expected_response_excludes=["error"],
        metadata={"requires_complex_planning": True}
    ),
]

