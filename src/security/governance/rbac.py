"""
RBAC (Role-Based Access Control) Enforcement for COR Layer

Checks user permissions before allowing access to sensitive tools.
Uses the knowledge graph (ArangoDB) to check for permission relationships.
"""
from typing import Dict, Any, Optional, Tuple
from src.utils.logger import setup_logger
from ..audit import SecurityAudit

logger = setup_logger(__name__)


# Define sensitive tools that require explicit permissions
PROTECTED_TOOLS: Dict[str, str] = {
    'email_send': 'email_write',           # Requires email write permission
    'calendar_create': 'calendar_write',   # Requires calendar write permission
    'calendar_delete': 'calendar_admin',   # Requires admin permission
    'task_create': 'tasks_write',
    'notion_create': 'notion_write',
    'notion_delete': 'notion_admin',
}

# Default permissions (everyone has these unless explicitly revoked)
DEFAULT_PERMISSIONS = [
    'email_read',
    'calendar_read', 
    'tasks_read',
    'notion_read',
    'notes_read',
    'notes_write',
]


class RBACEnforcer:
    """
    Enforces Role-Based Access Control via the knowledge graph.
    
    Checks ArangoDB for HAS_PERMISSION edges between User and Resources.
    """
    
    _instance = None

    @classmethod
    def get_instance(cls) -> 'RBACEnforcer':
        if cls._instance is None:
            cls._instance = RBACEnforcer()
        return cls._instance
    
    def __init__(self, graph_manager=None):
        self._graph_manager = graph_manager
        self._permission_cache: Dict[int, set] = {}  # Cache: {user_id: set(permissions)}
        self._cache_ttl_seconds = 300  # 5 min cache
    
    def _get_graph_manager(self):
        """Lazy-load graph manager to avoid circular imports"""
        if self._graph_manager:
            return self._graph_manager
        try:
            from api.dependencies import AppState
            return AppState.get_graph_manager()
        except Exception:
            return None
    
    async def check_permission(
        self, 
        user_id: int, 
        tool_name: str
    ) -> Tuple[bool, str]:
        """
        Check if a user has permission to use a tool.
        
        Args:
            user_id: The user's ID
            tool_name: The tool/action being attempted
            
        Returns:
            (is_allowed, rejection_reason)
        """
        # Check if tool requires special permission
        required_permission = PROTECTED_TOOLS.get(tool_name)
        
        if not required_permission:
            # Tool is not protected, allow by default
            return True, ""
        
        # Check default permissions first (fast path)
        if required_permission in DEFAULT_PERMISSIONS:
            return True, ""
        
        # Check graph for explicit permission
        user_permissions = await self._get_user_permissions(user_id)
        
        if required_permission in user_permissions:
            return True, ""
        
        # Check for wildcard/admin permissions
        if 'admin' in user_permissions or '*' in user_permissions:
            return True, ""
        
        # Log rejection
        SecurityAudit.log_event(
            event_type="RBAC_DENIED",
            status="BLOCKED",
            severity="WARNING",
            user_id=user_id,
            details={
                "tool": tool_name,
                "required_permission": required_permission,
                "user_permissions": list(user_permissions)[:10]  # Limit logged
            }
        )
        
        logger.warning(f"RBAC denied user {user_id} for {tool_name} (missing: {required_permission})")
        return False, f"You don't have permission to perform this action ({required_permission} required)."
    
    async def _get_user_permissions(self, user_id: int) -> set:
        """
        Get user's permissions from graph.
        Uses AQL to query HAS_PERMISSION edges.
        """
        # Check cache first
        if user_id in self._permission_cache:
            return self._permission_cache[user_id]
        
        permissions = set(DEFAULT_PERMISSIONS)
        
        graph = self._get_graph_manager()
        if not graph:
            logger.debug("RBAC: Graph manager unavailable, using default permissions")
            return permissions
        
        try:
            # AQL Query to find user's permissions
            # Pattern: User -[:HAS_PERMISSION]-> Permission
            aql_query = """
            FOR perm IN HAS_PERMISSION
                FILTER perm._from == @user_key
                RETURN perm.permission_name
            """
            
            # Also check role-based permissions
            role_query = """
            FOR role_edge IN HAS_ROLE
                FILTER role_edge._from == @user_key
                FOR perm IN ROLE_PERMISSION
                    FILTER perm._from == role_edge._to
                    RETURN perm.permission_name
            """
            
            user_key = f"User/{user_id}"
            
            # Execute direct permission query
            results = await graph.query(aql_query, {'user_key': user_key})
            for r in results or []:
                if r:
                    permissions.add(r)
            
            # Execute role-based permission query
            role_results = await graph.query(role_query, {'user_key': user_key})
            for r in role_results or []:
                if r:
                    permissions.add(r)
            
            # Cache results
            self._permission_cache[user_id] = permissions
            
        except Exception as e:
            logger.debug(f"RBAC graph query failed: {e}")
            # Fall back to default permissions on error
        
        return permissions
    
    def clear_cache(self, user_id: Optional[int] = None):
        """Clear permission cache for a user or all users."""
        if user_id:
            self._permission_cache.pop(user_id, None)
        else:
            self._permission_cache.clear()
    
    async def grant_permission(
        self, 
        user_id: int, 
        permission: str,
        granted_by: Optional[int] = None
    ) -> bool:
        """
        Grant a permission to a user (writes to graph).
        
        Args:
            user_id: User to grant permission to
            permission: Permission name
            granted_by: Admin user who granted it
        """
        graph = self._get_graph_manager()
        if not graph:
            return False
        
        try:
            from datetime import datetime
            
            # Create permission edge
            await graph.add_relationship(
                from_node=f"User/{user_id}",
                to_node=f"Permission/{permission}",
                rel_type="HAS_PERMISSION",
                properties={
                    "permission_name": permission,
                    "granted_at": datetime.utcnow().isoformat(),
                    "granted_by": granted_by
                }
            )
            
            # Clear cache
            self.clear_cache(user_id)
            
            logger.info(f"Granted permission '{permission}' to user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to grant permission: {e}")
            return False
