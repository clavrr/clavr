"""
Notion Autonomous Database Management

Provides automatic database management based on external actions.
"""
from typing import Optional, Dict, Any

from ...integrations.notion.service import NotionService
from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class NotionAutoManagement:
    """
    Autonomous database management for Notion.
    
    Provides:
    - Automatic database entry creation/updates based on external actions
    - Goal-driven reporting
    - Seamless integration with other systems
    """
    
    def __init__(
        self,
        notion_service: Optional[NotionService] = None,
        autonomous_execution: Optional[Any] = None  # For backward compatibility
    ):
        """
        Initialize Notion auto-management.
        
        Args:
            notion_service: NotionService instance (preferred)
            autonomous_execution: NotionAutonomousExecution instance (for backward compatibility)
        """
        self.notion_service = notion_service
        # Fallback for backward compatibility
        if not self.notion_service and autonomous_execution:
            self._autonomous_execution = autonomous_execution
        logger.info("[NOTION_AUTO_MGMT] Initialized")
    
    async def manage_database(
        self,
        action_type: str,
        source_system: str,
        action_data: Dict[str, Any],
        target_database_id: str
    ) -> Dict[str, Any]:
        """
        Automatically manage Notion database based on external action.
        
        Args:
            action_type: Type of action ('meeting_held', 'email_sent', etc.)
            source_system: Source system ('calendar', 'slack', 'email', etc.)
            action_data: Data from the action
            target_database_id: Notion database to update
            
        Returns:
            Result of database management operation
        """
        if self.notion_service:
            try:
                return await self.notion_service.auto_manage_database(
                    action_type=action_type,
                    source_system=source_system,
                    action_data=action_data,
                    target_database_id=target_database_id
                )
            except Exception as e:
                logger.error(f"[NOTION_AUTO_MGMT] Error managing database: {e}")
                return {
                    'success': False,
                    'error': str(e)
                }
        
        # Fallback for backward compatibility
        if hasattr(self, '_autonomous_execution') and self._autonomous_execution:
            return await self._autonomous_execution.database_management_at_scale(
                action_type=action_type,
                source_system=source_system,
                action_data=action_data,
                target_database_id=target_database_id
            )
        
        return {
            'success': False,
            'error': 'Autonomous execution integration not available'
        }
    
    def format_management_result(self, result: Dict[str, Any]) -> str:
        """
        Format auto-management result for display.
        
        Args:
            result: Management result dictionary
            
        Returns:
            Formatted string
        """
        if result.get('success'):
            created = result.get('created_entries', [])
            updated = result.get('updated_entries', [])
            return f"Database management completed: {len(created)} entries created, {len(updated)} entries updated"
        else:
            return f"Database management failed: {result.get('message', 'Unknown error')}"

