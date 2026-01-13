"""
Slack Integration Module

Provides Slack integration for Clavr agent using Socket Mode.
Implements the GraphRAG architecture with ArangoDB and Qdrant.
"""

from .client import SlackClient
from .event_handler import SlackEventHandler
from .contact_resolver import SlackContactResolver
from .orchestrator import clavr_orchestrator
from .ingestion import SlackIngestionPipeline
from .bot import SlackBot

__all__ = [
    'SlackClient',
    'SlackEventHandler',
    'SlackContactResolver',
    'clavr_orchestrator',
    'SlackIngestionPipeline',
    'SlackBot'
]



