# Roles Architecture

This document describes the architecture of the roles system, which orchestrates specialized components to understand, plan, execute, and synthesize responses to user queries.

## Roles System Overview

```
User Query → Orchestrator
                │
                ├─→ Analyzer Role → Query Analysis (Intent, Domains, Entities)
                ├─→ Memory Role → Context & Learning
                ├─→ Orchestrator Role → Execution Planning
                └─→ Researcher Role → Knowledge Retrieval
                    │
                    ├─→ Execution Plan (Steps + Dependencies)
                    │   │
                    │   └─→ Domain Specialist Roles
                    │       ├─→ Email Specialist → Email Tool
                    │       ├─→ Calendar Specialist → Calendar Tool
                    │       ├─→ Task Specialist → Task Tool
                    │       └─→ Notion Specialist → Notion Tool
                    │
                    ├─→ Researcher Role → RAG Engine (Pinecone) → Knowledge Retrieval
                    └─→ Contact Resolver Role → Knowledge Graph (Neo4j) → Name Resolution
                        │
                        ▼
Execution Results → Synthesizer Role → Response Formatter → Memory Role → Final Response
```

## Role Details

### 1. AnalyzerRole

**Purpose**: Understand query intent and complexity

**Responsibilities**:
- Classify query intent (search, create, update, delete, analyze)
- Detect domains involved (email, calendar, tasks, notion)
- Extract entities (dates, people, keywords)
- Assess complexity (single-step vs multi-step)
- Calculate confidence score

**Capabilities**:
- **NLPProcessor**: Advanced NLP processing
  - Sentiment analysis
  - Entity extraction with confidence scores
  - Keyword extraction
  - Language complexity assessment

**Output**: `QueryAnalysis` object with:
- Intent classification
- Domain detection
- Complexity score
- Extracted entities
- Confidence level
- NLP insights (sentiment, keywords, etc.)

### 2. OrchestratorRole

**Purpose**: Plan and coordinate execution

**Responsibilities**:
- Create execution plans from analysis
- Resolve dependencies between steps
- Identify parallelizable steps
- Estimate execution time
- Optimize plan for performance

**Capabilities**:
- **PredictiveExecutor**: Predictive planning
  - Pattern-based predictions
  - Adaptive optimization
  - Execution time estimation
  - Learning from past executions

**Output**: `ExecutionPlan` with:
- Ordered steps with dependencies
- Parallel execution flags
- Estimated duration
- Optimization suggestions

### 3. Domain Specialist Roles

**Base Class**: `DomainSpecialistRole`

**Specializations**:
- **EmailSpecialistRole**: Email operations
- **CalendarSpecialistRole**: Calendar operations
- **TaskSpecialistRole**: Task operations
- **NotionSpecialistRole**: Notion operations

**Responsibilities**:
- Execute domain-specific operations
- Handle domain-specific errors
- Optimize domain access (caching, batching)
- Use domain parsers for query understanding

**Features**:
- Parser integration (EmailParser, CalendarParser, etc.)
- Result caching
- Domain-specific optimizations
- Error recovery

### 4. ResearcherRole

**Purpose**: Retrieve knowledge from RAG and knowledge graph

**Responsibilities**:
- Semantic search via RAG engine
- Knowledge graph traversal
- Context retrieval for queries
- Entity relationship discovery

**Integration**:
- **RAG Engine (Pinecone)**: Vector search for documents
- **Knowledge Graph (Neo4j)**: Graph traversal for entity relationships
- **Hybrid Search**: Combines vector search (Pinecone) with graph traversal (Neo4j)

**Use Cases**:
- Finding relevant emails/documents
- Discovering entity relationships
- Context enrichment for queries
- Meeting preparation (finding related content)

### 5. ContactResolverRole

**Purpose**: Resolve contact names to canonical identifiers

**Responsibilities**:
- Name-to-email resolution
- Name-to-Slack-ID resolution
- Contact disambiguation
- Graph-based lookup

**Integration**:
- **Knowledge Graph**: Neo4j graph database
- **Cypher Queries**: Graph traversal for contacts
- **Fuzzy Matching**: Handle name variations

**Use Cases**:
- Calendar scheduling ("Schedule with Maniko" → finds email)
- Email composition ("Send to John" → resolves email)
- Task assignment ("Assign to Sarah" → resolves contact)

### 6. SynthesizerRole

**Purpose**: Combine results and format responses

**Responsibilities**:
- Synthesize results from multiple steps
- Format responses conversationally
- Personalize responses based on user profile
- Handle multi-step result aggregation

**Capabilities**:
- **ResponsePersonalizer**: Writing style matching
- Conversational formatting
- Context-aware synthesis
- Error message formatting

**Output**: Natural, conversational response

### 7. MemoryRole

**Purpose**: Learn patterns and optimize execution

**Responsibilities**:
- Store short-term conversation history
- Store long-term user preferences/goals
- Learn execution patterns
- Optimize future queries

**Storage**:
- **Short-term**: Recent messages (session-based)
- **Long-term**: User preferences, goals, patterns
- **Pattern Recognition**: Query pattern learning

**Integration**:
- **Neo4j Graph**: User and session nodes
- **ConversationMemory**: Message history
- **Pattern Recognition**: Execution pattern learning

**Use Cases**:
- Context injection for queries
- Personalization based on history
- Query optimization suggestions
- Pattern-based predictions

## Role Interaction Flow

```
User → Agent → Memory (Get context) → Analyzer (Analyze query) → Orchestrator (Create plan)
    │                                                                    │
    │                                                                    ├─→ Execute email search → RAG (Semantic search) → Results
    │                                                                    │
    │                                                                    └─→ Schedule meeting → Extract details → Create event
    │                                                                        │
    └← Synthesizer (Synthesize results) ← Memory (Save interaction) ←──────┘
```

## Role Capabilities Integration

**Capabilities** are advanced features that enhance roles:

1. **NLPProcessor** (AnalyzerRole):
   - Sentiment analysis
   - Entity extraction
   - Keyword extraction
   - Language complexity

2. **PredictiveExecutor** (OrchestratorRole):
   - Pattern-based predictions
   - Adaptive optimization
   - Execution learning

3. **ResponsePersonalizer** (SynthesizerRole):
   - Writing style matching
   - Tone adaptation
   - Personalization

4. **PatternRecognition** (MemoryRole):
   - Query pattern learning
   - Execution pattern recognition
   - Optimization suggestions

