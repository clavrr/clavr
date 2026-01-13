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
    2. Researcher: Queries Qdrant for relevant documents
    3. Contact Resolver: Resolves Slack IDs/Names to Email Addresses via ArangoDB
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
        
        # Initialize graph manager (for ArangoDB)
        if db:
            try:
                from ...services.indexing.graph.manager import KnowledgeGraphManager
                graph_manager = KnowledgeGraphManager(config=config)
                logger.info("[SLACK] Graph manager initialized")
            except Exception as e:
                logger.warning(f"Could not initialize graph manager: {e}")
        
        # Initialize RAG engine (for Qdrant)
        try:
            from api.dependencies import AppState
            rag_engine = AppState.get_rag_engine()
            logger.info("[SLACK] RAG engine initialized")
        except Exception as e:
            logger.warning(f"Could not initialize RAG engine: {e}")
        
        # 1. Contact Resolution (resolves names/IDs to emails)
        # Replaces ContactResolverRole with direct client usage
        slack_user_email = None
        try:
             # Get user info from Slack client
             user_info = slack_client.get_user_info(slack_user_id)
             if user_info and 'profile' in user_info:
                 slack_user_email = user_info['profile'].get('email')
                 if slack_user_email:
                     logger.info(f"[SLACK] Resolved user {slack_user_id} to email {slack_user_email}")
        except Exception as e:
            logger.warning(f"Could not resolve Slack user email: {e}")

        # Initialize tools for Executor
        tools = []
        try:
            from api.dependencies import AppState
            
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
                AppState.get_task_tool(user_id=db_user_id or 1, request=None, db=db),
                AppState.get_summarize_tool(),
                AppState.get_notion_tool(graph_manager=graph_manager_for_notion)
            ]
            logger.info(f"[SLACK] Initialized {len(tools)} tools for execution (including NotionTool)")
        except Exception as e:
            logger.error(f"Could not initialize tools: {e}", exc_info=True)
        
        # Use existing orchestrator for execution
        orchestrator = None
        try:
            from src.agents import SupervisorAgent
            # Use SupervisorAgent
            orchestrator = SupervisorAgent(
                tools=tools,
                config=config
            )
            logger.info("[SLACK] SupervisorAgent initialized")
        except Exception as e:
            logger.error(f"Could not create SupervisorAgent: {e}", exc_info=True)
            return "Sorry, I'm having trouble initializing my systems. Please try again later."
        
        # Execute query through orchestrator
        # The SupervisorAgent handles planning and execution

        
        if orchestrator:
            result = await orchestrator.route_and_execute(
                query=user_query,
                user_id=db_user_id
            )
            
            if result.get('success'):
                response_text = result.get('answer', str(result.get('results', [])))
                logger.info(f"[SLACK] SupervisorAgent returned success response ({len(response_text)} chars)")
                return response_text
            else:
                error_msg = result.get('error', "I encountered an error processing your request.")
                logger.warning(f"[SLACK] SupervisorAgent returned error: {error_msg}")
                return error_msg
        else:
            # Fallback if Supervisor unavailable
            logger.error("[SLACK] SupervisorAgent failed to initialize. Cannot process query.")
            return "Sorry, I'm having trouble initializing my internal systems. Please try again later."
        
    except Exception as e:
        logger.error(f"[SLACK] Error in clavr_orchestrator: {e}", exc_info=True)
        return f"Sorry, I encountered an error processing your request: {str(e)}"

