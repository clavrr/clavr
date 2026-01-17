# Email Parser Split Plan - Phase 3C

## Current State
- **File**: `src/agent/parsers/email_parser.py`
- **Total Lines**: 6,207 (LARGEST FILE)
- **Total Methods**: 104 (3 classes)
- **Target**: Split into modules <1,000 lines each

## Structure Analysis

### Classes Found:
1. **EmailSemanticPatternMatcher** (lines 42-237): ~195 lines, 3 methods
2. **EmailLearningSystem** (lines 239-309): ~70 lines, 5 methods
3. **EmailParser** (lines 311-6207): ~5,896 lines, 96 methods

### EmailParser Method Groups (96 methods):

#### Core Methods (6 methods):
- `__init__` (331)
- `get_supported_tools` (387)
- `parse_query` (391) - MAIN ENTRY POINT
- `_handle_conversational_query` (649)
- `_handle_contextual_email_query_with_memory` (728)
- `_handle_contextual_email_query` (1071)

#### Action Detection & Classification (6 methods):
- `_detect_email_action` (1157)
- `_detect_explicit_email_action` (1296)
- `_route_with_confidence` (1346)
- `_is_critical_email_misclassification` (1444)
- `_validate_classification` (1472)
- `_classify_email_query_with_enhancements` (1517)

#### Action Handlers (8 methods):
- `_handle_list_action` (1662)
- `_handle_send_action` (1925)
- `_handle_reply_action` (1939)
- `_handle_search_action` (1943)
- `_handle_mark_read_action` (3374)
- `_handle_mark_unread_action` (3378)
- `_handle_unread_action` (3382)
- `_handle_summarize_action` (5673)
- `_handle_archive_action` (6079)

#### Search & RAG Methods (7 methods):
- `_should_use_hybrid_search` (2282)
- `_should_use_rag` (2325)
- `_hybrid_search` (2410)
- `_extract_emails_from_result_string` (2685)
- `_extract_emails_from_rag_result` (2710)
- `_merge_search_results` (2767)
- `_detect_folder_from_query` (2849)
- `_handle_last_email_query` (2869)

#### Email Composition Methods (9 methods):
- `_parse_and_schedule_email` (3454)
- `_parse_and_send_email` (3463)
- `_extract_email_recipient` (3499)
- `_extract_email_subject` (3507)
- `_extract_email_body` (3584)
- `_generate_email_with_template` (3624)
- `_generate_simple_email` (3628)
- `_extract_meaningful_context` (3651)
- `_personalize_email_body` (3673)

#### Entity Extraction Methods (4 methods):
- `_extract_search_query` (3691)
- `extract_entities` (3760)
- `_extract_sender_from_query` (3260)
- `_extract_actual_query` (3340)
- `_extract_schedule_time` (3411)

#### Multi-Step Query Handling (6 methods):
- `_is_multi_step_query` (3784)
- `_handle_multi_step_query` (3872)
- `_decompose_query_steps` (3905)
- `_decompose_email_steps_with_structured_outputs` (3954)
- `_execute_query_step` (4018)
- `_execute_single_step` (4033)

#### Execution & Confirmation (5 methods):
- `_ask_for_clarification` (4048)
- `_execute_with_confirmation` (4073)
- `_generate_confirmation_message` (4096)
- `_execute_with_classification` (4115)
- `_build_advanced_search_query` (4218)
- `_build_contextual_search_query` (4376)
- `_expand_keywords` (4391)

#### LLM Generation Methods (7 methods):
- `_generate_email_summary_with_llm_for_multiple_emails` (4417)
- `_generate_email_summary_with_llm` (4549)
- `_generate_email_with_llm` (4665)
- `_generate_conversational_email_response` (4701)
- `_parse_emails_from_formatted_result` (5017)
- `_is_response_conversational` (5136)
- `_force_llm_regeneration` (5171)
- `_final_cleanup_conversational_response` (5217)
- `_generate_summary_with_llm` (5971)

#### Learning & Feedback (11 methods):
- `learn_from_feedback` (5278)
- `_save_feedback` (5306)
- `_load_feedback` (5335)
- `_analyze_feedback_patterns` (5350)
- `_is_intent_mismatch` (5397)
- `_missing_entities` (5416)
- `_date_related_mistake` (5425)
- `_sender_related_mistake` (5430)
- `_update_parsing_rules_from_feedback` (5435)
- `_extract_intent_correction_patterns` (5505)
- `_extract_entity_patterns` (5532)
- `_extract_date_expressions` (5556)
- `_extract_keyword_synonyms` (5572)
- `_save_learned_patterns` (5593)
- `_load_learned_patterns` (5616)
- `get_feedback_stats` (5638)
- `clear_feedback` (5655)

