"""
Verification tests for Financial Intelligence features.
"""
import asyncio
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timedelta

from src.agents.finance.agent import FinanceAgent
from src.tools.finance.tool import FinanceTool
from src.utils.config import Config

class TestFinanceIntelligence(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.config = MagicMock(spec=Config)
        self.graph_manager = MagicMock()
        self.graph_manager.query = AsyncMock()
        
        # Initialize tool and agent
        self.tool = FinanceTool(
            config=self.config,
            graph_manager=self.graph_manager,
            user_id=1
        )
        
        self.agent = FinanceAgent(
            config={},
            tools=[self.tool],
            domain_context=None
        )

    async def test_aggregate_spending_query(self):
        """Test that the agent correctly parses an aggregation query and calls the tool."""
        # Mock graph response
        self.graph_manager.query.return_value = [{"total_spend": 250.75, "count": 5}]
        
        query = "How much did I spend on Spotify in the last 60 days?"
        
        # We need to mock _extract_params to returning what we expect for the test
        # to avoid calling an actual LLM in unit tests.
        with patch.object(FinanceAgent, '_extract_params', return_value={
            "merchant": "Spotify",
            "days": 60
        }):
            response = await self.agent.run(query, {"user_id": 1})
            
            # Verify the tool was called with correct filter for Spotify
            self.graph_manager.query.assert_called_once()
            call_args = self.graph_manager.query.call_args[0]
            bind_vars = self.graph_manager.query.call_args[0][1]
            
            self.assertIn("Spotify", bind_vars['merchant'])
            self.assertEqual(bind_vars['merchant'], "(?i)Spotify")
            
            # Verify response content
            self.assertIn("$250.75", response)
            self.assertIn("Spotify", response)
            self.assertIn("60 days", response)

    async def test_last_transaction_query(self):
        """Test that the agent correctly handles 'last purchase' queries."""
        # Mock graph response
        self.graph_manager.query.return_value = [{
            "merchant": "Amazon",
            "total": 42.99,
            "date": "2025-12-20",
            "items": [{"name": "Book"}]
        }]
        
        query = "What was my last purchase at Amazon?"
        
        with patch.object(FinanceAgent, '_extract_params', return_value={
            "merchant": "Amazon"
        }):
            response = await self.agent.run(query, {"user_id": 1})
            
            # Verify response content
            self.assertIn("Amazon", response)
            self.assertIn("$42.99", response)
            self.assertIn("2025-12-20", response)
            self.assertIn("Book", response)

    async def test_no_results_handling(self):
        """Test handling when no receipts are found."""
        self.graph_manager.query.return_value = [{"total_spend": None, "count": 0}]
        
        query = "How much did I spend on Tesla?"
        
        with patch.object(FinanceAgent, '_extract_params', return_value={
            "merchant": "Tesla"
        }):
            response = await self.agent.run(query, {"user_id": 1})
            self.assertIn("I couldn't find any receipts at Tesla", response)

if __name__ == "__main__":
    unittest.main()
