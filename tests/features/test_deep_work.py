"""
Tests for Deep Work Logic
"""
import pytest
from datetime import datetime, timedelta
import pytz
from src.features.protection.deep_work import DeepWorkLogic, ProtectionLevel

class TestDeepWorkLogic:
    
    def test_calculate_busyness_score_empty(self):
        start = datetime(2023, 1, 1, 9, 0, tzinfo=pytz.UTC)
        end = datetime(2023, 1, 1, 11, 0, tzinfo=pytz.UTC)
        events = []
        score = DeepWorkLogic.calculate_busyness_score(events, start, end)
        assert score == 0.0

    def test_calculate_busyness_score_full(self):
        start = datetime(2023, 1, 1, 9, 0, tzinfo=pytz.UTC)
        end = datetime(2023, 1, 1, 10, 0, tzinfo=pytz.UTC)
        events = [{
            'start': {'dateTime': '2023-01-01T09:00:00Z'},
            'end': {'dateTime': '2023-01-01T10:00:00Z'}
        }]
        score = DeepWorkLogic.calculate_busyness_score(events, start, end)
        assert score == 1.0

    def test_calculate_busyness_score_partial_overlap(self):
        start = datetime(2023, 1, 1, 9, 0, tzinfo=pytz.UTC)
        end = datetime(2023, 1, 1, 10, 0, tzinfo=pytz.UTC) # 60 mins
        # Event 1: 9:00-9:15 (15m)
        # Event 2: 9:30-9:45 (15m)
        # Total: 30m = 0.5
        events = [
            {'start': {'dateTime': '2023-01-01T09:00:00Z'}, 'end': {'dateTime': '2023-01-01T09:15:00Z'}},
            {'start': {'dateTime': '2023-01-01T09:30:00Z'}, 'end': {'dateTime': '2023-01-01T09:45:00Z'}}
        ]
        score = DeepWorkLogic.calculate_busyness_score(events, start, end)
        assert score == 0.5

    def test_calculate_busyness_score_nested_overlap(self):
        start = datetime(2023, 1, 1, 9, 0, tzinfo=pytz.UTC)
        end = datetime(2023, 1, 1, 10, 0, tzinfo=pytz.UTC) # 60 mins
        # Event 1: 9:00-9:45 (45m)
        # Event 2: 9:15-9:30 (inside event 1)
        # Total expected: 45m = 0.75
        events = [
            {'start': {'dateTime': '2023-01-01T09:00:00Z'}, 'end': {'dateTime': '2023-01-01T09:45:00Z'}},
            {'start': {'dateTime': '2023-01-01T09:15:00Z'}, 'end': {'dateTime': '2023-01-01T09:30:00Z'}}
        ]
        score = DeepWorkLogic.calculate_busyness_score(events, start, end)
        assert score == 0.75

    def test_determine_protection_level(self):
        assert DeepWorkLogic.determine_protection_level(0.8) == ProtectionLevel.MEETING_HEAVY
        assert DeepWorkLogic.determine_protection_level(0.6) == ProtectionLevel.NORMAL
        # Based on current logic (only >0.7 is heavy)
        assert DeepWorkLogic.determine_protection_level(0.2) == ProtectionLevel.NORMAL

    def test_analyze_event_types_keywords(self):
        events = [{'summary': 'Deep Work Session'}]
        assert DeepWorkLogic.analyze_event_types(events) == ProtectionLevel.DEEP_WORK

        events = [{'summary': 'Weekly Focus Time'}]
        assert DeepWorkLogic.analyze_event_types(events) == ProtectionLevel.DEEP_WORK
        
        events = [{'summary': 'Marketing Sync'}]
        assert DeepWorkLogic.analyze_event_types(events) == ProtectionLevel.NORMAL
