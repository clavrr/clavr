
"""
Type definitions for Perception Agent
"""
from typing import Dict, Any, NamedTuple
from enum import Enum

class SignalType(str, Enum):
    NOISE = "noise"
    TRIGGER = "trigger"

class PerceptionEvent(NamedTuple):
    type: str # 'email', 'calendar', 'system'
    source_id: str
    content: Dict[str, Any]
    timestamp: str

class Trigger(NamedTuple):
    priority: str # 'low', 'medium', 'high', 'critical'
    category: str # 'meeting', 'urgent_email', 'break_detection'
    reason: str
    context: Dict[str, Any]
