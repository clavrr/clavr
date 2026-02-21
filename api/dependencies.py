"""
API Dependencies
Provides shared dependencies for FastAPI routers using proper dependency injection
"""
from __future__ import annotations

from typing import Optional, Generator, Any, TYPE_CHECKING
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends, Request, HTTPException, status

from src.utils.config import load_config, Config
from src.database import get_db, get_async_db, User
from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from src.ai.rag import RAGEngine
    from src.ai.llm_factory import LLMFactory
    from api.websocket_manager import ConnectionManager
from src.tools import EmailTool, CalendarTool, TaskTool, SummarizeTool, NotionTool, KeepTool, FinanceTool
from src.tools.weather.tool import WeatherTool
from src.services.indexing.event_stream import EventStreamHandler
from src.services.indexing.topic_extractor import TopicExtractor
from src.services.indexing.temporal_indexer import TemporalIndexer
from src.services.indexing.relationship_strength import RelationshipStrengthManager

logger = setup_logger(__name__)


# ============================================
# APPLICATION STATE (Singleton Pattern)
# ============================================

class AppState:
    """Application state holder for singleton instances"""
    _config: Optional[Config] = None
    _rag_engine: Optional[RAGEngine] = None
    _email_tool: Optional[EmailTool] = None
    _calendar_tool: Optional[CalendarTool] = None
    _task_tool: Optional[TaskTool] = None
    _summarize_tool: Optional[SummarizeTool] = None
    _notion_tool: Optional[NotionTool] = None
    _keep_tool: Optional[KeepTool] = None
    _weather_tool: Optional[WeatherTool] = None
    _finance_tool: Optional[FinanceTool] = None
    _orchestrator: Optional[Any] = None
    _connection_manager: Optional[ConnectionManager] = None
    _topic_extractor: Optional[TopicExtractor] = None
    _temporal_indexer: Optional[TemporalIndexer] = None
    _relationship_manager: Optional[RelationshipStrengthManager] = None
    _event_handler: Optional[EventStreamHandler] = None
    _revenue_classifier: Optional[Any] = None
    _follow_up_tracker: Optional[Any] = None
    _customer_health: Optional[Any] = None
    _pipeline_service: Optional[Any] = None
    _meeting_roi: Optional[Any] = None
    
    @classmethod
    def get_config(cls) -> Config:
        """Get or create config singleton"""
        if cls._config is None:
            cls._config = load_config()
            logger.info("[OK] Configuration loaded")
        return cls._config

    @classmethod
    def _get_credentials(cls, user_id: int, provider: str, request: Optional[Any] = None) -> Optional[Any]:
        """
        Consolidated helper to get credentials.
        Prioritizes integration-specific credentials from UserIntegration table.
        """
        from src.core.credential_provider import CredentialProvider
        from src.auth.oauth import GMAIL_SCOPES, CALENDAR_SCOPES, TASKS_SCOPES, DRIVE_SCOPES, LOGIN_SCOPES
        
        # Map provider to specific scopes
        scopes_map = {
            'gmail': GMAIL_SCOPES,
            'google_calendar': CALENDAR_SCOPES,
            'google_tasks': TASKS_SCOPES,
            'google_drive': DRIVE_SCOPES,
        }
        target_scopes = scopes_map.get(provider)

        # Priority 1: CredentialProvider (specific integration tokens with correct scopes)
        try:
            creds = CredentialProvider.get_integration_credentials(
                user_id=user_id,
                provider=provider,
                auto_refresh=True
            )
            if creds:
                return creds
        except Exception as e:
            logger.warning(f"Failed to get integration credentials for {provider}: {e}")

        # Priority 2: Request session (fallback for Gmail/backward compatibility)
        if provider == 'gmail' and request and hasattr(request.state, 'session') and request.state.session:
            try:
                from src.database import get_db_context
                from src.auth.token_refresh import get_valid_credentials
                
                session = request.state.session
                if session.gmail_access_token:
                    with get_db_context() as db:
                        # Pass GMAIL_SCOPES to ensure we don't request too much on refresh
                        return get_valid_credentials(db, session, scopes=GMAIL_SCOPES, auto_refresh=True)
            except Exception as e:
                logger.warning(f"Failed to get credentials from request session: {e}")
        
        return None
        
    @classmethod
    def get_knowledge_graph_manager(cls):
        """Get or create KnowledgeGraphManager singleton"""
        if not hasattr(cls, '_graph_manager') or cls._graph_manager is None:
            config = cls.get_config()
            try:
                from src.services.indexing.graph.manager import KnowledgeGraphManager
                cls._graph_manager = KnowledgeGraphManager(config=config)
                logger.info("[OK] KnowledgeGraphManager initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize KnowledgeGraphManager: {e}")
                cls._graph_manager = None
        return cls._graph_manager
    
    @classmethod
    def get_connection_manager(cls) -> Optional[ConnectionManager]:
        """Get or create ConnectionManager singleton for WebSocket notifications."""
        if cls._connection_manager is None:
            try:
                from api.websocket_manager import ConnectionManager
                cls._connection_manager = ConnectionManager()
                logger.info("[OK] ConnectionManager initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize ConnectionManager: {e}")
                cls._connection_manager = None
        return cls._connection_manager
    
    @classmethod
    def get_rag_engine(cls) -> RAGEngine:
        """Get or create RAG engine singleton"""
        if cls._rag_engine is None:
            from src.ai.rag import RAGEngine
            config = cls.get_config()
            cls._rag_engine = RAGEngine(config, collection_name="email-knowledge")
            logger.info("[OK] RAG engine initialized")
        return cls._rag_engine
    
    @classmethod
    def get_conversation_rag_engine(cls) -> RAGEngine:
        """Get RAG engine for conversation messages (separate from email-knowledge).
        
        This prevents conversation_messages from polluting the email search index.
        """
        if not hasattr(cls, '_conversation_rag_engine'):
            cls._conversation_rag_engine = None
        
        if cls._conversation_rag_engine is None:
            from src.ai.rag import RAGEngine
            config = cls.get_config()
            cls._conversation_rag_engine = RAGEngine(config, collection_name="conversations")
            logger.info("[OK] Conversation RAG engine initialized (collection: conversations)")
        
        return cls._conversation_rag_engine
    
    @classmethod
    def get_hybrid_coordinator(cls) -> Optional[Any]:
        """Get or create HybridIndexCoordinator singleton for Graph+Vector search"""
        if not hasattr(cls, '_hybrid_coordinator'):
            cls._hybrid_coordinator = None
        
        if cls._hybrid_coordinator is None:
            try:
                from src.services.indexing.hybrid_index import HybridIndexCoordinator
                
                config = cls.get_config()
                graph_manager = cls.get_knowledge_graph_manager()
                rag_engine = cls.get_rag_engine()
                
                if graph_manager and rag_engine:
                    cls._hybrid_coordinator = HybridIndexCoordinator(
                        graph_manager=graph_manager,
                        rag_engine=rag_engine,
                        enable_graph=True,
                        enable_vector=True
                    )
                    logger.info("[OK] HybridIndexCoordinator initialized")
                else:
                    logger.warning("HybridIndexCoordinator skipped: missing graph_manager or rag_engine")
            except Exception as e:
                logger.warning(f"Failed to initialize HybridIndexCoordinator: {e}")
                cls._hybrid_coordinator = None
        
        return cls._hybrid_coordinator
    
    @classmethod
    def get_rag_tool(cls) -> RAGEngine:
        """Get or create RAG tool singleton (deprecated - use get_rag_engine instead)"""
        logger.warning("get_rag_tool is deprecated. Use get_rag_engine instead.")
        return cls.get_rag_engine()
    
    @classmethod
    def get_email_tool(cls, user_id: int, request: Optional[Any] = None, user_first_name: Optional[str] = None) -> EmailTool:
        """Get EmailTool with consolidated credentials. user_id is required."""
        """Get EmailTool with consolidated credentials."""
        config = cls.get_config()
        rag_engine = cls.get_rag_engine()
        hybrid_coordinator = cls.get_hybrid_coordinator()
        credentials = cls._get_credentials(user_id, 'gmail', request)
        
        return EmailTool(
            config=config, 
            rag_engine=rag_engine, 
            user_id=user_id, 
            credentials=credentials, 
            user_first_name=user_first_name,
            hybrid_coordinator=hybrid_coordinator
        )
    
    @classmethod
    def get_calendar_tool(cls, user_id: Optional[int] = None, request: Optional[Any] = None) -> CalendarTool:
        """Get CalendarTool with consolidated credentials."""
        config = cls.get_config()
        rag_engine = cls.get_rag_engine()
        
        if not user_id and request and hasattr(request.state, 'user') and request.state.user:
            user_id = request.state.user.id
        
        if not user_id:
            raise ValueError("user_id is required for get_calendar_tool - cannot default to 1 for multi-tenancy")
        
        credentials = cls._get_credentials(user_id, 'google_calendar', request)
        return CalendarTool(config=config, user_id=user_id, credentials=credentials, rag_engine=rag_engine)

    @classmethod
    def get_drive_service(cls, user_id: int, request: Optional[Any] = None) -> Any:
        """Get GoogleDriveService with consolidated credentials. user_id is required."""
        """Get GoogleDriveService with consolidated credentials."""
        config = cls.get_config()
        credentials = cls._get_credentials(user_id, 'google_drive', request)
        
        from src.integrations.google_drive.service import GoogleDriveService
        return GoogleDriveService(config=config, credentials=credentials)
    
    @classmethod
    def get_task_tool(cls, user_id: int, request: Optional[Any] = None, user_first_name: Optional[str] = None, db: Optional[Any] = None) -> TaskTool:
        """Get TaskTool with consolidated credentials. user_id is required."""
        config = cls.get_config()
        storage_path = f"./data/tasks_{user_id}.json"
        
        if request and hasattr(request.state, 'user') and request.state.user:
            user_id = request.state.user.id
            
        credentials = cls._get_credentials(user_id, 'google_tasks', request)
        
        return TaskTool(
            storage_path=storage_path, 
            config=config,
            user_id=user_id,
            credentials=credentials,
            user_first_name=user_first_name
        )
    
    @classmethod
    def get_summarize_tool(cls) -> SummarizeTool:
        """Get or create SummarizeTool singleton"""
        if cls._summarize_tool is None:
            config = cls.get_config()
            cls._summarize_tool = SummarizeTool(config=config)
            logger.info("[OK] SummarizeTool initialized")
        return cls._summarize_tool
    
    @classmethod
    def get_notion_tool(
        cls,
        graph_manager: Optional[Any] = None,
        rag_engine: Optional[Any] = None,
        user_id: Optional[int] = None,
    ) -> NotionTool:
        """
        Get NotionTool.

        Args:
            graph_manager: Optional KnowledgeGraphManager for Neo4j
            rag_engine: Optional RAGEngine for Pinecone (defaults to singleton)
            user_id: Optional user context for OAuth token lookup.
        """
        config = cls.get_config()
        if rag_engine is None:
            rag_engine = cls.get_rag_engine()

        # IMPORTANT: Notion OAuth token is user-specific. Never reuse a singleton
        # tool for authenticated chat requests, or user_id remains unset.
        if user_id is not None:
            return NotionTool(
                config=config,
                user_id=user_id,
                graph_manager=graph_manager,
                rag_engine=rag_engine,
            )

        # Backward-compatible singleton for non-user contexts.
        if cls._notion_tool is None:
            cls._notion_tool = NotionTool(
                config=config,
                graph_manager=graph_manager,
                rag_engine=rag_engine,
            )
            logger.info("[OK] NotionTool initialized")

        return cls._notion_tool
    
    @classmethod
    def get_keep_tool(cls, user_id: int, request: Optional[Any] = None) -> KeepTool:
        """Get KeepTool with consolidated credentials. user_id is required."""
        config = cls.get_config()
        credentials = cls._get_credentials(user_id, 'gmail', request) # Keep uses Gmail scopes
        return KeepTool(config=config, user_id=user_id, credentials=credentials)
    
    @classmethod
    def get_weather_tool(cls) -> WeatherTool:
        """
        Get or create WeatherTool singleton.
        
        Weather tool doesn't require user-specific credentials - it uses 
        the Google Maps API key from config.
        """
        if cls._weather_tool is None:
            config = cls.get_config()
            cls._weather_tool = WeatherTool(config=config)
            logger.info("[OK] WeatherTool initialized")
        return cls._weather_tool
    
    @classmethod
    def get_drive_tool(cls, user_id: int, request: Optional[Any] = None):
        """Get DriveTool with consolidated credentials. user_id is required."""
        from src.tools.drive import DriveTool
        config = cls.get_config()
        credentials = cls._get_credentials(user_id, 'google_drive', request)
        
        try:
            return DriveTool(config=config, user_id=user_id, credentials=credentials)
        except Exception as e:
            logger.error(f"Failed to initialize DriveTool: {e}")
            return DriveTool(config=config, user_id=user_id, credentials=None)
    
    @classmethod
    def get_brief_service(cls, user_id: int, request: Optional[Any] = None) -> Any:
        """Get BriefService with aggregated services. user_id is required."""
        from src.services.dashboard.brief_service import BriefService
        from src.integrations.google_calendar.service import CalendarService
        config = cls.get_config()
        
        try:
            email_tool = cls.get_email_tool(user_id=user_id, request=request)
            email_tool._initialize_service()
            email_svc = email_tool._service
        except Exception:
            email_svc = None
            
        try:
            task_tool = cls.get_task_tool(user_id=user_id, request=request)
            task_svc = task_tool.task_service
        except Exception:
            task_svc = None
            
        try:
            cal_tool = cls.get_calendar_tool(user_id=user_id, request=request)
            cal_svc = CalendarService(config=config, credentials=cal_tool.credentials)
        except Exception:
            cal_svc = None
            
        return BriefService(
            config=config,
            email_service=email_svc,
            task_service=task_svc,
            calendar_service=cal_svc
        )

    @classmethod
    def get_brief_tool(cls, user_id: int = 1, request: Optional[Any] = None, user_first_name: Optional[str] = None) -> Any:
        """Get BriefTool with aggregated services."""
        from src.tools.brief.tool import BriefTool
        from src.ai.autonomy.briefing import BriefingGenerator
        
        config = cls.get_config()
        brief_service = cls.get_brief_service(user_id=user_id, request=request)
        brief_gen = BriefingGenerator(config=config)
        
        return BriefTool(
            config=config,
            user_id=user_id,
            user_first_name=user_first_name,
            brief_service=brief_service,
            brief_generator=brief_gen
        )
    
    # ============================================
    # REVENUE SERVICE FACTORIES
    # ============================================
    
    @classmethod
    def get_revenue_classifier(cls) -> Any:
        """Get or create RevenueSignalClassifier singleton."""
        if cls._revenue_classifier is None:
            from src.services.revenue_signals import RevenueSignalClassifier
            config = cls.get_config()
            cls._revenue_classifier = RevenueSignalClassifier(config=config)
            logger.info("[OK] RevenueSignalClassifier initialized")
        return cls._revenue_classifier

    @classmethod
    def get_follow_up_tracker(cls) -> Any:
        """Get or create FollowUpTracker singleton."""
        if cls._follow_up_tracker is None:
            from src.services.follow_up_tracker import FollowUpTracker
            config = cls.get_config()
            cls._follow_up_tracker = FollowUpTracker(config=config)
            logger.info("[OK] FollowUpTracker initialized")
        return cls._follow_up_tracker

    @classmethod
    def get_customer_health_service(cls, db_session: Optional[Any] = None) -> Any:
        """Get or create CustomerHealthService singleton."""
        if cls._customer_health is None:
            from src.services.customer_health import CustomerHealthService
            config = cls.get_config()
            cls._customer_health = CustomerHealthService(config=config, db_session=db_session)
            logger.info("[OK] CustomerHealthService initialized")
        return cls._customer_health

    @classmethod
    def get_pipeline_service(cls, db_session: Optional[Any] = None) -> Any:
        """Get or create PipelineService singleton."""
        if cls._pipeline_service is None:
            from src.services.pipeline_service import PipelineService
            config = cls.get_config()
            cls._pipeline_service = PipelineService(config=config, db_session=db_session)
            logger.info("[OK] PipelineService initialized")
        return cls._pipeline_service

    @classmethod
    def get_meeting_roi_service(cls, db_session: Optional[Any] = None) -> Any:
        """Get or create MeetingROIService singleton."""
        if cls._meeting_roi is None:
            from src.services.meeting_roi import MeetingROIService
            config = cls.get_config()
            cls._meeting_roi = MeetingROIService(config=config, db_session=db_session)
            logger.info("[OK] MeetingROIService initialized")
        return cls._meeting_roi

    @classmethod
    def get_orchestrator(cls, db: Optional[Any] = None, user_id: Optional[int] = None, request: Optional[Any] = None) -> Any:
        """
        Get or create orchestrator singleton.
        
        The orchestrator handles multi-step query execution with intelligent routing,
        query decomposition, and cross-domain coordination.
        
        Args:
            db: Optional database session for orchestrator operations
            user_id: Optional user ID for user-specific orchestration
            request: Optional FastAPI Request object for session-based credentials
        
        Returns:
            Orchestrator instance for handling complex multi-step queries
        """
        if cls._orchestrator is None:
            # Legacy orchestration module has been deprecated and removed
            # Raise explicit error instead of returning None to prevent NoneType errors
            raise NotImplementedError(
                "Legacy orchestration module is deprecated and removed. "
                "Use SupervisorAgent directly for multi-step query execution."
            )
        
        return cls._orchestrator
    
    @classmethod
    def get_finance_tool(cls, user_id: int) -> FinanceTool:
        """Get or create FinanceTool singleton. user_id is required."""
        if cls._finance_tool is None:
            config = cls.get_config()
            graph_manager = cls.get_knowledge_graph_manager()
            cls._finance_tool = FinanceTool(config=config, graph_manager=graph_manager, user_id=user_id)
            logger.info("[OK] FinanceTool initialized")
        return cls._finance_tool

    @classmethod
    def get_all_tools(cls, user_id: int, request: Optional[Any] = None, user_first_name: Optional[str] = None) -> list:
        """
        Get all available tools for a user, properly initialized with credentials.
        Used primarily by voice and chat interfaces.
        """
        from src.tools.maps.tool import MapsTool
        from src.tools.timezone.tool import TimezoneTool
        from src.tools.slack.tool import SlackTool
        from src.tools.asana.tool import AsanaTool
        from src.tools.ghost.tool import GhostTool
        
        config = cls.get_config()
        
        return [
            cls.get_task_tool(user_id=user_id, request=request, user_first_name=user_first_name),
            cls.get_calendar_tool(user_id=user_id, request=request),
            cls.get_email_tool(user_id=user_id, request=request, user_first_name=user_first_name),
            cls.get_brief_tool(user_id=user_id, request=request, user_first_name=user_first_name),
            cls.get_summarize_tool(),
            cls.get_keep_tool(user_id=user_id, request=request),
            cls.get_weather_tool(),
            cls.get_drive_tool(user_id=user_id, request=request),
            MapsTool(config=config),
            TimezoneTool(config=config),
            # Slack/Asana might need more user-specific setup if they have their own OAuth
            SlackTool(config=config, user_id=user_id),
            cls.get_notion_tool(user_id=user_id),
            AsanaTool(config=config, user_id=user_id),
            GhostTool(config=config, user_id=user_id)
        ]

    @classmethod
    def get_insight_service(cls) -> Optional[Any]:
        """Get or create InsightService singleton"""
        if not hasattr(cls, '_insight_service') or cls._insight_service is None:
            config = cls.get_config()
            graph_manager = cls.get_knowledge_graph_manager()
            if graph_manager:
                from src.services.insights.insight_service import InsightService
                cls._insight_service = InsightService(config, graph_manager)
                logger.info("[OK] InsightService initialized")
            else:
                cls._insight_service = None
        return cls._insight_service

    @classmethod
    def get_deep_work_logic(cls) -> Optional[Any]:
        """Get or create DeepWorkLogic singleton"""
        if not hasattr(cls, '_deep_work_logic') or cls._deep_work_logic is None:
            try:
                from src.features.protection.deep_work import DeepWorkLogic
                cls._deep_work_logic = DeepWorkLogic()
                logger.info("[OK] DeepWorkLogic initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize DeepWorkLogic: {e}")
                cls._deep_work_logic = None
        return cls._deep_work_logic

    @classmethod
    def get_cross_stack_context(cls) -> Optional[Any]:
        """Get or create CrossStackContext singleton"""
        if not hasattr(cls, '_cross_stack_context') or cls._cross_stack_context is None:
            try:
                from src.services.proactive.cross_stack_context import CrossStackContext
                config = cls.get_config()
                graph_manager = cls.get_knowledge_graph_manager()
                rag_engine = cls.get_rag_engine()
                cls._cross_stack_context = CrossStackContext(config, graph_manager=graph_manager, rag_engine=rag_engine)
                logger.info("[OK] CrossStackContext initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize CrossStackContext: {e}")
                cls._cross_stack_context = None
        return cls._cross_stack_context

    @classmethod
    def get_linear_service(cls, user_id: int) -> Optional[Any]:
        """Get or create LinearService for a user"""
        try:
            from src.integrations.linear.service import LinearService
            config = cls.get_config()
            return LinearService(config=config, user_id=user_id)
        except Exception as e:
            logger.warning(f"Failed to initialize LinearService: {e}")
            return None

    @classmethod
    def get_autonomous_bridge(cls, user_id: int) -> Optional[Any]:
        """Get AutonomousBridgeService for a user."""
        try:
            from src.services.autonomous_bridge import AutonomousBridgeService, _get_notion_service, _get_slack_client
            config = cls.get_config()
            linear_service = cls.get_linear_service(user_id)
            notion_service = _get_notion_service(config)
            slack_client = _get_slack_client(config, user_id)
            return AutonomousBridgeService(
                config=config,
                linear_service=linear_service,
                notion_service=notion_service,
                slack_client=slack_client,
                user_id=user_id,
            )
        except Exception as e:
            logger.warning(f"Failed to initialize AutonomousBridgeService: {e}")
            return None

    @classmethod
    def get_ghost_tool(cls, user_id: int) -> Any:
        """Get or create GhostTool for a user"""
        from src.tools.ghost.tool import GhostTool
        config = cls.get_config()
        return GhostTool(config=config, user_id=user_id)

    @classmethod
    def get_supervisor_agent(cls, user_id: int) -> Optional[Any]:
        """Get or create SupervisorAgent for a user."""
        from src.agents.supervisor import SupervisorAgent
        config = cls.get_config()
        # Use simple MemoryOrchestrator if available
        try:
            from src.memory.orchestrator import MemoryOrchestrator
            memory_orchestrator = MemoryOrchestrator(
                config=config,
                graph_manager=cls.get_knowledge_graph_manager(),
                rag_engine=cls.get_rag_engine(),
                semantic_memory=cls.get_insight_service(), # Using insight service as semantic memory provider
                deep_work_logic=cls.get_deep_work_logic(),
                cross_stack_context=cls.get_cross_stack_context(),
                linear_service=cls.get_linear_service(user_id)
            )
        except ImportError:
            memory_orchestrator = None
            
        return SupervisorAgent(
            config=config,
            tools=cls.get_all_tools(user_id=user_id),
            user_id=user_id,
            memory_orchestrator=memory_orchestrator
        )

    @classmethod
    def get_auth_service(cls, db: AsyncSession) -> Any:
        """Get the Auth service."""
        from src.services.auth_service import AuthService
        config = cls.get_config()
        return AuthService(db=db, config=config)

    @classmethod
    def get_integration_service(cls, db: AsyncSession) -> Any:
        """Get the Integration service."""
        from src.services.integration_service import IntegrationService
        config = cls.get_config()
        return IntegrationService(db=db, config=config)

    @classmethod
    def get_chat_service(cls, db: AsyncSession) -> Any:
        """Get the Chat service."""
        from src.services.chat_service import ChatService
        config = cls.get_config()
        return ChatService(db=db, config=config)

    @classmethod
    def get_topic_extractor(cls) -> Optional[TopicExtractor]:
        """Get or create TopicExtractor singleton"""
        if cls._topic_extractor is None:
            config = cls.get_config()
            graph_manager = cls.get_knowledge_graph_manager()
            if graph_manager:
                cls._topic_extractor = TopicExtractor(config, graph_manager)
            else:
                logger.warning("TopicExtractor skipped: missing graph_manager")
        return cls._topic_extractor

    @classmethod
    def get_temporal_indexer(cls) -> Optional[TemporalIndexer]:
        """Get or create TemporalIndexer singleton"""
        if cls._temporal_indexer is None:
            config = cls.get_config()
            graph_manager = cls.get_knowledge_graph_manager()
            rag_engine = cls.get_rag_engine()
            if graph_manager:
                cls._temporal_indexer = TemporalIndexer(config, graph_manager, rag_engine)
            else:
                logger.warning("TemporalIndexer skipped: missing graph_manager")
        return cls._temporal_indexer

    @classmethod
    def get_relationship_strength_manager(cls) -> Optional[RelationshipStrengthManager]:
        """Get or create RelationshipStrengthManager singleton"""
        if cls._relationship_manager is None:
            config = cls.get_config()
            graph_manager = cls.get_knowledge_graph_manager()
            if graph_manager:
                cls._relationship_manager = RelationshipStrengthManager(config, graph_manager)
            else:
                logger.warning("RelationshipStrengthManager skipped: missing graph_manager")
        return cls._relationship_manager

    @classmethod
    def get_event_stream_handler(cls) -> Optional[EventStreamHandler]:
        """Get or create EventStreamHandler singleton"""
        if cls._event_handler is None:
            config = cls.get_config()
            graph_manager = cls.get_knowledge_graph_manager()
            rag_engine = cls.get_rag_engine()
            hybrid_coordinator = cls.get_hybrid_coordinator()
            topic_extractor = cls.get_topic_extractor()
            temporal_indexer = cls.get_temporal_indexer()
            relationship_manager = cls.get_relationship_strength_manager()
            insight_service = cls.get_insight_service()
            
            if all([graph_manager, rag_engine, hybrid_coordinator]):
                cls._event_handler = EventStreamHandler(
                    config=config,
                    graph_manager=graph_manager,
                    rag_engine=rag_engine,
                    hybrid_coordinator=hybrid_coordinator,
                    topic_extractor=topic_extractor,
                    temporal_indexer=temporal_indexer,
                    relationship_manager=relationship_manager,
                    insight_service=insight_service
                )
                logger.info("[OK] EventStreamHandler initialized")
            else:
                logger.warning("EventStreamHandler skipped: missing core dependencies")
        return cls._event_handler

    @classmethod
    def reset(cls):
        """Reset all singletons (useful for testing)"""
        cls._config = None
        cls._rag_engine = None
        cls._email_tool = None
        cls._calendar_tool = None
        cls._task_tool = None
        cls._summarize_tool = None
        cls._orchestrator = None
        cls._event_handler = None
        cls._topic_extractor = None
        cls._temporal_indexer = None
        cls._relationship_manager = None
        if hasattr(cls, '_email_tool_cache'):
            cls._email_tool_cache = {}
        if hasattr(cls, '_task_tool_cache'):
            cls._task_tool_cache = {}
        logger.info("Reset application state")


