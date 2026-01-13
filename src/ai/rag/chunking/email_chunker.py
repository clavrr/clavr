"""
Email-Specific Chunking Module

Smart chunking for emails that preserves structure and improves search accuracy.
"""
import re
from typing import List, Dict, Any, Optional
from ....utils.logger import setup_logger
from .chunking import RecursiveTextChunker
from .chunking_constants import (
    SENT_FROM_PATTERN,
    OUTLOOK_FOOTER_PATTERN,
    SIGNATURE_DELIMITER_PATTERN,
    EXCESSIVE_NEWLINES_PATTERN,
    WHITESPACE_PATTERN,
    DISCLAIMER_KEYWORDS,
    MAX_METADATA_LENGTH,
    DEFAULT_CHUNK_SIZE_TOKENS,
    DEFAULT_OVERLAP_TOKENS
)

logger = setup_logger(__name__)


class EmailChunker:
    """
    Email-aware chunking that preserves structure.
    
    Creates separate chunks for:
    1. Metadata (subject, sender, date) - for filtering and sender queries
    2. Body content (semantic paragraphs) - for content search
    3. Preserves thread context and quoted text
    
    Benefits:
    - Better metadata filtering ("emails from John")
    - Cleaner content search (signatures/disclaimers removed)
    - Smaller, focused chunks for better semantic matching
    """
    
    def __init__(
        self, 
        chunk_size: int = DEFAULT_CHUNK_SIZE_TOKENS,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
        base_chunker: Optional[RecursiveTextChunker] = None
    ):
        """
        Initialize email chunker.
        
        Args:
            chunk_size: Target chunk size in tokens (default: 512)
            overlap_tokens: Overlap tokens (default: 50)
            base_chunker: Optional existing RecursiveTextChunker instance
        """
        self.chunk_size = chunk_size
        self.overlap_tokens = overlap_tokens
        
        # Use provided chunker or create new one
        if base_chunker:
            self.base_chunker = base_chunker
        else:
            self.base_chunker = RecursiveTextChunker(
                chunk_size=chunk_size,
                overlap_tokens=overlap_tokens,
                use_parent_child=False  # We handle structure manually
            )
    
    def chunk_email(self, email_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Chunk email into semantic units.
        
        Args:
            email_data: Dict with email fields (subject, sender, body, etc.)
            
        Returns:
            List of chunk dicts with 'content' and 'metadata'
        """
        chunks = []
        
        # Chunk 1: Metadata chunk (helps with sender/date/subject queries)
        metadata_chunk = self._create_metadata_chunk(email_data)
        chunks.append(metadata_chunk)
        
        # Chunk 2+: Body content chunks (semantic paragraphs)
        body = email_data.get('body', '') or email_data.get('content', '')
        if body:
            body_clean = self._clean_email_body(body)
            if body_clean.strip():
                body_chunks = self._chunk_body(body_clean, email_data)
                chunks.extend(body_chunks)
        
        # Add chunk indices for debugging and reconstruction
        for idx, chunk in enumerate(chunks):
            chunk['metadata']['chunk_index'] = idx
            chunk['metadata']['total_chunks'] = len(chunks)
        
        logger.debug(f"Chunked email '{email_data.get('subject', 'No subject')[:50]}' into {len(chunks)} chunks")
        
        return chunks
    
    def _create_safe_metadata(self, email_data: Dict[str, Any], chunk_type: str = 'body') -> Dict[str, Any]:
        """
        Create safe metadata that won't exceed vector store metadata limits.
        
        Only includes essential, small fields and truncates string values.
        """
        # Fields to exclude (large content fields)
        excluded_fields = {
            'body', 'content', 'html', 'raw_body', 'text', 'searchable_text', 
            'attachments', 'attachment_data', 'raw_content', 'full_body'
        }
        
        # Essential fields to always include (small, important)
        essential_fields = {
            'id', 'threadId', 'subject', 'sender', 'to', 'recipient', 'cc', 'bcc', 
            'date', 'timestamp', 'labels', 'has_attachments', 'folder', 'read', 
            'important', 'starred', 'message_id', 'email_id', 'chunk_type', 
            'chunk_index', 'parent_doc_id', 'total_chunks'
        }
        
        metadata = {'chunk_type': chunk_type}
        
        # Add essential fields with truncation
        for key in essential_fields:
            if key in email_data:
                value = email_data[key]
                # Truncate string values
                if isinstance(value, str) and len(value.encode('utf-8')) > MAX_METADATA_LENGTH:
                    metadata[key] = value[:MAX_METADATA_LENGTH] + '...'
                elif isinstance(value, list) and len(str(value).encode('utf-8')) > MAX_METADATA_LENGTH:
                    # Truncate list representation
                    str_val = str(value)
                    metadata[key] = str_val[:MAX_METADATA_LENGTH] + '...'
                else:
                    metadata[key] = value
        
        # Add other small fields (not in excluded list)
        for key, value in email_data.items():
            if key in excluded_fields or key in metadata:
                continue
            
            # Only include small values
            if isinstance(value, (int, float, bool)):
                metadata[key] = value
            elif isinstance(value, str):
                if len(value.encode('utf-8')) <= MAX_METADATA_LENGTH:
                    metadata[key] = value
            elif isinstance(value, list):
                str_val = str(value)
                if len(str_val.encode('utf-8')) <= MAX_METADATA_LENGTH:
                    metadata[key] = value
        
        # CRITICAL: Ensure robust field mapping for common aliases
        # This fixes missing metadata in index
        if 'sender' not in metadata and 'from' in email_data:
            metadata['sender'] = email_data['from']
        if 'from' not in metadata and 'sender' in metadata:
            metadata['from'] = metadata['sender']
            
        if 'date' not in metadata and 'timestamp' in email_data:
            metadata['date'] = email_data['timestamp']
        if 'timestamp' not in metadata and 'date' in metadata:
            metadata['timestamp'] = metadata['date']
            
        if 'recipient' not in metadata and 'to' in email_data:
            metadata['recipient'] = email_data['to']
        if 'to' not in metadata and 'recipient' in metadata:
            metadata['to'] = metadata['recipient']

        # Bug #4 Fix: Ensure sender_email and sender_name are preserved for filtering
        # These are crucial for sender-based search filtering
        if 'sender_email' not in metadata and 'sender' in metadata:
            # Extract email from sender string like "Name <email@domain.com>"
            sender = metadata.get('sender', '')
            if '@' in sender:
                if '<' in sender and '>' in sender:
                    # Format: "Name <email@domain.com>"
                    import re
                    email_match = re.search(r'<([^>]+@[^>]+)>', sender)
                    if email_match:
                        metadata['sender_email'] = email_match.group(1)
                        metadata['sender_name'] = sender.split('<')[0].strip().strip('"')
                else:
                    # Already an email address
                    metadata['sender_email'] = sender
                    metadata['sender_name'] = sender.split('@')[0]
            else:
                # Just a name, use as sender_name
                metadata['sender_name'] = sender
        
        # Ensure sender_email from email_data is preserved if present
        if 'sender_email' in email_data and 'sender_email' not in metadata:
            metadata['sender_email'] = email_data['sender_email']
        if 'sender_name' in email_data and 'sender_name' not in metadata:
            metadata['sender_name'] = email_data['sender_name']

        return metadata
    
    def _create_metadata_chunk(self, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create searchable metadata chunk.
        
        This chunk helps with queries like:
        - "emails from John"
        - "emails about meeting"
        - "emails sent yesterday"
        """
        subject = email_data.get('subject', '')
        sender = email_data.get('sender', '') or email_data.get('from', '')
        recipient = email_data.get('recipient', '') or email_data.get('to', '')
        date = email_data.get('date', '') or email_data.get('timestamp', '')
        labels = email_data.get('labels', []) or []
        
        # Create searchable metadata text
        metadata_lines = [
            f"Subject: {subject}",
            f"From: {sender}",
            f"To: {recipient}",
            f"Date: {date}",
        ]
        
        if labels:
            label_str = ', '.join(labels) if isinstance(labels, list) else str(labels)
            metadata_lines.append(f"Labels: {label_str}")
        
        metadata_text = '\n'.join(metadata_lines)
        
        # Use safe metadata creation
        metadata = self._create_safe_metadata(email_data, chunk_type='metadata')
        
        return {
            'content': metadata_text,
            'metadata': metadata
        }
    
    def _chunk_body(self, body: str, email_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Chunk email body using RecursiveTextChunker.
        
        Preserves:
        - Paragraph boundaries (via RecursiveTextChunker separators)
        - Semantic meaning (via token-based splitting)
        """
        if not body:
            return []
        
        # Use the base chunker to split text
        text_chunks = self.base_chunker.chunk(body)
        
        chunks = []
        for text_chunk in text_chunks:
            chunks.append({
                'content': text_chunk.text,
                'metadata': self._create_safe_metadata(email_data, chunk_type='body')
            })
        
        return chunks
    
    def _clean_email_body(self, body: str) -> str:
        """
        Clean email body by removing noise that doesn't help search.
        
        Removes:
        - Email signatures (common patterns)
        - Legal disclaimers
        - Excessive whitespace
        - "Sent from" footers
        """
        # Remove "Sent from" footers
        body = SENT_FROM_PATTERN.sub('', body)
        body = OUTLOOK_FOOTER_PATTERN.sub('', body)
        
        # Remove common signature delimiters
        body = SIGNATURE_DELIMITER_PATTERN.sub('', body)
        
        # Remove long legal disclaimers
        lines = body.split('\n')
        cleaned = []
        
        for line in lines:
            # If line is very long and contains disclaimer keywords, skip it
            if len(line) > 300:
                if any(keyword in line.lower() for keyword in DISCLAIMER_KEYWORDS):
                    continue  # Skip disclaimer line
            cleaned.append(line)
        
        body = '\n'.join(cleaned)
        
        # Clean excessive whitespace
        body = EXCESSIVE_NEWLINES_PATTERN.sub('\n\n', body)
        body = WHITESPACE_PATTERN.sub(' ', body)
        
        return body.strip()
    
    def chunk_email_simple(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Simplified chunking for already-processed email content.
        
        Use this when email is already cleaned or when you want simpler chunking.
        
        Args:
            content: Email content
            metadata: Optional metadata to attach
            
        Returns:
            List of chunks
        """
        if not content:
            return []
        
        # Clean content
        content_clean = self._clean_email_body(content)
        
        # Use the base chunker to split text
        text_chunks = self.base_chunker.chunk(content_clean)
        
        chunks = []
        for text_chunk in text_chunks:
            chunks.append({
                'content': text_chunk.text,
                'metadata': metadata or {}
            })
        
        return chunks
