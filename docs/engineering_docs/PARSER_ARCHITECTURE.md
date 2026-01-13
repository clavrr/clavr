# Parser Architecture

This document describes the architecture of the parser system, which converts natural language queries into structured parameters for domain-specific tools.

## Parser System Overview

```
User Query
    │
    ▼
BaseParser (Abstract)
    │
    ├─→ EmailParser → Email Handlers → Parse Result → Domain Tool
    ├─→ CalendarParser → Calendar Handlers → Parse Result → Domain Tool
    ├─→ TaskParser → Task Handlers → Parse Result → Domain Tool
    └─→ NotionParser → Notion Handlers → Parse Result → Domain Tool

Shared Components:
  - SemanticPatternMatcher (Gemini 768D / Sentence Trans 384D)
  - RAG Service (Optional Context)
  - Conversation Memory (Context)
```

## Parser Component Details

### BaseParser (Abstract Base Class)

**Responsibilities:**
- Common functionality for all parsers
- Semantic pattern matching via shared SemanticPatternMatcher
- RAG service integration for context retrieval
- Conversation memory integration for context awareness
- Response formatting utilities

**Key Methods:**
- `parse_query_to_params()`: Abstract method - parse query to structured params
- `get_context()`: Retrieve RAG context for query
- `get_conversation_context()`: Get recent conversation history
- `format_response_conversationally()`: Make responses natural

### EmailParser Architecture

```
Query → Classification Handlers → Intent Detection
                                    │
                                    ├─→ Search Handlers → RAG Semantic Search → Gmail API
                                    ├─→ Composition Handlers → LLM Generation → Email Service
                                    ├─→ Query Processing Handlers → Response Formatting
                                    └─→ Management Handlers → Bulk Operations
                                                          │
                                                          └─→ Parsed Result + Formatted Response
```

**EmailParser Handlers:**
1. **ClassificationHandlers**: Intent detection, confidence scoring
2. **SearchHandlers**: Email search (semantic + keyword), filtering
3. **CompositionHandlers**: Email creation, reply generation
4. **QueryProcessingHandlers**: List operations, formatting responses
5. **ManagementHandlers**: Organization, bulk operations, categorization
6. **ConversationalHandlers**: Natural language understanding
7. **LLMGenerationHandlers**: AI-powered email generation
8. **UtilityHandlers**: Common utilities, date parsing, entity extraction

### TaskParser Architecture

```
Query → Classification Handlers → Intent Detection
                                    │
                                    ├─→ Creation Handlers → Entity Extract → Task Service
                                    ├─→ Query Processing Handlers → Response Formatting
                                    ├─→ Action Handlers → Task Service
                                    └─→ Analytics Handlers → Productivity Insights
                                                          │
                                                          └─→ Parsed Result
```

**TaskParser Handlers:**
1. **ClassificationHandlers**: Intent detection, task-specific patterns
2. **CreationHandlers**: Task creation with entity extraction
3. **QueryProcessingHandlers**: List, search, filter operations
4. **ActionHandlers**: Complete, update, delete operations
5. **AnalyticsHandlers**: Productivity insights, task analysis
6. **UtilityHandlers**: Common utilities, date parsing

### CalendarParser Architecture

Similar modular structure with:
- **ClassificationHandlers**: Event intent detection
- **EventHandlers**: Event creation, update, deletion
- **ListSearchHandlers**: Calendar queries, free time detection
- **AdvancedHandlers**: Conflict detection, meeting prep
- **UtilityHandlers**: Date/time parsing, attendee extraction

## Semantic Pattern Matching

**Shared Component**: `SemanticPatternMatcher`

**Features:**
- Pre-computed pattern embeddings for fast matching
- Dual embedding providers:
  - **Gemini Embeddings** (768D, cached, more accurate)
  - **Sentence Transformers** (384D, local, faster)
- Cosine similarity matching with configurable thresholds
- Pattern-based intent classification

**Flow:**
1. Patterns loaded at initialization
2. Embeddings pre-computed for all patterns
3. Query embedding generated on-demand
4. Cosine similarity calculated against pattern embeddings
5. Best match above threshold returned

