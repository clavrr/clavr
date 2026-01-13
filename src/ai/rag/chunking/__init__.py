"""
RAG Chunking Strategies

Chunking implementations for different content types:
- RecursiveTextChunker: General text chunking
- EmailChunker: Email-specific chunking
- ContextualChunker: Metadata-enriched chunks for better embeddings
"""

from .chunking import RecursiveTextChunker, Chunk, ChunkMetadata
from .email_chunker import EmailChunker
from .contextual_chunker import (
    ContextualChunker,
    ContextualChunkConfig,
    EmailContextualChunker,
    DocumentContextualChunker,
    create_contextual_chunker
)

__all__ = [
    "RecursiveTextChunker",
    "Chunk",
    "ChunkMetadata",
    "EmailChunker",
    "ContextualChunker",
    "ContextualChunkConfig",
    "EmailContextualChunker",
    "DocumentContextualChunker",
    "create_contextual_chunker",
]



