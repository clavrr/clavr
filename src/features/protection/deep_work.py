"""
Deep Work Logic Module

Contains core logic for analyzing calendar density and determining
protection levels (The "Ghost" brain).
"""
from enum import Enum
from typing import List, Dict, Any
from datetime import datetime, timedelta
import pytz

class ProtectionLevel(Enum):
    NORMAL = "normal"
    MEETING_HEAVY = "meeting_heavy"
    DEEP_WORK = "deep_work"

class DeepWorkLogic:
    """
    Logic for "Deep Work Shield".
    Analyzes calendar events to determine if the user needs protection.
    """
    
    @staticmethod
    def calculate_busyness_score(
        events: List[Dict[str, Any]], 
        start_time: datetime,
        end_time: datetime
    ) -> float:
        """
        Calculate a busyness score (0.0 to 1.0) based on event density.
        
        Args:
            events: List of Google Calendar event dicts
            start_time: Window start (must be timezone aware)
            end_time: Window end (must be timezone aware)
            
        Returns:
            Float between 0.0 (empty) and 1.0 (fully booked)
        """
        if not events:
            return 0.0
        
        # Ensure aware datetimes
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=pytz.UTC)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=pytz.UTC)
            
        total_duration_minutes = (end_time - start_time).total_seconds() / 60
        if total_duration_minutes <= 0:
            return 0.0
            
        intervals = []
        for event in events:
            # Skip all-day events (often just reminders/holidays) unless transparent
            if 'date' in event.get('start', {}):
                # We skip all-day events for now to avoid blocking whole days for holidays
                # In future we can check transparency
                continue
            
            start_str = event.get('start', {}).get('dateTime')
            end_str = event.get('end', {}).get('dateTime')
            
            if start_str and end_str:
                try:
                    # Parse and normalize to UTC
                    e_start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    e_end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                    
                    if e_start.tzinfo is None:
                         e_start = e_start.replace(tzinfo=pytz.UTC)
                    if e_end.tzinfo is None:
                         e_end = e_end.replace(tzinfo=pytz.UTC)
                    
                    # Clip to window
                    if e_end <= start_time or e_start >= end_time:
                        continue
                        
                    effective_start = max(start_time, e_start)
                    effective_end = min(end_time, e_end)
                    
                    if effective_end > effective_start:
                        intervals.append((effective_start, effective_end))
                except ValueError:
                    continue
        
        # Merge intervals
        if not intervals:
            return 0.0
            
        intervals.sort(key=lambda x: x[0])
        merged = []
        if intervals:
            current_start, current_end = intervals[0]
            
            for next_start, next_end in intervals[1:]:
                if next_start < current_end: # overlap or adjacent
                    current_end = max(current_end, next_end)
                else:
                    merged.append((current_start, current_end))
                    current_start, current_end = next_start, next_end
            merged.append((current_start, current_end))
        
        # Sum duration
        busy_seconds = sum((end - start).total_seconds() for start, end in merged)
        score = busy_seconds / (total_duration_minutes * 60)
        
        return min(1.0, score)

    @staticmethod
    def determine_protection_level(busyness_score: float, events: List[Dict[str, Any]] = None) -> ProtectionLevel:
        """
        Determine protection level based on busyness score and explicit event titles.
        
        Priority:
        1. Explicit focus/deep work events (via analyze_event_types)
        2. High meeting density (>80%)
        3. Normal operations
        """
        # Check for explicit user intent first
        if events and DeepWorkLogic.analyze_event_types(events) == ProtectionLevel.DEEP_WORK:
            return ProtectionLevel.DEEP_WORK

        # Fallback to density heuristics
        if busyness_score >= 0.8:
            # Back-to-back meetings
            return ProtectionLevel.MEETING_HEAVY
            
        return ProtectionLevel.NORMAL

    @staticmethod
    def analyze_event_types(events: List[Dict[str, Any]]) -> ProtectionLevel:
        """
        Analyze events for key words like "Deep Work", "Focus", "Heads Down".
        Prioritizes explicit user intent.
        """
        focus_keywords = {"focus", "deep work", "heads down", "coding", "do not disturb"}
        
        for event in events:
            title = event.get('summary', '').lower()
            if any(k in title for k in focus_keywords):
                # Check if this event is happening NOW or covering a significant portion
                # For simplicity, if any focus event exists in the window, we assume Deep Work
                return ProtectionLevel.DEEP_WORK
                
        return ProtectionLevel.NORMAL
