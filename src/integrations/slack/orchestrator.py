"""
Clavr Orchestrator for Slack

Main orchestrator function that integrates Slack queries with the GraphRAG backend.
Implements the multi-role agent architecture: Planner, Researcher, Contact Resolver, Executor.

This orchestrator integrates:
- Agent roles (AnalyzerRole, OrchestratorRole, ResearcherRole, ContactResolverRole, DomainSpecialistRole)
- Services (EmailService, CalendarService, TaskService via tools)
- AI components (RAGEngine, LLMFactory, ConversationMemory)
"""
from typing import Optional, Dict, Any
import asyncio

from .client import SlackClient
from ...utils.logger import setup_logger
from ...utils.config import load_config

logger = setup_logger(__name__)


async def clavr_orchestrator(
    user_query: str,
    slack_user_id: str,
    slack_channel_id: str,
    config: Optional[Any] = None,
    db: Optional[Any] = None,
    slack_client: Optional[SlackClient] = None
) -> str:
    """
    Main orchestrator function for Slack integration.
    
    This function implements the integrated pipeline with multiple agent roles:
    1. Planner: Decomposes the task
    2. Researcher: Queries Pinecone for relevant documents
    3. Contact Resolver: Resolves Slack IDs/Names to Email Addresses via Neo4j
    4. Executor: Calls external APIs (Google Calendar, etc.)
    
    Args:
        user_query: User's query text from Slack
        slack_user_id: Slack user ID (for contact resolution and personalization)
        slack_channel_id: Slack channel ID (for context)
        config: Optional configuration object
        db: Optional database session
        slack_client: Optional SlackClient instance
        
    Returns:
        Response text to post back to Slack
    """
    try:
        logger.info(f"[SLACK] Orchestrating query: {user_query[:100]}...")
        
        # Load config if not provided
        if not config:
            config = load_config()
        
        # Initialize Slack client if not provided
        if not slack_client:
            from .client import SlackClient
            slack_client = SlackClient()
        
        # Initialize services and AI components
        graph_manager = None
        rag_engine = None
        email_service = None
        
        # Initialize graph manager (for Neo4j)
        if db:
            try:
                from ...services.indexing.graph.manager import KnowledgeGraphManager
                graph_manager = KnowledgeGraphManager(config=config)
                logger.info("[SLACK] Graph manager initialized")
            except Exception as e:
                logger.warning(f"Could not initialize graph manager: {e}")
        
        # Initialize RAG engine (for Pinecone)
        try:
            from api.dependencies import AppState
            rag_engine = AppState.get_rag_engine()
            logger.info("[SLACK] RAG engine initialized")
        except Exception as e:
            logger.warning(f"Could not initialize RAG engine: {e}")
        
        # Initialize agent roles
        # 1. Researcher Role (queries Pinecone + Neo4j)
        researcher_role = None
        try:
            from ...agent.roles import ResearcherRole
            researcher_role = ResearcherRole(
                rag_engine=rag_engine,
                graph_manager=graph_manager,
                config=config
            )
            logger.info("[SLACK] ResearcherRole initialized")
        except Exception as e:
            logger.warning(f"Could not initialize ResearcherRole: {e}")
        
        # 2. Contact Resolver Role (resolves names/IDs to emails)
        contact_resolver_role = None
        try:
            from ...agent.roles import ContactResolverRole
            # Get email service for fallback resolution
            email_service = None
            try:
                from api.dependencies import AppState
                email_tool = AppState.get_email_tool(user_id=1, request=None)
                if email_tool and hasattr(email_tool, 'email_service'):
                    email_service = email_tool.email_service
            except Exception as e:
                logger.debug(f"Could not get email service for ContactResolverRole: {e}")
            
            contact_resolver_role = ContactResolverRole(
                slack_client=slack_client,
                graph_manager=graph_manager,
                email_service=email_service,
                config=config
            )
            logger.info("[SLACK] ContactResolverRole initialized")
        except Exception as e:
            logger.warning(f"Could not initialize ContactResolverRole: {e}")
        
        # 3. Analyzer Role (understands query intent)
        analyzer_role = None
        try:
            from ...agent.roles import AnalyzerRole
            analyzer_role = AnalyzerRole(config=config)
            logger.info("[SLACK] AnalyzerRole initialized")
        except Exception as e:
            logger.warning(f"Could not initialize AnalyzerRole: {e}")
        
        # Initialize tools for Executor role
        tools = []
        try:
            from api.dependencies import AppState
            
            # Get Slack user's email for user_id mapping (using ContactResolverRole)
            slack_user_email = None
            if contact_resolver_role:
                resolution_result = await contact_resolver_role.resolve_contact(
                    identifier=slack_user_id,
                    identifier_type='slack_id'
                )
                if resolution_result.success:
                    slack_user_email = resolution_result.resolved_email
            
            # Map Slack user to database user_id (if exists)
            # For now, use None or default to 1 - in production, you'd have a mapping table
            db_user_id = None
            if slack_user_email and db:
                try:
                    from ...database.models import User
                    from sqlalchemy.orm import Session
                    if isinstance(db, Session):
                        user = db.query(User).filter(User.email == slack_user_email).first()
                        if user:
                            db_user_id = user.id
                            logger.info(f"[SLACK] Mapped Slack user {slack_user_id} to DB user_id {db_user_id}")
                except Exception as e:
                    logger.debug(f"Could not map Slack user to DB user: {e}")
            
            # Initialize tools (they'll handle None user_id gracefully)
            # Get graph manager for NotionTool
            graph_manager_for_notion = graph_manager  # Use the same graph_manager from above
            
            tools = [
                AppState.get_email_tool(user_id=db_user_id or 1, request=None),
                AppState.get_calendar_tool(user_id=db_user_id, request=None),
                AppState.get_task_tool(user_id=db_user_id or 1, request=None),
                AppState.get_summarize_tool(),
                AppState.get_notion_tool(graph_manager=graph_manager_for_notion)
            ]
            logger.info(f"[SLACK] Initialized {len(tools)} tools for execution (including NotionTool)")
        except Exception as e:
            logger.error(f"Could not initialize tools: {e}", exc_info=True)
        
        # Use existing orchestrator for execution
        orchestrator = None
        try:
            from ...agent.orchestration import create_orchestrator
            orchestrator = create_orchestrator(
                tools=tools,
                config=config,
                db=db,
                rag_engine=rag_engine,
                graph_manager=graph_manager
            )
            logger.info("[SLACK] Orchestrator initialized with all agent roles")
        except Exception as e:
            logger.error(f"Could not create orchestrator: {e}", exc_info=True)
            return "Sorry, I'm having trouble initializing my systems. Please try again later."
        
        # Execute query through orchestrator with agent roles
        # The orchestrator implements:
        # - Planner role (query decomposition via OrchestratorRole)
        # - Researcher role (Pinecone queries via ResearcherRole)
        # - Contact Resolver role (name/ID resolution via ContactResolverRole)
        # - Executor role (tool execution via DomainSpecialistRole)
        
        # Optionally enhance query with research context before execution
        research_context = None
        if researcher_role:
            try:
                research_result = await researcher_role.research(
                    query=user_query,
                    limit=5,
                    use_vector=True,
                    use_graph=True
                )
                if research_result.success and research_result.combined_results:
                    research_context = research_result.get_top_results(3)
                    logger.info(f"[SLACK] Research found {len(research_context)} contextual results")
            except Exception as e:
                logger.debug(f"Research context gathering failed (non-critical): {e}")
        
        if orchestrator:
            result = await orchestrator.execute_query(
                query=user_query,
                user_id=db_user_id
            )
            
            if result.success:
                response_text = result.final_result
                logger.info(f"[SLACK] Orchestrator returned success response ({len(response_text)} chars)")
                return response_text
            else:
                error_msg = result.error_message or "I encountered an error processing your request."
                logger.warning(f"[SLACK] Orchestrator returned error: {error_msg}")
                return error_msg
        else:
            # Fallback: use ClavrAgent directly
            try:
                from ...agent import ClavrAgent
                from ...ai.conversation_memory import ConversationMemory
                
                # Initialize ConversationMemory with RAG for semantic search
                rag_engine = AppState.get_rag_engine() if AppState else None
                memory = ConversationMemory(db, rag_engine=rag_engine) if db else None
                agent = ClavrAgent(
                    tools=tools,
                    config=config,
                    memory=memory,
                    db=db,
                    user_first_name=None  # Could extract from Slack user info
                )
                
                response = await agent.execute(
                    query=user_query,
                    user_id=db_user_id,
                    session_id=f"slack_{slack_user_id}"
                )
                
                logger.info(f"[SLACK] ClavrAgent returned response ({len(response)} chars)")
                return response
                
            except Exception as e:
                logger.error(f"Error executing with ClavrAgent: {e}", exc_info=True)
                return f"Sorry, I encountered an error: {str(e)}"
        
    except Exception as e:
        logger.error(f"[SLACK] Error in clavr_orchestrator: {e}", exc_info=True)
        return f"Sorry, I encountered an error processing your request: {str(e)}"

