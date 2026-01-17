"""
Finance Agent

Responsible for handling all financial and spending related queries:
- Aggregating spending over time (by merchant or category)
- Retrieving recent transactions and last purchases
"""
from typing import Dict, Any, Optional
from src.utils.logger import setup_logger
from ..base import BaseAgent
from ..constants import (
    TOOL_ALIASES_FINANCE,
    TOOL_ALIASES_EMAIL,
    INTENT_KEYWORDS
)
from .schemas import (
    AGGREGATION_SCHEMA, LOOKUP_SCHEMA
)
from src.ai.prompts.financial_prompts import (
    FINANCIAL_ANALYSIS_SYSTEM_PROMPT
)

logger = setup_logger(__name__)

class FinanceAgent(BaseAgent):
    """
    Specialized agent for Finance and Spending analysis.
    """
    
    async def run(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Execute financial queries with memory awareness.
        """
        logger.info(f"[{self.name}] Processing query: {query}")
        
        # 1. Enrich Query with Memory Context (handled in _extract_params)
        # Note: We rely on _extract_params to retrieve memory context
        # to avoid duplicating context in the query string and bloating the prompt.
        if self.memory_orchestrator:
             logger.debug(f"[{self.name}] MemoryOrchestrator active, context will be fetched for extraction.")

        query_lower = query.lower()
        user_id = context.get('user_id') if context else None
        if user_id is None:
            return "Error: user_id is required for financial queries - cannot default to 1 for multi-tenancy"
        
        # Route based on detected intent
        if any(w in query_lower for w in INTENT_KEYWORDS['finance']['lookup']):
            return await self._handle_lookup(query, user_id)
        else:
            # Default to aggregation for "how much" style queries
            return await self._handle_aggregation(query, user_id)

    async def _handle_aggregation(self, query: str, user_id: int) -> str:
        """Handle spending aggregation queries with LLM param extraction."""
        
        try:
            params = await self._extract_params(
                query, 
                AGGREGATION_SCHEMA, 
                user_id=user_id, 
                task_type="simple_extraction",
                use_fast_model=True
            )
            logger.info(f"[{self.name}] Extracted aggregation params: {params}")
            
            tool_input = {
                "action": "aggregate_spending",
                "merchant": params.get("merchant"),
                "category": params.get("category"),
                "days": params.get("days", 30),
                "start_date": params.get("start_date"),
                "end_date": params.get("end_date")
            }
            
            # Execute Finance Tool
            result = await self._safe_tool_execute(
                TOOL_ALIASES_FINANCE, tool_input, "calculating spending"
            )
            
            # Check for negative result and fallback to email
            if "couldn't find" in result.lower() or "no receipts" in result.lower():
                logger.info(f"[{self.name}] Graph lookup failed. Falling back to email search.")
                email_result = await self._fallback_to_email_search(
                    merchant=params.get("merchant"),
                    category=params.get("category"),
                    days=params.get("days", 30)
                )
                if email_result:
                    return email_result
            
            return result
            
        except Exception as e:
            logger.warning(f"[{self.name}] Param extraction failed: {e}")
            return await self._safe_tool_execute(
                TOOL_ALIASES_FINANCE, {"action": "aggregate_spending", "days": 30}, "calculating spending"
            )

    async def _handle_lookup(self, query: str, user_id: int) -> str:
        """Handle transaction lookup queries (e.g., 'last purchase at X')."""
        
        try:
            params = await self._extract_params(
                query, 
                LOOKUP_SCHEMA, 
                user_id=user_id,
                task_type="simple_extraction",
                use_fast_model=True
            )
            
            tool_input = {
                "action": "get_last_transaction",
                "merchant": params.get("merchant")
            }
            
            result = await self._safe_tool_execute(
                TOOL_ALIASES_FINANCE, tool_input, "looking up last transaction"
            )
            
            # Check for negative result and fallback to email
            if "couldn't find" in result.lower() or "no recent purchases" in result.lower():
                logger.info(f"[{self.name}] Graph lookup failed. Falling back to email search.")
                email_result = await self._fallback_to_email_search(
                    merchant=params.get("merchant"),
                    limit=1
                )
                if email_result:
                    return email_result
            
            return result

        except Exception as e:
            return f"I couldn't identify the merchant name from your query: {query}"

    async def _fallback_to_email_search(self, merchant: Optional[str] = None, category: Optional[str] = None, days: int = 30, limit: int = 5) -> Optional[str]:
        """
        Search emails for receipts when structured data is missing.
        """
        if not merchant and not category:
            return None
            
        # Construct search query
        # e.g. "Spotify receipt" or "Uber bill" or just "receipt" if category
        search_terms = []
        if merchant:
            search_terms.append(f'"{merchant}"')
        if category:
            search_terms.append(category)
            
        # Add receipt indicators
        query_base = " ".join(search_terms)
        email_query = f"{query_base} (receipt OR bill OR invoice OR order OR payment)"
        
        logger.info(f"[{self.name}] Searching emails with query: {email_query}")
        
        tool_input = {
            "action": "list", 
            "query": email_query,
            "days": days,
            "max_results": limit
        }
        
        # Execute Email Search
        emails_text = await self._safe_tool_execute(
            TOOL_ALIASES_EMAIL, tool_input, "searching emails for receipts"
        )
        
        if not emails_text or "no emails found" in emails_text.lower():
            return None
            
        # Extract financial data from email text
        return await self._extract_financial_data_from_email(emails_text, merchant or category)

    async def _extract_financial_data_from_email(self, email_content: str, target: str) -> str:
        """
        Use LLM to parse unstructured email text into a financial summary.
        """
        system_prompt = FINANCIAL_ANALYSIS_SYSTEM_PROMPT.format(target=target)
        
        try:
            # We use the fast model for this extraction
            response = await self.llm_factory.get_llm(self.config).invoke(
                 f"System: {system_prompt}\n\nEmails:\n{email_content}"
            )
            result = response.content.strip()
            
            if "NO_DATA" in result:
                return None
                
            return f"I couldn't find that in your transaction history, but checking your emails: {result}"
            
        except Exception as e:
            logger.warning(f"[{self.name}] Email financial extraction failed: {e}")
            return None
