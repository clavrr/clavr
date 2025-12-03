"""
General Attachment Parser using IBM Docling for Intelligent Document Processing

Handles various document types:
- PDFs (reports, contracts, invoices)
- Word documents (.docx)
- PowerPoint presentations (.pptx)
- Excel spreadsheets (.xlsx)
- HTML documents
- Markdown files
- Images (with OCR)

Docling provides:
- Layout-aware text extraction
- Table detection and extraction
- Heading/section identification
- Multi-format support
- OCR for images and scanned documents
"""
import json
import re
import io
import mimetypes
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from pathlib import Path

from .base import BaseParser, ParsedNode, Relationship, Entity
from ....utils.logger import setup_logger

logger = setup_logger(__name__)

# Import Docling components (required)
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import ConversionResult


class AttachmentParser(BaseParser):
    """
    Parse general attachments into structured Document nodes using IBM Docling
    
    Features:
    - Multi-format document parsing (PDF, DOCX, PPTX, XLSX, etc.)
    - Layout-aware text extraction
    - Table extraction
    - Heading/section detection
    - LLM-based content summarization
    - Entity extraction (dates, companies, people)
    - Relationship building to Email nodes
    
    Output: Document node with structured content and metadata
    """
    
    def __init__(self, llm_client=None):
        """
        Initialize attachment parser
        
        Args:
            llm_client: Optional LLM for summarization and entity extraction
        """
        self.llm_client = llm_client
        self.use_llm = llm_client is not None
        
        # Initialize Docling converter (required)
        self.converter = DocumentConverter()
        logger.info("Docling converter initialized for document parsing")
    
    async def parse(
        self, 
        attachment_data: bytes, 
        filename: str,
        email_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ParsedNode:
        """
        Parse attachment into structured Document node
        
        Args:
            attachment_data: Raw file bytes
            filename: Original filename
            email_id: ID of parent email (for relationship)
            metadata: Additional metadata (content_type, size, etc.)
            
        Returns:
            ParsedNode with document content and relationships
        """
        try:
            # Step 1: Detect document type
            doc_type = self._detect_document_type(filename, metadata)
            
            # Step 2: Extract content using Docling
            content = await self._extract_with_docling(attachment_data, filename, doc_type)
            
            if not content['text']:
                logger.warning(f"No content extracted from {filename}")
                return self._create_empty_document_node(filename, email_id)
            
            # Step 3: Extract structured information using LLM
            structured_data = await self._extract_document_structure(content, filename, doc_type)
            
            # Step 4: Build Document node
            node = self._build_document_node(
                content=content,
                structured_data=structured_data,
                filename=filename,
                doc_type=doc_type,
                email_id=email_id,
                metadata=metadata
            )
            
            logger.info(
                f"Parsed {doc_type} attachment: {filename} "
                f"({len(content['text'])} chars, {len(content['tables'])} tables)"
            )
            return node
            
        except Exception as e:
            logger.error(f"Failed to parse attachment {filename}: {e}", exc_info=True)
            return self._create_empty_document_node(filename, email_id)
    
    def _detect_document_type(self, filename: str, metadata: Optional[Dict] = None) -> str:
        """
        Detect document type from filename and metadata
        
        Returns: Document type category
        """
        ext = Path(filename).suffix.lower()
        
        # Check MIME type if available
        content_type = metadata.get('content_type', '') if metadata else ''
        
        # Document type mapping
        type_map = {
            # PDFs
            '.pdf': 'pdf_document',
            
            # Microsoft Office
            '.docx': 'word_document',
            '.doc': 'word_document',
            '.pptx': 'presentation',
            '.ppt': 'presentation',
            '.xlsx': 'spreadsheet',
            '.xls': 'spreadsheet',
            
            # Images
            '.jpg': 'image',
            '.jpeg': 'image',
            '.png': 'image',
            '.gif': 'image',
            '.tiff': 'image',
            '.tif': 'image',
            
            # Text formats
            '.txt': 'text',
            '.md': 'markdown',
            '.html': 'html',
            '.htm': 'html',
            '.csv': 'csv',
            '.json': 'json',
            '.xml': 'xml',
            
            # Other
            '.zip': 'archive',
            '.rar': 'archive',
        }
        
        doc_type = type_map.get(ext, 'unknown')
        
        # Try to infer from content type
        if doc_type == 'unknown' and content_type:
            if 'pdf' in content_type:
                doc_type = 'pdf_document'
            elif 'word' in content_type or 'msword' in content_type:
                doc_type = 'word_document'
            elif 'powerpoint' in content_type or 'presentation' in content_type:
                doc_type = 'presentation'
            elif 'excel' in content_type or 'spreadsheet' in content_type:
                doc_type = 'spreadsheet'
            elif 'image' in content_type:
                doc_type = 'image'
        
        return doc_type
    
    async def _extract_with_docling(
        self, 
        data: bytes, 
        filename: str,
        doc_type: str
    ) -> Dict[str, Any]:
        """
        Extract content using IBM Docling
        
        Args:
            data: File bytes
            filename: Original filename
            doc_type: Detected document type
            
        Returns:
            Dictionary with extracted content:
            {
                'text': str,
                'tables': List[Dict],
                'headings': List[Dict],
                'sections': List[Dict],
                'images': List[Dict],
                'metadata': Dict
            }
        """
        import tempfile
        import os
        
        # Determine Docling input format
        input_format = self._map_to_docling_format(filename, doc_type)
        
        # Docling requires a file path (Path or str), not BytesIO
        # Write to temporary file first, then pass the path
        temp_path = None
        try:
            # Create temporary file with appropriate extension
            file_ext = Path(filename).suffix or '.tmp'
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
                temp_file.write(data)
                temp_path = temp_file.name
            
            # Convert document using Docling (pass file path, not BytesIO)
            logger.debug(f"Converting {filename} with Docling (format: {input_format})")
            result: ConversionResult = self.converter.convert(
                temp_path, 
                raises_on_error=False
            )
        finally:
            # Clean up temporary file
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception as e:
                    logger.debug(f"Failed to delete temp file {temp_path}: {e}")
        
        # Extract structured content
        content = {
            'text': self._extract_text(result),
            'tables': self._extract_tables(result),
            'headings': self._extract_headings(result),
            'sections': self._extract_sections(result),
            'images': self._extract_images(result),
            'metadata': self._extract_metadata(result)
        }
        
        logger.debug(
            f"Docling extracted: {len(content['text'])} chars, "
            f"{len(content['tables'])} tables, "
            f"{len(content['headings'])} headings"
        )
        
        return content
    
    def _map_to_docling_format(self, filename: str, doc_type: str) -> InputFormat:
        """Map document type to Docling InputFormat"""
        ext = Path(filename).suffix.lower()
        
        format_map = {
            '.pdf': InputFormat.PDF,
            '.docx': InputFormat.DOCX,
            '.pptx': InputFormat.PPTX,
            '.xlsx': InputFormat.XLSX,
            '.html': InputFormat.HTML,
            '.htm': InputFormat.HTML,
            '.md': InputFormat.MD,
            '.jpg': InputFormat.IMAGE,
            '.jpeg': InputFormat.IMAGE,
            '.png': InputFormat.IMAGE,
            '.tiff': InputFormat.IMAGE,
            '.tif': InputFormat.IMAGE,
        }
        
        return format_map.get(ext, InputFormat.PDF)
    
    def _extract_text(self, result: ConversionResult) -> str:
        """Extract full text from Docling result"""
        try:
            # Export to markdown for clean text representation
            return result.document.export_to_markdown()
        except Exception as e:
            logger.debug(f"Failed to extract text: {e}")
            return ""
    
    def _extract_tables(self, result: ConversionResult) -> List[Dict]:
        """Extract tables from Docling result"""
        tables = []
        
        try:
            for idx, table in enumerate(result.document.tables):
                table_data = {
                    'index': idx,
                    'headers': table.data.columns.tolist() if hasattr(table.data, 'columns') else [],
                    'rows': table.data.values.tolist() if hasattr(table.data, 'values') else [],
                    'num_rows': len(table.data) if hasattr(table, 'data') else 0,
                    'num_cols': len(table.data.columns) if hasattr(table.data, 'columns') else 0,
                }
                tables.append(table_data)
            
        except Exception as e:
            logger.debug(f"Failed to extract tables: {e}")
        
        return tables
    
    def _extract_headings(self, result: ConversionResult) -> List[Dict]:
        """Extract headings/titles from document structure"""
        headings = []
        
        try:
            # Docling provides document structure with headings
            for item in result.document.body:
                if hasattr(item, 'heading') and item.heading:
                    headings.append({
                        'level': getattr(item, 'level', 1),
                        'text': str(item.heading),
                    })
        except Exception as e:
            logger.debug(f"Failed to extract headings: {e}")
        
        return headings
    
    def _extract_sections(self, result: ConversionResult) -> List[Dict]:
        """Extract document sections based on structure"""
        sections = []
        
        try:
            # Group content by headings
            current_section = None
            
            for item in result.document.body:
                if hasattr(item, 'heading') and item.heading:
                    # Start new section
                    if current_section:
                        sections.append(current_section)
                    
                    current_section = {
                        'heading': str(item.heading),
                        'level': getattr(item, 'level', 1),
                        'content': []
                    }
                elif current_section:
                    # Add to current section
                    current_section['content'].append(str(item))
            
            # Add last section
            if current_section:
                sections.append(current_section)
                
        except Exception as e:
            logger.debug(f"Failed to extract sections: {e}")
        
        return sections
    
    def _extract_images(self, result: ConversionResult) -> List[Dict]:
        """Extract image metadata from document"""
        images = []
        
        try:
            for idx, img in enumerate(result.document.pictures):
                images.append({
                    'index': idx,
                    'caption': getattr(img, 'caption', ''),
                    'alt_text': getattr(img, 'alt_text', ''),
                })
        except Exception as e:
            logger.debug(f"Failed to extract images: {e}")
        
        return images
    
    def _extract_metadata(self, result: ConversionResult) -> Dict[str, Any]:
        """Extract document metadata from Docling result"""
        metadata = {}
        
        try:
            doc = result.document
            metadata = {
                'title': getattr(doc, 'title', ''),
                'author': getattr(doc, 'author', ''),
                'created_date': getattr(doc, 'created_date', ''),
                'modified_date': getattr(doc, 'modified_date', ''),
                'num_pages': getattr(doc, 'num_pages', 0),
                'language': getattr(doc, 'language', ''),
            }
        except Exception as e:
            logger.debug(f"Failed to extract metadata: {e}")
        
        return metadata
    
    async def _extract_document_structure(
        self,
        content: Dict[str, Any],
        filename: str,
        doc_type: str
    ) -> Dict[str, Any]:
        """
        Extract structured information using LLM
        
        Args:
            content: Extracted content from Docling
            filename: Original filename
            doc_type: Document type
            
        Returns:
            Structured data: summary, key_points, entities, topics
        """
        if not self.use_llm:
            return self._fallback_structure_extraction(content, filename)
        
        try:
            prompt = self._build_structure_extraction_prompt(content, filename, doc_type)
            response = await self.llm_client.ainvoke(prompt)
            
            # Parse LLM response
            structured_data = self._parse_llm_structure_response(response)
            return structured_data
            
        except Exception as e:
            logger.warning(f"LLM structure extraction failed: {e}, using fallback")
            return self._fallback_structure_extraction(content, filename)
    
    def _build_structure_extraction_prompt(
        self,
        content: Dict[str, Any],
        filename: str,
        doc_type: str
    ) -> str:
        """Build prompt for LLM document structure extraction"""
        
        # Truncate text for LLM context window
        text = content['text'][:8000]
        
        # Include headings if available
        headings_text = ""
        if content['headings']:
            headings_text = "\n\nDocument Headings:\n" + "\n".join([
                f"{'#' * h['level']} {h['text']}"
                for h in content['headings'][:10]
            ])
        
        # Include table info if available
        tables_text = ""
        if content['tables']:
            tables_text = f"\n\nDocument contains {len(content['tables'])} tables with structured data."
        
        return f"""You are analyzing a {doc_type} document attachment. Extract structured information.

Filename: {filename}

Document Content:
{text}
{headings_text}
{tables_text}

Extract the following in JSON format:
{{
    "summary": "2-3 sentence summary of the document",
    "document_type": "report|contract|invoice|presentation|meeting_notes|other",
    "key_points": [
        "Important point 1",
        "Important point 2"
    ],
    "entities": {{
        "people": ["Person Name"],
        "companies": ["Company Name"],
        "dates": ["YYYY-MM-DD"],
        "locations": ["City, State"]
    }},
    "topics": ["topic1", "topic2"],
    "action_items": ["action if mentioned"],
    "financial_data": {{
        "amounts": ["$1000", "$500"],
        "total": "$1500"
    }},
    "confidence": 0.0-1.0
}}

Focus on:
- Identifying the main purpose of the document
- Extracting key information (people, companies, dates, amounts)
- Summarizing main points
- Detecting action items or next steps
- Categorizing by document type

Respond ONLY with valid JSON, no other text."""
    
    def _parse_llm_structure_response(self, response) -> Dict[str, Any]:
        """Parse LLM JSON response into structured data"""
        try:
            # Extract JSON from response
            if hasattr(response, 'content'):
                text = response.content
            else:
                text = str(response)
            
            # Clean markdown code blocks
            json_match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
            if json_match:
                text = json_match.group(1)
            
            data = json.loads(text)
            
            return {
                'summary': data.get('summary', ''),
                'document_type': data.get('document_type', 'other'),
                'key_points': data.get('key_points', []),
                'entities': data.get('entities', {}),
                'topics': data.get('topics', []),
                'action_items': data.get('action_items', []),
                'financial_data': data.get('financial_data', {}),
                'confidence': float(data.get('confidence', 0.5))
            }
            
        except Exception as e:
            logger.warning(f"Failed to parse LLM structure response: {e}")
            return self._create_default_structure()
    
    def _fallback_structure_extraction(
        self,
        content: Dict[str, Any],
        filename: str
    ) -> Dict[str, Any]:
        """Simple extraction without LLM"""
        text = content['text']
        
        # Extract basic entities with regex
        entities = {
            'people': self._extract_people_regex(text),
            'companies': self._extract_companies_regex(text),
            'dates': self._extract_dates_regex(text),
            'locations': []
        }
        
        # Create simple summary from first few sentences
        sentences = text.split('.')[:3]
        summary = '.'.join(sentences).strip()[:200]
        
        return {
            'summary': summary,
            'document_type': 'other',
            'key_points': content.get('headings', [])[:5],
            'entities': entities,
            'topics': [],
            'action_items': [],
            'financial_data': {},
            'confidence': 0.3
        }
    
    def _extract_people_regex(self, text: str) -> List[str]:
        """Extract potential person names using regex"""
        # Simple pattern: Capitalized words (2-3 words)
        pattern = r'\b([A-Z][a-z]+\s[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b'
        matches = re.findall(pattern, text)
        return list(set(matches[:10]))  # Dedupe, limit to 10
    
    def _extract_companies_regex(self, text: str) -> List[str]:
        """Extract potential company names"""
        # Look for "Inc", "LLC", "Corp", etc.
        pattern = r'\b([A-Z][A-Za-z\s&]+(?:Inc|LLC|Corp|Ltd|Corporation|Company)\.?)\b'
        matches = re.findall(pattern, text)
        return list(set(matches[:10]))
    
    def _extract_dates_regex(self, text: str) -> List[str]:
        """Extract dates using regex"""
        patterns = [
            r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}',
            r'\d{4}[/-]\d{1,2}[/-]\d{1,2}',
            r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}'
        ]
        dates = []
        for pattern in patterns:
            dates.extend(re.findall(pattern, text))
        return list(set(dates[:10]))
    
    def _convert_entities_to_array(self, entities_data: Any) -> List[Dict[str, str]]:
        """
        Convert entities dict to array format for schema compliance.
        
        Args:
            entities_data: Dict with keys like 'people', 'companies', etc.
                          Can be any type (will return [] if not a dict)
            
        Returns:
            List of entity dicts: [{"type": "person", "name": "..."}, ...]
        """
        if not isinstance(entities_data, dict):
            return []
        
        converted = []
        for entity_type, names in entities_data.items():
            if isinstance(names, list):
                for name in names:
                    if isinstance(name, str) and name.strip():
                        converted.append({"type": entity_type, "name": name.strip()})
        
        return converted
    
    def _sanitize_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize metadata dictionary to remove non-serializable objects.
        
        Args:
            metadata: Raw metadata dictionary
            
        Returns:
            Sanitized metadata dictionary with only serializable values
        """
        if not isinstance(metadata, dict):
            return {}
        
        sanitized = {}
        for key, value in metadata.items():
            try:
                # Skip methods and callable objects
                if callable(value) and not isinstance(value, (str, bytes)):
                    continue
                
                # Handle basic types
                if isinstance(value, (str, int, float, bool, type(None))):
                    sanitized[key] = value
                # Handle lists
                elif isinstance(value, (list, tuple)):
                    sanitized_list = []
                    for item in value:
                        if isinstance(item, (str, int, float, bool, type(None))):
                            sanitized_list.append(item)
                        elif isinstance(item, dict):
                            sanitized_list.append(self._sanitize_metadata(item))
                        elif not callable(item):
                            sanitized_list.append(str(item))
                    sanitized[key] = sanitized_list
                # Handle dictionaries - recursively sanitize
                elif isinstance(value, dict):
                    sanitized[key] = self._sanitize_metadata(value)
                # Handle datetime objects
                elif hasattr(value, 'isoformat'):
                    sanitized[key] = value.isoformat()
                # Convert other types to string (but skip callables)
                elif not callable(value):
                    sanitized[key] = str(value)
            except Exception as e:
                logger.debug(f"Error sanitizing metadata key {key}: {e}, skipping")
                continue
        
        return sanitized
    
    def _build_document_node(
        self,
        content: Dict[str, Any],
        structured_data: Dict[str, Any],
        filename: str,
        doc_type: str,
        email_id: Optional[str],
        metadata: Optional[Dict[str, Any]]
    ) -> ParsedNode:
        """Build Document node from extracted content and structure"""
        
        # Generate node ID
        node_id = self.generate_node_id('Document', filename)
        
        # Build relationships
        relationships = []
        
        # Document ATTACHED_TO Email
        if email_id:
            relationships.append(Relationship(
                from_node=email_id,
                to_node=node_id,
                rel_type='ATTACHED_TO',
                properties={'filename': filename}
            ))
        
        # Extract entities and create relationships
        entities_data = structured_data.get('entities', {})
        
        # Document MENTIONS Person
        for person in entities_data.get('people', [])[:5]:
            person_id = self.generate_node_id('Person', person)
            relationships.append(Relationship(
                from_node=node_id,
                to_node=person_id,
                rel_type='MENTIONS',
                properties={'entity_type': 'person', 'name': person}
            ))
        
        # Document MENTIONS Company
        for company in entities_data.get('companies', [])[:5]:
            company_id = self.generate_node_id('Company', company)
            relationships.append(Relationship(
                from_node=node_id,
                to_node=company_id,
                rel_type='MENTIONS',
                properties={'entity_type': 'company', 'name': company}
            ))
        
        # Document DISCUSSES Topic
        for topic in structured_data.get('topics', [])[:5]:
            topic_id = self.generate_node_id('Topic', topic)
            relationships.append(Relationship(
                from_node=node_id,
                to_node=topic_id,
                rel_type='DISCUSSES',
                properties={'topic': topic}
            ))
        
        # Build properties
        properties = {
            'filename': filename,
            'doc_type': doc_type,
            'file_size': metadata.get('size', 0) if metadata else 0,
            # Use 'unknown' instead of empty string to pass validation
            'content_type': metadata.get('content_type', 'unknown') if metadata else 'unknown',
            
            # Extracted content
            'full_text': content['text'],
            'num_tables': len(content['tables']),
            'num_headings': len(content['headings']),
            'num_sections': len(content['sections']),
            'num_images': len(content['images']),
            
            # Docling metadata - sanitize to remove non-serializable objects
            'docling_metadata': self._sanitize_metadata(content.get('metadata', {})),
            
            # Structured data from LLM
            'summary': structured_data.get('summary', ''),
            'document_type': structured_data.get('document_type', 'other'),
            'key_points': structured_data.get('key_points', []),
            # Convert entities dict to array format for schema compliance
            'entities': self._convert_entities_to_array(entities_data),
            'topics': structured_data.get('topics', []),
            'action_items': structured_data.get('action_items', []),
            'financial_data': structured_data.get('financial_data', {}),
            'confidence': structured_data.get('confidence', 0.5),
            
            # Parsing metadata - use UTC ISO format with timezone
            'parsed_at': datetime.now(timezone.utc).isoformat(),
            'parser': 'docling'
        }
        
        # Create node
        node = ParsedNode(
            node_id=node_id,
            node_type='Document',
            properties=properties,
            relationships=relationships,
            searchable_text=self._build_searchable_text(content, structured_data, filename)
        )
        
        return node
    
    def _build_searchable_text(
        self,
        content: Dict[str, Any],
        structured_data: Dict[str, Any],
        filename: str
    ) -> str:
        """Build searchable text for vector embedding"""
        parts = []
        
        # Add filename
        parts.append(f"Document: {filename}")
        
        # Add summary
        if structured_data.get('summary'):
            parts.append(structured_data['summary'])
        
        # Add headings
        if content.get('headings'):
            headings = " | ".join([h['text'] for h in content['headings'][:5]])
            parts.append(f"Sections: {headings}")
        
        # Add key points
        if structured_data.get('key_points'):
            points = " | ".join(structured_data['key_points'][:3])
            parts.append(f"Key Points: {points}")
        
        # Add topics
        if structured_data.get('topics'):
            topics = ", ".join(structured_data['topics'])
            parts.append(f"Topics: {topics}")
        
        # Add truncated full text (first 1000 chars)
        parts.append(content['text'][:1000])
        
        return "\n\n".join(parts)
    
    def _create_empty_document_node(
        self,
        filename: str,
        email_id: Optional[str]
    ) -> ParsedNode:
        """Create minimal document node when parsing fails"""
        relationships = []
        
        if email_id:
            relationships.append(Relationship(
                from_node=email_id,
                to_node=self.generate_node_id('Document', filename),
                rel_type='ATTACHED_TO',
                properties={'filename': filename}
            ))
        
        return ParsedNode(
            node_id=self.generate_node_id('Document', filename),
            node_type='Document',
            properties={
                'filename': filename,
                'doc_type': 'unknown',
                'parsing_failed': True,
                'confidence': 0.0
            },
            relationships=relationships
        )
    
    def _create_default_structure(self) -> Dict[str, Any]:
        """Create default structure data"""
        return {
            'summary': '',
            'document_type': 'other',
            'key_points': [],
            'entities': {},
            'topics': [],
            'action_items': [],
            'financial_data': {},
            'confidence': 0.0
        }
