"""
Notion Integration Module

Provides complete Notion integration for Clavr agent implementing three key capabilities:

1. 🔍 Enhanced Knowledge and RAG (Retrieval)
   - Graph-Grounded Search: Uses Notion API + Neo4j for contextual retrieval
   - Cross-Platform Synthesis: Combines Slack + Notion + other systems
   - Instant Knowledge Capture: Monitors Notion databases in real-time

2. 📋 Autonomous Workflow Execution (Action)
   - Database Management: Auto create/update Notion databases and pages
   - Goal-Driven Reporting: Generate complex reports from multiple sources
   - Seamless Integration: Updates Notion as external actions complete

3. ⚙️ Automation and Efficiency
   - Custom Agent Memory: Direct agent to specific Notion page/database for context
   - Data Integrity: Auto-enforce organization, tagging, categorization
   - Personalization: Adapt output format and tone to company/user standards
"""

from .client import NotionClient
from .config import NotionConfig
from .service import NotionService
from .rag_integration import NotionGraphRAGIntegration
from .autonomous_execution import NotionAutonomousExecution
from .automation_efficiency import NotionAutomationAndEfficiency
from .orchestrator import NotionOrchestrator
from .exceptions import (
    NotionServiceException,
    NotionPageNotFoundException,
    NotionDatabaseNotFoundException,
    NotionAuthenticationException,
    ServiceUnavailableException
)

__all__ = [
    'NotionClient',
    'NotionConfig',
    'NotionService',
    'NotionGraphRAGIntegration',
    'NotionAutonomousExecution',
    'NotionAutomationAndEfficiency',
    'NotionOrchestrator',
    'NotionServiceException',
    'NotionPageNotFoundException',
    'NotionDatabaseNotFoundException',
    'NotionAuthenticationException',
    'ServiceUnavailableException',
]
