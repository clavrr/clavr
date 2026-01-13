"""
Attachment Content Extraction Utility
Uses IBM Docling for advanced document parsing with OCR support.
Extracts text content from PDF, DOCX, PPTX and other formats.
"""
import io
import tempfile
from typing import Optional, Tuple, List
from pathlib import Path

from .logger import setup_logger

logger = setup_logger(__name__)

# Constants for attachment processing
SUPPORTED_FILE_EXTENSIONS: Tuple[str, ...] = (
    '.pdf', '.docx', '.pptx', '.doc', '.xlsx', '.html', '.md', '.txt'
)

# Text encoding fallback order (most common first)
DEFAULT_TEXT_ENCODING = 'utf-8'
FALLBACK_TEXT_ENCODINGS: List[str] = ['latin-1', 'cp1252', 'iso-8859-1']


class AttachmentProcessor:
    """Extract text content from email attachments using IBM Docling."""
    
    def __init__(self):
        """Initialize the attachment processor with Docling."""
        self.docling_available = False
        
        try:
            from docling.document_converter import DocumentConverter
            self.DocumentConverter = DocumentConverter
            self.docling_available = True
            logger.info("IBM Docling initialized successfully")
        except ImportError:
            logger.warning("IBM Docling not installed - falling back to basic extraction")
            logger.warning("Install with: pip install docling")
    
    def extract_text(self, attachment_data: bytes, filename: str) -> Optional[str]:
        """
        Extract text content from an attachment using IBM Docling.
        
        Args:
            attachment_data: Raw attachment file data
            filename: Name of the attachment file
        
        Returns:
            Extracted text content or None if extraction fails/unsupported
        """
        filename_lower = filename.lower()
        
        # Check if file type is supported
        if not filename_lower.endswith(SUPPORTED_FILE_EXTENSIONS):
            logger.debug(f"Unsupported attachment type: {filename}")
            return None
        
        try:
            if self.docling_available:
                return self._extract_with_docling(attachment_data, filename)
            else:
                # Fallback to basic text extraction
                return self._extract_text_file(attachment_data)
        except Exception as e:
            logger.error(f"Failed to extract text from {filename}: {e}")
            return None
    
    def _extract_with_docling(self, data: bytes, filename: str) -> Optional[str]:
        """Extract text using IBM Docling (advanced parsing with OCR)."""
        try:
            # Docling requires a file path, so write to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp_file:
                tmp_file.write(data)
                tmp_path = tmp_file.name
            
            try:
                # Initialize Docling converter
                converter = self.DocumentConverter()
                
                # Convert document
                result = converter.convert(tmp_path)
                
                # Extract text from the document
                # Docling provides structured output - we'll get the markdown representation
                text_content = result.document.export_to_markdown()
                
                if text_content and text_content.strip():
                    logger.info(f"Docling extracted {len(text_content)} chars from {filename}")
                    return text_content.strip()
                else:
                    logger.warning(f"Docling found no text in {filename}")
                    return None
                    
            finally:
                # Clean up temp file
                try:
                    Path(tmp_path).unlink()
                except OSError:
                    # File may have already been deleted or doesn't exist
                    pass
                    
        except Exception as e:
            logger.error(f"Docling extraction error for {filename}: {e}")
            return None
    
    def _extract_text_file(self, data: bytes) -> Optional[str]:
        """Extract text from plain text files."""
        try:
            # Try default encoding first
            text = data.decode(DEFAULT_TEXT_ENCODING)
            logger.info(f"Extracted {len(text)} chars from text file")
            return text.strip() if text.strip() else None
        except UnicodeDecodeError:
            # Try fallback encodings
            for encoding in FALLBACK_TEXT_ENCODINGS:
                try:
                    text = data.decode(encoding)
                    logger.info(f"Extracted {len(text)} chars from text file ({encoding})")
                    return text.strip() if text.strip() else None
                except (UnicodeDecodeError, ValueError):
                    continue
        
        logger.warning("Failed to decode text file with any encoding")
        return None
