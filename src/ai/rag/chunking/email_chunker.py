"""
Email-Specific Chunking Module

Smart chunking for emails that preserves structure and improves search accuracy.
"""
import re
from typing import List, Dict, Any, Optional
from ....utils.logger import setup_logger

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
    
    def __init__(self, max_chunk_words: int = 300):
        """
        Initialize email chunker.
        
        Args:
            max_chunk_words: Maximum words per body chunk (default: 300)
        """
        self.max_chunk_words = max_chunk_words
    
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
        Create safe metadata that won't exceed Pinecone's 40KB limit.
        
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
                # Truncate string values to max 500 chars
                if isinstance(value, str) and len(value.encode('utf-8')) > 500:
                    metadata[key] = value[:500] + '...'
                elif isinstance(value, list) and len(str(value).encode('utf-8')) > 500:
                    # Truncate list representation
                    str_val = str(value)
                    metadata[key] = str_val[:500] + '...'
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
                if len(value.encode('utf-8')) <= 500:
                    metadata[key] = value
            elif isinstance(value, list):
                str_val = str(value)
                if len(str_val.encode('utf-8')) <= 500:
                    metadata[key] = value
        
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
        Chunk email body by semantic paragraphs.
        
        Preserves:
        - Paragraph boundaries
        - List structure
        - Quoted text context
        """
        if not body:
            return []
        
        chunks = []
        
        # Split by paragraphs (double newline)
        paragraphs = re.split(r'\n\s*\n', body)
        
        current_chunk = []
        current_words = 0
        
        for para in paragraphs:
            if not para.strip():
                continue
            
            para_words = len(para.split())
            
            # Check if adding this paragraph exceeds max chunk size
            if current_words + para_words > self.max_chunk_words and current_chunk:
                # Finalize current chunk
                chunk_text = '\n\n'.join(current_chunk)
                chunks.append({
                    'content': chunk_text,
                    'metadata': self._create_safe_metadata(email_data, chunk_type='body')
                })
                
                # Start new chunk
                current_chunk = [para]
                current_words = para_words
            else:
                # Add to current chunk
                current_chunk.append(para)
                current_words += para_words
        
        # Add final chunk
        if current_chunk:
            chunk_text = '\n\n'.join(current_chunk)
            chunks.append({
                'content': chunk_text,
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
        # Remove "Sent from my iPhone/Android" footers
        body = re.sub(r'Sent from my (iPhone|iPad|Android|Mobile).*', '', body, flags=re.IGNORECASE)
        body = re.sub(r'Get Outlook for (iOS|Android).*', '', body, flags=re.IGNORECASE)
        
        # Remove common signature delimiters
        # Pattern: "-- " or "___" or "---" on its own line, followed by signature
        body = re.sub(r'\n--\s*\n.*', '', body, flags=re.DOTALL)
        body = re.sub(r'\n_{3,}\s*\n.*', '', body, flags=re.DOTALL)
        body = re.sub(r'\n-{3,}\s*\n.*', '', body, flags=re.DOTALL)
        
        # Remove long legal disclaimers (usually > 300 chars with specific keywords)
        lines = body.split('\n')
        cleaned = []
        disclaimer_keywords = [
            'confidential', 'intended recipient', 'disclaimer', 
            'privileged', 'unauthorized', 'dissemination'
        ]
        
        for line in lines:
            # If line is very long and contains disclaimer keywords, skip it
            if len(line) > 300:
                if any(keyword in line.lower() for keyword in disclaimer_keywords):
                    continue  # Skip disclaimer line
            cleaned.append(line)
        
        body = '\n'.join(cleaned)
        
        # Clean excessive whitespace
        body = re.sub(r'\n{3,}', '\n\n', body)  # Max 2 consecutive newlines
        body = re.sub(r'[ \t]+', ' ', body)  # Normalize spaces/tabs
        
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
        
        # Split into paragraphs
        paragraphs = re.split(r'\n\s*\n', content_clean)
        
        chunks = []
        current_chunk = []
        current_words = 0
        
        for para in paragraphs:
            if not para.strip():
                continue
            
            para_words = len(para.split())
            
            if current_words + para_words > self.max_chunk_words and current_chunk:
                chunk_text = '\n\n'.join(current_chunk)
                chunks.append({
                    'content': chunk_text,
                    'metadata': metadata or {}
                })
                current_chunk = [para]
                current_words = para_words
            else:
                current_chunk.append(para)
                current_words += para_words
        
        # Add final chunk
        if current_chunk:
            chunk_text = '\n\n'.join(current_chunk)
            chunks.append({
                'content': chunk_text,
                'metadata': metadata or {}
            })
        
        return chunks