# ============================================
# FASTAPI DEPENDENCIES
# ============================================

def get_config() -> Config:
    """
    FastAPI dependency for configuration
    
    Usage:
        @app.get("/")
        def endpoint(config: Config = Depends(get_config)):
            ...
    
    Returns:
        Config object loaded from config/config.yaml
    """
    return AppState.get_config()


def get_rag_engine() -> RAGEngine:
    """
    FastAPI dependency for RAG engine
    
    Usage:
        @app.get("/search")
        def search(rag: RAGEngine = Depends(get_rag_engine)):
            ...
    
    Returns:
        RAGEngine instance for email search and retrieval
    """
    return AppState.get_rag_engine()

def get_rag_tool() -> RAGEngine:
    """
    FastAPI dependency for RAG tool (deprecated - use get_rag_engine instead)
    
    Usage:
        @app.get("/search")
        def search(rag: RAGEngine = Depends(get_rag_tool)):
            ...
    
    Returns:
        RAGEngine instance for email search and retrieval
    """
    logger.warning("get_rag_tool dependency is deprecated. Use get_rag_engine instead.")
    return AppState.get_rag_engine()


def get_llm(config: Config = Depends(get_config)):
    """
    FastAPI dependency for LLM client
    
    Usage:
        @app.post("/generate")
        def generate(llm = Depends(get_llm)):
            ...
    
    Returns:
        LLM client instance (Google Gemini by default)
    """
    from src.ai.llm_factory import LLMFactory
    return LLMFactory.get_llm_for_provider(config, temperature=0.0)


