"""
Agent Mixins - Standardized patterns for agent development.

These mixins extract common patterns from domain agents to reduce
code duplication and ensure consistent behavior.

Usage:
    class EmailAgent(BaseAgent, ExtractParamsMixin, RoutingMixin):
        async def run(self, query, context):
            params = await self.extract_params_fast(query, schema, context)
            action = self.route_to_action(query, self.get_routes())
            ...
"""
from typing import Dict, Any, Optional, List, Protocol, runtime_checkable
import asyncio
from abc import ABC

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@runtime_checkable
class ParamExtractor(Protocol):
    """Protocol for agents that support parameter extraction."""
    async def _extract_params(
        self, 
        query: str, 
        schema: Dict[str, str], 
        user_id: Optional[int] = None,
        task_type: str = "general",
        use_fast_model: bool = True
    ) -> Dict[str, Any]:
        ...

@runtime_checkable
class Router(Protocol):
    """Protocol for agents that support routing."""
    def _route_query(self, query: str, routes: Dict[str, List[str]]) -> Optional[str]:
        ...


class ExtractParamsMixin:
    """
    Mixin for standardized parameter extraction with optimal defaults.
    
    Provides `extract_params_fast()` which automatically:
    - Extracts user_id from context
    - Uses fast model for simple extraction
    - Applies task_type optimization
    
    Requires the consuming class to implement `_extract_params` (usually via BaseAgent).
    """
    
    async def extract_params_fast(
        self,
        query: str,
        schema: Dict[str, str],
        context: Optional[Dict[str, Any]] = None,
        task_type: str = "simple_extraction"
    ) -> Dict[str, Any]:
        """
        Extract parameters with optimized defaults.
        
        Args:
            query: User query
            schema: Schema for extraction
            context: Context with user_id etc.
            task_type: Type of task (simple_extraction, planning, etc.)
            
        Returns:
            Extracted parameters dict
        """
        user_id = context.get('user_id') if context else None
        
        # Ensure self satisfies Protocol at runtime (duck typing check)
        if not hasattr(self, '_extract_params'):
            logger.error(f"Class {self.__class__.__name__} uses ExtractParamsMixin but lacks _extract_params method")
            return {}
            
        return await self._extract_params(
            query, 
            schema, 
            user_id=user_id, # type: ignore
            task_type=task_type,
            use_fast_model=True
        )


class RoutingMixin:
    """
    Mixin for standardized keyword-based routing.
    
    Provides `route_to_action()` which uses `_route_query()` from BaseAgent.
    """
    
    def get_routes(self) -> Dict[str, List[str]]:
        """
        Override in subclass to define routing keywords.
        
        Returns:
            Dict mapping action names to keyword lists
            
        Example:
            return {
                "create": ["create", "add", "new"],
                "list": ["list", "show", "get"],
                ...
            }
        """
        return {}
    
    def route_to_action(
        self, 
        query: str, 
        routes: Optional[Dict[str, List[str]]] = None
    ) -> Optional[str]:
        """
        Route query to action based on keyword matching.
        
        Args:
            query: User query
            routes: Optional routes dict (uses get_routes() if not provided)
            
        Returns:
            Action name or None
        """
        routes = routes or self.get_routes()
        
        # Ensure self has _route_query (usually from BaseAgent)
        if hasattr(self, '_route_query') and routes:
            return self._route_query(query, routes) # type: ignore
            
        return None


