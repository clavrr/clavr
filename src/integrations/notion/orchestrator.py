"""
Notion Bot Orchestrator

Main orchestrator that ties all Notion integrations together.
Implements all three capabilities:
1. GraphRAG (Knowledge Retrieval)
2. Autonomous Execution (Action)
3. Automation and Efficiency (Optimization)
"""
from typing import Optional, Dict, Any
import asyncio
import signal

from .client import NotionClient
from .config import NotionConfig
from .rag_integration import NotionGraphRAGIntegration
from .autonomous_execution import NotionAutonomousExecution
from .automation_efficiency import NotionAutomationAndEfficiency
from src.utils.logger import setup_logger
from src.utils.config import load_config

logger = setup_logger(__name__)


class NotionOrchestrator:
    """
    Main Notion orchestrator coordinating all integrations.
    
    Implements:
    1. GraphRAG - Enhanced Knowledge and RAG (Retrieval)
    2. Autonomous Execution - Automated, Context-Driven Actions
    3. Automation and Efficiency - Automation for productivity
    """
    
    def __init__(
        self,
        config: Optional[Any] = None,
        graph_manager: Optional[Any] = None,
        rag_engine: Optional[Any] = None,
        enable_all_capabilities: bool = True
    ):
        """
        Initialize Notion orchestrator.
        
        Args:
            config: Optional configuration object
            graph_manager: Optional KnowledgeGraphManager for ArangoDB
            rag_engine: Optional RAGEngine for Qdrant
            enable_all_capabilities: Whether to enable all three capabilities
        """
        # Validate Notion configuration
        if not NotionConfig.validate():
            raise ValueError("Notion configuration is invalid. Please check environment variables.")
        
        self.config = config or load_config()
        self.graph_manager = graph_manager
        self.rag_engine = rag_engine
        
        # Initialize Notion client
        self.notion_client = NotionClient()
        
        # Initialize capability integrations
        self.rag_integration = NotionGraphRAGIntegration(
            notion_client=self.notion_client,
            graph_manager=graph_manager,
            rag_engine=rag_engine,
            config=self.config
        ) if enable_all_capabilities else None
        
        self.autonomous_execution = NotionAutonomousExecution(
            notion_client=self.notion_client,
            rag_engine=rag_engine,
            config=self.config
        ) if enable_all_capabilities else None
        
        self.automation_efficiency = NotionAutomationAndEfficiency(
            notion_client=self.notion_client,
            config=self.config
        ) if enable_all_capabilities else None
        
        logger.info("Notion orchestrator initialized with all capabilities")
    
    async def handle_notion_query(
        self,
        query: str,
        database_id: str,
        query_type: str = 'search'
    ) -> Dict[str, Any]:
        """
        Handle a Notion query using GraphRAG.
        
        Args:
            query: User's search query
            database_id: Notion database to search
            query_type: Type of query ('search', 'synthesis', 'capture')
            
        Returns:
            Query result
        """
        try:
            if not self.rag_integration:
                return {'success': False, 'message': 'GraphRAG capability not enabled'}
            
            if query_type == 'search':
                return await self.rag_integration.graph_grounded_search(query, database_id)
            
            elif query_type == 'synthesis':
                return await self.rag_integration.cross_platform_synthesis(
                    query,
                    [database_id]
                )
            
            else:
                return {'success': False, 'message': f'Unknown query type: {query_type}'}
        
        except Exception as e:
            logger.error(f"Error handling Notion query: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    async def handle_autonomous_action(
        self,
        action_type: str,
        source_system: str,
        action_data: Dict[str, Any],
        target_database_id: str
    ) -> Dict[str, Any]:
        """
        Handle autonomous action execution.
        
        Args:
            action_type: Type of action ('meeting_held', 'email_sent', etc.)
            source_system: System action came from
            action_data: Action data
            target_database_id: Target Notion database
            
        Returns:
            Action result
        """
        try:
            if not self.autonomous_execution:
                return {'success': False, 'message': 'Autonomous execution not enabled'}
            
            return await self.autonomous_execution.database_management_at_scale(
                action_type,
                source_system,
                action_data,
                target_database_id
            )
        
        except Exception as e:
            logger.error(f"Error handling autonomous action: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    async def setup_personalized_memory(
        self,
        database_id: str,
        page_title: str,
        context_type: str,
        initial_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Setup personalized agent memory.
        
        Args:
            database_id: Database to store memory in
            page_title: Memory page title
            context_type: Context type
            initial_context: Initial context
            
        Returns:
            Setup result
        """
        try:
            if not self.automation_efficiency:
                return {'success': False, 'message': 'Automation capability not enabled'}
            
            return await self.automation_efficiency.setup_custom_agent_memory(
                database_id,
                page_title,
                context_type,
                initial_context
            )
        
        except Exception as e:
            logger.error(f"Error setting up personalized memory: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    async def enforce_data_organization(
        self,
        database_id: str,
        page_id: str,
        page_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Enforce data organization and integrity.
        
        Args:
            database_id: Database ID
            page_id: Page ID
            page_data: Page data
            
        Returns:
            Organization result
        """
        try:
            if not self.automation_efficiency:
                return {'success': False, 'message': 'Automation capability not enabled'}
            
            return await self.automation_efficiency.data_integrity_and_organization(
                database_id,
                page_id,
                page_data
            )
        
        except Exception as e:
            logger.error(f"Error enforcing data organization: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    async def personalize_output(
        self,
        response_text: str,
        company_standards_page_id: str,
        user_preferences_page_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Personalize output formatting.
        
        Args:
            response_text: Response to personalize
            company_standards_page_id: Company standards page
            user_preferences_page_id: Optional user preferences page
            
        Returns:
            Personalized response
        """
        try:
            if not self.automation_efficiency:
                return {'success': False, 'message': 'Automation capability not enabled'}
            
            return await self.automation_efficiency.personalize_output_formatting(
                response_text,
                company_standards_page_id,
                user_preferences_page_id
            )
        
        except Exception as e:
            logger.error(f"Error personalizing output: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        exit(0)