def get_email_tool(user_id: int = 1, config: Config = Depends(get_config)) -> EmailTool:
    """
    FastAPI dependency for EmailTool (cached singleton)
    
    Note: This version doesn't have access to request. Use AppState.get_email_tool() 
    directly with request parameter when you need user credentials.
    
    Usage:
        @app.post("/chat")
        def chat(email_tool: EmailTool = Depends(get_email_tool)):
            ...
    
    Returns:
        EmailTool instance (without user credentials - will load from session if user_id provided)
    """
    return AppState.get_email_tool(user_id=user_id, request=None)


def get_calendar_tool(user_id: Optional[int] = None, request: Optional[Request] = None, config: Config = Depends(get_config)) -> CalendarTool:
    """
    FastAPI dependency for CalendarTool with user credentials
    
    Args:
        user_id: Optional user ID (will be extracted from request if not provided)
        request: FastAPI Request object to get session credentials
        config: Configuration object
    """
    # Extract user_id from request if not provided
    if not user_id and request:
        try:
            # Try to get user from request state if available
            if hasattr(request.state, 'user') and request.state.user:
                user_id = request.state.user.id
        except Exception as e:
            logger.debug(f"[Dependencies] Failed to extract user_id from request: {e}")
    
    return AppState.get_calendar_tool(user_id=user_id, request=request)


