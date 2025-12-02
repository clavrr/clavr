"""
Agent Roles Module

Implements specialized roles for the ClavrAgent:
- AnalyzerRole: Understand query intent and complexity
- OrchestratorRole: Plan execution and manage dependencies
- DomainSpecialistRole: Execute domain-specific tasks
- SynthesizerRole: Combine results and format responses
- MemoryRole: Learn patterns and optimize execution

This module provides a role-based abstraction over the agent's capabilities
while maintaining backward compatibility with existing ClavrAgent interface.
"""

from .analyzer_role import AnalyzerRole, QueryAnalysis
from .orchestrator_role import OrchestratorRole, ExecutionPlan
from .domain_specialist_role import (
    DomainSpecialistRole,
    EmailSpecialistRole,
    CalendarSpecialistRole,
    TaskSpecialistRole,
    NotionSpecialistRole
)
from .synthesizer_role import SynthesizerRole
from .memory_role import MemoryRole
from .researcher_role import ResearcherRole, ResearchResult
from .contact_resolver_role import ContactResolverRole, ContactResolutionResult

__all__ = [
    'AnalyzerRole',
    'QueryAnalysis',
    'OrchestratorRole',
    'ExecutionPlan',
    'DomainSpecialistRole',
    'EmailSpecialistRole',
    'CalendarSpecialistRole',
    'TaskSpecialistRole',
    'NotionSpecialistRole',
    'SynthesizerRole',
    'MemoryRole',
    'ResearcherRole',
    'ResearchResult',
    'ContactResolverRole',
    'ContactResolutionResult',
]
