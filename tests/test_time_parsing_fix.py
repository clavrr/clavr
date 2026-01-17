"""
Quick Test for Time Parsing Fix

Verifies that the time parsing bug is fixed:
- "2pm" should parse to 14:00 (not 12am/midnight)
- "12am" should parse to 00:00 (midnight)
- "12pm" should parse to 12:00 (noon)
"""
from datetime import datetime
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_parse_schedule_time():
    """Test the enhanced time parser"""
    from tools.email.actions import EmailActions
    from unittest.mock import Mock
    
    # Create mock email service
    mock_service = Mock()
    actions = EmailActions(mock_service)
    
    print("=" * 60)
    print("TIME PARSING FIX VERIFICATION")
    print("=" * 60)
    print()
    
    test_cases = [
        ("2pm", 14, 0, "Plain afternoon time"),
        ("2 pm", 14, 0, "Afternoon time with space"),
        ("10am", 10, 0, "Morning time"),
        ("12am", 0, 0, "Midnight (critical test)"),
        ("12pm", 12, 0, "Noon"),
        ("2:30 pm", 14, 30, "Time with minutes"),
        ("3 pm", 15, 0, "Single digit with space"),
        ("11pm", 23, 0, "Late evening"),
    ]
    
    passed = 0
    failed = 0
    
    for time_str, expected_hour, expected_minute, description in test_cases:
        result = actions._parse_schedule_time(time_str)
        
        if result is None:
            print(f"❌ FAIL: '{time_str}' - {description}")
            print(f"   Expected: {expected_hour:02d}:{expected_minute:02d}")
            print(f"   Got: None (parsing failed)")
            failed += 1
        elif result.hour != expected_hour or result.minute != expected_minute:
            print(f"❌ FAIL: '{time_str}' - {description}")
            print(f"   Expected: {expected_hour:02d}:{expected_minute:02d}")
            print(f"   Got: {result.hour:02d}:{result.minute:02d}")
            failed += 1
        else:
            print(f"✅ PASS: '{time_str}' → {result.hour:02d}:{result.minute:02d} - {description}")
            passed += 1
    
    print()
    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed == 0:
        print("\n🎉 All tests passed! Time parsing bug is FIXED!")
        return True
    else:
        print(f"\n⚠️  {failed} test(s) failed. Please review the implementation.")
        return False

if __name__ == "__main__":
    success = test_parse_schedule_time()
    sys.exit(0 if success else 1)