#### Email Parsing & Formatting (8 methods):
- `_parse_email_search_result` (943)
- `_extract_email_id_from_result` (1013)
- `_format_email_context_response` (1044)
- `_handle_email_summary_query` (3109)
- `_format_email_search_with_content` (3234)
- `_extract_summarize_content` (6016)
- `_detect_summarize_format` (6034)
- `_detect_summarize_length` (6045)
- `_extract_summarize_focus` (6056)

#### Email Management Tools (3 methods):
- `_extract_message_id` (6112)
- `_handle_email_management_tool` (6129)
- `_handle_summarize_tool` (6156)
- `_extract_criteria_for_bulk_operation` (6191)
- `_extract_content_for_analysis` (6205)

## Proposed Module Structure

```
src/agent/parsers/email/
├── __init__.py                     # Empty (lazy loading)
├── semantic_matcher.py             # ~200 lines - EmailSemanticPatternMatcher
├── learning_system.py              # ~100 lines - EmailLearningSystem
├── action_handlers.py              # ~800 lines - All _handle_*_action methods
├── search_handlers.py              # ~900 lines - Search, RAG, hybrid methods
├── composition_handlers.py         # ~700 lines - Email composition & generation
├── entity_extraction.py            # ~600 lines - All extraction methods
├── multi_step.py                   # ~500 lines - Multi-step query handling
├── llm_generation.py               # ~900 lines - LLM generation methods
├── learning_feedback.py            # ~800 lines - Learning & feedback methods
└── utils.py                        # ~500 lines - Parsing, formatting, helpers
```

**Main file remaining**: ~800 lines (init, parse_query, core routing)

## Extraction Steps

### Step 1: Extract Helper Classes ✅ (PRIORITY)
- [x] Create `email/` module directory
- [x] Extract `EmailSemanticPatternMatcher` → `semantic_matcher.py`
- [x] Extract `EmailLearningSystem` → `learning_system.py`
- [x] Update imports in `email_parser.py`
- [x] Verify imports work

### Step 2: Extract Action Handlers
- [ ] Create `action_handlers.py`
- [ ] Move all `_handle_*_action` methods (9 methods)
- [ ] Update imports
- [ ] Verify

### Step 3: Extract Search Handlers
- [ ] Create `search_handlers.py`
- [ ] Move search, RAG, hybrid methods (8 methods)
- [ ] Update imports
- [ ] Verify

### Step 4: Extract Composition Handlers
- [ ] Create `composition_handlers.py`
- [ ] Move email composition methods (9 methods)
- [ ] Update imports
- [ ] Verify

### Step 5: Extract Entity Extraction
- [ ] Create `entity_extraction.py`
- [ ] Move all extraction methods (5 methods)
- [ ] Update imports
- [ ] Verify

### Step 6: Extract Multi-Step Handling
- [ ] Create `multi_step.py`
- [ ] Move multi-step query methods (6 methods)
- [ ] Update imports
- [ ] Verify

### Step 7: Extract LLM Generation
- [ ] Create `llm_generation.py`
- [ ] Move LLM generation methods (9 methods)
- [ ] Update imports
- [ ] Verify

### Step 8: Extract Learning & Feedback
- [ ] Create `learning_feedback.py`
- [ ] Move learning methods (16 methods)
- [ ] Update imports
- [ ] Verify

### Step 9: Extract Utils
- [ ] Create `utils.py`
- [ ] Move parsing/formatting methods (13 methods)
- [ ] Update imports
- [ ] Verify

### Step 10: Add Section Markers
- [ ] Add comprehensive section markers to remaining email_parser.py
- [ ] Document all sections in class docstring
- [ ] Final verification

## Expected Results
- **email_parser.py**: 6,207 → ~800 lines (-87% reduction)
- **9 new modules**: All <1,000 lines each
- **Maintainability**: Much improved
- **Functionality**: 100% preserved

## Verification Checklist
- [ ] All imports resolve correctly
- [ ] No circular dependencies
- [ ] All methods accessible
- [ ] Syntax check passes
- [ ] Documentation updated