def get_drive_service(user_id: Optional[int] = None, request: Optional[Request] = None, config: Config = Depends(get_config)) -> Any:
    """FastAPI dependency for DriveService"""
    # Extract user_id from request if not provided
    if not user_id and request:
        try:
            if hasattr(request.state, 'user') and request.state.user:
                user_id = request.state.user.id
        except Exception as e:
            logger.debug(f"[Dependencies] Failed to extract user_id from request: {e}")
    return AppState.get_drive_service(user_id=user_id or 1, request=request)


def get_task_tool(user_id: int = 1, config: Config = Depends(get_config)) -> TaskTool:
    """FastAPI dependency for TaskTool (cached singleton per user)"""
    return AppState.get_task_tool(user_id=user_id)


def get_summarize_tool(config: Config = Depends(get_config)) -> SummarizeTool:
    """FastAPI dependency for SummarizeTool (cached singleton)"""
    return AppState.get_summarize_tool()


def get_orchestrator(
    user_id: Optional[int] = None,
    request: Optional[Request] = None,
    db: Optional[Any] = None
) -> Any:
    """
    FastAPI dependency for Orchestrator
    
    The orchestrator handles multi-step query execution with intelligent routing,
    query decomposition, execution planning, and cross-domain coordination.
    
    Usage:
        @app.post("/orchestrate")
        async def orchestrate(
            query: str,
            orchestrator = Depends(get_orchestrator),
            db: AsyncSession = Depends(get_db)
        ):
            result = await orchestrator.execute_query(query)
            return {"result": result}
    
    Args:
        user_id: Optional user ID for user-specific orchestration
        request: Optional FastAPI Request object for session-based credentials
        db: Optional database session for orchestrator operations
    
    Returns:
        Orchestrator instance or None if orchestration module not available
    """
    return AppState.get_orchestrator(db=db, user_id=user_id, request=request)


def get_auth_service(db: AsyncSession = Depends(get_async_db)) -> Any:
    """FastAPI dependency for AuthService."""
    return AppState.get_auth_service(db=db)


def get_integration_service(db: AsyncSession = Depends(get_async_db)) -> Any:
    """FastAPI dependency for IntegrationService."""
    return AppState.get_integration_service(db=db)


def get_chat_service(db: AsyncSession = Depends(get_async_db)) -> Any:
    """FastAPI dependency for ChatService."""
    return AppState.get_chat_service(db=db)


def get_event_stream_handler() -> Optional[EventStreamHandler]:
    """FastAPI dependency for EventStreamHandler"""
    return AppState.get_event_stream_handler()


def get_current_user(request: Request) -> User:
    """
    Dependency to get the currently authenticated user.
    Raises 401 if not authenticated.
    """
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return user


# Alias for backward compatibility and explicit requirement
get_current_user_required = get_current_user


def get_optional_user(request: Request) -> Optional[User]:
    """
    Dependency to get the currently authenticated user if available.
    Returns None if not authenticated.
    """
    return getattr(request.state, 'user', None)
