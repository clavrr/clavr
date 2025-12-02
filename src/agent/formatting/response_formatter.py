"""
Response Formatter - Entity-Aware Response Formatting (Phase 4)

Creates richer, more contextual responses using extracted entities.
Customizes response formatting based on:
- Time references (urgent, today, tomorrow)
- Priorities (urgent, high, low)
- Actions (create, find, schedule)
- Domains (email, calendar, tasks)

This module replaces the old context_synthesizer for response formatting.
For cross-domain context enrichment during orchestration, see:
  src/agent/orchestration/context_synthesizer.py

Benefits:
- More relevant responses
- Time-aware formatting
- Priority-based presentation
- Context preservation
- No hardcoded values (uses SynthesisConfig)
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..orchestration.config.synthesis_config import SynthesisConfig


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
    
    def __init__(self):
        self._context_templates = {
            "urgent": "URGENT: {content}",
            "time_sensitive": "Time-Sensitive: {content}",
            "high_priority": "High Priority: {content}",
            "standard": "{content}"
        }
    
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
        if not entities:
            # No entities, return standard response
            return self._format_standard_response(results)
        
        # Determine context level
        context_level = self._determine_context_level(entities)
        
        # Format based on context
        if context_level == "urgent":
            return self._format_urgent_response(results, entities)
        elif context_level == "time_sensitive":
            return self._format_time_sensitive_response(results, entities)
        elif context_level == "high_priority":
            return self._format_high_priority_response(results, entities)
        else:
            return self._format_standard_response(results, entities)
    
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
        if any(keyword in str(priorities).lower() for keyword in SynthesisConfig.URGENT_KEYWORDS):
            return "urgent"
        
        # Check for time-sensitive indicators using config
        if any(keyword in str(time_refs).lower() for keyword in SynthesisConfig.TIME_SENSITIVE_KEYWORDS):
            return "time_sensitive"
        
        # Check for high priority using config
        if any(keyword in str(priorities).lower() for keyword in SynthesisConfig.HIGH_PRIORITY_KEYWORDS):
            return "high_priority"
        
        return "standard"
    
    def _format_urgent_response(
        self,
        results: Dict[str, Any],
        entities: Dict[str, Any]
    ) -> str:
        """Format response for urgent context - concise and actionable."""
        content_parts = []
        
        # Add urgent header
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
            max_urgent = SynthesisConfig.MAX_URGENT_ITEMS // 3  # Show top 3
            for i, action in enumerate(actions[:max_urgent], 1):
                content_parts.append(f"{i}. {action}")
        
        # Add time context if present
        time_refs = entities.get("time_references", [])
        if time_refs:
            content_parts.append("")
            content_parts.append(f"Timing: {', '.join(time_refs)}")
        
        return "\n".join(content_parts)
    
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
            max_items = SynthesisConfig.MAX_TIME_SENSITIVE_ITEMS // 2  # Show roughly half
            
            content_parts.append(f"**Found {len(items)} items:**")
            for item in items[:max_items]:
                content_parts.append(f"  • {item}")
            
            if len(items) > max_items:
                content_parts.append(f"  ... and {len(items) - max_items} more")
        
        return "\n".join(content_parts)
    
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
            max_items = SynthesisConfig.MAX_HIGH_PRIORITY_ITEMS
            
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
        
        return "\n".join(content_parts)
    
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
            max_items = SynthesisConfig.MAX_STANDARD_ITEMS
            
            content_parts.append(f"**Results ({len(items)} found):**")
            
            for item in items[:max_items]:
                content_parts.append(f"  • {item}")
            
            if len(items) > SynthesisConfig.EXTRA_ITEMS_THRESHOLD:
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
        
        return "\n".join(content_parts)


# Create shared formatter instance
_global_formatter = ResponseFormatter()


def get_formatter() -> ResponseFormatter:
    """Get the global response formatter instance."""
    return _global_formatter
