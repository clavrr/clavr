# Phase 3B: Extract Action Handlers & Entity Extraction - PLAN

**Date:** November 15, 2025  
**Status:** 📋 PLANNING  
**Target:** Reduce task_parser.py from 3,080 to ~1,500 lines

---

## Overview

Phase 3B will extract **action handlers** and **entity extraction** methods from task_parser.py. These are tightly coupled with the main parser but can be organized into separate, well-documented modules.

---

## Strategy Decision

### Option 1: Keep Methods in Main Class (RECOMMENDED)
**Approach:** Don't extract action handlers, instead document and organize them better  
**Rationale:**
- Action handlers heavily depend on instance methods (`self._extract_*`, `self._parse_and_*`)
- Extracting would require passing `self` or creating complex dependencies
- Risk of breaking functionality is HIGH
- Better to focus on splitting truly independent components

**What to do instead:**
1. Add clear section comments in task_parser.py
2. Extract truly independent utilities
3. Focus on calendar_parser and email_parser (larger files)

### Option 2: Extract to Mix-in Classes (MODERATE RISK)
**Approach:** Create mix-in classes that TaskParser inherits from  
**Example:**
```python
# src/agent/parsers/task/action_handlers.py
class TaskActionHandlerMixin:
    def _handle_create_action(self, tool, query):
        # Implementation
        
# src/agent/parsers/task_parser.py
class TaskParser(BaseParser, TaskActionHandlerMixin):
    # Main implementation
```

**Pros:**
- Organizes code into logical modules
- Reduces main file size
- Maintains access to `self`

**Cons:**
- More complex inheritance
- Harder to debug
- Mix-ins can be confusing

### Option 3: Extract to Helper Class (LOW RISK)
**Approach:** Create a helper class that holds references to parser  
**Example:**
```python
# src/agent/parsers/task/action_handlers.py
class TaskActionHandlers:
    def __init__(self, parser):
        self.parser = parser
    
    def handle_create(self, tool, query):
        # Can access parser methods via self.parser
        
# src/agent/parsers/task_parser.py
class TaskParser(BaseParser):
    def __init__(self, ...):
        self.action_handlers = TaskActionHandlers(self)
```

**Pros:**
- Clean separation
- Easy to test
- Low risk

**Cons:**
- Adds indirection (`self.action_handlers.handle_create`)
- More objects to manage

---

## Recommended Next Steps

### RECOMMENDED: Skip to Bigger Fish 🐟

**Why:**
- task_parser.py is now 3,080 lines (down from 3,334)
- This is a **24% improvement already** over target (<4,000 lines)
- email_parser.py is **6,207 lines** (LARGEST FILE!)
- calendar_parser.py is **5,485 lines** (SECOND LARGEST!)

**Better ROI:**
- Splitting email_parser.py will save ~4,000+ lines
- Splitting calendar_parser.py will save ~3,500+ lines  
- Further task_parser splitting will save ~1,500 lines

**Recommendation:** 
✅ **Move to Phase 3C: Split email_parser.py or calendar_parser.py**

---

## Alternative: Continue with task_parser.py

If you insist on continuing with task_parser.py, here's the plan:

### Phase 3B1: Organize Current Code (2 hours, LOW RISK)

Add clear section markers in task_parser.py:

```python
# ============================================================================
# ACTION HANDLERS - Dispatch task actions to appropriate methods
# ============================================================================

def _handle_analyze_action(self, tool, query):
    ...

# ============================================================================
# ENTITY EXTRACTION - Extract task details from natural language
# ============================================================================

def _extract_task_details(self, query):
    ...

# ============================================================================
# CONVERSATIONAL RESPONSE GENERATION
# ============================================================================

def _generate_conversational_task_response(self, ...):
    ...
```

### Phase 3B2: Extract True Utilities (4 hours, LOW RISK)

Create `src/agent/parsers/task/utils.py`:

```python
"""
Task Parser Utilities

Pure functions with no dependencies on TaskParser instance.
"""

def clean_task_description(desc: str) -> str:
    """Remove common filler words from task description"""
    # Implementation
    
def parse_priority_keyword(query: str) -> Optional[str]:
    """Extract priority from keywords"""
    # Implementation
```

### Phase 3B3: Document Method Groups (1 hour, LOW RISK)

Add comprehensive docstrings:

```python
class TaskParser(BaseParser):
    """
    Task Parser - Handles task-related queries
    
    Method Organization:
    
    1. Action Handlers (lines 832-1065)
       - _handle_analyze_action
       - _handle_create_action
       - _handle_list_action
       - ... (13 methods total)
    
    2. Entity Extraction (lines 1086-1830)
       - _extract_task_details
       - _extract_priority
       - _extract_due_date
       - ... (19 methods total)
    
    3. Response Generation (lines 1831-2550)
       - _generate_conversational_task_response
       - _generate_conversational_task_analysis_response
       - ... (8 methods total)
    
    4. Analysis & Search (lines 2551-3080)
       - _parse_and_analyze_tasks
       - _search_tasks_by_query
       - ... (12 methods total)
    """
```

