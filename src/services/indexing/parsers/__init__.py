"""
Parsers Package - Intelligent Data Parsing for Knowledge Graph

This package contains specialized parsers that transform raw data into
structured knowledge graph nodes.
"""

from .base import (
    BaseParser,
    ParsedNode,
    Relationship,
    Entity,
    ExtractedIntents
)
from .email_parser import EmailParser
from .receipt_parser import ReceiptParser
from .attachment_parser import AttachmentParser

__all__ = [
    'BaseParser',
    'ParsedNode',
    'Relationship',
    'Entity',
    'ExtractedIntents',
    'EmailParser',
    'ReceiptParser',
    'AttachmentParser',
]
