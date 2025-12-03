"""
Orchestration Configuration - Centralized configuration

This module contains all configuration classes for orchestration:
- OrchestratorConfig: Configuration for pattern-based orchestrator
- AutonomousOrchestratorConfig: Configuration for autonomous orchestrator
- SynthesisConfig: Configuration for context synthesis
- CrossDomainConfig: Configuration for cross-domain queries
- DomainValidationConfig: Configuration for domain validation
"""

from .orchestrator_config import OrchestratorConfig
from .autonomous_config import AutonomousOrchestratorConfig
from .synthesis_config import SynthesisConfig
from .cross_domain_config import CrossDomainConfig
from .domain_validation_config import DomainValidationConfig
from .orchestrator_constants import (
    LOG_INFO, LOG_ERROR, LOG_OK, LOG_WARNING,
    LOG_AI, LOG_ALERT, LOG_CONTEXT, LOG_FAST, LOG_LLM,
    LOG_RESTART, LOG_SEARCH, LOG_STATS, LOG_TASK,
    INTENT_TO_TOOL_MAP,
    MULTI_STEP_SEPARATORS,
    MULTI_STEP_INDICATORS
)

__all__ = [
    'OrchestratorConfig',
    'AutonomousOrchestratorConfig',
    'SynthesisConfig',
    'CrossDomainConfig',
    'DomainValidationConfig',
    # Logging constants
    'LOG_INFO', 'LOG_ERROR', 'LOG_OK', 'LOG_WARNING',
    'LOG_AI', 'LOG_ALERT', 'LOG_CONTEXT', 'LOG_FAST', 'LOG_LLM',
    'LOG_RESTART', 'LOG_SEARCH', 'LOG_STATS', 'LOG_TASK',
    # Intent mapping
    'INTENT_TO_TOOL_MAP',
    'MULTI_STEP_SEPARATORS',
    'MULTI_STEP_INDICATORS'
]


