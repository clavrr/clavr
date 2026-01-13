# End-to-End Query Flow Architecture

This document describes the high-level architecture of how user queries flow through the Clavr Agent system from initial request to final response.

## High-Level Architecture: User Query to Response

```
User Query → API Router → Auth → ClavrAgent
                                    │
                                    ├─→ Cache Check
                                    │   ├─→ Cache Hit → Response
                                    │   └─→ Cache Miss
                                    │       │
                                    │       ├─→ Simple Query → Tool Execution → Response
                                    │       │
                                    │       └─→ Complex Query
                                    │           │
                                    │           ├─→ Orchestrator
                                    │           │   ├─→ Memory Role (Context)
                                    │           │   ├─→ Analyzer Role (Analysis)
                                    │           │   ├─→ Execution Plan
                                    │           │   └─→ Execute Steps
                                    │           │       │
                                    │           │       ├─→ Email Tool + Parser → Email Service → Gmail API
                                    │           │       ├─→ Calendar Tool + Parser → Calendar Service → Calendar API
                                    │           │       └─→ Task Tool + Parser → Task Service → Tasks API
                                    │           │
                                    │           ├─→ RAG Engine (if needed)
                                    │           │   ├─→ Vector Search (Pinecone)
                                    │           │   └─→ Direct API
                                    │           │
                                    │           └─→ Synthesizer Role → Response Formatter → Memory → Response
                                    │
                                    └─→ Streaming → User Receives Response
```

## Detailed Flow Explanation

### 1. API Entry Point
- **Endpoint**: `POST /api/query`
- **Authentication**: Session token validation via middleware
- **Request**: `UnifiedQueryRequest` with query text and optional max_results

### 2. ClavrAgent Initialization
- Loads tools (EmailTool, CalendarTool, TaskTool, SummarizeTool)
- Initializes ConversationMemory for context tracking
- Sets up caching layers (IntentPatternsCache, ComplexityAwareCache)
- Configures workflow event emitter for streaming

### 3. Query Routing Decision
- **Intent Cache Check**: Fast lookup for similar queries
- **Complexity Analysis**: Determines if orchestration needed
- **Routing Logic**:
  - Simple queries → Direct tool execution
  - Complex queries → Orchestrator with multi-step planning

### 4. Orchestrator Execution Flow
- **Memory Context Injection**: Retrieves user preferences, recent messages, goals
- **Query Analysis**: AnalyzerRole extracts intent, domains, entities, complexity
- **Plan Generation**: Creates execution plan with dependencies
- **Step Execution**: Executes steps sequentially or in parallel based on dependencies

### 5. Tool Execution
- Each tool uses its domain parser (EmailParser, CalendarParser, TaskParser)
- Parsers extract structured parameters from natural language
- Tools execute via service layer (EmailService, CalendarService, TaskService)
- Service layer handles API calls and error handling

### 6. RAG Integration (for email queries)
- Semantic search via vector embeddings
- Hybrid search (semantic + keyword)
- Result reranking for relevance
- Context enrichment for better responses

### 7. Response Synthesis
- SynthesizerRole combines results from multiple steps
- ResponseFormatter makes output conversational
- ConversationMemory saves interaction for future context

### 8. Streaming Support
- Workflow events show reasoning steps in real-time
- Text chunks stream for natural typing effect
- Final response delivered when complete

