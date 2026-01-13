"""
Graph Audit Trail for COR Layer

Logs every agent action as a traceable path in the knowledge graph.
Enables compliance auditing and forensic tracing.

Pattern: (:User)-[:QUERIED]->(:Agent)-[:RETRIEVED]->(:Resource {id, type})
"""
from datetime import datetime
from typing import Dict, Any, Optional
from src.utils.logger import setup_logger
from .audit import SecurityAudit

logger = setup_logger(__name__)


class GraphAuditTrail:
    """
    Logs agent actions to the knowledge graph for compliance auditing.
    
    Each action creates an audit node and relationships:
    User -[PERFORMED]-> AuditEvent -[ACCESSED]-> Resource
    """
    
    _instance = None

    @classmethod
    def get_instance(cls) -> 'GraphAuditTrail':
        if cls._instance is None:
            cls._instance = GraphAuditTrail()
        return cls._instance
    
    def __init__(self, graph_manager=None):
        self._graph_manager = graph_manager
    
    def _get_graph_manager(self):
        """Lazy-load graph manager"""
        if self._graph_manager:
            return self._graph_manager
        try:
            from api.dependencies import AppState
            return AppState.get_graph_manager()
        except Exception:
            return None
    
    async def log_action(
        self,
        user_id: int,
        action_type: str,
        agent_name: str,
        resource_ids: list = None,
        resource_type: str = None,
        metadata: Dict[str, Any] = None
    ) -> Optional[str]:
        """
        Log an agent action to the graph.
        
        Args:
            user_id: User who triggered the action
            action_type: Type of action (QUERY, CREATE, UPDATE, DELETE, SEND)
            agent_name: Name of the agent (EmailAgent, CalendarAgent, etc.)
            resource_ids: IDs of resources accessed/modified
            resource_type: Type of resource (Email, CalendarEvent, Task, etc.)
            metadata: Additional context (query text, params, etc.)
            
        Returns:
            Audit event ID if successful
        """
        timestamp = datetime.utcnow().isoformat()
        audit_id = f"audit_{user_id}_{int(datetime.utcnow().timestamp() * 1000)}"
        
        # Always log to file-based audit (fast, reliable)
        SecurityAudit.log_event(
            event_type="AGENT_ACTION",
            status="LOGGED",
            severity="INFO",
            user_id=user_id,
            details={
                "audit_id": audit_id,
                "action_type": action_type,
                "agent": agent_name,
                "resource_type": resource_type,
                "resource_count": len(resource_ids) if resource_ids else 0,
                "metadata": metadata
            }
        )
        
        # Try to log to graph (best effort, don't block on failure)
        graph = self._get_graph_manager()
        if not graph:
            logger.debug("Graph audit: Graph manager unavailable, file log only")
            return audit_id
        
        try:
            # Create AuditEvent node
            audit_node_props = {
                "id": audit_id,
                "user_id": user_id,
                "timestamp": timestamp,
                "action_type": action_type,
                "agent": agent_name,
                "resource_type": resource_type,
                "resource_count": len(resource_ids) if resource_ids else 0,
                "query_snippet": (metadata.get('query', '')[:100] if metadata else None)
            }
            
            await graph.add_node(
                node_id=audit_id,
                node_type="AuditEvent",
                properties=audit_node_props
            )
            
            # Create User -[PERFORMED]-> AuditEvent relationship
            user_key = f"User/{user_id}"
            await graph.add_relationship(
                from_node=user_key,
                to_node=audit_id,
                rel_type="PERFORMED",
                properties={"timestamp": timestamp}
            )
            
            # Create AuditEvent -[ACCESSED]-> Resource relationships
            if resource_ids:
                for res_id in resource_ids[:10]:  # Limit to 10 resources
                    try:
                        await graph.add_relationship(
                            from_node=audit_id,
                            to_node=str(res_id),
                            rel_type="ACCESSED",
                            properties={
                                "timestamp": timestamp,
                                "action_type": action_type
                            }
                        )
                    except Exception:
                        # Resource node might not exist, skip
                        pass
            
            logger.debug(f"Graph audit logged: {audit_id}")
            return audit_id
            
        except Exception as e:
            logger.warning(f"Graph audit write failed: {e}")
            # File audit already logged, so this is acceptable
            return audit_id
    
    async def get_user_audit_trail(
        self,
        user_id: int,
        limit: int = 50,
        action_types: list = None
    ) -> list:
        """
        Retrieve audit trail for a user.
        
        Args:
            user_id: User to get trail for
            limit: Maximum events to return
            action_types: Filter by action types
            
        Returns:
            List of audit events
        """
        graph = self._get_graph_manager()
        if not graph:
            return []
        
        try:
            # AQL query for audit events
            aql = """
            FOR audit IN AuditEvent
                FILTER audit.user_id == @user_id
                SORT audit.timestamp DESC
                LIMIT @limit
                RETURN audit
            """
            
            results = await graph.query(aql, {
                'user_id': user_id,
                'limit': limit
            })
            
            return results or []
            
        except Exception as e:
            logger.warning(f"Failed to retrieve audit trail: {e}")
            return []
    
    async def get_resource_access_history(
        self,
        resource_id: str,
        limit: int = 20
    ) -> list:
        """
        Get who accessed a specific resource.
        
        Useful for investigating data leaks.
        """
        graph = self._get_graph_manager()
        if not graph:
            return []
        
        try:
            aql = """
            FOR edge IN ACCESSED
                FILTER edge._to == @resource_id
                FOR audit IN AuditEvent
                    FILTER audit.id == edge._from
                    SORT audit.timestamp DESC
                    LIMIT @limit
                    RETURN {
                        user_id: audit.user_id,
                        action_type: audit.action_type,
                        agent: audit.agent,
                        timestamp: audit.timestamp
                    }
            """
            
            results = await graph.query(aql, {
                'resource_id': resource_id,
                'limit': limit
            })
            
            return results or []
            
        except Exception as e:
            logger.warning(f"Failed to retrieve resource history: {e}")
            return []
