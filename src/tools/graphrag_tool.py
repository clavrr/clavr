"""
GraphRAG Tool - Financial Analysis & Insights

Provides GraphRAG capabilities for the agent:
- Spending analysis with LLM-based advice
- Vendor analysis and insights
- Receipt trend analysis
- Custom graph queries with automated insights

This tool demonstrates the full GraphRAG pattern:
1. Graph Traversal → 2. Graph Aggregation → 3. Analysis & Generation
"""
from typing import Optional, Any
from langchain.tools import Tool
from pydantic import BaseModel, Field

from ..services.indexing import GraphRAGAnalyzer, AnalysisType
from ..services.indexing.indexer_factory import get_indexer
from .constants import ToolLimits
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class GraphRAGInput(BaseModel):
    """Input schema for GraphRAG tool"""
    action: str = Field(
        ...,
        description=(
            "Action to perform: 'analyze_spending', 'analyze_vendors', "
            "'receipt_trends', 'custom_query'"
        )
    )
    user_id: str = Field(
        default="user@example.com",
        description="User email/ID to analyze"
    )
    category: Optional[str] = Field(
        default=None,
        description="Category filter (e.g., 'Restaurant', 'Grocery')"
    )
    vendor: Optional[str] = Field(
        default=None,
        description="Vendor/merchant filter (e.g., 'Chipotle', 'Amazon')"
    )
    time_range_days: int = Field(
        default=14,
        description="Number of days to analyze (default: 14)"
    )
    query: Optional[str] = Field(
        default=None,
        description="Custom graph query (for action='custom_query')"
    )
    generate_advice: bool = Field(
        default=True,
        description="Whether to generate LLM-based advice/insights"
    )


