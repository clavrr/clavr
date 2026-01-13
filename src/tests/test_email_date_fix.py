
import sys
import os
from unittest.mock import MagicMock
from datetime import datetime

# Add project root to path
sys.path.append(os.getcwd())

from src.integrations.gmail.search_service import EmailSearchService

def test_date_range_query():
    print("Testing EmailSearchService date range query...")
    
    # Mock parent EmailService
    parent = MagicMock()
    parent.config = MagicMock()
    
    # Initialize date parser manually and attach to parent
    from src.utils.datetime.flexible_date_parser import FlexibleDateParser
    parent.date_parser = FlexibleDateParser(parent.config)
    parent.date_parser.timezone_name = "UTC" # Fix mock error
    
    # Debug: test the parser directly
    test_range = parent.date_parser.parse_date_expression("emails from yesterday", prefer_future=False)
    print(f"DEBUG: Parser returned for 'emails from yesterday': {test_range}")
    
    # Mock hybrid_coordinator and other parent props
    parent.hybrid_coordinator = MagicMock()
    parent.hybrid_coordinator.graph = None
    parent.llm_client = None
    
    # Initialize service with mock parent
    service = EmailSearchService(parent=parent)
    
    # Mock internal methods to avoid API calls
    service._ensure_available = lambda: None
    
    # Capture the query passed to gmail_client
    captured_query = ""
    def mock_search_emails(query, folder, limit):
        nonlocal captured_query
        captured_query = query
        return []
    
    service.gmail_client.search_emails = mock_search_emails
    
    # Test query "emails from yesterday"
    query = "emails from yesterday"
    service.search_emails(query=query, folder="all")
    
    print(f"Generated Gmail Query: {captured_query}")
    
    # Verification
    assert "after:" in captured_query, f"Missing 'after:' in query: {captured_query}"
    assert "before:" in captured_query, f"Missing 'before:' in query: {captured_query}"
    
    print("SUCCESS: Gmail query contains both after: and before: filters.")

if __name__ == "__main__":
    try:
        test_date_range_query()
    except Exception as e:
        print(f"FAILURE: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
