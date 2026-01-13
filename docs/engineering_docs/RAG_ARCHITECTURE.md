# RAG Architecture

This document describes the Retrieval-Augmented Generation (RAG) architecture, including document ingestion, vector storage, query processing, and integration with the Knowledge Graph.

## RAG System Overview

### Document Ingestion Pipeline

```
Documents (Emails, Attachments, Receipts)
    │
    ▼
UnifiedParserRAGBridge
    │
    ├─→ EmailParser → EmailChunker (300 words)
    ├─→ ReceiptParser (OCR+LLM)
    └─→ AttachmentParser (Docling)
        │
        └─→ RecursiveTextChunker (Parent-Child)
            │
            ▼
Document Chunks + Metadata
    │
    ▼
Embedding Provider
    ├─→ Gemini Embed (768D, cached)
    └─→ Sentence Transformer (384D, local)
        │
        ▼
Dual Indexing (GraphRAG)
    ├─→ Qdrant (Vector Store: Chunks + Embeddings, includes arango_node_id)
    └─→ ArangoDB (Knowledge Graph: Entities + Relations)
        │
        └─→ Linked via arango_node_id
```

### Query Processing Pipeline

```
User Query
    │
    ├─→ Query Enhancer (LLM Expansion)
    ├─→ Query Embedding
    └─→ Hybrid Search Engine
        │
        ├─→ Vector Similarity → Qdrant (Semantic Search)
        └─→ Keyword Search → ArangoDB (Graph Traversal)
            │
            ▼
Hybrid Results (Combined Vector + Graph)
    │
    ▼
Result Reranker (Multi-Factor)
    ├─→ Semantic Score (40%)
    ├─→ Keyword Score (20%)
    ├─→ Metadata Score (20%)
    └─→ Recency Score (20%)
        │
        ▼
Final Ranked Results → Query Result Cache → Response to User
```

## RAG Component Details

### 1. Document Ingestion Pipeline

**UnifiedParserRAGBridge**:
- Single entry point for all document types
- Type-aware parsing and chunking
- Metadata enrichment
- Relationship preservation

**Parsers**:
- **EmailParser**: Extracts intent, actions, entities from emails
- **ReceiptParser**: OCR + LLM extraction for receipts (vendor, amount, date)
- **AttachmentParser**: Docling-based parsing for PDFs, DOCX, PPTX, images

**Chunkers**:
- **EmailChunker**: Email-specific chunking (300 words max, preserves thread context)
- **RecursiveTextChunker**: Semantic parent-child chunking for documents
  - Parent chunks: High-level context
  - Child chunks: Detailed content
  - Enables hierarchical retrieval

### 2. Embedding Generation

**Embedding Providers**:
- **GeminiEmbeddingProvider**: Google Gemini embeddings (768D, cached)
- **SentenceTransformerEmbeddingProvider**: Local embeddings (384D, faster)

**Features**:
- Batch processing for efficiency
- Caching for repeated documents
- Dimension normalization

### 3. Vector Storage

**Primary Backend**:
- **Qdrant**: High-performance vector database (PRIMARY)
  - Open-source and cloud-native
  - Precise filtering and advanced indexing
  - Sub-15ms query latency
  - Multi-tenancy via collections

**Note**: PostgreSQL with pgvector is available as a fallback option only if Qdrant initialization fails.

**Operations**:
- Document indexing with metadata
- Chunk indexing with parent-child relationships
- Collection management (per-user isolation via namespaces)
- Each chunk includes `arango_node_id` in metadata for linking to Knowledge Graph

### 4. Query Processing

**Query Enhancement**:
- LLM-based query expansion (optional)
- Synonym generation
- Context-aware rewriting

**Hybrid Search**:
- **Semantic Search**: Vector similarity (cosine distance)
- **Keyword Search**: BM25 or full-text search
- **Combined Scoring**: Weighted combination of both

### 5. Result Reranking

**Multi-Factor Reranking**:
- **Semantic Score** (40%): Vector similarity
- **Keyword Score** (20%): Keyword match relevance
- **Metadata Score** (20%): Document type, source, etc.
- **Recency Score** (20%): Document age (newer = better)

**Adaptive Reranking**:
- Weights adjust based on query type
- Recent queries prioritize recency
- Content queries prioritize semantic similarity

### 6. Performance Optimizations

**Caching**:
- Query result cache (TTL-based)
- Embedding cache for repeated queries
- Pattern embedding cache

**Circuit Breaker**:
- Prevents cascading failures
- Automatic recovery after timeout
- Fallback to keyword-only search

**Monitoring**:
- Query latency tracking
- Cache hit rates
- Error rates and types

## RAG Integration with Agent

```
ClavrAgent
    │
    ├─→ Email Tool → semantic_search → RAG Engine → Hybrid Search → Qdrant + ArangoDB → Combined Results → Email Parser → Format Results
    │
    └─→ Researcher Role → Context Retrieval → RAG Engine → Knowledge Graph Query → Qdrant + ArangoDB → Combined Results → Researcher (with context)
                                                                                                                              │
                                                                                                                              └─→ ClavrAgent
```

**Integration Points**:
1. **EmailTool**: Uses RAG for semantic email search
2. **ResearcherRole**: Retrieves context from knowledge base
3. **Parsers**: Use RAG for context-aware parsing
4. **Orchestrator**: Enriches queries with RAG context

## Knowledge Graph Integration (ArangoDB)

**Important**: ArangoDB is used for the **Knowledge Graph** (entity relationships), NOT for vector storage. The Knowledge Graph works alongside RAG:

- **RAG (Qdrant)**: Stores document chunks with embeddings for semantic search
- **Knowledge Graph (ArangoDB)**: Stores structured entities and relationships (people, vendors, receipts, emails, etc.)

**GraphRAG Architecture**:
- Documents are indexed in both systems:
  1. **Qdrant**: Chunks stored with embeddings (includes `arango_node_id` in metadata)
  2. **ArangoDB**: Entities and relationships stored as graph nodes and edges
- Queries combine both:
  1. Vector search in Qdrant finds relevant document chunks
  2. Graph traversal in ArangoDB finds related entities and relationships
  3. Results are merged for comprehensive answers

**Example**: "Find all receipts from Amazon"
- Qdrant: Semantic search finds emails/documents mentioning "Amazon" and "receipt"
- ArangoDB: Graph traversal finds all VENDOR nodes connected to RECEIPT nodes
- Combined: Complete picture of spending patterns and vendor relationships

