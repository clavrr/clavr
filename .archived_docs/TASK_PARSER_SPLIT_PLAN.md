# Phase 3: Task Parser File Splitting Plan

## Current State
- **task_parser.py**: 3,334 lines, 74 methods, 3 classes
- Classes: TaskSemanticPatternMatcher, TaskLearningSystem, TaskParser

## Completed
✅ Extracted `TaskSemanticPatternMatcher` → `semantic_matcher.py` (180 lines)
✅ Extracted `TaskLearningSystem` → `learning_system.py` (90 lines)
✅ Created `__init__.py` for module exports

## Proposed Module Structure

```
src/agent/parsers/task/
├── __init__.py                    # Module exports (DONE)
├── semantic_matcher.py            # TaskSemanticPatternMatcher (DONE)
├── learning_system.py             # TaskLearningSystem (DONE)
├── task_parser.py                 # Main TaskParser class (~500 lines)
├── classification.py              # Classification & routing (~400 lines)
├── action_handlers.py             # All _handle_*_action methods (~1200 lines)
├── entity_extraction.py           # All _extract_* methods (~900 lines)
└── utils.py                       # Helper functions (~200 lines)
```

## Method Distribution

### task_parser.py (Main Parser)
- `__init__` - Initialization
- `parse_query` - Main entry point
- `_detect_task_action` - Action detection
- `_detect_explicit_task_action` - Explicit pattern matching
- `validate_tool` - Tool validation (inherited)
- `format_response_conversationally` - Response formatting

### classification.py
- `_classify_task_query_with_enhancements` - Enhanced classification
- `_route_with_confidence` - Confidence-based routing
- `_is_critical_task_misclassification` - Misclassification detection
- `_validate_classification` - Classification validation
- `_execute_task_with_classification` - Execute with classification
- `_parse_and_create_task_with_classification` - Create with classification

### action_handlers.py (13 methods)
- `_handle_analyze_action`
- `_handle_create_action`
- `_handle_list_action`
- `_handle_complete_action`
- `_handle_delete_action`
- `_handle_search_action`
- `_handle_analytics_action`
- `_handle_template_action`
- `_handle_recurring_action`
- `_handle_reminders_action`
- `_handle_overdue_action`
- `_handle_subtasks_action`
- `_handle_bulk_action`

### entity_extraction.py (19 methods)
- `_extract_task_details`
- `_extract_tags`
- `_extract_project`
- `_extract_subtasks`
- `_extract_notes`
- `_extract_reminder_days`
- `_extract_estimated_hours`
- `_extract_actual_query`
- `_extract_task_description`
- `_extract_core_action`
- `_extract_priority`
- `_extract_due_date`
- `_extract_due_date_patterns`
- `_extract_category`
- `_extract_analysis_type`
- `_extract_task_description_llm`
- `_extract_due_date_with_llm`
- `_extract_priority_from_classification`
- `_extract_category_from_classification`

### utils.py
- Helper functions
- Constants
- Shared utilities

## Implementation Steps

1. ✅ Extract semantic_matcher.py
2. ✅ Extract learning_system.py
3. ⏳ Extract action_handlers.py
4. ⏳ Extract entity_extraction.py
5. ⏳ Extract classification.py
6. ⏳ Create utils.py
7. ⏳ Refactor main task_parser.py
8. ⏳ Update imports in __init__.py
9. ⏳ Test imports and functionality
10. ⏳ Update references throughout codebase

## Risk Mitigation
- Keep original file as backup until verified
- Test after each extraction
- Verify no circular imports
- Check all usages in codebase

## Expected Benefits
- Files < 1,200 lines (currently 3,334)
- Clearer separation of concerns
- Easier to test individual components
- Reduced cognitive load
- Better maintainability

## Next: Extract action_handlers.py
