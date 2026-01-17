"""
Pagination Tests
Tests for pagination utilities and paginated responses
"""
import pytest
from src.utils.pagination import (
    PaginationParams,
    PageInfo,
    PaginatedResponse,
    paginate_list,
    get_pagination_links,
    EmailListItem,
    PaginatedEmailResponse
)


class TestPaginationParams:
    """Tests for PaginationParams"""
    
    def test_default_values(self):
        """Test default pagination parameters"""
        params = PaginationParams()
        assert params.page == 1
        assert params.page_size == 20
    
    def test_custom_values(self):
        """Test custom pagination parameters"""
        params = PaginationParams(page=3, page_size=50)
        assert params.page == 3
        assert params.page_size == 50
    
    def test_offset_calculation(self):
        """Test offset calculation"""
        # Page 1
        params = PaginationParams(page=1, page_size=20)
        assert params.offset == 0
        
        # Page 2
        params = PaginationParams(page=2, page_size=20)
        assert params.offset == 20
        
        # Page 3 with different page size
        params = PaginationParams(page=3, page_size=10)
        assert params.offset == 20
    
    def test_limit_property(self):
        """Test limit property"""
        params = PaginationParams(page_size=15)
        assert params.limit == 15
    
    def test_page_validation(self):
        """Test that page must be >= 1"""
        with pytest.raises(ValueError):
            PaginationParams(page=0)
        
        with pytest.raises(ValueError):
            PaginationParams(page=-1)
    
    def test_page_size_validation(self):
        """Test page size constraints"""
        # Too small
        with pytest.raises(ValueError):
            PaginationParams(page_size=0)
        
        # Too large
        with pytest.raises(ValueError):
            PaginationParams(page_size=101)
        
        # Valid values
        assert PaginationParams(page_size=1).page_size == 1
        assert PaginationParams(page_size=100).page_size == 100


class TestPageInfo:
    """Tests for PageInfo"""
    
    def test_page_info_first_page(self):
        """Test page info for first page"""
        info = PageInfo(
            page=1,
            page_size=20,
            total_items=100,
            total_pages=5,
            has_next=True,
            has_prev=False,
            next_page=2,
            prev_page=None
        )
        
        assert info.page == 1
        assert info.has_next is True
        assert info.has_prev is False
        assert info.next_page == 2
        assert info.prev_page is None
    
    def test_page_info_middle_page(self):
        """Test page info for middle page"""
        info = PageInfo(
            page=3,
            page_size=20,
            total_items=100,
            total_pages=5,
            has_next=True,
            has_prev=True,
            next_page=4,
            prev_page=2
        )
        
        assert info.has_next is True
        assert info.has_prev is True
        assert info.next_page == 4
        assert info.prev_page == 2
    
    def test_page_info_last_page(self):
        """Test page info for last page"""
        info = PageInfo(
            page=5,
            page_size=20,
            total_items=100,
            total_pages=5,
            has_next=False,
            has_prev=True,
            next_page=None,
            prev_page=4
        )
        
        assert info.has_next is False
        assert info.has_prev is True
        assert info.next_page is None
        assert info.prev_page == 4


class TestPaginatedResponse:
    """Tests for PaginatedResponse"""
    
    def test_create_first_page(self):
        """Test creating paginated response for first page"""
        items = [1, 2, 3, 4, 5]
        response = PaginatedResponse.create(
            items=items,
            total_items=100,
            page=1,
            page_size=5
        )
        
        assert response.items == items
        assert response.pagination.page == 1
        assert response.pagination.page_size == 5
        assert response.pagination.total_items == 100
        assert response.pagination.total_pages == 20
        assert response.pagination.has_next is True
        assert response.pagination.has_prev is False
    
    def test_create_last_page(self):
        """Test creating paginated response for last page"""
        items = [96, 97, 98, 99, 100]
        response = PaginatedResponse.create(
            items=items,
            total_items=100,
            page=20,
            page_size=5
        )
        
        assert response.pagination.page == 20
        assert response.pagination.has_next is False
        assert response.pagination.has_prev is True
        assert response.pagination.next_page is None
        assert response.pagination.prev_page == 19
    
    def test_create_partial_last_page(self):
        """Test last page with fewer items than page_size"""
        items = [96, 97]
        response = PaginatedResponse.create(
            items=items,
            total_items=97,
            page=5,
            page_size=20
        )
        
        assert len(response.items) == 2
        assert response.pagination.total_pages == 5
        assert response.pagination.has_next is False
    
    def test_create_empty_page(self):
        """Test empty page"""
        response = PaginatedResponse.create(
            items=[],
            total_items=0,
            page=1,
            page_size=20
        )
        
        assert response.items == []
        assert response.pagination.total_items == 0
        assert response.pagination.total_pages == 0
        assert response.pagination.has_next is False
        assert response.pagination.has_prev is False


