# Phase 3D - Iteration 3: Action Classification Handlers - IN PROGRESS

**Date:** November 15, 2025  
**Status:** 🔄 **STARTING** - Action Classification Module Extraction  
**Iteration:** 3 of 6

---

## 🎯 Iteration 3 Objectives

Extract action classification and routing methods into dedicated module:
- Create `calendar/action_classifiers.py`
- Extract 11 classification and routing methods
- Target: ~600-700 lines
- Timeline: ~3 hours

---

## 📦 Target Methods for Extraction

### Classification & Routing Operations (11 methods)

1. **`_detect_calendar_action`** (line 395, ~85 lines)
   - Main action detection from query patterns
   - Handles all calendar action types
   - Priority-based pattern matching

2. **`_detect_explicit_calendar_action`** (line 480, ~53 lines)
   - Detect explicit calendar-specific patterns
   - Prevents LLM misclassification
   - High-priority pattern matching

3. **`_route_with_confidence`** (line 533, ~97 lines)
   - Confidence-based routing logic
   - Combines LLM + semantic + explicit patterns
   - Intelligent decision-making

4. **`_is_critical_misclassification`** (line 630, ~22 lines)
   - Detect critical classification errors
   - Override incorrect LLM classifications

5. **`_validate_classification`** (line 652, ~51 lines)
   - Self-validation of LLM classification
   - Correction mechanism

6. **`_extract_corrected_action`** (line 703, ~27 lines)
   - Extract corrected action from validation

7. **`_classify_calendar_query`** (line 730, ~58 lines)
   - Main LLM classification method
   - Structured output support
   - JSON parsing

8. **`_classify_calendar_with_structured_outputs`** (line 788, ~50 lines)
   - Structured output classification
   - Type-safe schema support

9. **`_build_calendar_classification_prompt`** (line 838, ~116 lines)
   - Build comprehensive classification prompts
   - Few-shot learning support
   - Chain-of-thought reasoning

10. **`_basic_calendar_classify`** (line 954, ~27 lines)
    - Fallback pattern-based classification
    - No LLM required

11. **`_execute_calendar_with_classification`** (line 981, ~46 lines)
    - Execute calendar actions with LLM classification
    - Route to appropriate handlers
    - Safeguards against misrouting

**Total Estimated Lines:** ~632 lines

---

## 📋 Implementation Steps

### Step 1: Create Module File
- [ ] Create `src/agent/parsers/calendar/action_classifiers.py`
- [ ] Add class `CalendarActionClassifiers`
- [ ] Add imports and initialization

### Step 2: Extract Methods
- [ ] Extract all 11 methods from calendar_parser.py
- [ ] Update method signatures (self.parser references)
- [ ] Fix internal method calls
- [ ] Preserve all classification logic

### Step 3: Update Lazy Loading
- [ ] Add to `calendar/__init__.py` `__all__` list
- [ ] Add to `__getattr__` function

### Step 4: Update calendar_parser.py
- [ ] Import `CalendarActionClassifiers`
- [ ] Initialize: `self.action_classifiers = CalendarActionClassifiers(self)`
- [ ] Create delegation stubs for all 11 methods
- [ ] Remove original implementations

### Step 5: Validation
- [ ] Check for compilation errors
- [ ] Verify file size reduction
- [ ] Verify each method appears only once
- [ ] Test classification still works

---

## 📊 Expected Results

### Before Iteration 3
```
calendar_parser.py: 1,127 lines
```

### After Iteration 3
```
calendar_parser.py: ~495 lines (reduction: ~632 lines, 56% further reduction)
calendar/action_classifiers.py: ~632 lines (new)
```

---

## 🎯 Success Criteria

- [ ] Module created with all 11 methods
- [ ] File size reduced by ~632 lines
- [ ] 0 compilation errors
- [ ] All methods delegating correctly
- [ ] Lazy loading implemented
- [ ] Classification logic preserved
- [ ] Clean code structure

---

## 📝 Notes

- This module is critical for intent detection and routing
- Must preserve LLM integration carefully
- Chain-of-thought prompts are large - handle carefully
- Few-shot learning logic must be preserved
- Confidence-based routing is complex - test thoroughly

---

## Current File State

```
calendar_parser.py: 1,127 lines
├── Classification methods: ~632 lines (to extract)
├── Conversational methods: ~200 lines (Iteration 4)
├── Special features: ~150 lines (Iteration 5)
└── Utilities: ~145 lines (remaining core)
```

**Status:** Ready to begin extraction
