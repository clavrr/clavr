# Clavr: Features & Agents Deep Dive

This document provides a technical walkthrough of Clavr's core agents and most critical features. It is intended for engineers who want to understand the "Why" and "How" behind the system's intelligence.

---

## 1. The Agent Architecture

Clavr is built on a **Supervisor-Worker** pattern. Instead of one giant prompt, we use specialized agents that coordinate to solve complex problems.

### A. The Supervisor Agent (`src/agents/supervisor.py`)
The **Supervisor** is the high-level manager. Its responsibilities include:
- **Decomposition**: Breaking a user query (e.g., "Plan my trip to NYC based on my emails and invite my team") into discrete steps.
- **Routing**: Deciding which specialized agents or tools are needed for each step.
- **Verification**: Reviewing the output of tools to ensure they meet the user's intent.
- **State Management**: Maintaining the conversation "scratchpad" using `src/agents/state.py`.

### B. Specialized Agents
- **Research Agent (`src/agents/research/`)**: Focused on deep-diving into documents and web data. It uses RAG to prioritize accuracy over speed.
- **ClavrAgent (`src/agents/base.py`)**: The standard interface for tool execution. It handles "low-level" autonomy like parameter extraction and safe execution.

---

## 2. Core Features (The "Power" Tools)

While we have many integrations, these four represent the core value of Clavr:

### A. Intelligence-Led Email (`src/tools/email/`)
- **Beyond Send/Receive**: Our email tool uses semantic search (via Qdrant) to find relevant history.
- **Automated Templates**: It can draft replies based on previous writing styles.
- **Entity Extraction**: Automatically identifies dates, participants, and action items from threads.

### B. Semantic Memory & Knowledge Graph (`src/ai/memory/`)
This is Clavr's "Long-Term Memory." 
- **Fact Extraction**: Every conversation is processed to extract "Facts" (e.g., "The user prefers meeting in the afternoon").
- **Graph Linkage**: Facts are linked in a Knowledge Graph (ArangoDB) to track relationships between people, projects, and entities.
- **Context Injection**: Before an agent starts a task, relevant "Memory" is injected into the prompt so it doesn't have to ask "Who is Anthony?" twice.

### C. The Daily Briefing (`src/tools/brief/`)
The Briefing tool is a high-level synthesizer.
- **Multi-Source Aggregation**: It pulls from Calendar, Tasks, Gmail, and Slack.
- **Conflict Detection**: It proactively flags when two meetings overlap or when a task is due but no time is blocked.
- **Actionable Summary**: It doesn't just list events; it suggests actions (e.g., "You have a meeting with X, here are the 3 latest emails from them").

### D. Voice Mode (`src/ai/voice/`)
Our voice system is designed for "Human-Parity" latency.
- **Gemini Live Integrated**: Uses the latest multi-modal models for fast, interruptible speech.
- **Tool Grounding**: Unlike pure voice bots, Clavr Grounding ensures the voice agent can't "hallucinate" sending an email; it must get tool confirmation.

---

## 3. How Agents Use Tools

Every tool in Clavr inherits from `BaseTool`. This creates a predictable interface:
1. **Schema Definition**: Every tool defines a Pydantic `Input` class. The LLM uses this to know exactly what parameters to fill.
2. **Pre-flight Validation**: Before running, the `PreflightValidator` checks if the user has the necessary OAuth tokens connected.
3. **Execution**: Most tools have both `_run` (sync) and `_arun` (async) implementations.
4. **Event Emission**: Tools emit "Workflow Events" so the frontend can show a "Sending email..." spinner or progress bar.

---

## 4. Summary Table

| Feature / Agent | Primary File(s) | Role | Key Technology |
| :--- | :--- | :--- | :--- |
| **Supervisor** | `src/agents/supervisor.py` | Orchestration & Planning | LangGraph |
| **Email Tool** | `src/tools/email/tool.py` | Gmail Management | Google API + RAG |
| **Semantic Memory** | `src/ai/memory/enhanced_semantic_memory.py` | Long-term context | Qdrant + ArangoDB |
| **Voice Client** | `src/ai/voice/gemini_live_client.py` | Real-time interaction | WebSockets + Gemini |
| **Daily Brief** | `src/services/dashboard/brief_service.py` | Multi-app synthesis | Proprietary Logic |

---

> [!NOTE]
> When adding a new feature, always consider if it should be a **Tool** (stateless action) or an **Agent** (stateful decision maker). Most new integrations should start as Tools.
