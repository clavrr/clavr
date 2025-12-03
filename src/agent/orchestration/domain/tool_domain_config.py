"""
Tool Domain Configuration - Centralized mapping of tools to domains

This module provides a single source of truth for:
- Tool to domain associations
- Tool naming conventions
- Domain hierarchies
- Tool capability metadata
- Domain-to-tool reverse mapping

This eliminates hardcoded tool mappings scattered throughout the codebase
and provides a unified interface for tool/domain routing decisions.

Integration Points:
- Used by: Orchestrator, ExecutionPlanner, DomainValidator, CrossDomainHandler
- Provides: Single source of truth for tool-domain mappings
- Enables: Consistent routing and validation across all orchestration components
- Supports: EMAIL, TASK, CALENDAR, NOTION, GENERAL, MIXED domains
"""

from typing import Dict, List, Optional, Set
from enum import Enum
from threading import Lock

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class Domain(Enum):
    """Canonical domain types for all routing and validation"""
    EMAIL = "email"
    TASK = "task"
    CALENDAR = "calendar"
    NOTION = "notion"
    # Note: Slack is a platform/entry point, not a data source domain
    GENERAL = "general"
    MIXED = "mixed"  # Query spans multiple domains


class ToolDomainConfig:
    """
    Centralized configuration for tool-to-domain mappings.
    
    This is the single source of truth for:
    - Which tools belong to which domains
    - How tool names map to domains
    - Domain-specific tool capabilities
    
    Usage:
        >>> config = ToolDomainConfig()
        >>> domain = config.get_domain_for_tool('email')
        Domain.EMAIL
        
        >>> config.register_tool('my_email_tool', Domain.EMAIL)
        >>> config.get_tools_for_domain(Domain.EMAIL)
        ['email', 'my_email_tool']
    """
    
    def __init__(self):
        """Initialize with standard tool mappings"""
        # Base tool-to-domain mappings
        # These are the canonical mappings - all tool names should normalize to one of these
        self._tool_to_domain: Dict[str, Domain] = {
            # Email domain tools
            'email': Domain.EMAIL,
            'email_tool': Domain.EMAIL,
            'analyze_email': Domain.EMAIL,
            'compose_email': Domain.EMAIL,
            'search_email': Domain.EMAIL,
            
            # Task domain tools
            'task': Domain.TASK,
            'tasks': Domain.TASK,
            'task_tool': Domain.TASK,
            'task_manager': Domain.TASK,
            'todo': Domain.TASK,
            
            # Calendar domain tools
            'calendar': Domain.CALENDAR,
            'calendar_tool': Domain.CALENDAR,
            'event_manager': Domain.CALENDAR,
            'schedule': Domain.CALENDAR,
            
            # Notion domain tools
            'notion': Domain.NOTION,
            'notion_tool': Domain.NOTION,
            'notion_search': Domain.NOTION,
            'notion_page': Domain.NOTION,
            'notion_database': Domain.NOTION,
            
            # General/utility tools
            'summarize': Domain.GENERAL,
            'summarize_tool': Domain.GENERAL,
            'summary': Domain.GENERAL,
            
            # Note: Slack is a platform/entry point, not a data source domain
        }
        
        # Canonical tool names per domain (for reverse lookup)
        # These are the preferred tool names when mapping domain -> tool
        self._domain_to_canonical_tool: Dict[Domain, str] = {
            Domain.EMAIL: 'email',
            Domain.TASK: 'tasks',
            Domain.CALENDAR: 'calendar',
            Domain.NOTION: 'notion',
            Domain.GENERAL: 'summarize',  # Summarize is the general utility tool
            Domain.MIXED: 'email'  # Fallback for mixed queries
        }
        
        # Build reverse mapping (domain to tools)
        self._domain_to_tools: Dict[Domain, Set[str]] = {}
        for tool_name, domain in self._tool_to_domain.items():
            if domain not in self._domain_to_tools:
                self._domain_to_tools[domain] = set()
            self._domain_to_tools[domain].add(tool_name)
        
        logger.debug(
            f"[CONFIG] ToolDomainConfig initialized: "
            f"{len(self._tool_to_domain)} tools across {len(self._domain_to_tools)} domains"
        )
    
    def register_tool(self, tool_name: str, domain: Domain) -> None:
        """
        Register a new tool with its domain.
        
        Args:
            tool_name: Name of the tool
            domain: Domain the tool belongs to
            
        Usage:
            >>> config.register_tool('custom_email_tool', Domain.EMAIL)
        """
        tool_name_lower = tool_name.lower()
        self._tool_to_domain[tool_name_lower] = domain
        
        if domain not in self._domain_to_tools:
            self._domain_to_tools[domain] = set()
        self._domain_to_tools[domain].add(tool_name_lower)
    
    def register_tools_batch(self, tools: Dict[str, Domain]) -> None:
        """
        Register multiple tools at once.
        
        Args:
            tools: Dictionary mapping tool names to domains
            
        Usage:
            >>> config.register_tools_batch({
            ...     'email_search': Domain.EMAIL,
            ...     'task_create': Domain.TASK,
            ...     'meeting_schedule': Domain.CALENDAR
            ... })
        """
        for tool_name, domain in tools.items():
            self.register_tool(tool_name, domain)
    
    def unregister_tool(self, tool_name: str) -> bool:
        """
        Unregister a tool from the configuration.
        
        Args:
            tool_name: Name of the tool to unregister
            
        Returns:
            True if tool was unregistered, False if not found
        """
        tool_name_lower = tool_name.lower()
        if tool_name_lower not in self._tool_to_domain:
            return False
        
        domain = self._tool_to_domain.pop(tool_name_lower)
        if domain in self._domain_to_tools:
            self._domain_to_tools[domain].discard(tool_name_lower)
        
        return True
    
    def get_domain_for_tool(self, tool_name: str) -> Optional[Domain]:
        """
        Get the domain for a given tool name.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Domain enum or None if tool not found
        """
        return self._tool_to_domain.get(tool_name.lower())
    
    def get_tools_for_domain(self, domain: Domain) -> List[str]:
        """
        Get all tools registered for a given domain.
        
        Args:
            domain: Domain to query
            
        Returns:
            List of tool names in that domain
        """
        return sorted(list(self._domain_to_tools.get(domain, set())))
    
    def is_tool_in_domain(self, tool_name: str, domain: Domain) -> bool:
        """
        Check if a tool belongs to a specific domain.
        
        Args:
            tool_name: Name of the tool
            domain: Domain to check
            
        Returns:
            True if tool is in domain, False otherwise
        """
        return self.get_domain_for_tool(tool_name) == domain
    
    def normalize_tool_name(self, tool_name: str) -> str:
        """
        Get the canonical tool name for a tool (case-insensitive lookup).
        
        Args:
            tool_name: Tool name to normalize
            
        Returns:
            Canonical tool name, or original if not found
        """
        tool_lower = tool_name.lower()
        if tool_lower in self._tool_to_domain:
            return tool_lower
        return tool_name
    
    def build_from_available_tools(self, tools: Dict[str, any]) -> Dict[str, Domain]:
        """
        Build tool-to-domain mapping from available tools.
        
        This method creates a mapping of tools that are actually available in the system.
        Unknown tools are mapped to GENERAL domain.
        
        Args:
            tools: Dict of available tools (name -> tool_object)
            
        Returns:
            Dict mapping tool names to domains
        """
        mapping = {}
        unregistered_tools = []
        
        for tool_name in tools.keys():
            tool_lower = tool_name.lower()
            domain = self.get_domain_for_tool(tool_lower)
            
            if domain is None:
                # Unknown tool gets GENERAL domain
                domain = Domain.GENERAL
                unregistered_tools.append(tool_lower)
            
            mapping[tool_lower] = domain
        
        # Log warning if unknown tools detected
        if unregistered_tools:
            logger.warning(
                f"[CONFIG] Unknown tools detected, mapped to GENERAL domain: {unregistered_tools}. "
                f"Consider registering these tools for proper routing."
            )
        
        return mapping
    
    def get_all_domains(self) -> List[Domain]:
        """
        Get all registered domains.
        
        Returns:
            List of all Domain enums that have tools
        """
        return sorted(list(self._domain_to_tools.keys()), key=lambda d: d.value)
    
    def get_all_tools(self) -> Dict[str, Domain]:
        """
        Get all registered tool-to-domain mappings.
        
        Returns:
            Dict of all tool names mapped to their domains
        """
        return dict(self._tool_to_domain)
    
    def to_dict(self) -> Dict[str, any]:
        """
        Export configuration as dictionary.
        
        Returns:
            Dict representation of the configuration
        """
        return {
            'tool_to_domain': dict(self._tool_to_domain),
            'domain_to_tools': {
                domain.value: list(tools) 
                for domain, tools in self._domain_to_tools.items()
            }
        }
    
    def __repr__(self) -> str:
        """String representation for debugging"""
        return (
            f"ToolDomainConfig("
            f"tools={len(self._tool_to_domain)}, "
            f"domains={len(self._domain_to_tools)})"
        )
    
    def validate_tool_exists(self, tool_name: str) -> bool:
        """
        Check if a tool is registered in the configuration.
        
        Args:
            tool_name: Name of the tool to check
            
        Returns:
            True if tool is registered, False otherwise
        """
        return tool_name.lower() in self._tool_to_domain
    
    def get_domain_name(self, domain: Domain) -> str:
        """
        Get human-readable domain name.
        
        Args:
            domain: Domain enum
            
        Returns:
            Domain name as string
        """
        return domain.value
    
    def get_all_tool_names(self) -> List[str]:
        """
        Get all registered tool names.
        
        Returns:
            Sorted list of all tool names
        """
        return sorted(list(self._tool_to_domain.keys()))
    
    def count_tools_in_domain(self, domain: Domain) -> int:
        """
        Get count of tools in a specific domain.
        
        Args:
            domain: Domain to count
            
        Returns:
            Number of tools in domain
        """
        return len(self._domain_to_tools.get(domain, set()))
    
    def map_domain_to_tool(self, domain: str, available_tools: Optional[Dict[str, any]] = None) -> Optional[str]:
        """
        Map a domain name to its canonical tool name.
        
        This is the reverse of get_domain_for_tool() and is used for routing
        queries to the correct tool based on detected domain.
        
        Args:
            domain: Domain name (string or Domain enum)
            available_tools: Optional dict of available tools to validate against
            
        Returns:
            Canonical tool name, or None if domain not found
            
        Example:
            >>> config.map_domain_to_tool('email')
            'email'
            >>> config.map_domain_to_tool('task')
            'tasks'
            >>> config.map_domain_to_tool('notion')
            'notion'
        """
        # Handle Domain enum
        if isinstance(domain, Domain):
            domain_enum = domain
        else:
            # Convert string to Domain enum
            domain_lower = domain.lower()
            domain_map = {
                'email': Domain.EMAIL,
                'task': Domain.TASK,
                'tasks': Domain.TASK,
                'calendar': Domain.CALENDAR,
                'notion': Domain.NOTION,
                'general': Domain.GENERAL,
                'mixed': Domain.MIXED
            }
            domain_enum = domain_map.get(domain_lower)
            if not domain_enum:
                logger.warning(f"[CONFIG] Unknown domain: {domain}, returning None")
                return None
        
        # Get canonical tool name
        canonical_tool = self._domain_to_canonical_tool.get(domain_enum)
        
        # If available_tools provided, validate tool exists
        if available_tools is not None:
            if canonical_tool and canonical_tool in available_tools:
                return canonical_tool
            
            # Try to find any tool in this domain
            tools_in_domain = self.get_tools_for_domain(domain_enum)
            for tool_name in tools_in_domain:
                if tool_name in available_tools:
                    logger.debug(f"[CONFIG] Using tool '{tool_name}' for domain '{domain_enum.value}' (canonical '{canonical_tool}' not available)")
                    return tool_name
            
            logger.warning(
                f"[CONFIG] No available tool found for domain '{domain_enum.value}'. "
                f"Canonical: '{canonical_tool}', Available tools: {list(available_tools.keys())}"
            )
            return None
        
        return canonical_tool
    
    def get_canonical_tool_for_domain(self, domain: Domain) -> Optional[str]:
        """
        Get the canonical tool name for a domain.
        
        Args:
            domain: Domain enum
            
        Returns:
            Canonical tool name, or None if not found
        """
        return self._domain_to_canonical_tool.get(domain)
    
    def set_canonical_tool_for_domain(self, domain: Domain, tool_name: str) -> bool:
        """
        Set the canonical tool name for a domain.
        
        Args:
            domain: Domain enum
            tool_name: Tool name to set as canonical
            
        Returns:
            True if set successfully, False if tool not registered for domain
        """
        if not self.is_tool_in_domain(tool_name, domain):
            logger.warning(
                f"[CONFIG] Cannot set canonical tool '{tool_name}' for domain '{domain.value}': "
                f"tool not registered in this domain"
            )
            return False
        
        self._domain_to_canonical_tool[domain] = tool_name.lower()
        logger.debug(f"[CONFIG] Set canonical tool '{tool_name}' for domain '{domain.value}'")
        return True
    
    def get_domain_string(self, domain: Domain) -> str:
        """
        Get domain as string (convenience method).
        
        Args:
            domain: Domain enum
            
        Returns:
            Domain value as string
        """
        return domain.value
    
    def normalize_domain_string(self, domain_str: str) -> Optional[Domain]:
        """
        Normalize a domain string to Domain enum.
        
        Args:
            domain_str: Domain string (case-insensitive)
            
        Returns:
            Domain enum or None if invalid
        """
        domain_lower = domain_str.lower()
        domain_map = {
            'email': Domain.EMAIL,
            'task': Domain.TASK,
            'tasks': Domain.TASK,
            'calendar': Domain.CALENDAR,
            'notion': Domain.NOTION,
            'general': Domain.GENERAL,
            'mixed': Domain.MIXED
        }
        return domain_map.get(domain_lower)



# Global singleton instance with thread-safe initialization
_global_tool_domain_config: Optional[ToolDomainConfig] = None
_config_lock: Lock = Lock()


def get_tool_domain_config() -> ToolDomainConfig:
    """
    Get or create the global ToolDomainConfig instance (thread-safe singleton).
    
    Returns:
        Global ToolDomainConfig instance
        
    Usage:
        >>> config = get_tool_domain_config()
        >>> domain = config.get_domain_for_tool('email')
        >>> tool = config.map_domain_to_tool('email')
    """
    global _global_tool_domain_config
    
    if _global_tool_domain_config is None:
        with _config_lock:
            # Double-check pattern for thread safety
            if _global_tool_domain_config is None:
                _global_tool_domain_config = ToolDomainConfig()
                logger.info("[CONFIG] Global ToolDomainConfig instance created")
    
    return _global_tool_domain_config


def reset_tool_domain_config() -> None:
    """
    Reset the global config (mainly for testing).
    
    WARNING: This should only be used in tests. Resetting the config
    in production can cause inconsistent behavior.
    """
    global _global_tool_domain_config
    
    with _config_lock:
        _global_tool_domain_config = None
        logger.debug("[CONFIG] Global ToolDomainConfig instance reset")
