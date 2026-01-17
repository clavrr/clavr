"""
Email Service - Business logic layer for email operations (Facade)

This module acts as a facade, coordinating specialized sub-services for search,
actions, and workflows.
"""
from typing import Optional, List, Dict, Any
from src.core.email.google_client import GoogleGmailClient
from src.utils.logger import setup_logger
from src.utils.config import Config
from .exceptions import ServiceUnavailableException

# Import sub-services
from .search_service import EmailSearchService
from .action_service import EmailActionService
from .workflow_service import EmailWorkflowService

logger = setup_logger(__name__)

class EmailService:
    """
    Email service providing a unified interface for email operations.
    Delegates to specialized services for search, actions, and workflows.
    """
    
    def __init__(
        self,
        config: Config,
        credentials: Optional[Any] = None,
        rag_engine: Optional[Any] = None,
        hybrid_coordinator: Optional[Any] = None,
        user_id: Optional[int] = None
    ):
        self.config = config
        self.credentials = credentials
        self.rag_engine = rag_engine
        self.hybrid_coordinator = hybrid_coordinator
        self.user_id = user_id
        
        # Shared parsers
        self.date_parser = None
        self.llm_client = None
        
        self._init_parsers()
        self._init_gmail_client()
        
        # Initialize sub-services (Facade components)
        self.search_service = EmailSearchService(self)
        self.action_service = EmailActionService(self)
        self.workflow_service = EmailWorkflowService(self)
        
        logger.info("[EMAIL_SERVICE] Re-architected EmailService initialized as Facade")

    def _init_parsers(self):
        try:
            from ..utils import FlexibleDateParser
            self.date_parser = FlexibleDateParser(self.config)
        except Exception as e:
            logger.debug(f"[EMAIL_SERVICE] FlexibleDateParser not available: {e}")
        
        try:
            from ..ai.llm_factory import LLMFactory
            self.llm_client = LLMFactory.get_llm_for_provider(self.config, temperature=0.1)
        except Exception as e:
            logger.debug(f"[EMAIL_SERVICE] LLM client not available: {e}")

    def _init_gmail_client(self):
        try:
            self.gmail_client = GoogleGmailClient(self.config, credentials=self.credentials)
        except Exception as e:
            logger.error(f"[EMAIL_SERVICE] Gmail client init failed: {e}")
            self.gmail_client = None

    def _ensure_available(self):
        if not self.gmail_client or not self.gmail_client.is_available():
            raise ServiceUnavailableException("Gmail service not available", service_name="email")

    # --- Search Operations (Delegated) ---
    def search_emails(self, **kwargs) -> List[Dict[str, Any]]:
        return self.search_service.search_emails(**kwargs)

    def list_unread_emails(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.search_service.list_unread_emails(limit=limit)

    def list_recent_emails(self, limit: int = 10, folder: str = "inbox") -> List[Dict[str, Any]]:
        return self.search_service.list_recent_emails(limit=limit, folder=folder)

    async def get_unread_count(self) -> int:
        return await self.search_service.get_unread_count()

    async def semantic_search(self, **kwargs) -> List[Dict[str, Any]]:
        return await self.search_service.semantic_search(**kwargs)

    # --- Action Operations (Delegated) ---
    def send_email(self, **kwargs) -> Dict[str, Any]:
        return self.action_service.send_email(**kwargs)

    def reply_to_email(self, **kwargs) -> Dict[str, Any]:
        return self.action_service.reply_to_email(**kwargs)

    def get_email(self, message_id: str) -> Dict[str, Any]:
        return self.action_service.get_email(message_id)

    def mark_as_read(self, message_ids: List[str]):
        return self.action_service.mark_as_read(message_ids)

    def mark_as_unread(self, message_ids: List[str]):
        return self.action_service.mark_as_unread(message_ids)

    def archive_emails(self, message_ids: List[str]):
        return self.action_service.archive_emails(message_ids)

    def delete_emails(self, message_ids: List[str]):
        return self.action_service.delete_emails(message_ids)

    def apply_label(self, message_ids: List[str], label: str):
        return self.action_service.apply_label(message_ids, label)

    def remove_label(self, message_ids: List[str], label: str):
        return self.action_service.remove_label(message_ids, label)

    def get_inbox_stats(self) -> Dict[str, Any]:
        return self.action_service.get_inbox_stats()

    # --- Workflow Operations (Delegated) ---
    def create_event_from_email(self, **kwargs) -> Dict[str, Any]:
        return self.workflow_service.create_event_from_email(**kwargs)

    def create_task_from_email(self, **kwargs) -> Dict[str, Any]:
        return self.workflow_service.create_task_from_email(**kwargs)
