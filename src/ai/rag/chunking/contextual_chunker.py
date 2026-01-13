"""
Contextual Chunking - Enriched Chunk Headers for Better Embeddings

Prepends relevant metadata as context headers to chunks before embedding.
This helps embeddings capture entity and temporal information that would
otherwise be lost in the chunking process.

Expected impact: +10% on entity-specific queries

Example:
    Original chunk: "discussed the quarterly results with the team"
    
    Contextual chunk: "[From: john@example.com | Subject: Q4 Review | Date: 2024-12-15]
    discussed the quarterly results with the team"
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class ContextualChunkConfig:
    """Configuration for contextual chunking."""
    include_sender: bool = True
    include_subject: bool = True
    include_date: bool = True
    include_recipients: bool = False  # Can be verbose
    include_source: bool = True
    include_document_summary: bool = True  # New: Prepend global document summary
    max_header_length: int = 300  # Increased for summary
    max_summary_length: int = 150
    date_format: str = "%Y-%m-%d"


class ContextualChunker:
    """
    Creates contextual chunks with metadata headers.
    
    By prepending metadata as natural language headers, the embedding
    model can capture:
    - Who sent/created the content
    - When it was created
    - What it's about (subject/title)
    - Source application
    
    This significantly improves retrieval for queries like:
    - "emails from Carol about the budget"
    - "meeting notes from last week"
    - "documents shared by the marketing team"
    
    Usage:
        chunker = ContextualChunker()
        contextual_text = chunker.create_contextual_chunk(
            text="discussed quarterly results",
            metadata={'sender': 'john@example.com', 'subject': 'Q4 Review'}
        )
        # Returns: "[From: john@example.com | Subject: Q4 Review]\ndiscussed..."
    """
    
    def __init__(self, config: Optional[ContextualChunkConfig] = None):
        """
        Initialize contextual chunker.
        
        Args:
            config: Optional configuration
        """
        self.config = config or ContextualChunkConfig()
        logger.info("ContextualChunker initialized")
    
    def create_contextual_chunk(
        self,
        text: str,
        metadata: Dict[str, Any]
    ) -> str:
        """
        Create a chunk with contextual header.
        
        Args:
            text: Original chunk text
            metadata: Document/chunk metadata
            
        Returns:
            Text with prepended context header
        """
        header = self._build_header(metadata)
        
        if header:
            return f"{header}\n{text}"
        else:
            return text
    
    def _build_header(self, metadata: Dict[str, Any]) -> str:
        """Build the context header from metadata."""
        parts = []
        
        # Sender/Author
        if self.config.include_sender:
            sender = self._extract_sender(metadata)
            if sender:
                parts.append(f"From: {sender}")
        
        # Subject/Title
        if self.config.include_subject:
            subject = self._extract_subject(metadata)
            if subject:
                parts.append(f"Subject: {subject}")
        
        # Date
        if self.config.include_date:
            date_str = self._extract_date(metadata)
            if date_str:
                parts.append(f"Date: {date_str}")
        
        # Recipients (optional)
        if self.config.include_recipients:
            recipients = self._extract_recipients(metadata)
            if recipients:
                parts.append(f"To: {recipients}")
        
        # Source
        if self.config.include_source:
            source = metadata.get('source') or metadata.get('source_type')
            if source:
                parts.append(f"Source: {source}")
        
        # Document Summary (Global Context)
        if self.config.include_document_summary:
            summary = metadata.get('document_summary') or metadata.get('summary')
            if summary:
                # Truncate summary if too long
                trunc_summary = summary[:self.config.max_summary_length]
                if len(summary) > self.config.max_summary_length:
                    trunc_summary += "..."
                parts.append(f"Doc Context: {trunc_summary}")
        
        if not parts:
            return ""
        
        # Join and truncate if needed
        header = "[" + " | ".join(parts) + "]"
        
        if len(header) > self.config.max_header_length:
            header = header[:self.config.max_header_length - 3] + "...]"
        
        return header
    
    def _extract_sender(self, metadata: Dict[str, Any]) -> Optional[str]:
        """Extract sender/author from metadata."""
        # Try various common keys
        for key in ['sender', 'from', 'author', 'creator', 'sent_by']:
            if key in metadata:
                value = metadata[key]
                if isinstance(value, str):
                    # Clean up email format
                    if '<' in value:
                        # Extract name from "Name <email>" format
                        return value.split('<')[0].strip()
                    return value
        return None
    
    def _extract_subject(self, metadata: Dict[str, Any]) -> Optional[str]:
        """Extract subject/title from metadata."""
        for key in ['subject', 'title', 'name', 'heading', 'topic']:
            if key in metadata and metadata[key]:
                subject = str(metadata[key])[:80]  # Limit length
                return subject
        return None
    
    def _extract_date(self, metadata: Dict[str, Any]) -> Optional[str]:
        """Extract and format date from metadata."""
        for key in ['date', 'sent_at', 'created_at', 'timestamp', 'sent_date']:
            if key in metadata and metadata[key]:
                value = metadata[key]
                
                # If already a string, use as-is or parse
                if isinstance(value, str):
                    try:
                        # Try to parse and reformat
                        from dateutil import parser
                        dt = parser.parse(value)
                        return dt.strftime(self.config.date_format)
                    except Exception:
                        return value[:10]  # Take first 10 chars as fallback
                
                # If datetime object
                elif isinstance(value, datetime):
                    return value.strftime(self.config.date_format)
                
                # If timestamp (int/float)
                elif isinstance(value, (int, float)):
                    try:
                        dt = datetime.fromtimestamp(value)
                        return dt.strftime(self.config.date_format)
                    except Exception:
                        pass
        
        return None
    
    def _extract_recipients(self, metadata: Dict[str, Any]) -> Optional[str]:
        """Extract recipients from metadata."""
        for key in ['to', 'recipients', 'to_addresses']:
            if key in metadata and metadata[key]:
                value = metadata[key]
                if isinstance(value, list):
                    # Join first 3 recipients
                    names = [self._clean_email(r) for r in value[:3]]
                    result = ", ".join(names)
                    if len(value) > 3:
                        result += f" (+{len(value) - 3} more)"
                    return result
                elif isinstance(value, str):
                    return self._clean_email(value)
        return None
    
    def _clean_email(self, email: str) -> str:
        """Extract name from email address."""
        if '<' in email:
            return email.split('<')[0].strip()
        if '@' in email:
            return email.split('@')[0]
        return email
    
    def process_chunks(
        self,
        chunks: List[Dict[str, Any]],
        shared_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Process multiple chunks, adding contextual headers.
        
        Args:
            chunks: List of chunk dicts with 'text' and 'metadata'
            shared_metadata: Optional metadata shared by all chunks
            
        Returns:
            Chunks with contextual text
        """
        processed = []
        
        for chunk in chunks:
            text = chunk.get('text') or chunk.get('content', '')
            metadata = chunk.get('metadata', {})
            
            # Merge shared metadata
            if shared_metadata:
                merged_metadata = {**shared_metadata, **metadata}
            else:
                merged_metadata = metadata
            
            # Create contextual text
            contextual_text = self.create_contextual_chunk(text, merged_metadata)
            
            # Return modified chunk
            processed_chunk = chunk.copy()
            processed_chunk['contextual_text'] = contextual_text
            processed_chunk['original_text'] = text
            processed.append(processed_chunk)
        
        return processed


