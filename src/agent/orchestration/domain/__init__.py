"""
Domain Management - Domain detection, validation, and routing

This module contains domain-related functionality:
- DomainValidator: Validates and detects query domains
- ToolDomainConfig: Maps tools to domains
- RoutingAnalytics: Tracks routing decisions and outcomes
"""

from .domain_validator import DomainValidator
from .tool_domain_config import Domain, ToolDomainConfig, get_tool_domain_config
from .routing_analytics import get_routing_analytics, RoutingOutcome

__all__ = [
    'Domain',
    'DomainValidator',
    'ToolDomainConfig',
    'get_tool_domain_config',
    'get_routing_analytics',
    'RoutingOutcome'
]