class ContextMixin:
    """
    Mixin for standardized context handling.
    
    Extracts common context fields: user_id, session_id, etc.
    """
    
    @staticmethod
    def extract_user_id(context: Optional[Dict[str, Any]]) -> Optional[int]:
        """Extract user_id from context."""
        return context.get('user_id') if context else None
    
    @staticmethod
    def extract_session_id(context: Optional[Dict[str, Any]]) -> Optional[str]:
        """Extract session_id from context."""
        return context.get('session_id') if context else None
    
    @staticmethod
    def extract_metadata(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract all metadata from context."""
        if not context:
            return {}
        return {
            'user_id': context.get('user_id'),
            'session_id': context.get('session_id'),
            'user_name': context.get('user_name'),
            'timestamp': context.get('timestamp'),
        }
        
    @staticmethod
    def extract_detailed_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract detailed typed context structure.
        
        Returns a guaranteed dictionary with keys, allowing safe access.
        """
        if not context:
            return {
                'user_id': None,
                'session_id': None,
                'email': None,
                'timezone': None
            }
            
        return {
            'user_id': context.get('user_id'),
            'session_id': context.get('session_id'),
            'email': context.get('email'),
            'timezone': context.get('timezone', 'UTC'),
            # Pass through original context
            'original': context
        }


class ValidationMixin:
    """
    Mixin for pre-flight validation of tool arguments.
    
    Integrates with ToolPreflightValidator.
    """
    
    _preflight_validator = None
    
    def get_preflight_validator(self):
        """
        Get or create preflight validator.
        
        Lazy-loads components to avoid circular imports and allow proper injection.
        Uses AppState and DomainContext if available on self.
        """
        if self._preflight_validator is None:
            try:
                from src.tools.preflight_validator import ToolPreflightValidator
                from api.dependencies import AppState
                
                # Try to get dependencies from self (Agent instance)
                graph_manager = None
                if hasattr(self, 'domain_context') and self.domain_context: # type: ignore
                    graph_manager = self.domain_context.graph_manager # type: ignore
                
                # Fallback to global singletons if not in domain context
                if not graph_manager:
                    graph_manager = AppState.get_knowledge_graph_manager()
                
                # Try to get contact resolver (usually via integration services or graph)
                # For now, we can pass None or a dedicated resolver if available
                # But ToolPreflightValidator can work with just graph_manager for some tasks
                
                # Initialize
                self._preflight_validator = ToolPreflightValidator(
                    graph_manager=graph_manager,
                    # contact_resolver=... # Add when ContactResolver is strictly available
                    calendar_service=AppState.get_calendar_tool() # Reuse calendar tool as service proxy if interface matches
                )
                
            except ImportError as e:
                logger.warning(f"Could not import validator dependencies: {e}")
                pass
            except Exception as e:
                logger.warning(f"Failed to initialize preflight validator: {e}")
                
        return self._preflight_validator
    
    async def validate_contact(
        self, 
        name_or_email: str, 
        user_id: int
    ) -> Dict[str, Any]:
        """
        Validate and resolve a contact reference.
        
        Returns:
            {
                'resolved': True/False,
                'email': resolved email or None,
                'alternatives': list of alternatives if ambiguous,
                'clarification_needed': True/False
            }
        """
        validator = self.get_preflight_validator()
        if not validator:
            return {'resolved': False, 'email': name_or_email}
        
        try:
            # We use validate_email_args underneath, assuming 'to' list
            result = await validator.validate_email_args(
                user_id=user_id,
                to=[name_or_email]
            )
            
            if result.status.value == "valid":
                resolved_list = result.resolved_args.get('to', [])
                if resolved_list:
                    return {
                        'resolved': True,
                        'email': resolved_list[0]
                    }
                else:
                     # e.g. Valid but no change (already email)
                     return {'resolved': True, 'email': name_or_email}
                     
            elif result.status.value == "ambiguous":
                # Find the issue relevant to this contact
                relevant_issues = [i for i in result.issues if i.value == name_or_email]
                alternatives = []
                prompt = result.clarification_prompt
                
                if relevant_issues:
                     alternatives = relevant_issues[0].candidates
                
                return {
                    'resolved': False,
                    'clarification_needed': True,
                    'alternatives': alternatives,
                    'prompt': prompt
                }
            else:
                return {'resolved': False, 'email': name_or_email}
        except Exception as e:
            logger.warning(f"Validation failed: {e}")
            return {'resolved': False, 'email': name_or_email}


# Combined mixin for convenience
class AgentMixin(ExtractParamsMixin, RoutingMixin, ContextMixin):
    """
    Combined mixin providing all standard agent patterns.
    
    Usage:
        class MyAgent(BaseAgent, AgentMixin):
            def get_routes(self):
                return {...}
            
            async def run(self, query, context):
                user_id = self.extract_user_id(context)
                action = self.route_to_action(query)
                params = await self.extract_params_fast(query, schema, context)
    """
    pass