class EmailContextualChunker(ContextualChunker):
    """
    Specialized contextual chunker for email content.
    
    Adds email-specific context like thread information
    and conversation participants.
    """
    
    def __init__(self, config: Optional[ContextualChunkConfig] = None):
        super().__init__(config)
        # Override defaults for email
        self.config.include_recipients = True
    
    def _build_header(self, metadata: Dict[str, Any]) -> str:
        """Build email-specific header."""
        parts = []
        
        # Thread context
        if metadata.get('thread_id'):
            parts.append("Thread")
        
        # Reply indicator
        if metadata.get('is_reply') or metadata.get('in_reply_to'):
            parts.append("Reply")
        
        # Parent header
        parent_header = super()._build_header(metadata)
        
        if parts:
            prefix = "[" + " | ".join(parts) + "] "
            return prefix + parent_header
        
        return parent_header


class DocumentContextualChunker(ContextualChunker):
    """
    Specialized contextual chunker for documents (Drive, Notion, etc).
    """
    
    def _build_header(self, metadata: Dict[str, Any]) -> str:
        """Build document-specific header."""
        parts = []
        
        # Document type
        doc_type = metadata.get('mime_type') or metadata.get('type')
        if doc_type:
            if 'document' in doc_type.lower():
                parts.append("Document")
            elif 'spreadsheet' in doc_type.lower():
                parts.append("Spreadsheet")
            elif 'presentation' in doc_type.lower():
                parts.append("Presentation")
            elif 'pdf' in doc_type.lower():
                parts.append("PDF")
        
        # Folder path if available
        folder = metadata.get('folder') or metadata.get('parent_folder')
        if folder:
            parts.append(f"Folder: {folder}")
        
        # Add parent header components
        base_header = super()._build_header(metadata)
        
        if parts and base_header:
            return "[" + " | ".join(parts) + "] " + base_header
        elif parts:
            return "[" + " | ".join(parts) + "]"
        
        return base_header


def create_contextual_chunker(content_type: str = "general") -> ContextualChunker:
    """
    Factory function to create appropriate contextual chunker.
    
    Args:
        content_type: Type of content ('email', 'document', 'general')
        
    Returns:
        Appropriate ContextualChunker instance
    """
    if content_type == 'email':
        return EmailContextualChunker()
    elif content_type == 'document':
        return DocumentContextualChunker()
    else:
        return ContextualChunker()
