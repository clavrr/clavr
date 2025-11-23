"""
RAG Chunking Strategies

Chunking implementations for different content types:
- RecursiveTextChunker: General text chunking
- EmailChunker: Email-specific chunking
"""

from .chunking import RecursiveTextChunker, Chunk, ChunkMetadata
from .email_chunker import EmailChunker

__all__ = [
    "RecursiveTextChunker",
    "Chunk",
    "ChunkMetadata",
    "EmailChunker",
]


