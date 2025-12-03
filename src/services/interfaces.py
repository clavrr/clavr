"""
Service Interfaces - Define contracts for service implementations

Provides abstract base classes and protocols for service implementations,
ensuring consistent APIs across different service backends and implementations.

This helps with:
- Type checking
- Documentation
- Testing (mock implementations)
- Future extensibility
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Protocol
from datetime import datetime


# ===================================================================
# BASE PROTOCOLS
# ===================================================================

class CredentialAware(Protocol):
    """Protocol for services that require credentials"""
    
    def is_available(self) -> bool:
        """Check if service is available with current credentials"""
        ...


class SearchableService(Protocol):
    """Protocol for services that support search functionality"""
    
    def search(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        """Search for items matching query"""
        ...


class BulkOperationService(Protocol):
    """Protocol for services that support bulk operations"""
    
    def bulk_delete(self, ids: List[str]) -> Dict[str, Any]:
        """Delete multiple items by ID"""
        ...
    
    def bulk_update(self, updates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Update multiple items"""
        ...


# ===================================================================
# EMAIL SERVICE INTERFACE
# ===================================================================

class EmailServiceInterface(ABC):
    """Abstract interface for email services"""
    
    @abstractmethod
    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Send a new email"""
        pass
    
    @abstractmethod
    def reply_to_email(
        self,
        email_id: str,
        body: str,
        reply_all: bool = False
    ) -> Dict[str, Any]:
        """Reply to an email"""
        pass
    
    @abstractmethod
    def search_emails(
        self,
        query: str,
        max_results: int = 50
    ) -> List[Dict[str, Any]]:
        """Search emails"""
        pass
    
    @abstractmethod
    def get_email(self, email_id: str) -> Dict[str, Any]:
        """Get a single email by ID"""
        pass
    
    @abstractmethod
    def list_emails(
        self,
        limit: int = 50,
        page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """List emails with pagination"""
        pass
    
    @abstractmethod
    def archive_email(self, email_id: str) -> Dict[str, Any]:
        """Archive an email"""
        pass
    
    @abstractmethod
    def delete_email(self, email_id: str) -> Dict[str, Any]:
        """Delete an email"""
        pass


# ===================================================================
# CALENDAR SERVICE INTERFACE
# ===================================================================

class CalendarServiceInterface(ABC):
    """Abstract interface for calendar services"""
    
    @abstractmethod
    def create_event(
        self,
        summary: str,
        start_time: str,
        end_time: str,
        description: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        calendar_id: str = "primary"
    ) -> Dict[str, Any]:
        """Create a new calendar event"""
        pass
    
    @abstractmethod
    def update_event(
        self,
        event_id: str,
        summary: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        description: Optional[str] = None,
        calendar_id: str = "primary"
    ) -> Dict[str, Any]:
        """Update an existing event"""
        pass
    
    @abstractmethod
    def delete_event(
        self,
        event_id: str,
        calendar_id: str = "primary"
    ) -> Dict[str, Any]:
        """Delete an event"""
        pass
    
    @abstractmethod
    def get_event(
        self,
        event_id: str,
        calendar_id: str = "primary"
    ) -> Dict[str, Any]:
        """Get a single event by ID"""
        pass
    
    @abstractmethod
    def list_events(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        calendar_id: str = "primary",
        max_results: int = 50
    ) -> List[Dict[str, Any]]:
        """List events in time range"""
        pass
    
    @abstractmethod
    def find_free_time(
        self,
        duration_minutes: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        calendar_id: str = "primary"
    ) -> List[Dict[str, Any]]:
        """Find free time slots"""
        pass


# ===================================================================
# TASK SERVICE INTERFACE
# ===================================================================

class TaskServiceInterface(ABC):
    """Abstract interface for task services"""
    
    @abstractmethod
    def create_task(
        self,
        title: str,
        due_date: Optional[str] = None,
        notes: Optional[str] = None,
        priority: str = "medium",
        category: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Create a new task"""
        pass
    
    @abstractmethod
    def update_task(
        self,
        task_id: str,
        title: Optional[str] = None,
        due_date: Optional[str] = None,
        notes: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update an existing task"""
        pass
    
    @abstractmethod
    def complete_task(self, task_id: str) -> Dict[str, Any]:
        """Mark a task as complete"""
        pass
    
    @abstractmethod
    def delete_task(self, task_id: str) -> Dict[str, Any]:
        """Delete a task"""
        pass
    
    @abstractmethod
    def get_task(self, task_id: str) -> Dict[str, Any]:
        """Get a single task by ID"""
        pass
    
    @abstractmethod
    def list_tasks(
        self,
        status: str = "pending",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List tasks with filters"""
        pass
    
    @abstractmethod
    def search_tasks(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search tasks"""
        pass


# ===================================================================
# RAG SERVICE INTERFACE
# ===================================================================

class RAGServiceInterface(ABC):
    """Abstract interface for RAG services"""
    
    @abstractmethod
    def get_context(
        self,
        query: str,
        max_results: int = 3,
        use_llm: bool = True
    ) -> Dict[str, Any]:
        """Get context for a query using semantic search"""
        pass
    
    @abstractmethod
    def add_documents(
        self,
        documents: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Add documents to the knowledge base"""
        pass
    
    @abstractmethod
    def search_knowledge(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search the knowledge base"""
        pass
    
    @abstractmethod
    def get_insights(
        self,
        topic: str,
        context_window: int = 30
    ) -> Dict[str, Any]:
        """Get insights about a topic"""
        pass


# ===================================================================
# SERVICE FACTORY INTERFACE
# ===================================================================

class ServiceFactoryInterface(ABC):
    """Abstract interface for service factories"""
    
    @abstractmethod
    def create_email_service(self, **kwargs) -> EmailServiceInterface:
        """Create email service instance"""
        pass
    
    @abstractmethod
    def create_calendar_service(self, **kwargs) -> CalendarServiceInterface:
        """Create calendar service instance"""
        pass
    
    @abstractmethod
    def create_task_service(self, **kwargs) -> TaskServiceInterface:
        """Create task service instance"""
        pass
    
    @abstractmethod
    def create_rag_service(self, **kwargs) -> RAGServiceInterface:
        """Create RAG service instance"""
        pass


# ===================================================================
# INTEGRATION INTERFACES
# ===================================================================

class EmailTaskIntegration(Protocol):
    """Protocol for email-task integration"""
    
    def create_task_from_email(
        self,
        email_id: str,
        email_subject: str,
        email_body: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create task from email"""
        ...


class CalendarTaskIntegration(Protocol):
    """Protocol for calendar-task integration"""
    
    def create_task_from_event(
        self,
        event_id: str,
        event_title: str,
        event_time: str,
        task_type: str = "preparation"
    ) -> Dict[str, Any]:
        """Create task from calendar event"""
        ...


class EmailCalendarIntegration(Protocol):
    """Protocol for email-calendar integration"""
    
    def create_event_from_email(
        self,
        email_id: str,
        email_subject: str,
        email_body: str
    ) -> Dict[str, Any]:
        """Create calendar event from email"""
        ...


# ===================================================================
# UTILITY INTERFACES
# ===================================================================

class CacheableService(Protocol):
    """Protocol for services that support caching"""
    
    def clear_cache(self) -> None:
        """Clear service cache"""
        ...
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        ...