class GraphRAGTool:
    """
    GraphRAG Tool for Financial Analysis
    
    Features:
    - Spending analysis with automatic advice generation
    - Vendor spending breakdown with insights
    - Receipt trend analysis
    - Custom graph queries with LLM interpretation
    
    Examples:
        # Analyze dining spending
        tool.run(action="analyze_spending", category="Restaurant", time_range_days=14)
        
        # Get top vendors
        tool.run(action="analyze_vendors", time_range_days=30)
        
        # Custom query
        tool.run(action="custom_query", query="MATCH (u:User)...")
    """
    
    def __init__(self, config=None, llm_client=None):
        """
        Initialize GraphRAG tool
        
        Args:
            config: Application config
            llm_client: LLM client for advice generation
        """
        self.config = config
        self.llm_client = llm_client
        
        # Get indexer (which includes graph manager)
        try:
            indexer = get_indexer(config=config, llm_client=llm_client)
            
            if hasattr(indexer, 'graph_manager') and indexer.graph_manager:
                self.graph_manager = indexer.graph_manager
                
                # Initialize GraphRAG analyzer
                self.analyzer = GraphRAGAnalyzer(
                    graph_manager=self.graph_manager,
                    llm_client=llm_client,
                    config=config
                )
                
                self.available = True
                logger.info("[OK] GraphRAG tool initialized with LLM-based analysis")
            else:
                self.available = False
                logger.warning("Knowledge graph not available - GraphRAG disabled")
                
        except Exception as e:
            self.available = False
            logger.warning(f"Failed to initialize GraphRAG: {e}")
    
    def _run(self, **kwargs) -> str:
        """
        Execute GraphRAG action
        
        Args:
            **kwargs: Action parameters (see GraphRAGInput)
            
        Returns:
            Analysis results with advice/insights
        """
        if not self.available:
            return "[ERROR] GraphRAG not available - knowledge graph not initialized"
        
        action = kwargs.get('action', 'analyze_spending')
        user_id = kwargs.get('user_id', 'user@example.com')
        
        try:
            # Route to appropriate analysis method
            if action == "analyze_spending":
                return self._analyze_spending_wrapper(**kwargs)
            
            elif action == "analyze_vendors":
                return self._analyze_vendors_wrapper(**kwargs)
            
            elif action == "receipt_trends":
                return self._receipt_trends_wrapper(**kwargs)
            
            elif action == "custom_query":
                return self._custom_query_wrapper(**kwargs)
            
            else:
                return (
                    f"[ERROR] Unknown action: {action}. "
                    "Use: analyze_spending, analyze_vendors, receipt_trends, custom_query"
                )
                
        except Exception as e:
            logger.error(f"GraphRAG execution failed: {e}", exc_info=True)
            return f"[ERROR] GraphRAG analysis failed: {str(e)}"
    
    def _analyze_spending_wrapper(self, **kwargs) -> str:
        """Wrapper for spending analysis"""
        import asyncio
        
        user_id = kwargs.get('user_id', 'user@example.com')
        category = kwargs.get('category')
        vendor = kwargs.get('vendor')
        time_range_days = kwargs.get('time_range_days', 14)
        generate_advice = kwargs.get('generate_advice', True)
        
        # Run async analysis
        result = asyncio.run(
            self.analyzer.analyze_spending(
                user_id=user_id,
                category=category,
                vendor=vendor,
                time_range_days=time_range_days,
                generate_advice=generate_advice
            )
        )
        
        # Format response
        if 'error' in result:
            return f"[ERROR] {result['error']}"
        
        output = "**Spending Analysis**\n\n"
        output += f"**Total Spent:** ${result['total_spent']:.2f}\n"
        output += f"**Purchases:** {result['receipt_count']}\n"
        output += f"**Time Period:** {result['time_range']}\n"
        
        if category:
            output += f"**Category:** {category}\n"
        if vendor:
            output += f"**Vendor:** {vendor}\n"
        
        output += f"**Threshold Exceeded:** {'Yes' if result.get('threshold_exceeded') else 'No'}\n\n"
        
        # Add receipts breakdown
        if result.get('receipts'):
            output += "**Recent Receipts:**\n"
            for receipt in result['receipts'][:ToolLimits.MAX_RECEIPTS_DISPLAY]:
                merchant = receipt.get('merchant', 'Unknown')
                total = receipt.get('total', 0)
                date = receipt.get('date', 'Unknown date')
                output += f"- {merchant}: ${total:.2f} ({date})\n"
            
            if len(result['receipts']) > 5:
                output += f"\n...and {len(result['receipts']) - 5} more\n"
        
        # Add LLM-generated advice
        if 'advice' in result:
            output += f"\n**Financial Advice:**\n{result['advice']}\n"
        
        return output
    
    def _analyze_vendors_wrapper(self, **kwargs) -> str:
        """Wrapper for vendor analysis"""
        import asyncio
        
        user_id = kwargs.get('user_id', 'user@example.com')
        time_range_days = kwargs.get('time_range_days', 30)
        generate_advice = kwargs.get('generate_advice', True)
        
        result = asyncio.run(
            self.analyzer.analyze_vendor_spending(
                user_id=user_id,
                time_range_days=time_range_days,
                top_n=5,
                generate_advice=generate_advice
            )
        )
        
        output = "**Vendor Spending Analysis**\n\n"
        output += f"**Total Spent:** ${result['total_spent']:.2f}\n"
        output += f"**Total Purchases:** {result['receipt_count']}\n"
        output += f"**Time Period:** Past {time_range_days} days\n\n"
        
        # Add vendor breakdown
        if result.get('vendors'):
            output += "**Top Vendors:**\n"
            for i, vendor_data in enumerate(result['vendors'], 1):
                vendor = vendor_data['vendor']
                total = vendor_data['total']
                count = vendor_data['count']
                avg = total / count if count > 0 else 0
                output += f"{i}. {vendor}: ${total:.2f} ({count} purchases, avg ${avg:.2f})\n"
        
        # Add LLM-generated insights
        if 'insights' in result:
            output += f"\n**Insights:**\n{result['insights']}\n"
        
        return output
    
    def _receipt_trends_wrapper(self, **kwargs) -> str:
        """Analyze receipt trends over time"""
        import asyncio
        
        user_id = kwargs.get('user_id', 'user@example.com')
        time_range_days = kwargs.get('time_range_days', 30)
        
        # Use spending analysis without category filter
        result = asyncio.run(
            self.analyzer.analyze_spending(
                user_id=user_id,
                time_range_days=time_range_days,
                generate_advice=True
            )
        )
        
        output = "**Receipt Trends**\n\n"
        output += f"**Total Receipts:** {result.get('receipt_count', 0)}\n"
        output += f"**Total Amount:** ${result.get('total_spent', 0):.2f}\n"
        output += f"**Time Period:** {result.get('time_range', 'Unknown')}\n"
        
        if result.get('receipt_count', 0) > 0:
            avg_per_receipt = result['total_spent'] / result['receipt_count']
            output += f"**Average per Receipt:** ${avg_per_receipt:.2f}\n"
        
        if 'advice' in result:
            output += f"\n**Analysis:**\n{result['advice']}\n"
        
        return output
    
    def _custom_query_wrapper(self, **kwargs) -> str:
        """Execute custom graph query"""
        import asyncio
        
        query = kwargs.get('query')
        if not query:
            return "[ERROR] No query provided. Use query='MATCH ...' parameter"
        
        generate_insights = kwargs.get('generate_advice', True)
        
        result = asyncio.run(
            self.analyzer.execute_custom_query(
                query=query,
                generate_insights=generate_insights
            )
        )
        
        output = "**Custom Graph Query Results**\n\n"
        output += f"**Query:** {query}\n"
        output += f"**Results Found:** {result.get('result_count', 0)}\n\n"
        
        # Show results
        if result.get('results'):
            output += "**Results:**\n"
            for i, r in enumerate(result['results'][:10], 1):
                output += f"{i}. {str(r)}\n"
            
            if len(result['results']) > 10:
                output += f"\n...and {len(result['results']) - 10} more\n"
        
        # Add LLM insights
        if 'insights' in result:
            output += f"\n**Insights:**\n{result['insights']}\n"
        
        return output


def create_graphrag_tool(config=None, llm_client=None) -> Tool:
    """
    Factory function to create GraphRAG LangChain tool
    
    Args:
        config: Application config
        llm_client: LLM client for advice generation
        
    Returns:
        LangChain Tool instance
    """
    graphrag = GraphRAGTool(config=config, llm_client=llm_client)
    
    return Tool(
        name="graphrag",
        description=(
            "GraphRAG tool for financial analysis and insights. "
            "Analyzes spending patterns, vendor breakdowns, and receipt trends. "
            "Provides LLM-generated advice based on graph query results. "
            "Actions: analyze_spending (analyze spending by category/vendor), "
            "analyze_vendors (top vendors breakdown), "
            "receipt_trends (receipt patterns over time), "
            "custom_query (execute custom graph queries). "
            "Use for questions like 'How much did I spend on dining?' or "
            "'Which vendors do I spend the most at?'"
        ),
        func=graphrag._run,
        args_schema=GraphRAGInput
    )
