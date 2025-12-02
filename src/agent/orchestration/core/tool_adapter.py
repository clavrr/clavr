"""
Tool Adapter - Maps Formal Tool Declarations to Actual Tools and Roles

This module adapts the formal tool declarations used in the orchestrator prompt
(e.g., `contact_lookup`, `knowledge_search`, `calendar_scheduler`) to the actual
tools and roles in the system.
"""

from typing import Dict, Any, Optional, Tuple
from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class ToolAdapter:
    """
    Adapter that maps formal tool declarations to actual tools and roles
    
    Formal Tool Declarations (from orchestrator prompt):
    - contact_lookup(name: str) → Contact Resolver Role
    - knowledge_search(query: str, sources: list) → Researcher Role
    - calendar_scheduler(participants, start_time, duration, title) → Calendar Tool
    - task_manager(assignee, due_date, description) → Task Tool
    """
    
    def __init__(self, 
                 tools: Dict[str, Any],
                 contact_resolver_role: Optional[Any] = None,
                 researcher_role: Optional[Any] = None):
        """
        Initialize Tool Adapter
        
        Args:
            tools: Dictionary of actual tools (email, calendar, tasks)
            contact_resolver_role: ContactResolverRole instance
            researcher_role: ResearcherRole instance
        """
        self.tools = tools
        self.contact_resolver_role = contact_resolver_role
        self.researcher_role = researcher_role
        
        # Mapping from tool names to handlers
        # Supports both actual tool names and any aliases/formal declarations
        self.tool_mapping = {
            # Actual tool names (primary)
            'email': self._handle_email,
            'calendar': self._handle_calendar_direct,
            'tasks': self._handle_tasks_direct,
            
            # Aliases/formal declarations (for backward compatibility)
            'contact_lookup': self._handle_contact_lookup,
            'contact_resolver': self._handle_contact_lookup,
            'knowledge_search': self._handle_knowledge_search,
            'researcher': self._handle_knowledge_search,
            'calendar_scheduler': self._handle_calendar_scheduler,
            'task_manager': self._handle_task_manager,
        }
    
    async def execute_formal_tool(self, tool_name: str, parameters: Dict[str, Any]) -> str:
        """
        Execute a tool by name, supporting both actual tool names and aliases
        
        Args:
            tool_name: Tool name (e.g., 'email', 'calendar', 'tasks', or aliases)
            parameters: Tool parameters
            
        Returns:
            Tool execution result as string
        """
        tool_name_lower = tool_name.lower()
        handler = self.tool_mapping.get(tool_name_lower)
        
        if handler:
            try:
                return await handler(parameters)
            except Exception as e:
                logger.error(f"Error executing tool '{tool_name}': {e}", exc_info=True)
                return f"Error executing {tool_name}: {str(e)}"
        
        # Try direct tool lookup as fallback
        if tool_name in self.tools:
            return await self._execute_direct_tool(tool_name, parameters)
        
        return f"Error: Unknown tool '{tool_name}'. Available tools: {list(self.tools.keys())}"
    
    async def _handle_contact_lookup(self, parameters: Dict[str, Any]) -> str:
        """Handle contact_lookup tool call"""
        name = parameters.get('name', '')
        
        if not self.contact_resolver_role:
            # Fallback: try to use email tool to search for contact
            email_tool = self.tools.get('email')
            if email_tool:
                query = f"from:{name} OR to:{name}"
                try:
                    result = await self._execute_direct_tool('email', {'action': 'search', 'query': query})
                    return f"Contact lookup for '{name}': {result}"
                except Exception as e:
                    return f"Error: Contact resolver not available and email search failed: {e}"
            
            return f"Error: Contact Resolver Role not available"
        
        try:
            result = await self.contact_resolver_role.resolve_contact(
                identifier=name,
                identifier_type='name'
            )
            
            if result.success and result.resolved_email:
                return f"Contact resolved: {name} → {result.resolved_email} (confidence: {result.confidence:.2f}, method: {result.resolution_method})"
            else:
                return f"Could not resolve contact '{name}': {result.error or 'No match found'}"
        except Exception as e:
            return f"Error resolving contact '{name}': {str(e)}"
    
    async def _handle_knowledge_search(self, parameters: Dict[str, Any]) -> str:
        """Handle knowledge_search tool call"""
        query = parameters.get('query', '')
        sources = parameters.get('sources', [])
        
        if not self.researcher_role:
            # Fallback: use email tool for semantic search
            email_tool = self.tools.get('email')
            if email_tool:
                try:
                    result = await self._execute_direct_tool('email', {
                        'action': 'semantic_search',
                        'query': query
                    })
                    return f"Knowledge search results for '{query}': {result}"
                except Exception as e:
                    return f"Error: Researcher Role not available and email search failed: {e}"
            
            return f"Error: Researcher Role not available"
        
        try:
            research_result = await self.researcher_role.research(
                query=query,
                limit=5,
                use_vector=True,
                use_graph=True
            )
            
            if research_result.success and research_result.combined_results:
                top_results = research_result.get_top_results(3)
                results_summary = "\n".join([
                    f"- {r.get('content', r.get('text', ''))[:200]}"
                    for r in top_results
                ])
                return f"Knowledge search found {len(research_result.combined_results)} results for '{query}':\n{results_summary}"
            else:
                return f"No knowledge found for '{query}'"
        except Exception as e:
            return f"Error searching knowledge base: {str(e)}"
    
    async def _handle_calendar_scheduler(self, parameters: Dict[str, Any]) -> str:
        """Handle calendar_scheduler tool call"""
        calendar_tool = self.tools.get('calendar')
        
        if not calendar_tool:
            return "Error: Calendar tool not available"
        
        # Extract parameters
        participants = parameters.get('participants', [])
        start_time = parameters.get('start_time', '')
        duration = parameters.get('duration', 60)
        title = parameters.get('title', 'Meeting')
        
        # Build query for calendar tool
        # Format: "Schedule meeting with [participants] at [start_time] for [duration] minutes about [title]"
        participants_str = ", ".join(participants) if isinstance(participants, list) else str(participants)
        query = f"Schedule {title} with {participants_str} at {start_time} for {duration} minutes"
        
        try:
            result = await self._execute_direct_tool('calendar', {
                'action': 'create',
                'query': query
            })
            return result
        except Exception as e:
            return f"Error scheduling calendar event: {str(e)}"
    
    async def _handle_task_manager(self, parameters: Dict[str, Any]) -> str:
        """Handle task_manager tool call"""
        task_tool = self.tools.get('tasks')
        
        if not task_tool:
            return "Error: Task tool not available"
        
        # Extract parameters
        assignee = parameters.get('assignee', '')
        due_date = parameters.get('due_date', '')
        description = parameters.get('description', '')
        
        # Build query for task tool
        query = f"Create task: {description}"
        if assignee:
            query += f" assigned to {assignee}"
        if due_date:
            query += f" due {due_date}"
        
        try:
            result = await self._execute_direct_tool('tasks', {
                'action': 'create',
                'query': query
            })
            return result
        except Exception as e:
            return f"Error creating task: {str(e)}"
    
    async def _handle_email(self, parameters: Dict[str, Any]) -> str:
        """Handle email tool call"""
        return await self._execute_direct_tool('email', parameters)
    
    async def _handle_calendar_direct(self, parameters: Dict[str, Any]) -> str:
        """Handle calendar tool call directly"""
        return await self._execute_direct_tool('calendar', parameters)
    
    async def _handle_tasks_direct(self, parameters: Dict[str, Any]) -> str:
        """Handle tasks tool call directly"""
        return await self._execute_direct_tool('tasks', parameters)
    
    async def _execute_direct_tool(self, tool_name: str, parameters: Dict[str, Any]) -> str:
        """Execute a tool directly"""
        tool = self.tools.get(tool_name)
        
        if not tool:
            return f"Error: Tool '{tool_name}' not found"
        
        try:
            # Build query from parameters
            query = parameters.get('query', '')
            if not query:
                # Build query from action and other parameters
                action = parameters.get('action', '')
                query = f"{action} {parameters}"
            
            # Execute tool
            if hasattr(tool, '_run'):
                result = tool._run(query)
            elif hasattr(tool, 'run'):
                result = tool.run(query)
            elif hasattr(tool, 'ainvoke'):
                result = await tool.ainvoke({'query': query, **parameters})
            else:
                result = str(tool.invoke({'query': query, **parameters}))
            
            return str(result) if result else "Tool executed successfully"
        except Exception as e:
            logger.error(f"Error executing tool '{tool_name}': {e}", exc_info=True)
            return f"Error executing {tool_name}: {str(e)}"

