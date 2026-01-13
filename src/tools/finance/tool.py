"""
Finance Tool - Financial analysis and spending aggregation capabilities
"""
import asyncio
from typing import Optional, Any, Type, Dict, List
from langchain.tools import BaseTool
from pydantic import Field, BaseModel
from datetime import datetime, timedelta

from ...utils.logger import setup_logger
from ...utils.config import Config

logger = setup_logger(__name__)


class FinanceInput(BaseModel):
    """Input for FinanceTool."""
    action: str = Field(description="Action to perform (aggregate_spending, get_last_transaction)")
    merchant: Optional[str] = Field(default=None, description="Merchant name (e.g., 'Spotify', 'Chipotle', 'Amazon')")
    category: Optional[str] = Field(default=None, description="Spending category (e.g., 'food', 'retail', 'entertainment')")
    location: Optional[str] = Field(default=None, description="Location filter (e.g., 'New York', 'San Francisco')")
    days: Optional[int] = Field(default=30, description="Timeframe in days (default 30)")
    start_date: Optional[str] = Field(default=None, description="Start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(default=None, description="End date (YYYY-MM-DD)")


class FinanceTool(BaseTool):
    """Financial analysis tool for querying receipt data in the knowledge graph"""
    name: str = "finance"
    description: str = "Financial analysis (spending aggregation, transaction lookup). Use this for queries about spending, last purchases, or budget."
    args_schema: Type[BaseModel] = FinanceInput
    
    config: Optional[Config] = Field(default=None)
    graph_manager: Optional[Any] = Field(default=None)
    user_id: int = Field(default=1)
    
    def __init__(self, config: Optional[Config] = None, graph_manager: Optional[Any] = None, 
                 user_id: int = 1, **kwargs):
        super().__init__(
            config=config,
            graph_manager=graph_manager,
            user_id=user_id,
            **kwargs
        )
        if not graph_manager:
            logger.warning("[FinanceTool] Initialized without GraphManager")

    def _get_graph_manager(self):
        """Lazy initialization or retrieval of GraphManager"""
        if self.graph_manager:
            return self.graph_manager
            
        try:
            from ...services.indexing.graph.manager import KnowledgeGraphManager
            self.graph_manager = KnowledgeGraphManager(config=self.config)
            return self.graph_manager
        except Exception as e:
            logger.error(f"Failed to initialize KnowledgeGraphManager: {e}")
            return None

    def _run(self, action: str, **kwargs) -> str:
        """Execute finance tool action"""
        graph = self._get_graph_manager()
        if not graph:
            return "I'm having trouble accessing my knowledge graph right now. Please try again later."

        try:
            if action == "aggregate_spending":
                return asyncio.run(self._handle_aggregate_spending(kwargs))
            elif action == "get_last_transaction":
                return asyncio.run(self._handle_get_last_transaction(kwargs))
            else:
                return f"Error: Unknown action '{action}'"
        except Exception as e:
            logger.error(f"FinanceTool error: {e}", exc_info=True)
            return f"Error: {str(e)}"

    async def _handle_aggregate_spending(self, params: Dict[str, Any]) -> str:
        """Sum spending for a merchant or category over a timeframe"""
        merchant = params.get('merchant')
        category = params.get('category')
        location = params.get('location')
        days = params.get('days', 30)
        start_date = params.get('start_date')
        end_date = params.get('end_date') or datetime.now().strftime('%Y-%m-%d')
        
        if not start_date:
            start_dt = datetime.now() - timedelta(days=days)
            start_date = start_dt.strftime('%Y-%m-%d')

        filters = []
        if merchant:
            filters.append("r.merchant =~ @merchant")
        if category:
            filters.append("r.category == @category")
        if location:
            filters.append("r.location =~ @location")
        
        filter_str = " AND ".join(filters)
        if filter_str:
            filter_str = f"AND {filter_str}"

        query = f"""
        FOR r IN Receipt
        FILTER r.date >= @start_date AND r.date <= @end_date
        {filter_str}
        COLLECT AGGREGATE total_spend = SUM(r.total), count = COUNT(r)
        RETURN {{ total_spend, count }}
        """
        
        bind_vars = {
            'start_date': start_date,
            'end_date': end_date,
            'merchant': f"(?i){merchant}" if merchant else None,
            'category': category,
            'location': f"(?i){location}" if location else None
        }
        
        results = await self.graph_manager.query(query, bind_vars)
        
        if not results or not results[0]['count']:
            target = f" at {merchant}" if merchant else f" in {category}" if category else ""
            return f"I couldn't find any receipts{target} between {start_date} and {end_date}."

        res = results[0]
        total = res['total_spend'] or 0.0
        count = res['count']
        
        target_name = merchant or category or "everything"
        timeframe = f"last {days} days" if not params.get('start_date') else f"from {start_date} to {end_date}"
        
        return f"You spent a total of **${total:.2f}** on **{target_name}** ({count} transactions) in the {timeframe}."

    async def _handle_get_last_transaction(self, params: Dict[str, Any]) -> str:
        """Retrieve the most recent receipt for a specific merchant"""
        merchant = params.get('merchant')
        if not merchant:
            return "Please specify a merchant name to find your last purchase."

        bind_vars = {
            'merchant': f"(?i){merchant}",
            'location': f"(?i){params.get('location')}" if params.get('location') else None
        }
        
        filter_clause = "FILTER r.merchant =~ @merchant"
        if params.get('location'):
            filter_clause += " AND r.location =~ @location"

        query = f"""
        FOR r IN Receipt
        {filter_clause}
        SORT r.date DESC, r.time DESC
        LIMIT 1
        RETURN r
        """
        results = await self.graph_manager.query(query, bind_vars)
        
        if not results:
            return f"I couldn't find any recent purchases at {merchant}."

        receipt = results[0]
        total = receipt.get('total', 0.0)
        date = receipt.get('date', 'Unknown date')
        items = receipt.get('items', [])
        
        item_str = ""
        if items:
            item_names = [i.get('name') for i in items if i.get('name')]
            if item_names:
                item_str = f" for {', '.join(item_names[:3])}"
                if len(item_names) > 3:
                    item_str += " and more"

        return f"Your last purchase at **{receipt.get('merchant', merchant)}** was on **{date}** for **${total:.2f}**{item_str}."

    async def _arun(self, action: str, **kwargs) -> str:
        """Async execution"""
        return await asyncio.to_thread(self._run, action=action, **kwargs)
