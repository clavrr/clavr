"""
Response Formatter - Entity-Aware Response Formatting

Creates richer, more contextual responses using extracted entities.
Customizes response formatting based on:
- Time references (urgent, today, tomorrow)
- Priorities (urgent, high, low)
- Actions (create, find, schedule)
- Domains (email, calendar, tasks)


This module replaces the old context_synthesizer for response formatting.

Typical flow:
    1. Extract entities from query
    2. ResponseFormatter.synthesize() → Context-aware base response
    3. ResponsePersonalizer.personalize() → Add user preferences

Benefits:
- More relevant responses
- Time-aware formatting
- Priority-based presentation
- Context preservation
- No hardcoded values (uses centralized constants)
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from src.utils.logger import setup_logger

# Import centralized constants
from src.agents.constants import (
    URGENT_KEYWORDS, TIME_SENSITIVE_KEYWORDS, HIGH_PRIORITY_KEYWORDS,
    MAX_URGENT_ITEMS, MAX_TIME_SENSITIVE_ITEMS, MAX_HIGH_PRIORITY_ITEMS,
    MAX_STANDARD_ITEMS, EXTRA_ITEMS_THRESHOLD
)

logger = setup_logger(__name__)

# Capabilities
try:
    from src.ai.capabilities import ResponsePersonalizer, UserPreferences
except ImportError:
    ResponsePersonalizer = None
    UserPreferences = None


class ResponseFormatter:
    """
    Formats context-aware responses using extracted entities.
    
    Takes raw execution results and entities, then creates a response
    that's tailored to the user's specific context and intent.
    
    Usage:
        formatter = ResponseFormatter()
        
        entities = extract_entities(query)
        response = formatter.synthesize(
            query=query,
            results=execution_results,
            entities=entities
        )
    """
    
    # Context templates for response headers
    CONTEXT_TEMPLATES = {
        "urgent": "🚨 URGENT: {content}",
        "time_sensitive": "⏰ Time-Sensitive: {content}",
        "high_priority": "⚡ High Priority: {content}",
        "multi_agent": "🤖 Multi-Agent Result: {content}",
        "standard": "{content}"
    }
    
    def __init__(self):
        """Initialize formatter"""
        if ResponsePersonalizer:
            self.personalizer = ResponsePersonalizer()
        else:
            self.personalizer = None
        logger.debug("ResponseFormatter initialized")
    
    def synthesize(
        self,
        query: str,
        results: Dict[str, Any],
        entities: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Synthesize context-aware response.
        
        Args:
            query: Original user query
            results: Execution results
            entities: Extracted entities from query
            
        Returns:
            Formatted, context-aware response
        """
        if results.get("cross_stack_summary") or results.get("topic"):
            # This is a Semantic Sync result
            base_response = self._format_cross_stack_response(results, entities)
        elif not entities:
            # No entities, return standard response
            base_response = self._format_standard_response(results)
        else:
            # Determine context level
            context_level = self._determine_context_level(entities)
            
            # Format based on context
            if context_level == "urgent":
                 base_response = self._format_urgent_response(results, entities)
            elif context_level == "time_sensitive":
                 base_response = self._format_time_sensitive_response(results, entities)
            elif context_level == "high_priority":
                 base_response = self._format_high_priority_response(results, entities)
            else:
                 base_response = self._format_standard_response(results, entities)
        
        # Apply personalization if available
        if self.personalizer:
            # Extract basic context
            context_data = {'data': results}
            # Try to get user_id from results metadata if present, else default
            user_id = results.get('user_id', 1)
            
            return self.personalizer.personalize_response(
                response_text=base_response,
                user_id=user_id,
                query=query,
                context=context_data
            )
            
        return base_response
    
    def _determine_context_level(self, entities: Dict[str, Any]) -> str:
        """
        Determine context level from entities.
        
        Args:
            entities: Extracted entities
            
        Returns:
            Context level: "urgent", "time_sensitive", "high_priority", "standard"
        """
        priorities = entities.get("priorities", [])
        time_refs = entities.get("time_references", [])
        
        # Check for urgent indicators using config
        if any(keyword in str(priorities).lower() for keyword in URGENT_KEYWORDS):
            return "urgent"
        
        # Check for time-sensitive indicators using config
        if any(keyword in str(time_refs).lower() for keyword in TIME_SENSITIVE_KEYWORDS):
            return "time_sensitive"
        
        # Check for high priority using config
        if any(keyword in str(priorities).lower() for keyword in HIGH_PRIORITY_KEYWORDS):
            return "high_priority"
        
        return "standard"
    
    def _apply_template(self, context_level: str, content: str) -> str:
        """
        Apply context template to content.
        
        Args:
            context_level: The context level (urgent, time_sensitive, etc.)
            content: The content to wrap
            
        Returns:
            Content wrapped in appropriate template
        """
        template = self.CONTEXT_TEMPLATES.get(context_level, self.CONTEXT_TEMPLATES["standard"])
        return template.format(content=content)
    
    def _format_urgent_response(
        self,
        results: Dict[str, Any],
        entities: Dict[str, Any]
    ) -> str:
        """Format response for urgent context - concise and actionable."""
        content_parts = []
        
        # Add urgent header using template
        content_parts.append("URGENT RESPONSE")
        content_parts.append("")
        
        # Extract key information
        if "summary" in results:
            content_parts.append(f"**Summary:** {results['summary']}")
        
        # Add immediate actions if present
        if "action_items" in results or "actions" in entities.get("actions", []):
            content_parts.append("")
            content_parts.append("**IMMEDIATE ACTIONS:**")
            
            actions = results.get("action_items", [])
            max_urgent = MAX_URGENT_ITEMS // 3  # Show top 3
            for i, action in enumerate(actions[:max_urgent], 1):
                content_parts.append(f"{i}. {action}")
        
        # Add time context if present
        time_refs = entities.get("time_references", [])
        if time_refs:
            content_parts.append("")
            content_parts.append(f"Timing: {', '.join(time_refs)}")
        
        content = "\n".join(content_parts)
        return self._apply_template("urgent", content)
    
    def _format_time_sensitive_response(
        self,
        results: Dict[str, Any],
        entities: Dict[str, Any]
    ) -> str:
        """Format response for time-sensitive context."""
        content_parts = []
        
        # Add time-sensitive header
        time_refs = entities.get("time_references", [])
        time_context = time_refs[0] if time_refs else "today"
        
        content_parts.append(f"Time-Sensitive ({time_context.upper()})")
        content_parts.append("")
        
        # Main content
        if "summary" in results:
            content_parts.append(results["summary"])
        
        # Add timing details
        if len(time_refs) > 1:
            content_parts.append("")
            content_parts.append(f"**Timeframe:** {', '.join(time_refs)}")
        
        # Add results
        if "items" in results:
            content_parts.append("")
            items = results["items"]
            max_items = MAX_TIME_SENSITIVE_ITEMS // 2  # Show roughly half
            
            content_parts.append(f"**Found {len(items)} items:**")
            for item in items[:max_items]:
                content_parts.append(f"  • {item}")
            
            if len(items) > max_items:
                content_parts.append(f"  ... and {len(items) - max_items} more")
        
        content = "\n".join(content_parts)
        return self._apply_template("time_sensitive", content)
    
    def _format_high_priority_response(
        self,
        results: Dict[str, Any],
        entities: Dict[str, Any]
    ) -> str:
        """Format response for high priority context."""
        content_parts = []
        
        # Add priority header
        content_parts.append("High Priority")
        content_parts.append("")
        
        # Main content with emphasis
        if "summary" in results:
            content_parts.append(f"**{results['summary']}**")
        
        # Add detailed results
        if "items" in results:
            content_parts.append("")
            items = results["items"]
            max_items = MAX_HIGH_PRIORITY_ITEMS
            
            content_parts.append(f"**Details ({len(items)} total):**")
            
            for item in items[:max_items]:
                content_parts.append(f"  • {item}")
            
            if len(items) > max_items:
                content_parts.append(f"  ... and {len(items) - max_items} more")
        
        # Add priority context
        priorities = entities.get("priorities", [])
        if priorities:
            content_parts.append("")
            content_parts.append(f"**Priority Level:** {', '.join(priorities)}")
        
        content = "\n".join(content_parts)
        return self._apply_template("high_priority", content)
    
    def _format_standard_response(
        self,
        results: Dict[str, Any],
        entities: Optional[Dict[str, Any]] = None
    ) -> str:
        """Format standard response."""
        content_parts = []
        
        # Add summary if present
        if "summary" in results:
            content_parts.append(results["summary"])
            content_parts.append("")
        
        # Add items if present
        if "items" in results:
            items = results["items"]
            max_items = MAX_STANDARD_ITEMS
            
            content_parts.append(f"**Results ({len(items)} found):**")
            
            for item in items[:max_items]:
                content_parts.append(f"  • {item}")
            
            if len(items) > EXTRA_ITEMS_THRESHOLD:
                content_parts.append(f"  ... and {len(items) - max_items} more")
        
        # Add context from entities if available
        if entities:
            # Add domain context
            domains = entities.get("domains", [])
            if domains:
                content_parts.append("")
                content_parts.append(f"**Domain:** {', '.join(domains)}")
            
            # Add action context
            actions = entities.get("actions", [])
            if actions:
                max_actions = 3
                content_parts.append(f"**Actions:** {', '.join(actions[:max_actions])}")
        
        return "\n".join(content_parts)
    
    def _format_cross_stack_response(
        self,
        results: Dict[str, Any],
        entities: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Format a professional 360-degree synthesis response (Semantic Sync).
        """
        topic = results.get("topic", "Project Summary")
        summary = results.get("cross_stack_summary") or results.get("summary", "No summary available.")
        
        content_parts = [
            f"🌐 **360° Executive Summary: {topic}**",
            "---",
            summary,
            ""
        ]
        
        # Add Key Facts if present (Semantic Sync specific)
        facts = results.get("key_facts", [])
        if facts:
            content_parts.append("**Key Intelligence:**")
            for fact in facts[:5]:
                content_parts.append(f"• {fact}")
            content_parts.append("")
            
        # Add Action Items
        actions = results.get("action_items", [])
        if actions:
            content_parts.append("**⚡ Recommended Actions:**")
            for action in actions[:3]:
                title = action.get("title", "Unknown Task")
                source = action.get("source", "Clavr")
                content_parts.append(f"• [{source.upper()}] {title}")
            content_parts.append("")
            
        # Add involved people
        people = results.get("people_involved", [])
        if people:
            content_parts.append(f"**👥 Key Stakeholders:** {', '.join(people[:5])}")
            
        return "\n".join(content_parts)

    def format_supervisor_plan(self, plan_steps: List[Dict[str, Any]]) -> str:
        """
        Format the Supervisor's execution plan for the user.
        
        Args:
            plan_steps: List of plan steps
            
        Returns:
            Formatted plan string
        """
        content_parts = ["**Execution Plan:**"]
        
        for step in plan_steps:
             step_num = step.get('step', '?')
             domain = step.get('domain', 'general').upper()
             action = step.get('action', 'unknown')
             reasoning = step.get('reasoning', '')
             
             content_parts.append(f"{step_num}. **[{domain}]** {action}")
             if reasoning:
                 content_parts.append(f"   _{reasoning}_")
        
        return "\n".join(content_parts)

    def format_multi_agent_response(self, results: Dict[str, Any]) -> str:
        """
        Format combined results from multiple agents.
        
        Args:
            results: Dictionary of agent results
            
        Returns:
            Formatted response
        """
        content_parts = []
        
        # Check for error first
        if not results.get("success", True):
             return f"🚨 **Error:** {results.get('error', 'Unknown error occurred')}"
        
        # Format based on execution type
        exec_type = results.get("execution_type", "unknown")
        
        if exec_type == "multi_agent_supervisor":
             content_parts.append(self.format_supervisor_plan(results.get("plan", [])))
             content_parts.append("")
             content_parts.append("---")
             content_parts.append("")
             content_parts.append(results.get("final_response", "Request completed."))
             
             return self._apply_template("multi_agent", "\n".join(content_parts))
             
        return self._format_standard_response(results)

    def format_error_response(
        self,
        error: Exception,
        query: str,
        entities: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Format error response with context.
        
        Args:
            error: Exception that occurred
            query: Original query
            entities: Optional entities for context
            
        Returns:
            Formatted error response
        """
        content_parts = []
        
        # Determine if urgent/time-sensitive
        is_urgent = False
        if entities:
            context_level = self._determine_context_level(entities)
            is_urgent = context_level in ["urgent", "time_sensitive"]
        
        if is_urgent:
            content_parts.append("ERROR (Urgent Query)")
        else:
            content_parts.append("Error")
        
        content_parts.append("")
        content_parts.append(f"**Query:** {query}")
        content_parts.append(f"**Error:** {str(error)}")
        
        # Add suggested actions for urgent errors
        if is_urgent:
            content_parts.append("")
            content_parts.append("**Suggested Actions:**")
            content_parts.append("1. Try simplifying your query")
            content_parts.append("2. Check your connection")
            content_parts.append("3. Contact support if urgent")
        
        logger.warning(f"Error response formatted for query: {query[:50]}...")
        
        return "\n".join(content_parts)
