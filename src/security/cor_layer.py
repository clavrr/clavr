"""
COR Layer: Clavr Orchestration Resilient Layer

Central orchestrator for all security checks.

Phase 1: Input Validation, Output Sanitization
Phase 2: Rate Limiting, Parameter Validation, RBAC, Audit Trail
"""
from typing import Dict, Any, Optional, Tuple
from .detectors.prompt_guard import PromptGuard
from .detectors.data_guard import DataGuard
from .audit import SecurityAudit
from .governance.rate_limiter import ToolRateLimiter
from .governance.parameter_validator import ParameterValidator
from .governance.rbac import RBACEnforcer
from .audit_graph import GraphAuditTrail
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class CORLayer:
    """
    Clavr Orchestration Resilient (COR) Layer.
    
    Provides a unified security interface for agents:
    
    Phase 1:
    1. Input Validation (Prompt Guard)
    2. Output Sanitization (Data Guard)
    3. Security Auditing
    
    Phase 2:
    4. Rate Limiting (Tool Governance)
    5. Parameter Validation
    6. RBAC Enforcement
    7. Graph Audit Trail
    """
    
    _instance = None
    
    @classmethod
    def get_instance(cls, config: Dict[str, Any] = None) -> 'CORLayer':
        if cls._instance is None:
            if config is None:
                config = {}
            cls._instance = CORLayer(config)
        return cls._instance
        
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Phase 1 Components
        self.prompt_guard = PromptGuard(config)
        self.data_guard = DataGuard(config)
        
        # Phase 2 Components
        self.rate_limiter = ToolRateLimiter.get_instance()
        self.param_validator = ParameterValidator.get_instance()
        self.rbac = RBACEnforcer.get_instance()
        self.audit_trail = GraphAuditTrail.get_instance()
        
        logger.info("[SEC] COR Layer initialized (Phase 1 + 2)")

    # =========================================================================
    # Phase 1: Input/Output Guards
    # =========================================================================
    
    async def validate_input(self, query: str, user_id: Optional[int] = None) -> Tuple[bool, str]:
        """
        Validate incoming user query against injection attacks.
        
        Returns:
            (is_safe, failure_reason)
        """
        is_safe, reason, score = await self.prompt_guard.validate_input(query, user_id)
        if not is_safe:
            return False, reason
        return True, ""

    def sanitize_output(self, response: str, user_id: Optional[int] = None) -> str:
        """Sanitize outgoing agent response for PII."""
        # 1. Check for massive leaks first
        if self.data_guard.scan_for_leaks(response):
             return "[SECURITY_BLOCK] Response blocked due to potential data leakage (massive PII dump detected)."

        # 2. Redact specific PII
        return self.data_guard.sanitize_output(response, user_id)

    # =========================================================================
    # Phase 2: Tool Governance
    # =========================================================================
    
    async def check_tool_access(
        self,
        user_id: int,
        tool_name: str,
        params: Dict[str, Any] = None
    ) -> Tuple[bool, str]:
        """
        Full governance check before tool execution.
        
        Checks:
        1. Rate limit
        2. RBAC permission
        3. Parameter validation
        
        Args:
            user_id: User attempting the action
            tool_name: Tool/action name (e.g., 'email_send', 'calendar_create')
            params: Tool parameters for validation
            
        Returns:
            (is_allowed, rejection_reason)
        """
        # 1. Rate Limit Check
        allowed, reason = await self.rate_limiter.check_limit(user_id, tool_name)
        if not allowed:
            return False, reason
        
        # 2. RBAC Permission Check
        allowed, reason = await self.rbac.check_permission(user_id, tool_name)
        if not allowed:
            return False, reason
        
        # 3. Parameter Validation
        if params:
            valid, reason = self.param_validator.validate(tool_name, params, user_id)
            if not valid:
                return False, reason
        
        return True, ""
    
    async def record_tool_call(
        self,
        user_id: int,
        tool_name: str,
        agent_name: str,
        resource_ids: list = None,
        metadata: Dict[str, Any] = None
    ):
        """
        Record a successful tool call for rate limiting and auditing.
        """
        # Record for rate limiting
        await self.rate_limiter.record_call(user_id, tool_name)
        
        # Log to audit trail
        await self.audit_trail.log_action(
            user_id=user_id,
            action_type=tool_name.upper(),
            agent_name=agent_name,
            resource_ids=resource_ids,
            resource_type=tool_name.split('_')[0] if '_' in tool_name else tool_name,
            metadata=metadata
        )

    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def audit(self, event_type: str, details: Dict[str, Any], user_id: Optional[int] = None):
        """Log a custom security event."""
        SecurityAudit.log_event(event_type, "REPORTED", details, user_id)
    
    async def get_user_usage(self, user_id: int, tool_name: str) -> Dict:
        """Get current rate limit usage for a user's tool."""
        return await self.rate_limiter.get_usage(user_id, tool_name)
    
    async def get_audit_trail(self, user_id: int, limit: int = 50) -> list:
        """Get user's audit trail."""
        return await self.audit_trail.get_user_audit_trail(user_id, limit)

