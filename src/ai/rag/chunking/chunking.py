"""
Structure-Aware Recursive Text Chunking

Implements the gold standard for RAG chunking:
1. Recursive splitting with hierarchical separators (paragraphs → sentences → words)
2. Parent-child chunk relationships for optimal retrieval
3. Token-based sizing for accuracy
4. Respects document structure

Based on best practices:
- 512 tokens per chunk (parent)
- 128-256 tokens per child chunk
- 10-20% overlap (50-100 tokens)
"""
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import hashlib
from ....utils.logger import setup_logger

logger = setup_logger(__name__)

# Try to import tiktoken for accurate token counting
try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False
    logger.warning(
        "tiktoken not installed. Using word-based approximation. "
        "Install with: pip install tiktoken"
    )


@dataclass
class ChunkMetadata:
    """Metadata for a text chunk"""
    chunk_id: str
    parent_id: Optional[str]
    child_ids: List[str]
    token_count: int
    char_start: int
    char_end: int
    separator_used: str
    depth: int


@dataclass
class Chunk:
    """A text chunk with metadata"""
    text: str
    metadata: ChunkMetadata
    
    def __str__(self) -> str:
        return f"Chunk({self.metadata.chunk_id}, {self.metadata.token_count} tokens)"


class RecursiveTextChunker:
    """
    Structure-aware recursive text chunker following RAG best practices.
    
    Features:
    - Recursive splitting with hierarchical separators
    - Parent-child chunk relationships
    - Token-based sizing (not word-based)
    - Intelligent overlap at separator boundaries
    - Document structure preservation
    
    Recommended Settings:
    - Parent chunks: 512 tokens (for LLM context)
    - Child chunks: 128-256 tokens (for precise retrieval)
    - Overlap: 10-20% (50-100 tokens)
    
    Usage:
        chunker = RecursiveTextChunker(
            chunk_size=512,
            child_chunk_size=256,
            overlap_tokens=100
        )
        
        # Get parent chunks for indexing
        parent_chunks = chunker.chunk(text)
        
        # Get child chunks for precise retrieval
        child_chunks = chunker.get_child_chunks(text)
        
        # Get both with relationships
        result = chunker.chunk_with_children(text)
    """
    
    # Hierarchical separators (priority order)
    SEPARATORS = [
        "\n\n\n",    # Section breaks (3+ newlines)
        "\n\n",      # Paragraph breaks
        "\n",        # Line breaks
        ". ",        # Sentences
        "! ",        # Exclamations
        "? ",        # Questions
        "; ",        # Semicolons
        ", ",        # Commas
        " ",         # Words
        ""           # Characters (last resort)
    ]
    
    def __init__(
        self,
        chunk_size: int = 512,           # Parent chunk size in tokens
        child_chunk_size: int = 256,     # Child chunk size in tokens
        overlap_tokens: int = 100,       # Overlap size in tokens (20% of chunk_size)
        min_chunk_size: int = 50,        # Minimum chunk size to avoid tiny chunks
        model_name: Optional[str] = None,  # Model for token counting (uses config default if None)
        use_parent_child: bool = True,   # Enable parent-child architecture
        use_cache: bool = True           # Cache token counts
    ):
        """
        Initialize recursive chunker.
        
        Args:
            chunk_size: Target parent chunk size in tokens (default: 512)
            child_chunk_size: Target child chunk size in tokens (default: 256)
            overlap_tokens: Overlap between chunks in tokens (default: 100)
            min_chunk_size: Minimum chunk size to avoid tiny chunks (default: 50)
            model_name: Model name for tiktoken encoding (uses DEFAULT_MODEL_NAME if None)
            use_parent_child: Enable parent-child chunk relationships
            use_cache: Cache token counts for performance
        """
        from src.ai.llm_constants import DEFAULT_MODEL_NAME
        
        self.chunk_size = chunk_size
        self.child_chunk_size = child_chunk_size
        self.overlap_tokens = overlap_tokens
        self.min_chunk_size = min_chunk_size
        self.use_parent_child = use_parent_child
        self.use_cache = use_cache
        
        # Use model from config or default
        model = model_name or DEFAULT_MODEL_NAME
        
        # Initialize tokenizer
        if HAS_TIKTOKEN:
            try:
                self.tokenizer = tiktoken.encoding_for_model(model)
                self.token_counter = self._count_tokens_tiktoken
                logger.info(f"Using tiktoken with {model} encoding")
            except Exception as e:
                logger.warning(f"Failed to load tiktoken for {model_name}: {e}. Using approximation.")
                self.tokenizer = None
                self.token_counter = self._count_tokens_approximation
        else:
            self.tokenizer = None
            self.token_counter = self._count_tokens_approximation
        
        # Token count cache
        self._token_cache: Dict[str, int] = {} if use_cache else None
        
        # Validate parameters
        if overlap_tokens >= chunk_size:
            raise ValueError(f"overlap_tokens ({overlap_tokens}) must be less than chunk_size ({chunk_size})")
        
        if child_chunk_size >= chunk_size:
            logger.warning(
                f"child_chunk_size ({child_chunk_size}) should be smaller than "
                f"chunk_size ({chunk_size}) for optimal retrieval"
            )
    
    def _count_tokens_tiktoken(self, text: str) -> int:
        """Count tokens using tiktoken (accurate)"""
        if self.use_cache and self._token_cache is not None:
            cache_key = hashlib.md5(text.encode()).hexdigest()
            if cache_key in self._token_cache:
                return self._token_cache[cache_key]
        
        token_count = len(self.tokenizer.encode(text))
        
        if self.use_cache and self._token_cache is not None:
            cache_key = hashlib.md5(text.encode()).hexdigest()
            self._token_cache[cache_key] = token_count
            
            # Limit cache size
            if len(self._token_cache) > 10000:
                # Remove oldest 1000 entries
                keys_to_remove = list(self._token_cache.keys())[:1000]
                for key in keys_to_remove:
                    del self._token_cache[key]
        
        return token_count
    
    def _count_tokens_approximation(self, text: str) -> int:
        """
        Approximate token count (when tiktoken unavailable).
        Rule of thumb: 1 token ≈ 0.75 words or 4 characters
        """
        # Use character-based approximation (more accurate than word-based)
        return len(text) // 4
    
    def _generate_chunk_id(self, text: str, index: int, depth: int) -> str:
        """Generate unique chunk ID"""
        text_hash = hashlib.md5(text[:100].encode()).hexdigest()[:8]
        return f"chunk_{depth}_{index}_{text_hash}"
    
    def chunk(self, text: str) -> List[Chunk]:
        """
        Split text into parent chunks using recursive splitting.
        
        Args:
            text: Text to chunk
            
        Returns:
            List of parent chunks
        """
        if not text or not text.strip():
            return []
        
        chunks = self._recursive_split(
            text=text,
            target_size=self.chunk_size,
            separators=self.SEPARATORS,
            depth=0
        )
        
        return chunks
    
    def get_child_chunks(self, text: str) -> List[Chunk]:
        """
        Get child chunks for precise retrieval.
        
        Args:
            text: Text to chunk
            
        Returns:
            List of child chunks (smaller, more granular)
        """
        if not text or not text.strip():
            return []
        
        chunks = self._recursive_split(
            text=text,
            target_size=self.child_chunk_size,
            separators=self.SEPARATORS,
            depth=0,
            is_child=True
        )
        
        return chunks
    
    def chunk_with_children(self, text: str) -> Dict[str, Any]:
        """
        Create parent and child chunks with relationships.
        
        This implements the "Parent Document Retrieval (Small-to-Big)" strategy:
        - Child chunks: Small, precise (for retrieval accuracy)
        - Parent chunks: Large, contextual (for LLM generation)
        - Linked: Each child knows its parent
        
        Args:
            text: Text to chunk
            
        Returns:
            Dictionary with:
            - parent_chunks: List of parent chunks
            - child_chunks: List of child chunks
            - relationships: Mapping of child_id -> parent_id
        """
        if not self.use_parent_child:
            parent_chunks = self.chunk(text)
            return {
                "parent_chunks": parent_chunks,
                "child_chunks": [],
                "relationships": {}
            }
        
        # Create parent chunks
        parent_chunks = self.chunk(text)
        
        # Create child chunks from each parent
        all_child_chunks = []
        relationships = {}
        
        for parent in parent_chunks:
            # Split parent into children
            child_chunks = self._recursive_split(
                text=parent.text,
                target_size=self.child_chunk_size,
                separators=self.SEPARATORS,
                depth=parent.metadata.depth + 1,
                parent_id=parent.metadata.chunk_id,
                is_child=True
            )
            
            # Update parent with child IDs
            parent.metadata.child_ids = [c.metadata.chunk_id for c in child_chunks]
            
            # Track relationships
            for child in child_chunks:
                relationships[child.metadata.chunk_id] = parent.metadata.chunk_id
            
            all_child_chunks.extend(child_chunks)
        
        logger.info(
            f"Created {len(parent_chunks)} parent chunks and "
            f"{len(all_child_chunks)} child chunks"
        )
        
        return {
            "parent_chunks": parent_chunks,
            "child_chunks": all_child_chunks,
            "relationships": relationships
        }
    
    def _recursive_split(
        self,
        text: str,
        target_size: int,
        separators: List[str],
        depth: int,
        parent_id: Optional[str] = None,
        is_child: bool = False,
        char_offset: int = 0
    ) -> List[Chunk]:
        """
        Recursively split text using hierarchical separators.
        
        Algorithm:
        1. Count tokens in text
        2. If within target size, return as single chunk
        3. Otherwise, try splitting with current separator
        4. If chunks still too large, recursively split with next separator
        5. Add overlap between chunks
        6. Merge small chunks
        
        Args:
            text: Text to split
            target_size: Target chunk size in tokens
            separators: List of separators to try (in priority order)
            depth: Current recursion depth
            parent_id: Parent chunk ID (for child chunks)
            is_child: Whether creating child chunks
            char_offset: Character offset in original document
            
        Returns:
            List of chunks
        """
        if not text or not text.strip():
            return []
        
        # Count tokens
        token_count = self.token_counter(text)
        
        # Base case: text fits in target size
        if token_count <= target_size:
            chunk_id = self._generate_chunk_id(text, 0, depth)
            metadata = ChunkMetadata(
                chunk_id=chunk_id,
                parent_id=parent_id,
                child_ids=[],
                token_count=token_count,
                char_start=char_offset,
                char_end=char_offset + len(text),
                separator_used="none",
                depth=depth
            )
            return [Chunk(text=text.strip(), metadata=metadata)]
        
        # Recursive case: split text
        if not separators:
            # No more separators, force split by characters
            return self._force_split(text, target_size, depth, parent_id, char_offset)
        
        # Try current separator
        separator = separators[0]
        remaining_separators = separators[1:]
        
        # Split by separator
        if separator:
            splits = text.split(separator)
        else:
            # Empty separator means split by characters
            splits = list(text)
        
        # Recombine splits into chunks
        chunks = []
        current_chunk = []
        current_tokens = 0
        chunk_index = 0
        current_char_offset = char_offset
        
        for i, split in enumerate(splits):
            if not split:
                continue
            
            # Add separator back (except for last split)
            if separator and i < len(splits) - 1:
                split_with_sep = split + separator
            else:
                split_with_sep = split
            
            split_tokens = self.token_counter(split_with_sep)
            
            # Check if adding this split would exceed target
            if current_tokens + split_tokens > target_size and current_chunk:
                # Finalize current chunk
                chunk_text = "".join(current_chunk)
                
                # If chunk is still too large, recursively split
                if self.token_counter(chunk_text) > target_size and remaining_separators:
                    sub_chunks = self._recursive_split(
                        text=chunk_text,
                        target_size=target_size,
                        separators=remaining_separators,
                        depth=depth + 1,
                        parent_id=parent_id,
                        is_child=is_child,
                        char_offset=current_char_offset
                    )
                    chunks.extend(sub_chunks)
                else:
                    # Create chunk
                    chunk_id = self._generate_chunk_id(chunk_text, chunk_index, depth)
                    metadata = ChunkMetadata(
                        chunk_id=chunk_id,
                        parent_id=parent_id,
                        child_ids=[],
                        token_count=self.token_counter(chunk_text),
                        char_start=current_char_offset,
                        char_end=current_char_offset + len(chunk_text),
                        separator_used=separator or "char",
                        depth=depth
                    )
                    chunk_text_stripped = chunk_text.strip()
                    # Only add non-empty chunks
                    if chunk_text_stripped:
                        chunks.append(Chunk(text=chunk_text_stripped, metadata=metadata))
                
                # Start new chunk with overlap
                if self.overlap_tokens > 0 and chunks:
                    overlap_text = self._get_overlap(chunk_text, separator)
                    current_chunk = [overlap_text, split_with_sep]
                    current_tokens = self.token_counter(overlap_text) + split_tokens
                else:
                    current_chunk = [split_with_sep]
                    current_tokens = split_tokens
                
                chunk_index += 1
                current_char_offset += len(chunk_text) - len(overlap_text) if self.overlap_tokens > 0 else len(chunk_text)
            else:
                # Add to current chunk
                current_chunk.append(split_with_sep)
                current_tokens += split_tokens
        
        # Add final chunk
        if current_chunk:
            chunk_text = "".join(current_chunk)
            
            # If chunk is still too large, recursively split
            if self.token_counter(chunk_text) > target_size and remaining_separators:
                sub_chunks = self._recursive_split(
                    text=chunk_text,
                    target_size=target_size,
                    separators=remaining_separators,
                    depth=depth + 1,
                    parent_id=parent_id,
                    is_child=is_child,
                    char_offset=current_char_offset
                )
                chunks.extend(sub_chunks)
            else:
                chunk_id = self._generate_chunk_id(chunk_text, chunk_index, depth)
                metadata = ChunkMetadata(
                    chunk_id=chunk_id,
                    parent_id=parent_id,
                    child_ids=[],
                    token_count=self.token_counter(chunk_text),
                    char_start=current_char_offset,
                    char_end=current_char_offset + len(chunk_text),
                    separator_used=separator or "char",
                    depth=depth
                )
                chunk_text_stripped = chunk_text.strip()
                # Only add non-empty chunks
                if chunk_text_stripped:
                    chunks.append(Chunk(text=chunk_text_stripped, metadata=metadata))
        
        # Merge small chunks
        chunks = self._merge_small_chunks(chunks, target_size)
        
        # Final filter: remove any empty chunks that might have been created during merging
        chunks = [chunk for chunk in chunks if chunk.text and chunk.text.strip()]
        
        return chunks
    
    def _get_overlap(self, text: str, separator: str) -> str:
        """
        Get overlap text from end of chunk.
        
        Extracts whole units (paragraphs, sentences) for better context.
        """
        if not separator or separator == " ":
            # For word-level, take last N tokens worth of words
            words = text.split()
            overlap_word_count = min(
                len(words),
                max(1, self.overlap_tokens // 4)  # Approximate 4 chars per token
            )
            return " ".join(words[-overlap_word_count:])
        
        # For structural separators, take whole units
        parts = text.split(separator)
        overlap_parts = []
        overlap_tokens = 0
        
        for part in reversed(parts):
            if not part.strip():
                continue
            
            part_tokens = self.token_counter(part)
            if overlap_tokens + part_tokens <= self.overlap_tokens:
                overlap_parts.insert(0, part)
                overlap_tokens += part_tokens
            else:
                break
        
        return separator.join(overlap_parts) + separator if overlap_parts else ""
    
    def _force_split(
        self,
        text: str,
        target_size: int,
        depth: int,
        parent_id: Optional[str],
        char_offset: int
    ) -> List[Chunk]:
        """
        Force split text when no separators work (last resort).
        Splits by character count to ensure chunks fit.
        """
        chunks = []
        char_per_token = 4  # Approximation
        target_chars = target_size * char_per_token
        overlap_chars = self.overlap_tokens * char_per_token
        
        start = 0
        chunk_index = 0
        
        while start < len(text):
            end = min(start + target_chars, len(text))
            chunk_text = text[start:end]
            
            chunk_id = self._generate_chunk_id(chunk_text, chunk_index, depth)
            metadata = ChunkMetadata(
                chunk_id=chunk_id,
                parent_id=parent_id,
                child_ids=[],
                token_count=self.token_counter(chunk_text),
                char_start=char_offset + start,
                char_end=char_offset + end,
                separator_used="force",
                depth=depth
            )
            chunks.append(Chunk(text=chunk_text.strip(), metadata=metadata))
            
            start = end - overlap_chars
            chunk_index += 1
        
        return chunks
    
    def _merge_small_chunks(self, chunks: List[Chunk], target_size: int) -> List[Chunk]:
        """
        Merge chunks that are too small to avoid fragmentation.
        """
        if len(chunks) <= 1:
            return chunks
        
        merged = []
        current_merge = []
        current_tokens = 0
        
        for chunk in chunks:
            chunk_tokens = chunk.metadata.token_count
            
            # If chunk is too small, try to merge
            if chunk_tokens < self.min_chunk_size:
                current_merge.append(chunk)
                current_tokens += chunk_tokens
            else:
                # Finalize previous merge if exists
                if current_merge:
                    if current_tokens + chunk_tokens <= target_size:
                        # Merge with current chunk
                        current_merge.append(chunk)
                        merged_text = " ".join(c.text for c in current_merge).strip()
                        # Only create merged chunk if it has content
                        if merged_text:
                            merged_chunk = Chunk(
                                text=merged_text,
                                metadata=ChunkMetadata(
                                    chunk_id=self._generate_chunk_id(merged_text, len(merged), 0),
                                    parent_id=current_merge[0].metadata.parent_id,
                                    child_ids=[],
                                    token_count=self.token_counter(merged_text),
                                    char_start=current_merge[0].metadata.char_start,
                                    char_end=current_merge[-1].metadata.char_end,
                                    separator_used="merged",
                                    depth=current_merge[0].metadata.depth
                                )
                            )
                            merged.append(merged_chunk)
                        # If merged text is empty, skip this merge
                    else:
                        # Create separate merged chunk
                        merged_text = " ".join(c.text for c in current_merge).strip()
                        # Only create merged chunk if it has content
                        if merged_text:
                            merged_chunk = Chunk(
                                text=merged_text,
                                metadata=ChunkMetadata(
                                    chunk_id=self._generate_chunk_id(merged_text, len(merged), 0),
                                    parent_id=current_merge[0].metadata.parent_id,
                                    child_ids=[],
                                    token_count=self.token_counter(merged_text),
                                    char_start=current_merge[0].metadata.char_start,
                                    char_end=current_merge[-1].metadata.char_end,
                                    separator_used="merged",
                                    depth=current_merge[0].metadata.depth
                                )
                            )
                            merged.append(merged_chunk)
                        # If merged text is empty, skip this merge
                        merged.append(chunk)
                    
                    current_merge = []
                    current_tokens = 0
                else:
                    # Add chunk as-is
                    merged.append(chunk)
        
        # Add final merge
        if current_merge:
            merged_text = " ".join(c.text for c in current_merge).strip()
            # Only create merged chunk if it has content
            if merged_text:
                merged_chunk = Chunk(
                    text=merged_text,
                    metadata=ChunkMetadata(
                        chunk_id=self._generate_chunk_id(merged_text, len(merged), 0),
                        parent_id=current_merge[0].metadata.parent_id,
                        child_ids=[],
                        token_count=self.token_counter(merged_text),
                        char_start=current_merge[0].metadata.char_start,
                        char_end=current_merge[-1].metadata.char_end,
                        separator_used="merged",
                        depth=current_merge[0].metadata.depth
                    )
                )
                merged.append(merged_chunk)
        
        return merged if merged else chunks
    
    def clear_cache(self) -> None:
        """Clear token count cache"""
        if self._token_cache is not None:
            self._token_cache.clear()
            logger.info("Token cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get chunker statistics"""
        return {
            "chunk_size": self.chunk_size,
            "child_chunk_size": self.child_chunk_size,
            "overlap_tokens": self.overlap_tokens,
            "min_chunk_size": self.min_chunk_size,
            "use_parent_child": self.use_parent_child,
            "has_tiktoken": HAS_TIKTOKEN,
            "cache_size": len(self._token_cache) if self._token_cache else 0
        }
