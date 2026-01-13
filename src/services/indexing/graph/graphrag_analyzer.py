"""
GraphRAG Analyzer - Reasoning & Advice Flow

Implements the GraphRAG patterns:
1. Graph Traversal: Find entities and filter by properties
2. Graph Aggregation: Run aggregations (SUM, COUNT, etc.) across relationships
3. Analysis & Generation: Compare to thresholds and generate LLM-based advice

This enables complex queries like:
- "How much did I spend on dining out in the past two weeks?"
- "Advise the user to reduce spending on eating out"
- "Which vendors have I spent the most money at?"

Integrates with:
- KnowledgeGraphManager: For graph traversal and aggregation
- LLM Client: For generating insights and advice
- RAG System: Via graph-rag bridge for context-aware analysis
"""
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from enum import Enum

from .manager import KnowledgeGraphManager
from .schema import NodeType, RelationType
from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)


# Analysis Configuration Constants
DEFAULT_SPENDING_THRESHOLD = 100.0
DEFAULT_TOP_VENDORS = 5
MAX_SAMPLE_RESULTS = 5
LLM_ADVICE_MAX_LENGTH = 500

# Use centralized time range constant
from src.services.service_constants import ServiceConstants
DEFAULT_TIME_RANGE_DAYS = ServiceConstants.GRAPH_DEFAULT_TIME_RANGE_DAYS


class AnalysisType(str, Enum):
    """Types of GraphRAG analyses"""
    SPENDING = "spending"
    VENDOR = "vendor"
    RECEIPT_TRENDS = "receipt_trends"
    CATEGORY = "category"
    RELATIONSHIP = "relationship"
    PATTERN = "pattern"
    CUSTOM = "custom"


