# Clavr

Clavr is an AI Agent that converts unstructured natural language directly into perfect, traceable, cross-platform action.

## The Solution

**The Core Value:** We are the intelligent layer that sits on top of all your productivity tools (Gmail, Slack, Calendar, Notion, etc) making them reliably autonomous.

**The Promise:** We make "Your Conversations into Actions" a reality.

**The Vision:** We will be the default autonomous operating system for every digital worker, turning the pain of context switching into the power of instant, reliable action.

## Capabilities

### Natural Language to Action

Clavr understands natural language queries and executes actions across your productivity stack:

- **Email Management**: Search, send, reply, organize with semantic search and RAG-powered context
- **Calendar Management**: Schedule meetings, check availability, detect conflicts, manage events
- **Task Management**: Create, track, complete tasks with email and calendar integration
- **Notion Integration**: Search knowledge base, create pages, update databases autonomously
- **Slack Integration**: Execute actions from Slack conversations with contact resolution

### Autonomous Workflows

Multi-step queries execute independently using LangGraph orchestration:

- Decomposes complex queries into executable steps
- Resolves dependencies and executes in parallel when possible
- Maintains conversation memory for context-aware responses
- Confidence-based decision making (high/medium/low autonomy levels)

### AI-Powered Intelligence

- **Semantic Search**: RAG-powered search across emails and attachments using Pinecone vector store
- **Knowledge Graph**: Neo4j-powered entity relationships for spending analysis, vendor insights, receipt trends
- **Auto-Reply Generation**: Personalized responses matching your writing style
- **Document Summarization**: Executive summaries and key data extraction
- **Meeting Preparation**: Pre-meeting briefs, agendas, and preparation tasks
- **Sentiment Analysis**: Email priority scoring and intent detection

## Architecture

```
User Query → ClavrAgent → Intent Analysis → Tool Orchestration
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
            Email Tool      Calendar Tool    Task Tool
                    │               │               │
            Gmail API      Calendar API     Tasks API
                    │               │               │
                    └───────────────┼───────────────┘
                                    │
                    RAG Engine (Pinecone + Neo4j)
                                    │
                            Knowledge Graph
```

## Integrations

- **Gmail**: Email search, composition, organization, push notifications
- **Google Calendar**: Event management, conflict detection, availability checking
- **Google Tasks**: Task creation, tracking, completion
- **Notion**: Knowledge retrieval, database management, autonomous execution
- **Slack**: Conversation-based actions, contact resolution

## Technology Stack

**AI & Orchestration:**
- LangGraph for multi-step workflow orchestration
- LangChain for tool integration
- Google Gemini 2.0 Flash for LLM capabilities
- Sentence Transformers for local embeddings

**Data & Storage:**
- Pinecone (primary) for vector storage and semantic search
- Neo4j for knowledge graph and entity relationships
- PostgreSQL (fallback) for relational data and vector storage
- Redis for caching and session management

**Backend:**
- FastAPI for REST API
- Python 3.13 with async/await
- OAuth 2.0 for Google authentication
- Webhooks for real-time event notifications

## Installation

```bash
pip install -r requirements.txt
```

Create `.env` file:

```bash
# Google OAuth
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret

# AI Provider
GOOGLE_API_KEY=your-gemini-api-key

# Vector Store (Primary)
PINECONE_API_KEY=your-pinecone-api-key
PINECONE_INDEX_NAME=clavr-emails
PINECONE_NAMESPACE=default

# Knowledge Graph
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password

# Database (Fallback)
DATABASE_URL=postgresql://user:password@localhost:5432/clavr

# Application
SECRET_KEY=your-secret-key
ENCRYPTION_KEY=your-encryption-key
```

## Usage

### Start API Server

```bash
python api/main.py
```

Server starts on `http://localhost:8000`

### Natural Language Queries

```bash
# Email search
curl -X POST http://localhost:8000/api/query \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"query": "Find urgent emails from last week"}'

# Multi-step workflow
curl -X POST http://localhost:8000/api/query \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"query": "Find budget emails and schedule a meeting with the team tomorrow"}'

# Calendar management
curl -X POST http://localhost:8000/api/query \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"query": "What conflicts are in my calendar this week?"}'
```

## Development

### Code Quality

```bash
# Check for circular imports
make check-imports

# Run linters
make lint

# Format code
make format
```

### Import Guidelines

Follow the import hierarchy to prevent circular imports:
- `utils/` → No dependencies on other src modules
- `ai/` → Depends on `utils/` only
- `core/` → Depends on `utils/`, `ai/`
- `services/` → Depends on `utils/`, `ai/`, `core/`
- `agent/` → Depends on `utils/`, `ai/`, `core/`, `services/`

See [docs/IMPORT_GUIDELINES.md](docs/IMPORT_GUIDELINES.md) for detailed guidelines.

## Documentation

### User Guides
- [User Query Guide](docs/USER_QUERY_GUIDE.md) - Complete guide with query examples
- [Quick Reference](docs/QUICK_REFERENCE.md) - Quick reference for common queries
- [Autonomous Features](docs/AUTONOMOUS_FEATURES.md) - Multi-step queries and autonomous capabilities

### Technical Documentation
- [API Reference](docs/API.md) - Complete API documentation
- [Architecture](docs/engineering_docs/END_TO_END_QUERY_FLOW.md) - System architecture and design
- [RAG Architecture](docs/engineering_docs/RAG_ARCHITECTURE.md) - Retrieval-Augmented Generation system
- [Parser Architecture](docs/engineering_docs/PARSER_ARCHITECTURE.md) - Query parsing system
- [Roles Architecture](docs/engineering_docs/ROLES_ARCHITECTURE.md) - Agent roles and capabilities

## License

MIT
