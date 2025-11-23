"""
Pagination utilities for API responses
Provides consistent pagination across all list endpoints
"""
from typing import TypeVar, Generic, List, Optional, Any, Dict
from pydantic import BaseModel, Field
from math import ceil

T = TypeVar('T')


class PaginationParams(BaseModel):
    """Pagination query parameters"""
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")
    
    @property
    def offset(self) -> int:
        """Calculate offset for database queries"""
        return (self.page - 1) * self.page_size
    
    @property
    def limit(self) -> int:
        """Get limit for database queries"""
        return self.page_size


class PageInfo(BaseModel):
    """Pagination metadata"""
    page: int = Field(description="Current page number")
    page_size: int = Field(description="Items per page")
    total_items: int = Field(description="Total number of items")
    total_pages: int = Field(description="Total number of pages")
    has_next: bool = Field(description="Whether there is a next page")
    has_prev: bool = Field(description="Whether there is a previous page")
    next_page: Optional[int] = Field(default=None, description="Next page number")
    prev_page: Optional[int] = Field(default=None, description="Previous page number")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response"""
    items: List[T] = Field(description="List of items for current page")
    pagination: PageInfo = Field(description="Pagination metadata")
    
    @classmethod
    def create(
        cls,
        items: List[T],
        total_items: int,
        page: int = 1,
        page_size: int = 20
    ) -> "PaginatedResponse[T]":
        """
        Create a paginated response
        
        Args:
            items: List of items for current page
            total_items: Total number of items across all pages
            page: Current page number (1-indexed)
            page_size: Number of items per page
            
        Returns:
            PaginatedResponse with items and pagination info
        """
        total_pages = ceil(total_items / page_size) if page_size > 0 else 0
        has_next = page < total_pages
        has_prev = page > 1
        
        pagination = PageInfo(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=has_next,
            has_prev=has_prev,
            next_page=page + 1 if has_next else None,
            prev_page=page - 1 if has_prev else None
        )
        
        return cls(items=items, pagination=pagination)


def paginate_list(
    items: List[T],
    page: int = 1,
    page_size: int = 20
) -> PaginatedResponse[T]:
    """
    Paginate an in-memory list
    
    Args:
        items: Full list of items
        page: Current page number (1-indexed)
        page_size: Number of items per page
        
    Returns:
        PaginatedResponse with sliced items
    """
    total_items = len(items)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_items = items[start_idx:end_idx]
    
    return PaginatedResponse.create(
        items=page_items,
        total_items=total_items,
        page=page,
        page_size=page_size
    )


def get_pagination_links(
    base_url: str,
    page: int,
    page_size: int,
    total_pages: int,
    query_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Optional[str]]:
    """
    Generate pagination links for API responses
    
    Args:
        base_url: Base URL for the endpoint
        page: Current page number
        page_size: Items per page
        total_pages: Total number of pages
        query_params: Additional query parameters
        
    Returns:
        Dictionary with 'next', 'prev', 'first', 'last' links
    """
    query_params = query_params or {}
    
    def build_url(page_num: Optional[int]) -> Optional[str]:
        if page_num is None or page_num < 1 or page_num > total_pages:
            return None
        params = {**query_params, 'page': page_num, 'page_size': page_size}
        param_str = '&'.join(f"{k}={v}" for k, v in params.items())
        return f"{base_url}?{param_str}"
    
    return {
        'self': build_url(page),
        'first': build_url(1) if total_pages > 0 else None,
        'prev': build_url(page - 1) if page > 1 else None,
        'next': build_url(page + 1) if page < total_pages else None,
        'last': build_url(total_pages) if total_pages > 0 else None
    }


# Example email response models with pagination
class EmailListItem(BaseModel):
    """Email list item for paginated responses"""
    id: str
    subject: str
    sender: str
    recipient: Optional[str] = None
    date: str
    snippet: Optional[str] = None
    has_attachments: bool = False
    is_read: bool = False
    folder: str = "inbox"


class PaginatedEmailResponse(PaginatedResponse[EmailListItem]):
    """Paginated email list response"""
    pass


class CalendarEventItem(BaseModel):
    """Calendar event item for paginated responses"""
    id: str
    summary: str
    start_time: str
    end_time: str
    location: Optional[str] = None
    description: Optional[str] = None
    attendees: List[str] = []


class PaginatedCalendarResponse(PaginatedResponse[CalendarEventItem]):
    """Paginated calendar events response"""
    pass
