
import sys
import os
import asyncio
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.getcwd())

from src.tools.finance.tool import FinanceTool

async def test_finance_location_query():
    print("Testing FinanceTool location-based query generation...")
    
    # Mock GraphManager
    graph_manager = MagicMock()
    # Capture the query and bind_vars
    captured_query = ""
    captured_bind_vars = {}
    
    async def mock_query(query, bind_vars):
        nonlocal captured_query, captured_bind_vars
        captured_query = query
        captured_bind_vars = bind_vars
        return [{'total_spend': 100.0, 'count': 1, 'merchant': 'Chipotle', 'date': '2025-01-01'}]
        
    graph_manager.query = mock_query
    
    # Initialize tool
    tool = FinanceTool(graph_manager=graph_manager)
    tool._get_graph_manager = lambda: graph_manager # Inject mock
    
    # Test 1: Aggregate spending with location
    print("Running Test 1: _handle_aggregate_spending with location...")
    params1 = {
        "merchant": "Chipotle", 
        "location": "New York"
    }
    await tool._handle_aggregate_spending(params1)
    
    print(f"DEBUG: Captured AQL: {captured_query}")
    print(f"DEBUG: Captured Bind Vars: {captured_bind_vars}")
    
    assert "r.location =~ @location" in captured_query
    assert captured_bind_vars['location'] == "(?i)New York"
    print("Test 1 SUCCESS.")
    
    # Test 2: Get last transaction with location
    print("\nRunning Test 2: _handle_get_last_transaction with location...")
    params2 = {
        "merchant": "Amazon", 
        "location": "Seattle"
    }
    await tool._handle_get_last_transaction(params2)
    
    print(f"DEBUG: Captured AQL: {captured_query}")
    print(f"DEBUG: Captured Bind Vars: {captured_bind_vars}")
    
    assert "AND r.location =~ @location" in captured_query
    assert captured_bind_vars['location'] == "(?i)Seattle"
    print("Test 2 SUCCESS.")

if __name__ == "__main__":
    try:
        asyncio.run(test_finance_location_query())
    except Exception as e:
        print(f"FAILURE: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
