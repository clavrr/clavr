"""
Base Tool Class for Clavr
Extends LangChain's BaseTool with Clavr-specific functionality 
"""
from abc import ABC
from typing import Optional, Type, Dict, Any
from langchain.tools import BaseTool
from pydantic import BaseModel

from ..utils.logger import setup_logger
from ..utils.config import Config
from .constants import ToolConfig

logger = setup_logger(__name__)


class ClavrBaseTool(BaseTool, ABC):
    """
    Base class for all Clavr tools 
    
    Provides:
    - Standard logging
    - Error handling
    - Common utilities
    - LangChain compatibility
    - NLP utilities (QueryClassifier, FlexibleDateParser, LLM client)
    - Performance tracking
    - Shared credential retrieval utilities
    """
    
    # Tool metadata (override in subclasses)
    name: str = "base_tool"
    description: str = "Base tool class"
    args_schema: Optional[Type[BaseModel]] = None
    return_direct: bool = False  # Return result directly or pass to agent
    
    def __init__(self, config: Optional[Config] = None, **kwargs):
        """
        Initialize tool with logging and NLP utilities
        
        Args:
            config: Optional configuration object for NLP utilities
        """
        super().__init__(**kwargs)
        self.config = config
        
        # Initialize NLP utilities if config available
        # Use _set_attr helper to bypass Pydantic validation cleanly
        self._set_attr('classifier', None)
        self._set_attr('date_parser', None)
        self._set_attr('llm_client', None)
        
        if config:
            self._init_nlp_utilities()
        
        logger.info(f"[OK] {self.name} tool initialized")
    
    def _set_attr(self, name: str, value: Any) -> None:
        """
        Helper method to set attributes that bypass Pydantic validation.
        
        This is cleaner than using object.__setattr__ directly throughout the code.
        Always uses object.__setattr__ to bypass Pydantic validation.
        
        Args:
            name: Attribute name
            value: Attribute value
        """
        object.__setattr__(self, name, value)
    
    def _init_nlp_utilities(self) -> None:
        """
        Initialize NLP utilities (QueryClassifier, FlexibleDateParser, LLM client).
        
        This method is called automatically if config is provided.
        Subclasses can override this if they need custom NLP initialization.
        """
        try:
            from ..ai.query_classifier import QueryClassifier
            from ..utils import FlexibleDateParser
            from ..ai.llm_factory import LLMFactory
            
            self._set_attr('classifier', QueryClassifier(self.config))
            self._set_attr('date_parser', FlexibleDateParser())
            self._set_attr('llm_client', LLMFactory.get_llm_for_provider(
                self.config, 
                temperature=ToolConfig.DEFAULT_LLM_TEMPERATURE
            ))
            logger.info(f"[OK] {self.name} initialized with NLP capabilities")
        except Exception as e:
            logger.warning(f"Enhanced NLP features not available for {self.name}: {e}")
    
    def _emit_workflow_event(self, workflow_emitter, event_type: str, message: str, **kwargs):
        """
        Helper method to emit workflow events if emitter is available.
        Handles async emission from synchronous context.
        
        Args:
            workflow_emitter: Optional WorkflowEventEmitter instance
            event_type: Type of event (e.g., 'validation_start', 'action_executing')
            message: Event message
            **kwargs: Additional event data
        """
        if not workflow_emitter:
            return
        
        try:
            import asyncio
            
            # Map string event types to emitter method names
            event_type_map = {
                'validation_start': 'emit_validation_start',
                'validation_check': 'emit_validation_check',
                'action_planned': 'emit_action_planned',
                'action_executing': 'emit_action_executing',
                'action_complete': 'emit_action_complete',
                'tool_progress': 'emit_tool_progress',
            }
            
            method_name = event_type_map.get(event_type)
            if method_name and hasattr(workflow_emitter, method_name):
                method = getattr(workflow_emitter, method_name)
                
                # Handle async emission from sync context
                try:
                    # Try to get the current event loop
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # If loop is running, schedule the coroutine
                        asyncio.create_task(method(message, **kwargs))
                    else:
                        # If loop exists but not running, run the coroutine
                        loop.run_until_complete(method(message, **kwargs))
                except RuntimeError:
                    # No event loop, create a new one
                    asyncio.run(method(message, **kwargs))
        except Exception as e:
            logger.debug(f"Failed to emit workflow event: {e}")
    
    def _get_credentials_from_session(
        self, 
        user_id: Optional[int], 
        service_name: str = "service"
    ) -> Optional[Any]:
        """
        Get Google OAuth credentials from user session.
        
        This is a shared utility method used by all tools that need Google API access.
        Uses get_db_context() for proper session management.
        
        Args:
            user_id: User ID to retrieve credentials for
            service_name: Service name for logging (e.g., "EMAIL", "CAL", "TASKS")
            
        Returns:
            Google OAuth credentials object or None if not available
        """
        if not user_id:
            logger.warning(f"[{service_name}] Cannot get credentials: no user_id provided")
            return None
        
        try:
            from ..database import get_db_context
            from ..database.models import Session as DBSession
            import os
            from datetime import datetime
            
            logger.info(f"[{service_name}] Looking up session for user_id={user_id}")
            with get_db_context() as db:
                # Get most recent active session for this user
                session = db.query(DBSession).filter(
                    DBSession.user_id == user_id,
                    DBSession.expires_at > datetime.utcnow()
                ).order_by(DBSession.created_at.desc()).first()
                
                if not session:
                    logger.warning(f"[{service_name}] No active session found for user {user_id}")
                    return None
                
                if not session.gmail_access_token:
                    logger.warning(f"[{service_name}] Session found for user {user_id} but no access token")
                    return None
                
                logger.info(f"[{service_name}] Found session with credentials for user {user_id}")
                
                # Get OAuth client credentials
                client_id = os.getenv('GOOGLE_CLIENT_ID')
                client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
                
                if not client_id or not client_secret:
                    logger.warning("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET not configured")
                    return None
                
                # Get valid credentials with automatic refresh
                from src.auth.token_refresh import get_valid_credentials
                credentials = get_valid_credentials(db, session, auto_refresh=True)
                
                if not credentials:
                    logger.warning(f"Failed to get valid credentials for user {user_id}")
                    return None
                
                logger.info(f"[OK] {service_name}Tool using credentials from session (user_id={user_id})")
                return credentials
                
        except Exception as e:
            logger.error(f"Failed to get credentials from session: {e}", exc_info=True)
            return None
    
    def _handle_error(self, error: Exception, context: str = "") -> str:
        """
        Standard error handling for all tools
        
        Args:
            error: Exception that occurred
            context: Additional context about what was being done
            
        Returns:
            User-friendly error message
        """
        error_msg = f"Error in {self.name}"
        if context:
            error_msg += f" ({context})"
        error_msg += f": {str(error)}"
        
        logger.error(error_msg, exc_info=True)
        return f"[ERROR] {error_msg}"
    
    def _log_execution(self, action: str, **kwargs):
        """Log tool execution for debugging"""
        logger.info(f"{self.name}.{action} called with {kwargs}")
    
    def _format_success(self, message: str) -> str:
        """Format success message consistently"""
        return f"[OK] {message}"
    
    def _format_list(self, items: list, title: str = "") -> str:
        """Format list of items for output"""
        if not items:
            return f"No {title} found"
        
        output = f"**{title}:**\n\n" if title else ""
        for i, item in enumerate(items, 1):
            output += f"{i}. {item}\n"
        return output
    
    def _has_nlp_support(self) -> bool:
        """Check if NLP utilities are available"""
        return self.classifier is not None or self.date_parser is not None or self.llm_client is not None
    
    def _classify_query(self, query: str) -> Dict[str, Any]:
        """
        Classify query using NLP if available
        
        Args:
            query: User query
            
        Returns:
            Classification dictionary with intent, confidence, entities, etc.
        """
        if not self.classifier:
            return {
                'intent': 'unknown',
                'confidence': ToolConfig.DEFAULT_CONFIDENCE_THRESHOLD,
                'entities': {}
            }
        
        try:
            return self.classifier.classify_query(query)
        except Exception as e:
            logger.warning(f"Query classification failed: {e}")
            return {
                'intent': 'unknown',
                'confidence': ToolConfig.DEFAULT_CONFIDENCE_THRESHOLD,
                'entities': {}
            }
    
    def _parse_date(self, date_str: str, prefer_future: bool = True) -> Optional[Dict[str, Any]]:
        """
        Parse date expression using NLP if available
        
        Args:
            date_str: Date expression to parse
            prefer_future: Prefer future dates when ambiguous
            
        Returns:
            Parsed date dictionary or None
        """
        if not self.date_parser:
            return None
        
        try:
            return self.date_parser.parse_date_expression(date_str, prefer_future=prefer_future)
        except Exception as e:
            logger.warning(f"Date parsing failed: {e}")
            return None
    
    def _enhance_with_llm(self, prompt: str, temperature: float = ToolConfig.DEFAULT_LLM_TEMPERATURE) -> Optional[str]:
        """
        Generate content using LLM if available
        
        Args:
            prompt: Prompt for LLM
            temperature: Temperature for generation
            
        Returns:
            Generated content or None
        """
        if not self.llm_client:
            return None
        
        try:
            response = self.llm_client.invoke(prompt)
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.warning(f"LLM generation failed: {e}")
            return None
