"""
Email Agent

Responsible for handling all email-related queries:
- Reading emails (list, search)
- Sending emails
- Drafting emails
- Managing emails (mark as read, archive, etc.)
"""
from typing import Dict, Any, Optional
from src.utils.logger import setup_logger
from ..base import BaseAgent
from ..constants import (
    TOOL_ALIASES_EMAIL,
    INTENT_KEYWORDS,
    ERROR_NO_RECIPIENT
)
from .schemas import (
    SEARCH_SCHEMA, SEND_SCHEMA, MANAGEMENT_SCHEMA
)
from .constants import (
    COUNT_KEYWORDS, ACTION_DESCRIPTIONS
)

logger = setup_logger(__name__)

class EmailAgent(BaseAgent):
    """
    Specialized agent for Email operations (Gmail).
    """
    
    # Inherits __init__ from BaseAgent
        
    async def run(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Execute email-related queries with memory awareness.
        """
        logger.info(f"[{self.name}] Processing query: {query}")
        
        # 1. Enrich Query with Memory Context
        if self.memory_orchestrator:
             user_id = context.get('user_id') if context else None
             if user_id:
                 mem_context = await self.memory_orchestrator.get_context_for_agent(
                     user_id=user_id,
                     agent_name="EmailAgent",
                     query=query,
                     task_type="communication",
                     include_layers=["graph", "semantic"]
                 )
                 
                 context_strs = []
                 
                 # Related People (e.g. for Recipient Resolution)
                 if mem_context.related_people:
                     people_str = ", ".join([f"{p['name']} ({p.get('context', 'unknown')})" for p in mem_context.related_people])
                     context_strs.append(f"Related People: {people_str}")
                 
                 # Knowledge Graph & RAG Context (e.g. for Intelligent Drafting)
                 if mem_context.graph_context:
                     # Filter for useful context items
                     rag_items = [f"- {g['content']} ({g.get('type', 'Info')})" for g in mem_context.graph_context]
                     if rag_items:
                         knowledge_str = "\n".join(rag_items[:5]) # Top 5 items
                         context_strs.append(f"Relevant Context:\n{knowledge_str}")
                         
                 if context_strs:
                     enriched_context = "\n\n".join(context_strs)
                     # Prepend context to query so _extract_params sees it
                     query = f"[CONTEXT]\n{enriched_context}\n[END CONTEXT]\n\nRequest: {query}"
                     logger.info(f"[{self.name}] Enriched query with context: {len(enriched_context)} chars")
        
        # Simple keyword-based routing for now
        query_lower = query.lower()
        
        # Check startswith "email " to handle "Email Alice" vs "Check email"
        is_send = any(w in query_lower for w in INTENT_KEYWORDS['email']['send'])
        if not is_send and query_lower.startswith("email "):
             is_send = True

        if is_send:
            return await self._handle_send(query, context)
        elif any(w in query_lower for w in INTENT_KEYWORDS['email']['manage']):
            return await self._handle_management(query, context)
        elif any(w in query_lower for w in COUNT_KEYWORDS):
            # Count intent
            tool_input = {"action": "count", "query": query}
            return await self._safe_tool_execute(
                TOOL_ALIASES_EMAIL, tool_input, "checking email count"
            )
        else:
            # Default to list/search
            return await self._handle_list(query, context)

    async def _handle_list(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle list/search queries with LLM param extraction."""
        query_lower = query.lower()
        user_id = context.get('user_id') if context else None
        
        # Determine action type
        action = "list"
        if "unread" in query_lower or "new" in query_lower:
            action = "unread"
        elif "search" in query_lower or "find" in query_lower or "from" in query_lower:
            action = "search"
        
        # For targeted searches (e.g., "email from Vicky" or "receipt for Eleven Labs"), extract params
        # Expand trigger keywords to catch more specific searches
        trigger_keywords = ["from", "about", "regarding", "for", "containing", "with", "search", "find", "charged", "subscription", "receipt", "invoice", "billing"]
        if any(w in query_lower for w in trigger_keywords) or action == "search":
            try:
                # Optimized extraction: Fast model + No heavy memory retrieval
                params = await self._extract_params(
                    query, 
                    SEARCH_SCHEMA, 
                    user_id=user_id, 
                    task_type="simple_extraction",
                    use_fast_model=True
                )
                logger.info(f"[{self.name}] Extracted search params: {params}")
                
                # HEURISTIC: LLMs often over-extract 'subject_contains' from the query 
                # (e.g. "charged for eleven labs" -> subject="subscription charge").
                # This causes Gmail's 'subject:' filter to fail if synonyms aren't exact.
                # We relax this: if user didn't say "subject" or "titled", we move it to keywords.
                extracted_subject = params.get("subject_contains")
                final_subject = extracted_subject
                final_query = query
                
                # Check if user explicitly wanted a subject filter
                subject_explicit = any(w in query_lower for w in ["subject", "title", "titled", "labeled", "tagged"])
                if extracted_subject and not subject_explicit:
                   # Merge into query and clear subject filter for safety
                   if extracted_subject.lower() not in final_query.lower():
                       final_query = f"{final_query} {extracted_subject}"
                   final_subject = None
                   logger.info(f"[{self.name}] Relaxed subject filter '{extracted_subject}' into query keywords")

                tool_input = {
                    "action": action,
                    "query": final_query,
                    "sender": params.get("sender"),
                    "subject": final_subject,
                }
                
                # Add unread filter if specified
                if params.get("is_unread"):
                    action = "unread"
                    tool_input["action"] = action
                
            except Exception as e:
                logger.warning(f"[{self.name}] Param extraction failed: {e}")
                tool_input = {"action": action, "query": query}
        else:
            # Simple query - just pass through
            tool_input = {"action": action, "query": query}
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_EMAIL, tool_input, "accessing emails"
        )

    async def _handle_send(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Handle send queries with LLM extraction"""
        user_id = context.get('user_id') if context else None
        # Optimized extraction for sending
        params = await self._extract_params(
            query, 
            SEND_SCHEMA, 
            user_id=user_id,
            task_type="simple_extraction",
            use_fast_model=True
        )
        if not params.get("recipient"):
            return ERROR_NO_RECIPIENT
             
        tool_input = {
            "action": "send",
            "to": params["recipient"],
            "subject": params.get("subject", "No Subject"),
            "body": params.get("body", "")
        }
        
        return await self._safe_tool_execute(
            TOOL_ALIASES_EMAIL, tool_input, "sending email"
        )

    async def _handle_management(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Handle email management queries (archive, delete, mark as read, label).
        
        Supports:
        - "archive the email from John"
        - "delete spam emails"
        - "mark Carol's email as read"
        - "label the budget email as important"
        """
        user_id = context.get('user_id') if context else None
        query_lower = query.lower()
        
        # Determine management action from keywords
        action = "archive"  # Default
        if "delete" in query_lower or "trash" in query_lower:
            action = "delete"
        elif "mark" in query_lower and ("read" in query_lower or "unread" in query_lower):
            action = "mark_read" if "read" in query_lower and "unread" not in query_lower else "mark_unread"
        elif "label" in query_lower or "tag" in query_lower:
            action = "label"
        elif "spam" in query_lower:
            action = "mark_spam"
        
        params = await self._extract_params(
            query, MANAGEMENT_SCHEMA,
            user_id=user_id,
            task_type="simple_extraction",
            use_fast_model=True
        )
        
        if not params.get("email_identifier"):
            return "I need more details to identify which email(s) you want to manage. Please specify the sender, subject, or other identifying details."
        
        tool_input = {
            "action": action,
            "query": params["email_identifier"]
        }
        
        # Add label if specified
        if action == "label" and params.get("label_name"):
            tool_input["label"] = params["label_name"]
        
        description = ACTION_DESCRIPTIONS.get(action, "managing email")
        if action == 'label':
             description = f"labeling email as {params.get('label_name', 'specified')}"
             
        return await self._safe_tool_execute(
            TOOL_ALIASES_EMAIL, 
            tool_input, 
            description
        )