---

## File Size Analysis

### Current State
```
task_parser.py: 3,080 lines
├── Imports & Setup: ~50 lines
├── __init__: ~50 lines
├── parse_query: ~350 lines (main routing)
├── Action Handlers: ~235 lines (13 methods)
├── Entity Extraction: ~744 lines (19 methods)
├── Response Generation: ~720 lines (8 methods)
├── Analysis & Search: ~530 lines (12 methods)
└── Helper Methods: ~401 lines (various)
```

### Possible Reductions

| Extraction | Lines Saved | Risk | Effort | Worth It? |
|------------|-------------|------|--------|-----------|
| Action handlers → mix-in | 235 | High | 4-6h | ❌ No (high risk, low reward) |
| Entity extraction → mix-in | 744 | High | 6-8h | ❌ No (high coupling) |
| Response gen → helper | 720 | Medium | 4-6h | 🤔 Maybe |
| Utilities → separate file | 200 | Low | 2h | ✅ Yes |
| **Better: Split email_parser** | **4,000+** | Medium | **8-10h** | ✅✅✅ **YES!** |

---

## Recommendation: PIVOT TO EMAIL PARSER 🎯

### Why Email Parser Next?

1. **Size:** 6,207 lines (2x task_parser!)
2. **Impact:** Biggest file in codebase
3. **Clear structure:** Can be split logically:
   - semantic_matcher.py (~800 lines)
   - search_handlers.py (~1,500 lines)
   - composition_handlers.py (~1,000 lines)
   - action_handlers.py (~1,500 lines)
   - utils.py (~900 lines)

4. **Better ROI:** More lines saved for similar effort

### Email Parser Splitting Plan

```
src/agent/parsers/email/
├── __init__.py                 # Main EmailParser
├── semantic_matcher.py         # ~800 lines
├── search_handlers.py          # ~1,500 lines
├── composition_handlers.py     # ~1,000 lines
├── action_handlers.py          # ~1,500 lines
└── utils.py                    # ~900 lines
```

**Expected result:** email_parser.py ~1,000 lines (from 6,207!)

---

## Decision Matrix

| Option | Lines Saved | Risk | Effort | Recommendation |
|--------|-------------|------|--------|----------------|
| Continue task_parser | ~1,500 | High | 14-20h | ⚠️ Medium priority |
| Split email_parser | ~4,000 | Medium | 8-10h | ✅ HIGH PRIORITY |
| Split calendar_parser | ~3,500 | Medium | 8-10h | ✅ HIGH PRIORITY |
| Document task_parser | 0 | Low | 2h | ✅ Quick win |

---

## Final Recommendation

### ✅ RECOMMENDED PATH FORWARD:

1. **Quick Win (30 min):** Add section comments to task_parser.py for better organization
2. **Big Impact (8-10h):** Split email_parser.py (saves ~4,000 lines!)
3. **Follow-up (8-10h):** Split calendar_parser.py (saves ~3,500 lines!)
4. **Polish (optional):** Return to task_parser.py if time permits

### 📊 Impact Comparison:

| Approach | Time | Lines Saved | Files Improved |
|----------|------|-------------|----------------|
| **Continue task_parser** | 14-20h | 1,500 | 1 |
| **Split email + calendar** | 16-20h | **7,500** | **2** |

**Winner:** Split email_parser and calendar_parser! 🏆

---

## Next Steps (If Proceeding with Email Parser)

1. Create backup of email_parser.py
2. Analyze email_parser structure
3. Identify extraction targets
4. Create email module structure
5. Extract components incrementally
6. Test after each extraction
7. Document changes

See: **PHASE3C_EMAIL_PARSER_PLAN.md** (to be created)

---

## Conclusion

While we CAN continue extracting from task_parser.py, the **better investment** is to tackle the larger files (email_parser, calendar_parser) which will have bigger impact with similar effort.

**Status:** ⏸️ PAUSED - Recommend pivoting to email_parser  
**Next:** Create Phase 3C plan for email_parser splitting

---

**What would you like to do?**

A) ✅ **RECOMMENDED:** Pivot to email_parser.py splitting (8-10h, saves 4,000+ lines)  
B) Continue with task_parser.py extraction (14-20h, saves 1,500 lines)  
C) Add organization/comments to task_parser.py (30min, improves readability)  
D) Move to calendar_parser.py instead (8-10h, saves 3,500+ lines)
