"""
Integrations Module

Provides integrations with external platforms like Slack, Teams, etc.

All integrations inherit from BaseIntegration which provides:
- Service integration (EmailService, CalendarService, TaskService)
- AI component integration (RAGEngine, LLMFactory, ConversationMemory)
- Agent role integration (AnalyzerRole, ResearcherRole, ContactResolverRole, etc.)
"""

from .integration_base import BaseIntegration

__all__ = ['BaseIntegration']

