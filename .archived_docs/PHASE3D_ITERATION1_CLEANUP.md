# Phase 3D Iteration 1 - Final Cleanup Instructions

## Current Status: 99% Complete

### ✅ What's Done:
1. Created `calendar/event_handlers.py` (1,071 lines, 11 methods)
2. Updated `calendar/__init__.py` with lazy loading
3. Updated `calendar_parser.py` imports and initialization  
4. Added delegation stubs (lines 3229-3277)

### ❌ What Needs to Be Done:
**Remove the original method implementations that are now duplicates**

## Exact Lines to Delete:

You need to remove **lines 2266 through 3224** from `calendar_parser.py`.

This range contains the original implementations of these 11 methods:
1. `_handle_create_action` (starts ~line 2266)
2. `_handle_search_action` (starts ~line 2380)  
3. `_handle_move_action` (starts ~line 2403)
4. `_handle_update_action` (starts ~line 2413)
5. `_handle_move_reschedule_action` (starts ~line 2494)
6. `_extract_event_title_from_move_query` (starts ~line 2588)
7. `_find_event_by_title` (starts ~line 2623)
8. `_extract_new_time_from_move_query` (starts ~line 2659)
9. `_parse_relative_time_to_iso` (starts ~line 2700)
10. `_handle_delete_action` (starts ~line 2789)
11. `_parse_and_create_calendar_event_with_conflict_check` (starts ~line 3027)
12. `_check_calendar_conflicts` (starts ~line 3160, ends ~line 3224)

## How to Do It:

### Option 1: Using sed (Terminal)
```bash
cd /Users/maniko/Documents/notely-agent
cp src/agent/parsers/calendar_parser.py src/agent/parsers/calendar_parser.py.backup
sed -i '' '2266,3224d' src/agent/parsers/calendar_parser.py
```

### Option 2: Using VS Code
1. Open `src/agent/parsers/calendar_parser.py`
2. Go to line 2266 (Cmd+G or Ctrl+G)
3. Select from line 2266 to line 3224
4. Delete the selection
5. Save the file

### Option 3: Using Python Script
```python
# Save this as remove_duplicates.py
with open('src/agent/parsers/calendar_parser.py', 'r') as f:
    lines = f.readlines()

# Keep lines 1-2265 and 3225-end
new_lines = lines[:2265] + lines[3224:]

with open('src/agent/parsers/calendar_parser.py', 'w') as f:
    f.writelines(new_lines)

print(f"Removed {len(lines) - len(new_lines)} lines")
print(f"New file size: {len(new_lines)} lines")
```

## Expected Result:

After deletion:
- **Before:** 5,291 lines
- **After:** ~4,332 lines (removed ~959 lines)
- **No errors** in `calendar_parser.py`

## Verification:

Run this to verify:
```bash
# Check line count
wc -l src/agent/parsers/calendar_parser.py

# Verify no duplicate methods (should see only ONE of each)
grep -n "def _handle_create_action" src/agent/parsers/calendar_parser.py
grep -n "def _handle_update_action" src/agent/parsers/calendar_parser.py  
grep -n "def _handle_delete_action" src/agent/parsers/calendar_parser.py

# Check for errors
python -m py_compile src/agent/parsers/calendar_parser.py
```

## What You Should See After Cleanup:

Each extracted method should appear **exactly once** - as a delegation stub like this:
```python
def _handle_create_action(self, tool: BaseTool, query: str) -> str:
    """Delegate to event_handlers module"""
    return self.event_handlers.handle_create_action(tool, query)
```

The delegation stubs section should be around line 2266 (after the cleanup).

## Note:
The warnings in `calendar/__init__.py` about `CalendarSemanticPatternMatcher`, etc. being "specified in __all__ but not present" are expected and harmless - they're just the linter not understanding lazy loading. This is the same pattern we used successfully in the email parser.
