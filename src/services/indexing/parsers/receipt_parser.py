"""
Receipt Parser using IBM Docling for Intelligent OCR and Structure Extraction

Docling provides:
- Advanced OCR for images
- Layout-aware document parsing
- Table extraction
- Structured data extraction from PDFs and images

This parser transforms receipts into structured Receipt nodes for the knowledge graph.
"""
import json
import re
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import io
import tempfile
import os

from .base import BaseParser, ParsedNode, Relationship, Entity
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Import Docling components (optional)
try:
    from docling.document_converter import DocumentConverter
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.document import ConversionResult
    DOCLING_AVAILABLE = True
except ImportError:
    DocumentConverter = None
    InputFormat = None
    ConversionResult = None
    DOCLING_AVAILABLE = False


class ReceiptParser(BaseParser):
    """
    Parse receipts and invoices into structured data using IBM Docling
    """
    
    def __init__(self, llm_client=None):
        """
        Initialize receipt parser
        """
        self.llm_client = llm_client
        self.use_llm = llm_client is not None
        
        # Initialize Docling converter if available
        if DOCLING_AVAILABLE:
            self.converter = DocumentConverter()
            logger.info("Docling converter initialized for receipt parsing")
        else:
            self.converter = None
            logger.warning("Docling not available. Receipt parsing will use limited regex fallback.")
    
    async def parse(self, attachment_data: bytes, filename: str, email_date: Optional[str] = None) -> ParsedNode:
        """
        Parse receipt into structured Receipt node
        
        Args:
            attachment_data: Raw file bytes
            filename: Original filename
            email_date: Optional email date to use as fallback for receipt date
            
        Returns:
            ParsedNode with structured receipt data and relationships
        """
        try:
            # Step 1: Extract text using Docling
            extracted_text, tables = await self._extract_with_docling(attachment_data, filename)
            
            if not extracted_text:
                logger.warning(f"No text extracted from receipt: {filename}")
                return self._create_empty_receipt_node(filename, email_date)
            
            # Step 2: Extract structured data using LLM
            receipt_data = await self._extract_receipt_structure(extracted_text, tables, filename)
            
            # Normalize date if present (fix malformed dates)
            if receipt_data.get('date'):
                receipt_data['date'] = self._normalize_date(receipt_data['date'])
            
            # Ensure date is set (use email_date as fallback if receipt parsing didn't extract date)
            if not receipt_data.get('date') and email_date:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(email_date)
                    receipt_data['date'] = dt.strftime('%Y-%m-%d')
                except Exception:
                    # Fallback: try to extract date from string or use today
                    try:
                        dt = datetime.strptime(email_date.split(',')[1].strip()[:11], '%d %b %Y')
                        receipt_data['date'] = dt.strftime('%Y-%m-%d')
                    except Exception:
                        receipt_data['date'] = datetime.now().strftime('%Y-%m-%d')
            elif not receipt_data.get('date'):
                # No date from receipt or email - use today
                receipt_data['date'] = datetime.now().strftime('%Y-%m-%d')
            
            # Step 3: Build Receipt node
            node = self._build_receipt_node(receipt_data, filename)
            
            logger.info(f"Parsed receipt: {filename} → {receipt_data.get('merchant', 'Unknown')}, ${receipt_data.get('total', 0)}")
            return node
            
        except Exception as e:
            logger.error(f"Failed to parse receipt {filename}: {e}", exc_info=True)
            return self._create_empty_receipt_node(filename, email_date)
    
    async def _extract_with_docling(self, data: bytes, filename: str) -> Tuple[str, List[Dict]]:
        """
        Extract text and tables using IBM Docling
        
        Args:
            data: File bytes
            filename: Original filename
            
        Returns:
            Tuple of (extracted_text, tables)
        """
        # Determine input format
        input_format = self._detect_format(filename)
        
        # Docling requires a file path, not BytesIO - write to temporary file
        temp_file = None
        try:
            # Create temporary file with appropriate extension
            file_ext = os.path.splitext(filename)[1] or '.pdf'
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
                temp_file.write(data)
                temp_path = temp_file.name
            
            # Convert document using Docling (expects Path or string)
            result: ConversionResult = self.converter.convert(
                temp_path, 
                raises_on_error=False
            )
            
            # Extract text content
            extracted_text = result.document.export_to_markdown()
            
            # Extract tables if present
            tables = self._extract_tables_from_result(result)
            
            logger.debug(f"Docling extracted {len(extracted_text)} chars and {len(tables)} tables from {filename}")
            return extracted_text, tables
            
        finally:
            # Clean up temporary file
            if temp_file and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception as e:
                    logger.debug(f"Failed to delete temp file {temp_path}: {e}")
    
    def _detect_format(self, filename: str) -> InputFormat:
        """Detect document format from filename"""
        ext = filename.lower().split('.')[-1]
        
        format_map = {
            'pdf': InputFormat.PDF,
            'jpg': InputFormat.IMAGE,
            'jpeg': InputFormat.IMAGE,
            'png': InputFormat.IMAGE,
            'tiff': InputFormat.IMAGE,
            'tif': InputFormat.IMAGE,
            'docx': InputFormat.DOCX,
            'html': InputFormat.HTML,
            'md': InputFormat.MD,
        }
        
        return format_map.get(ext, InputFormat.PDF)
    
    def _extract_tables_from_result(self, result: ConversionResult) -> List[Dict]:
        """
        Extract tables from Docling conversion result
        
        Returns list of table dictionaries with headers and rows
        """
        tables = []
        
        try:
            # Docling provides structured table data
            for table in result.document.tables:
                table_data = {
                    'headers': table.data.columns.tolist() if hasattr(table.data, 'columns') else [],
                    'rows': table.data.values.tolist() if hasattr(table.data, 'values') else [],
                    'num_rows': len(table.data) if hasattr(table, 'data') else 0
                }
                tables.append(table_data)
            
            logger.debug(f"Extracted {len(tables)} tables from document")
            
        except Exception as e:
            logger.debug(f"Failed to extract tables: {e}")
        
        return tables
    
    async def _extract_receipt_structure(
        self, 
        text: str, 
        tables: List[Dict],
        filename: str
    ) -> Dict[str, Any]:
        """
        Extract structured receipt data using LLM
        
        Args:
            text: Extracted text from receipt
            tables: Extracted tables (if any)
            filename: Original filename
            
        Returns:
            Structured receipt data dictionary
        """
        if not self.use_llm:
            return self._fallback_structure_extraction(text, tables)
        
        try:
            prompt = self._build_receipt_extraction_prompt(text, tables, filename)
            try:
                # Use invoke in thread to avoid blocking loop if sync
                import asyncio
                response = await asyncio.to_thread(self.llm_client.invoke, prompt)
            except AttributeError:
                # Fallback if invoke missing (e.g. raw client)
                response = await self.llm_client.generate_content_async(prompt)
            
            # Parse LLM response
            structured_data = self._parse_llm_response(response)
            return structured_data
            
        except Exception as e:
            logger.warning(f"LLM extraction failed: {e}, using fallback")
            return self._fallback_structure_extraction(text, tables)
    
    def _build_receipt_extraction_prompt(
        self, 
        text: str, 
        tables: List[Dict],
        filename: str
    ) -> str:
        """Build prompt for LLM receipt data extraction"""
        
        # Include table data if available
        table_context = ""
        if tables:
            table_context = "\n\nTables found in receipt:\n"
            for i, table in enumerate(tables[:3]):  # Max 3 tables
                table_context += f"\nTable {i+1}:\n"
                table_context += f"Headers: {table.get('headers', [])}\n"
                table_context += f"Rows: {table.get('rows', [])[:5]}\n"  # First 5 rows
        
        return f"""You are parsing a receipt/invoice. Extract structured financial data.

Filename: {filename}

Receipt Text:
{text[:3000]}
{table_context}

Extract the following in JSON format:
{{
    "merchant": "Store/company name",
    "total": 0.00,  // Total amount as float
    "subtotal": 0.00,  // Optional subtotal
    "tax": 0.00,  // Optional tax amount
    "date": "YYYY-MM-DD",  // Transaction date
    "time": "HH:MM",  // Optional time
    "payment_method": "Cash|Credit|Debit|Other",
    "currency": "USD",  // Default USD
    "category": "food|retail|gas|services|other",
    "items": [  // Optional line items
        {{"name": "Item name", "price": 0.00, "quantity": 1}}
    ],
    "receipt_number": "...",  // Optional
    "location": "City, State",  // Optional store location
    "confidence": 0.0-1.0  // Your confidence in this extraction
}}

Focus on:
- Finding the total amount (usually labeled "Total", "Amount Due", "Balance")
- Identifying the merchant/store name (usually at top of receipt)
- Extracting the date (various formats: MM/DD/YYYY, DD-MM-YYYY, etc)
- Categorizing by merchant type (Chipotle=food, Shell=gas, etc)
- Extracting line items if clearly itemized

If you can't find a field with confidence, omit it or set to null.

Respond ONLY with valid JSON, no other text."""
    
    
    def _parse_llm_response(self, response) -> Dict[str, Any]:
        """Parse LLM JSON response into structured data"""
        try:
            # Use base class helper
            data = self._parse_json_response(response)
            
            # Validate and clean data
            return {
                'merchant': data.get('merchant', 'Unknown'),
                'total': float(data.get('total', 0)),
                'subtotal': float(data.get('subtotal', 0)) if data.get('subtotal') else None,
                'tax': float(data.get('tax', 0)) if data.get('tax') else None,
                'date': data.get('date'),
                'time': data.get('time'),
                'payment_method': data.get('payment_method', 'Unknown'),
                'currency': data.get('currency', 'USD'),
                'category': data.get('category', 'other'),
                'items': data.get('items', []),
                'receipt_number': data.get('receipt_number'),
                'location': data.get('location'),
                'confidence': float(data.get('confidence', 0.5))
            }
            
        except Exception as e:
            logger.warning(f"Failed to parse LLM receipt response: {e}")
            return self._create_default_receipt_data()
    
    def _fallback_structure_extraction(self, text: str, tables: List[Dict]) -> Dict[str, Any]:
        """Simple regex-based fallback when LLM unavailable"""
        data = self._create_default_receipt_data()
        
        # Extract total amount
        total_patterns = [
            r'total[:\s]+\$?(\d+\.\d{2})',
            r'amount due[:\s]+\$?(\d+\.\d{2})',
            r'balance[:\s]+\$?(\d+\.\d{2})',
            r'total cost[:\s]+\$?(\d+\.\d{2})',
            r'amount paid[:\s]+\$?(\d+\.\d{2})',
            r'total amount paid[:\s]+\$?(\d+\.\d{2})',
            r'grand total[:\s]+\$?(\d+\.\d{2})',
            r'charged[:\s]+\$?(\d+\.\d{2})',
        ]
        for pattern in total_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                data['total'] = float(match.group(1))
                break
        
        # Extract merchant (usually first few lines)
        lines = text.split('\n')[:5]
        for line in lines:
            line = line.strip()
            if len(line) > 3 and not any(c.isdigit() for c in line):
                data['merchant'] = line
                break
        
        # Extract date
        date_patterns = [
            r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})',
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                data['date'] = match.group(1)
                break
        
        # Categorize by merchant name
        merchant_lower = data['merchant'].lower()
        if any(kw in merchant_lower for kw in ['chipotle', 'mcdonalds', 'starbucks', 'restaurant']):
            data['category'] = 'food'
        elif any(kw in merchant_lower for kw in ['shell', 'chevron', 'exxon', 'gas']):
            data['category'] = 'gas'
        elif any(kw in merchant_lower for kw in ['target', 'walmart', 'amazon']):
            data['category'] = 'retail'
        
        data['confidence'] = 0.3  # Low confidence for regex extraction
        
        return data
    
    def _build_receipt_node(self, receipt_data: Dict[str, Any], filename: str) -> ParsedNode:
        """Build Receipt node from structured data"""
        
        # Generate node ID
        unique_key = f"{receipt_data.get('merchant', 'unknown')}_{receipt_data.get('date', '')}_{receipt_data.get('total', 0)}"
        node_id = self.generate_node_id('Receipt', unique_key)
        
        # Build relationships
        relationships = []
        
        # Receipt FROM_STORE Company
        merchant = receipt_data.get('merchant', 'Unknown')
        if merchant and merchant != 'Unknown':
            company_id = self.generate_node_id('Company', merchant)
            relationships.append(Relationship(
                from_node=node_id,
                to_node=company_id,
                rel_type='FROM_STORE',
                properties={'merchant_name': merchant}
            ))
        
        # Create node
        node = ParsedNode(
            node_id=node_id,
            node_type='Receipt',
            properties={
                **receipt_data,
                'filename': filename,
                'parsed_at': datetime.now().isoformat(),
                'parser': 'docling'
            },
            relationships=relationships,
            searchable_text=self._build_searchable_text(receipt_data)
        )
        
        return node
    
    def _build_searchable_text(self, receipt_data: Dict[str, Any]) -> str:
        """Build searchable text for vector embedding"""
        parts = []
        
        if receipt_data.get('merchant'):
            parts.append(f"Receipt from {receipt_data['merchant']}")
        
        if receipt_data.get('total'):
            parts.append(f"Total: ${receipt_data['total']:.2f}")
        
        if receipt_data.get('date'):
            parts.append(f"Date: {receipt_data['date']}")
        
        if receipt_data.get('category'):
            parts.append(f"Category: {receipt_data['category']}")
        
        if receipt_data.get('items'):
            items_text = ", ".join([item.get('name', '') for item in receipt_data['items'][:5]])
            parts.append(f"Items: {items_text}")
        
        return " | ".join(parts)
    
    def _create_empty_receipt_node(self, filename: str, email_date: Optional[str] = None) -> ParsedNode:
        """
        Create minimal receipt node when parsing fails
        """
        # Extract date from email_date if available, otherwise use today
        receipt_date = None
        if email_date:
            try:
                # Try to parse email date format
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(email_date)
                receipt_date = dt.strftime('%Y-%m-%d')
            except Exception:
                receipt_date = datetime.now().strftime('%Y-%m-%d')
        else:
            receipt_date = datetime.now().strftime('%Y-%m-%d')
        
        return ParsedNode(
            node_id=self.generate_node_id('Receipt', filename),
            node_type='Receipt',
            properties={
                'filename': filename,
                'merchant': 'Unknown',
                'total': 0.0,
                'date': receipt_date,  # Required property
                'confidence': 0.0,
                'parsing_failed': True
            },
            relationships=[]
        )
    
    def _create_default_receipt_data(self) -> Dict[str, Any]:
        """Create default receipt data structure"""
        return {
            'merchant': 'Unknown',
            'total': 0.0,
            'subtotal': None,
            'tax': None,
            'date': None,
            'time': None,
            'payment_method': 'Unknown',
            'currency': 'USD',
            'category': 'other',
            'items': [],
            'receipt_number': None,
            'location': None,
            'confidence': 0.0
        }
    
    # _normalize_date removed - using base class implementation
    
    def _is_image(self, filename: str) -> bool:
        """Check if file is an image"""
        return filename.lower().endswith(('.jpg', '.jpeg', '.png', '.tiff', '.tif', '.gif'))