class TestPaginateList:
    """Tests for paginate_list helper function"""
    
    def test_paginate_full_list(self):
        """Test paginating a full list"""
        items = list(range(1, 101))  # 100 items
        
        # First page
        page1 = paginate_list(items, page=1, page_size=20)
        assert page1.items == list(range(1, 21))
        assert page1.pagination.total_items == 100
        assert page1.pagination.total_pages == 5
        
        # Second page
        page2 = paginate_list(items, page=2, page_size=20)
        assert page2.items == list(range(21, 41))
        
        # Last page
        page5 = paginate_list(items, page=5, page_size=20)
        assert page5.items == list(range(81, 101))
    
    def test_paginate_small_list(self):
        """Test paginating a list smaller than page size"""
        items = [1, 2, 3, 4, 5]
        
        result = paginate_list(items, page=1, page_size=20)
        
        assert result.items == [1, 2, 3, 4, 5]
        assert result.pagination.total_pages == 1
        assert result.pagination.has_next is False
    
    def test_paginate_empty_list(self):
        """Test paginating an empty list"""
        result = paginate_list([], page=1, page_size=20)
        
        assert result.items == []
        assert result.pagination.total_items == 0
        assert result.pagination.total_pages == 0
    
    def test_paginate_beyond_end(self):
        """Test requesting a page beyond the end"""
        items = [1, 2, 3, 4, 5]
        
        result = paginate_list(items, page=10, page_size=20)
        
        assert result.items == []
        assert result.pagination.page == 10
        assert result.pagination.total_pages == 1


class TestPaginationLinks:
    """Tests for pagination links generation"""
    
    def test_links_first_page(self):
        """Test links for first page"""
        links = get_pagination_links(
            base_url="/api/emails",
            page=1,
            page_size=20,
            total_pages=5
        )
        
        assert "/api/emails?page=1" in links['self']
        assert "/api/emails?page=1" in links['first']
        assert links['prev'] is None
        assert "/api/emails?page=2" in links['next']
        assert "/api/emails?page=5" in links['last']
    
    def test_links_middle_page(self):
        """Test links for middle page"""
        links = get_pagination_links(
            base_url="/api/emails",
            page=3,
            page_size=20,
            total_pages=5
        )
        
        assert "/api/emails?page=2" in links['prev']
        assert "/api/emails?page=4" in links['next']
    
    def test_links_last_page(self):
        """Test links for last page"""
        links = get_pagination_links(
            base_url="/api/emails",
            page=5,
            page_size=20,
            total_pages=5
        )
        
        assert "/api/emails?page=4" in links['prev']
        assert links['next'] is None
        assert "/api/emails?page=5" in links['last']
    
    def test_links_with_query_params(self):
        """Test links with additional query parameters"""
        links = get_pagination_links(
            base_url="/api/emails",
            page=2,
            page_size=20,
            total_pages=5,
            query_params={"folder": "inbox", "unread": "true"}
        )
        
        assert "folder=inbox" in links['self']
        assert "unread=true" in links['self']
        assert "page=2" in links['self']
    
    def test_links_single_page(self):
        """Test links when only one page"""
        links = get_pagination_links(
            base_url="/api/emails",
            page=1,
            page_size=20,
            total_pages=1
        )
        
        assert links['prev'] is None
        assert links['next'] is None
        assert "/api/emails?page=1" in links['first']
        assert "/api/emails?page=1" in links['last']


class TestEmailPagination:
    """Tests for email-specific pagination"""
    
    def test_email_list_item(self):
        """Test EmailListItem model"""
        email = EmailListItem(
            id="msg123",
            subject="Test Email",
            sender="sender@example.com",
            recipient="recipient@example.com",
            date="2025-11-14T10:00:00Z",
            snippet="This is a test email",
            has_attachments=True,
            is_read=False,
            folder="inbox"
        )
        
        assert email.id == "msg123"
        assert email.subject == "Test Email"
        assert email.has_attachments is True
        assert email.is_read is False
    
    def test_paginated_email_response(self):
        """Test PaginatedEmailResponse"""
        emails = [
            EmailListItem(
                id=f"msg{i}",
                subject=f"Email {i}",
                sender=f"sender{i}@example.com",
                date="2025-11-14T10:00:00Z"
            )
            for i in range(1, 21)
        ]
        
        response = PaginatedEmailResponse.create(
            items=emails,
            total_items=100,
            page=1,
            page_size=20
        )
        
        assert len(response.items) == 20
        assert response.pagination.total_items == 100
        assert isinstance(response.items[0], EmailListItem)


class TestEdgeCases:
    """Tests for edge cases"""
    
    def test_very_large_page_number(self):
        """Test with very large page number"""
        items = list(range(1, 101))
        result = paginate_list(items, page=1000, page_size=20)
        
        assert result.items == []
        assert result.pagination.page == 1000
    
    def test_page_size_one(self):
        """Test with page_size of 1"""
        items = [1, 2, 3, 4, 5]
        
        page1 = paginate_list(items, page=1, page_size=1)
        assert page1.items == [1]
        assert page1.pagination.total_pages == 5
        
        page3 = paginate_list(items, page=3, page_size=1)
        assert page3.items == [3]
    
    def test_exact_division(self):
        """Test when total items divides evenly by page_size"""
        items = list(range(1, 101))  # Exactly 100 items
        result = paginate_list(items, page=5, page_size=20)  # Last page
        
        assert len(result.items) == 20
        assert result.pagination.total_pages == 5
        assert result.pagination.has_next is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
