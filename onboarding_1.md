# Clavr: Extensive Architecture & Features Guide

This guide provides an in-depth technical analysis of Clavr's "Brain," "Muscle," and "Memory." It is designed for engineers who need to understand the full lifecycle of a user request and the autonomous systems that power Clavr.

---

## 1. High-Level Core Architecture

Clavr follows a **Multi-Agent Orchestration** framework. Instead of a monolithic LLM, we use a specialized fleet of agents managed by a **Supervisor**.

### The Lifecycle of a Query
1.  **Entry Point**: `ChatService.execute_unified_query()` is called by the API.
2.  **Intent Detection**: Before routing, we use lightweight keyword matching and LLM analysis to determine if the query is a "Search" (RAG), an "Action" (Tool), or "Research."
3.  **Planning**: `SupervisorAgent._plan_execution()` uses a fast model (Gemini Flash) to decompose the query into a sequence of `SupervisorPlanStep`.
4.  **Orchestration**: We use **LangGraph** to manage the execution state. The state is tracked in `AgentState` (defined in `src/agents/state.py`).
5.  **Execution**: Specialized worker agents (or the Supervisor itself) execute the plan steps using individual **Tools**.
6.  **Synthesis**: The final response is passed through a "Conversational Enhancer" to ensure it sounds human and context-aware.

---

## 2. The Core Agents

### A. Supervisor Agent (`src/agents/supervisor.py`)
The **Supervisor** is the central nervous system.
-   **Routing Logic**: It maps user intent to domain agents (e.g., "email", "calendar", "tasks").
-   **Stateful Planning**: Unlike 0-shot prompts, it looks at the `Interaction History` to resolve pronouns (e.g., "What did *he* say?" -> resolves "he" to the person from the previous email).
-   **Security Loop**: It passes all inputs/outputs through the **COR (Chain of Responsibility)** layer for sanitization and policy enforcement.

### B. ClavrAgent (`src/agents/base.py`)
The **BaseAgent** provides the shared capabilities for all workers:
-   **Parameter Extraction**: Uses the LLM to turn "Send a meeting invite to Bob for 3pm tomorrow" into a structured JSON `ToolInput`.
-   **Robust JSON Repair**: LLMs often output malformed JSON; the agent has a built-in `_repair_json` system.
-   **Safe Execution**: Every tool call is wrapped in a "Guardrail" that emits events (workflow updates) while catching/logging errors.

### C. Research Agent (`src/agents/research/agent.py`)
A specialized agent for "Deep Research."
-   **Technology**: Uses Google's `deep-research-pro-preview` models.
-   **Workflow**: It performs recursive searches, synthesizes documents, and generates multi-page reports.
-   **Background Processing**: Research can take minutes; the agent handles backgrounding and progress emission.

---

## 3. The Memory System ("The Brain")

Clavr doesn't just "remember" text; it builds a **Semantic Model** of your life.

### Enhanced Semantic Memory (`src/ai/memory/enhanced_semantic_memory.py`)
-   **Fact Lifecycle**:
    1.  **Observation**: `ChatService._observe_message_for_learning` listens to user messages.
    2.  **Extraction**: An LLM extracts atomic "Facts."
    3.  **Contradiction Check**: If a new fact contradicts an old one, the system creates a `ClarificationQuestion` instead of overwriting.
    4.  **Provenance**: Every fact tracks its *Source* (e.g., "Source: Gmail thread [ID]") and *Confidence Score*.
-   **Context Injection**: The `get_context_bundle()` function pulls relevant facts *before* a tool is executed, giving agents "Human-like" awareness.

### Graph Observer & Watchdog (`src/ai/memory/observer.py`)
The **Observer** is a background process that looks for connections the user didn't explicitly ask for.
-   **Opportunity Detection**: "You have an unread email about a Project that matches a Task in Notion. Shall I link them?"
-   **Anomalies**: Detects unusual activity (e.g., late-night meetings) and flags them for review.

---

## 4. Key Features

### Bi-Directional Voice Mode (`src/services/voice_service.py`)
-   **Low-Latency Streaming**: Uses WebSockets to stream audio directly to/from **Gemini Live** (`src/ai/voice/gemini_live_client.py`).
-   **Tool Grounding**: The voice agent uses real-time tool calls. We use a strict "System Instruction" that forbids the agent from "pretending" to take an action—it must wait for the backend to return a `tool_result`.

### Multi-Source Briefing (`src/services/dashboard/brief_service.py`)
The "Daily Brief" isn't a simple list:
-   **Synthesis**: It aggregates data from **Gmail**, **Google Tasks**, **Notion**, **Calendar**, and **ActionableItems**.
-   **Intelligent Greeting**: Uses an LLM to write a summary like: "Good morning! You have 3 meetings today, including a crucial pitch at 2 PM. I found 2 related emails from the CEO you might want to see first."

### Unified Indexer (`src/services/indexing/unified_indexer.py`)
The ingestion engine.
-   **Managed Lifecycle**: Scales ingestion from multiple apps (Gmail, Slack, Notion) into a single unified stream.
-   **Consolidation**: Runs daily loops to "clean up" the memory, merges duplicate entities, and strengthens relationship links between people.

---

## 5. Summary of Key Files for Onboarding

| Concept | Primary Source File | What to look for |
| :--- | :--- | :--- |
| **Orchestration** | `src/agents/supervisor.py` | `_plan_execution` |
| **Agent State** | `src/agents/state.py` | `AgentState` TypedDict |
| **Memory** | `src/ai/memory/enhanced_semantic_memory.py` | `learn_fact_enhanced` | Qdrant + ArangoDB |
| **Voice** | `src/ai/voice/gemini_live_client.py` | `stream_audio` |
| **Dashboard** | `src/services/dashboard/brief_service.py` | `get_dashboard_briefs` |
| **Indexing** | `src/services/indexing/unified_indexer.py` | `start_unified_indexing` |

---

Welcome to the deep end! Clavr is a complex system, but every module is built on the core principle of **Grounding AI in Real-World Context.**