class GraphRAGAnalyzer:
    """
    GraphRAG Analyzer for Reasoning & Advice Generation
    
    Implements the 3-step GraphRAG pattern:
    1. Graph Traversal: Navigate relationships and filter nodes
    2. Graph Aggregation: SUM, COUNT, AVG across related nodes
    3. Analysis & Generation: Compare to thresholds, trigger LLM advice
    
    Example Usage:
        analyzer = GraphRAGAnalyzer(graph_manager, llm_client)
        
        # Analyze spending on dining
        result = await analyzer.analyze_spending(
            user_id="user@example.com",
            category="Restaurant",
            time_range_days=14
        )
        # Returns: aggregated data + LLM-generated advice
    """
    
    def __init__(
        self,
        graph_manager: KnowledgeGraphManager,
        llm_client=None,
        config: Optional[Config] = None
    ):
        """
        Initialize GraphRAG analyzer
        
        Args:
            graph_manager: Knowledge graph manager instance
            llm_client: LLM client for advice generation
            config: Optional configuration (for thresholds, etc.)
        """
        self.graph = graph_manager
        self.llm_client = llm_client
        self.config = config
        
        # Get threshold from config or use default
        if config and hasattr(config, 'spending_threshold'):
            self.spending_threshold = config.spending_threshold
        else:
            self.spending_threshold = DEFAULT_SPENDING_THRESHOLD
        
        logger.info(
            f"Initialized GraphRAG Analyzer "
            f"(threshold=${self.spending_threshold:.2f}, "
            f"llm={'enabled' if llm_client else 'disabled'})"
        )
    
    async def analyze_spending(
        self,
        user_id: str,
        category: Optional[str] = None,
        vendor: Optional[str] = None,
        time_range_days: int = DEFAULT_TIME_RANGE_DAYS,
        generate_advice: bool = True
    ) -> Dict[str, Any]:
        """
        Analyze user spending patterns using GraphRAG
        
        Implements the pattern:
        1. TRAVERSE: User -[RECEIVED]-> Email -[HAS_RECEIPT]-> Receipt
        2. FILTER: By date range, category, vendor
        3. AGGREGATE: SUM(Receipt.total)
        4. ANALYZE: Compare to threshold
        5. GENERATE: LLM advice if threshold exceeded
        
        Args:
            user_id: User identifier (email)
            category: Optional category filter (e.g., "Restaurant", "Chipotle")
            vendor: Optional vendor filter
            time_range_days: Days to look back
            generate_advice: Whether to generate LLM advice
            
        Returns:
            {
                'total_spent': float,
                'receipt_count': int,
                'receipts': List[Dict],
                'time_range': str,
                'threshold_exceeded': bool,
                'advice': str (if generate_advice=True)
            }
        """
        logger.info(
            f"[GraphRAG] Analyzing spending for {user_id} "
            f"(category={category}, vendor={vendor}, days={time_range_days})"
        )
        
        # Step 1: Graph Traversal - Find User node
        user_node = await self._find_user_node(user_id)
        if not user_node:
            logger.warning(f"User node not found: {user_id}")
            return {
                'error': f'User not found: {user_id}',
                'total_spent': 0,
                'receipt_count': 0
            }
        
        # Step 2: Graph Traversal - Find receipts via relationships
        # Pattern: User -[RECEIVED]-> Email -[HAS_RECEIPT]-> Receipt
        receipts = await self._traverse_user_receipts(
            user_id,
            time_range_days,
            category,
            vendor
        )
        
        # Step 3: Graph Aggregation - Calculate totals
        total_spent = sum(r.get('total', 0) for r in receipts)
        receipt_count = len(receipts)
        
        # Calculate time range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=time_range_days)
        time_range_str = f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        
        # Step 4: Analysis - Check threshold
        threshold_exceeded = total_spent > self.spending_threshold
        
        result = {
            'total_spent': total_spent,
            'receipt_count': receipt_count,
            'receipts': receipts,
            'time_range': time_range_str,
            'threshold_exceeded': threshold_exceeded,
            'category': category,
            'vendor': vendor,
            'analysis_type': AnalysisType.SPENDING.value
        }
        
        # Step 5: LLM Generation - Generate advice if needed
        if generate_advice and self.llm_client:
            advice = await self._generate_spending_advice(result)
            result['advice'] = advice
        
        logger.info(
            f"[GraphRAG] Spending analysis complete: ${total_spent:.2f} "
            f"({receipt_count} receipts, threshold_exceeded={threshold_exceeded})"
        )
        
        return result
    
    async def analyze_vendor_spending(
        self,
        user_id: str,
        time_range_days: int = DEFAULT_TIME_RANGE_DAYS,
        top_n: int = DEFAULT_TOP_VENDORS,
        generate_advice: bool = True
    ) -> Dict[str, Any]:
        """
        Analyze spending by vendor (GraphRAG aggregation)
        
        Pattern:
        1. MATCH: All receipts for user in time range
        2. GROUP BY: Receipt.merchant (or Vendor.name)
        3. AGGREGATE: SUM(Receipt.total) per vendor
        4. SORT: By total descending
        5. GENERATE: LLM insights about top vendors
        
        Args:
            user_id: User identifier
            time_range_days: Days to analyze
            top_n: Number of top vendors to return
            generate_advice: Whether to generate LLM insights
            
        Returns:
            {
                'vendors': [{vendor, total, count}],
                'total_spent': float,
                'insights': str (LLM-generated)
            }
        """
        logger.info(f"[GraphRAG] Analyzing vendor spending for {user_id}")
        
        # Traverse to get all receipts
        receipts = await self._traverse_user_receipts(user_id, time_range_days)
        
        # Group by vendor and aggregate
        vendor_totals: Dict[str, Dict[str, Any]] = {}
        
        for receipt in receipts:
            vendor_name = receipt.get('merchant', 'Unknown')
            
            if vendor_name not in vendor_totals:
                vendor_totals[vendor_name] = {
                    'vendor': vendor_name,
                    'total': 0,
                    'count': 0,
                    'receipts': []
                }
            
            vendor_totals[vendor_name]['total'] += receipt.get('total', 0)
            vendor_totals[vendor_name]['count'] += 1
            vendor_totals[vendor_name]['receipts'].append(receipt)
        
        # Sort by total and get top N
        sorted_vendors = sorted(
            vendor_totals.values(),
            key=lambda x: x['total'],
            reverse=True
        )[:top_n]
        
        total_spent = sum(r.get('total', 0) for r in receipts)
        
        result = {
            'vendors': sorted_vendors,
            'total_spent': total_spent,
            'receipt_count': len(receipts),
            'time_range_days': time_range_days,
            'analysis_type': AnalysisType.VENDOR.value
        }
        
        # Generate LLM insights
        if generate_advice and self.llm_client and sorted_vendors:
            insights = await self._generate_vendor_insights(result)
            result['insights'] = insights
        
        logger.info(
            f"[GraphRAG] Vendor analysis complete: {len(sorted_vendors)} vendors, "
            f"${total_spent:.2f} total"
        )
        
        return result
    
    async def execute_custom_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        generate_insights: bool = True
    ) -> Dict[str, Any]:
        """
        Execute a custom graph query and optionally generate insights
        
        Supports queries like:
        - "MATCH (u:User)-[:RECEIVED]->(e:Email)-[:HAS_RECEIPT]->(r:Receipt) 
           WHERE r.merchant = 'Chipotle' AND r.date >= '2024-01-01' 
           RETURN SUM(r.total)"
        
        Args:
            query: Graph query string (legacy-style syntax)
            params: Query parameters
            generate_insights: Whether to generate LLM insights from results
            
        Returns:
            {
                'results': List[Dict],
                'insights': str (if generate_insights=True)
            }
        """
        logger.info(f"[GraphRAG] Executing custom query: {query[:100]}...")
        
        # Execute query via graph manager
        results = await self.graph.query(query, params)
        
        response = {
            'results': results,
            'query': query,
            'result_count': len(results),
            'analysis_type': AnalysisType.CUSTOM.value
        }
        
        # Generate insights from results
        if generate_insights and self.llm_client and results:
            insights = await self._generate_query_insights(query, results)
            response['insights'] = insights
        
        return response
    
    # ==================== Private Helper Methods ====================
    
    async def _find_user_node(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Find user node by email/ID"""
        # Try to get by node ID first (if it follows convention)
        node = await self.graph.get_node(f"user_{user_id}")
        if node:
            return node
        
        # Fallback: Search through all User nodes using AQL
        # Replaced legacy "MATCH (u:User) WHERE u.email = @user_id RETURN u"
        query = """
        FOR u IN User
            FILTER u.email == @user_id
            RETURN u
        """
        results = await self.graph.query(query, {'user_id': user_id})
        
        return results[0] if results else None
    
    async def _traverse_user_receipts(
        self,
        user_id: str,
        time_range_days: int,
        category: Optional[str] = None,
        vendor: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Traverse graph to find user's receipts
        
        Pattern: User -[RECEIVED]-> Email -[HAS_RECEIPT]-> Receipt
        """
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=time_range_days)
        start_date_str = start_date.strftime('%Y-%m-%d')
        
        # Build AQL query
        # We perform explicit 2-hop traversal: User -> Email -> Receipt
        # This avoids multi-hop legacy query limitations and ensures we use correct edge collections
        
        query_parts = [
            "FOR u IN User FILTER u.email == @user_id",
            "FOR e IN 1..1 OUTBOUND u RECEIVED",  # User -> Email
            "FOR r IN 1..1 OUTBOUND e HAS_RECEIPT", # Email -> Receipt
            "FILTER r.date >= @start_date"
        ]
        
        params = {'user_id': user_id, 'start_date': start_date_str}
        
        if category:
            query_parts.append("FILTER r.category == @category")
            params['category'] = category
        
        if vendor:
            # Case-insensitive contains check using AQL function
            query_parts.append("FILTER CONTAINS(LOWER(r.merchant), LOWER(@vendor))")
            params['vendor'] = vendor
        
        query_parts.append("RETURN r")
        query = "\n".join(query_parts)
        
        # Execute query
        results = await self.graph.query(query, params)
        
        # Extract receipt data (manager returns list of dicts)
        return results
    
    async def _generate_spending_advice(self, analysis_result: Dict[str, Any]) -> str:
        """
        Generate LLM-based spending advice
        
        This is Step 5 of GraphRAG: Analysis & Generation
        """
        if not self.llm_client:
            return "LLM client not available for advice generation"
        
        total_spent = analysis_result.get('total_spent', 0)
        receipt_count = analysis_result.get('receipt_count', 0)
        time_range = analysis_result.get('time_range', 'unknown period')
        category = analysis_result.get('category', 'all categories')
        vendor = analysis_result.get('vendor', 'all vendors')
        threshold_exceeded = analysis_result.get('threshold_exceeded', False)
        
        # Import and use SPENDING_ANALYSIS_PROMPT
        from src.ai.prompts import SPENDING_ANALYSIS_PROMPT
        
        prompt = SPENDING_ANALYSIS_PROMPT.format(
            total_spent=total_spent,
            receipt_count=receipt_count,
            time_range=time_range,
            category=category,
            vendor=vendor,
            threshold=self.spending_threshold,
            threshold_exceeded=threshold_exceeded
        )

        try:
            # Call LLM
            response = await self.llm_client.ainvoke(prompt)
            
            # Extract text from response
            if hasattr(response, 'content'):
                advice = response.content
            else:
                advice = str(response)
            
            return advice.strip()
            
        except Exception as e:
            logger.error(f"Failed to generate advice: {e}")
            return f"Unable to generate advice: {str(e)}"
    
    async def _generate_vendor_insights(self, analysis_result: Dict[str, Any]) -> str:
        """Generate LLM insights about vendor spending patterns"""
        if not self.llm_client:
            return "LLM client not available"
        
        vendors = analysis_result.get('vendors', [])
        total_spent = analysis_result.get('total_spent', 0)
        time_range_days = analysis_result.get('time_range_days', 30)
        
        # Build vendor summary
        vendor_summary = "\n".join([
            f"- {v['vendor']}: ${v['total']:.2f} ({v['count']} purchases)"
            for v in vendors
        ])
        
        # Import and use VENDOR_ANALYSIS_PROMPT
        from src.ai.prompts import VENDOR_ANALYSIS_PROMPT
        
        prompt = VENDOR_ANALYSIS_PROMPT.format(
            time_range_days=time_range_days,
            vendor_summary=vendor_summary,
            total_spent=total_spent
        )

        try:
            response = await self.llm_client.ainvoke(prompt)
            
            if hasattr(response, 'content'):
                insights = response.content
            else:
                insights = str(response)
            
            return insights.strip()
            
        except Exception as e:
            logger.error(f"Failed to generate insights: {e}")
            return f"Unable to generate insights: {str(e)}"
    
    async def _generate_query_insights(
        self,
        query: str,
        results: List[Dict[str, Any]]
    ) -> str:
        """Generate insights from custom query results"""
        if not self.llm_client:
            return "LLM client not available"
        
        # Summarize results
        result_summary = f"Query returned {len(results)} results"
        
        if results:
            # Sample first few results
            sample_results = results[:5]
            result_details = "\n".join([
                f"- {str(r)}"
                for r in sample_results
            ])
            result_summary += f"\n\nSample results:\n{result_details}"
        
        prompt = f"""Analyze the following graph query results and provide insights.

**Query:** {query}

**Results:**
{result_summary}

Provide a brief analysis of what these results indicate (2-3 sentences)."""

        try:
            response = await self.llm_client.ainvoke(prompt)
            
            if hasattr(response, 'content'):
                insights = response.content
            else:
                insights = str(response)
            
            return insights.strip()
            
        except Exception as e:
            logger.error(f"Failed to generate insights: {e}")
            return f"Unable to generate insights: {str(e)}"
