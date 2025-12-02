"""
Cross-Domain Handler - Handles queries spanning multiple domains

This module provides intelligent handling of queries that require coordination
across multiple domains (email, task, calendar). It:

1. Detects multi-domain queries
2. Decomposes them into domain-specific sub-queries
3. Coordinates parallel or sequential execution
4. Synthesizes results into coherent responses

Examples of cross-domain queries:
- "Show my tasks and meetings for today"
- "Email my team about tomorrow's meeting"
- "Create a task for each unread email from my boss"
- "What do I need to prepare for my meeting tomorrow?"

Architecture:
    Orchestrator → CrossDomainHandler → [Tool1, Tool2, ...] → Response Synthesizer

Key Features:
- Multi-domain query detection
- Query decomposition into sub-queries
- Dependency resolution (sequential vs parallel)
- Result synthesis and formatting
- Context sharing between tools
"""

import re
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime
from enum import Enum

from ....utils.logger import setup_logger
from ..config.cross_domain_config import CrossDomainConfig
from ..domain.tool_domain_config import Domain
from ..domain.domain_validator import DomainValidator
from ..domain.routing_analytics import get_routing_analytics, RoutingOutcome

# Import intent patterns for entity extraction
from ...intent import extract_entities

logger = setup_logger(__name__)


class ExecutionMode(Enum):
    """Execution mode for multi-domain queries"""
    PARALLEL = "parallel"  # Execute all sub-queries in parallel
    SEQUENTIAL = "sequential"  # Execute sub-queries one after another
    DEPENDENT = "dependent"  # Later queries depend on earlier results


class SubQuery:
    """Represents a sub-query for a specific domain"""
    
    def __init__(
        self,
        id: str,
        query: str,
        domain: Domain,
        tool_name: str,
        action: str = "search",
        dependencies: Optional[List[str]] = None,
        priority: int = 0
    ):
        self.id = id
        self.query = query
        self.domain = domain
        self.tool_name = tool_name
        self.action = action
        self.dependencies = dependencies or []
        self.priority = priority
        self.result: Optional[Any] = None
        self.executed: bool = False
        self.error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/debugging"""
        return {
            'id': self.id,
            'query': self.query,
            'domain': self.domain.value if self.domain else None,
            'tool_name': self.tool_name,
            'action': self.action,
            'dependencies': self.dependencies,
            'priority': self.priority,
            'executed': self.executed,
            'has_result': self.result is not None,
            'has_error': self.error is not None
        }


class CrossDomainHandler:
    """
    Handles queries that span multiple domains
    
    Examples:
        >>> handler = CrossDomainHandler()
        >>> result = handler.handle_cross_domain_query(
        ...     "Show my tasks and meetings for today",
        ...     tools={'task': task_tool, 'calendar': calendar_tool}
        ... )
    """
    
    def __init__(
        self,
        enable_parallel_execution: Optional[bool] = None,
        synthesizer_role: Optional[Any] = None,
        analyzer_role: Optional[Any] = None,
        config: Optional[Any] = None
    ):
        """
        Initialize cross-domain handler
        
        Args:
            enable_parallel_execution: If True, execute independent queries in parallel.
                                      If None, uses config default.
            synthesizer_role: Optional SynthesizerRole for enhanced result synthesis
            analyzer_role: Optional AnalyzerRole for enhanced query analysis
            config: Optional config for initialization
        """
        self.enable_parallel_execution = (
            enable_parallel_execution 
            if enable_parallel_execution is not None 
            else CrossDomainConfig.ENABLE_PARALLEL_EXECUTION
        )
        
        # Store agent roles for enhanced capabilities
        self.synthesizer_role = synthesizer_role
        self.analyzer_role = analyzer_role
        self.config = config
        
        # Initialize domain validator for domain detection with AnalyzerRole
        self.domain_validator = DomainValidator(
            strict_mode=False,
            analyzer_role=self.analyzer_role
        )
        
        # Initialize routing analytics for tracking cross-domain queries
        self.analytics = get_routing_analytics()
        
        # Cross-domain patterns (built lazily on first use)
        self._cross_domain_patterns = None
        
        if CrossDomainConfig.LOG_EXECUTION_MODE:
            logger.info(
                f"[CROSS-DOMAIN] Handler initialized "
                f"(parallel_execution={self.enable_parallel_execution}, "
                f"synthesizer_role={synthesizer_role is not None}, "
                f"analyzer_role={analyzer_role is not None})"
            )
    
    @property
    def cross_domain_patterns(self) -> List[Dict[str, Any]]:
        """Lazy-load cross-domain patterns from config (cached after first use)"""
        if self._cross_domain_patterns is None:
            self._cross_domain_patterns = self._build_cross_domain_patterns()
        return self._cross_domain_patterns
    
    def _build_cross_domain_patterns(self) -> List[Dict[str, Any]]:
        """Build patterns for detecting cross-domain queries (uses config)"""
        return [
            {
                'pattern': r'\b(tasks?|todos?)\s+and\s+(meetings?|events?|calendar)\b',
                'domains': [Domain.TASK, Domain.CALENDAR],
                'description': 'Tasks and calendar events'
            },
            {
                'pattern': r'\b(meetings?|events?|calendar)\s+and\s+(tasks?|todos?)\b',
                'domains': [Domain.CALENDAR, Domain.TASK],
                'description': 'Calendar events and tasks'
            },
            {
                'pattern': r'\b(email|send|message)\s+.*\s+(about|regarding)\s+.*(meeting|event|task)\b',
                'domains': [Domain.EMAIL, Domain.CALENDAR, Domain.TASK],
                'description': 'Email about calendar/task items'
            },
            {
                'pattern': r'\bcreate\s+(task|todo)\s+for\s+each\s+(email|message)\b',
                'domains': [Domain.EMAIL, Domain.TASK],
                'description': 'Create tasks from emails'
            },
            {
                'pattern': r'\bprepare\s+for\s+(meeting|event)\b',
                'domains': [Domain.CALENDAR, Domain.TASK, Domain.EMAIL],
                'description': 'Meeting preparation (calendar + tasks + emails)'
            },
            {
                'pattern': r'\b(what|show|list)\s+.*(tasks?|todos?)\s+and\s+(meetings?|events?|calendar)\s+(today|tomorrow|this week)\b',
                'domains': [Domain.TASK, Domain.CALENDAR],
                'description': 'List both tasks and calendar for time period'
            },
            {
                'pattern': r'\b(what|show|list)\s+.*(meetings?|events?|calendar)\s+and\s+(tasks?|todos?)\s+(today|tomorrow|this week)\b',
                'domains': [Domain.CALENDAR, Domain.TASK],
                'description': 'List both calendar and tasks for time period'
            },
            # Time-based queries (calendar + tasks for time calculations)
            {
                'pattern': r'\b(how much|how many)\s+(time|hours?|minutes?)\s+(do i have|left|until|before|till)',
                'domains': [Domain.CALENDAR, Domain.TASK],
                'description': 'Time calculation queries'
            },
            {
                'pattern': r'\b(what|when)\s+(time|was|is)\s+(my|the)\s+.*(meeting|event|standup|call)',
                'domains': [Domain.CALENDAR],
                'description': 'Event time queries'
            },
            {
                'pattern': r'\b(what|show|list)\s+(do i have|have i got|is there)\s+(between|from|until|before)',
                'domains': [Domain.CALENDAR, Domain.TASK],
                'description': 'Time range queries'
            },
            {
                'pattern': r'\b(how long|how much time)\s+(until|before|till|to)\s+(my|the|next)',
                'domains': [Domain.CALENDAR, Domain.TASK],
                'description': 'Time until queries'
            },
            # Notion + other domains
            {
                'pattern': r'\b(create|update|add)\s+.*(notion|page|database).*\s+(about|for|from)\s+.*(meeting|event|task|email)',
                'domains': [Domain.NOTION, Domain.CALENDAR, Domain.TASK, Domain.EMAIL],
                'description': 'Create Notion page from calendar/task/email'
            },
            {
                'pattern': r'\b(notion|page|database).*\s+and\s+(tasks?|meetings?|emails?)',
                'domains': [Domain.NOTION, Domain.TASK, Domain.CALENDAR, Domain.EMAIL],
                'description': 'Notion and other domains'
            },
            {
                'pattern': r'\b(tasks?|meetings?|emails?).*\s+and\s+(notion|page|database)',
                'domains': [Domain.TASK, Domain.CALENDAR, Domain.EMAIL, Domain.NOTION],
                'description': 'Other domains and Notion'
            },
        ]
    
    async def is_cross_domain_query(self, query: str) -> Tuple[bool, List[Domain], float]:
        """
        Detect if a query spans multiple domains
        
        Args:
            query: User's natural language query
            
        Returns:
            Tuple of (is_cross_domain, detected_domains, confidence)
        """
        query_lower = query.lower()
        
        # CRITICAL: If query is ONLY about email content, don't treat as cross-domain
        # Check for email-only patterns first (highest priority)
        is_email_only = any(
            re.search(pattern, query_lower, re.IGNORECASE) 
            for pattern in CrossDomainConfig.EMAIL_ONLY_PATTERNS
        )
        # Also check if query explicitly mentions email keywords but NOT calendar/tasks
        has_email_keyword = any(
            keyword in query_lower 
            for keyword in CrossDomainConfig.EMAIL_KEYWORDS
        )
        has_calendar_keyword = any(
            keyword in query_lower 
            for keyword in CrossDomainConfig.CALENDAR_KEYWORDS
        )
        has_task_keyword = any(
            keyword in query_lower 
            for keyword in CrossDomainConfig.TASK_KEYWORDS
        )
        
        # If query is email-only (mentions email but NOT calendar/tasks), don't treat as cross-domain
        if (is_email_only or (has_email_keyword and not has_calendar_keyword and not has_task_keyword)):
            if CrossDomainConfig.LOG_PATTERN_MATCHING:
                logger.info(f"[CROSS-DOMAIN] Query is email-only, not cross-domain: '{query}'")
            return False, [], 0.0
        
        # CRITICAL: If query is ONLY about calendar, don't treat as cross-domain
        is_calendar_only = any(
            re.search(pattern, query_lower) 
            for pattern in CrossDomainConfig.CALENDAR_ONLY_PATTERNS
        )
        has_task_word = any(
            word in query_lower 
            for word in CrossDomainConfig.TASK_KEYWORDS
        )
        
        if is_calendar_only and not has_task_word:
            if CrossDomainConfig.LOG_PATTERN_MATCHING:
                logger.info("[CROSS-DOMAIN] Query is calendar-only, not cross-domain")
            return False, [], 0.0
        
        # Check explicit cross-domain patterns
        for pattern_info in self.cross_domain_patterns:
            if re.search(pattern_info['pattern'], query_lower):
                if CrossDomainConfig.LOG_PATTERN_MATCHING:
                    logger.info(
                        f"[CROSS-DOMAIN] Detected pattern: {pattern_info['description']}"
                    )
                return True, pattern_info['domains'], CrossDomainConfig.PATTERN_MATCH_CONFIDENCE
        
        # Use domain validator to detect multiple domains
        if self.domain_validator:
            domain, confidence, details = await self.domain_validator.detect_domain(query)
            
            if domain == Domain.MIXED:
                # Check which domains are involved
                domains = details.get('domains', [])
                if CrossDomainConfig.LOG_PATTERN_MATCHING:
                    logger.info(
                        f"[CROSS-DOMAIN] Mixed domain query detected: "
                        f"{[d.value for d in domains]}"
                    )
                return True, domains, CrossDomainConfig.MIXED_DOMAIN_CONFIDENCE
        
        # Check for multiple domain keywords in query
        detected_domains = set()
        
        # Task keywords
        if any(kw in query_lower for kw in CrossDomainConfig.TASK_KEYWORDS):
            detected_domains.add(Domain.TASK)
        
        # Calendar keywords - don't use 'event' alone as it's too generic
        if any(kw in query_lower for kw in CrossDomainConfig.CALENDAR_KEYWORDS):
            detected_domains.add(Domain.CALENDAR)
        
        # Email keywords
        if any(kw in query_lower for kw in CrossDomainConfig.EMAIL_KEYWORDS):
            detected_domains.add(Domain.EMAIL)
        
        # Notion keywords
        if any(kw in query_lower for kw in CrossDomainConfig.NOTION_KEYWORDS):
            detected_domains.add(Domain.NOTION)
        
        # Note: Slack is a platform/entry point, not a data source with a tool
        # So we don't include it in cross-domain detection
        
        if len(detected_domains) >= 2:
            if CrossDomainConfig.LOG_PATTERN_MATCHING:
                logger.info(
                    f"[CROSS-DOMAIN] Multiple domain keywords detected: "
                    f"{[d.value for d in detected_domains]}"
                )
            return True, list(detected_domains), CrossDomainConfig.KEYWORD_DETECTION_CONFIDENCE
        
        return False, [], 0.0
    
    def decompose_query(
        self,
        query: str,
        domains: List[Domain],
        available_tools: Dict[str, Any]
    ) -> List[SubQuery]:
        """
        Decompose cross-domain query into domain-specific sub-queries
        
        Args:
            query: Original user query
            domains: List of domains involved
            available_tools: Dictionary of available tools
            
        Returns:
            List of SubQuery objects
        """
        sub_queries = []
        query_lower = query.lower()
        
        logger.info(
            f"[CROSS-DOMAIN] Decomposing query into {len(domains)} domains: "
            f"{[d.value for d in domains]}"
        )
        
        # Extract common context (time period, etc.)
        time_context = self._extract_time_context(query)
        
        # Create sub-queries for each domain
        for i, domain in enumerate(domains):
            tool_name = self._map_domain_to_tool(domain, available_tools)
            
            if not tool_name:
                logger.warning(f"[CROSS-DOMAIN] No tool found for domain: {domain.value}")
                continue
            
            # Generate domain-specific sub-query
            sub_query_text = self._generate_sub_query(
                query, domain, time_context
            )
            
            # Determine action based on query intent
            action = self._determine_action(query, domain)
            
            # Create SubQuery object
            sub_query = SubQuery(
                id=f"subquery_{i+1}_{domain.value}",
                query=sub_query_text,
                domain=domain,
                tool_name=tool_name,
                action=action,
                priority=i  # Maintain order
            )
            
            sub_queries.append(sub_query)
            
            logger.info(
                f"[CROSS-DOMAIN] Created sub-query {i+1}: "
                f"'{sub_query_text}' → {tool_name}"
            )
        
        # Detect dependencies
        self._detect_dependencies(sub_queries, query)
        
        return sub_queries
    
    def _extract_time_context(self, query: str) -> Optional[str]:
        """Extract time context from query (e.g., 'today', 'tomorrow', 'this week')"""
        query_lower = query.lower()
        
        for pattern in CrossDomainConfig.TIME_CONTEXT_PATTERNS:
            match = re.search(pattern, query_lower)
            if match:
                return match.group(0)
        
        return None
    
    def _generate_sub_query(
        self,
        original_query: str,
        domain: Domain,
        time_context: Optional[str]
    ) -> str:
        """
        Generate domain-specific sub-query from original query
        
        Args:
            original_query: Original cross-domain query
            domain: Target domain for sub-query
            time_context: Time context extracted from query
            
        Returns:
            Domain-specific sub-query string
        """
        query_lower = original_query.lower()
        
        # Build sub-query based on domain
        if domain == Domain.TASK:
            # Extract task-related parts
            if 'tasks' in query_lower or 'task' in query_lower:
                if time_context:
                    return f"Show my tasks for {time_context}"
                else:
                    return "Show my tasks"
            elif 'create' in query_lower and 'task' in query_lower:
                # Extract task description
                return original_query  # Use full query for task creation
            else:
                return f"List tasks {time_context if time_context else ''}"
        
        elif domain == Domain.CALENDAR:
            # Extract calendar-related parts
            if 'meeting' in query_lower or 'event' in query_lower:
                if time_context:
                    return f"Show my meetings for {time_context}"
                else:
                    return "Show my meetings"
            elif 'schedule' in query_lower:
                return original_query  # Use full query for scheduling
            else:
                return f"List calendar events {time_context if time_context else ''}"
        
        elif domain == Domain.EMAIL:
            # Extract email-related parts
            if 'send' in query_lower or 'email' in query_lower:
                return original_query  # Use full query for email operations
            elif 'unread' in query_lower:
                return "Show unread emails"
            else:
                return f"Search emails {time_context if time_context else ''}"
        
        elif domain == Domain.NOTION:
            # Extract Notion-related parts
            if 'create' in query_lower or 'add' in query_lower or 'update' in query_lower:
                return original_query  # Use full query for Notion operations
            elif 'search' in query_lower or 'find' in query_lower:
                return f"Search Notion {time_context if time_context else ''}"
            else:
                return f"Query Notion {time_context if time_context else ''}"
        
        # Note: Slack is a platform, not a data source, so no tool mapping needed
        
        # Use original query as default
        return original_query
    
    def _determine_action(self, query: str, domain: Domain) -> str:
        """Determine the action for a domain based on query intent"""
        query_lower = query.lower()
        
        # Create/Add actions (using config)
        if any(word in query_lower for word in CrossDomainConfig.CREATE_KEYWORDS):
            if domain == Domain.TASK:
                return 'create'
            elif domain == Domain.CALENDAR:
                return 'create'
            elif domain == Domain.EMAIL:
                return 'send'
            elif domain == Domain.NOTION:
                return 'create_page'
        
        # Search actions (using config)
        if any(word in query_lower for word in CrossDomainConfig.SEARCH_KEYWORDS):
            return 'search'
        
        # List/Show actions (default)
        return 'list'
    
    def _map_domain_to_tool(
        self,
        domain: Domain,
        available_tools: Dict[str, Any]
    ) -> Optional[str]:
        """
        Map a domain to available tool name using ToolDomainConfig.
        
        Uses centralized ToolDomainConfig to ensure consistent mapping.
        """
        from ..domain.tool_domain_config import get_tool_domain_config
        
        config = get_tool_domain_config()
        tool_name = config.map_domain_to_tool(domain, available_tools=available_tools)
        
        # Check if tool exists in available tools
        if tool_name and tool_name in available_tools:
            return tool_name
        
        # Try alternate names
        alternates = {
            Domain.TASK: ['tasks', 'task_tool'],
            Domain.CALENDAR: ['calendar_tool'],
            Domain.EMAIL: ['email_tool'],
            Domain.NOTION: ['notion_tool'],
        }
        
        for alt_name in alternates.get(domain, []):
            if alt_name in available_tools:
                return alt_name
        
        return None
    
    def _detect_dependencies(self, sub_queries: List[SubQuery], original_query: str):
        """
        Detect dependencies between sub-queries
        
        Updates sub_queries in-place to set dependencies.
        """
        query_lower = original_query.lower()
        
        # Pattern: "Create task for each email" (using config)
        if re.search(CrossDomainConfig.CREATE_FROM_EMAIL_PATTERN, query_lower):
            for sq in sub_queries:
                if sq.domain == Domain.TASK:
                    email_sq = next((s for s in sub_queries if s.domain == Domain.EMAIL), None)
                    if email_sq:
                        sq.dependencies.append(email_sq.id)
                        if CrossDomainConfig.LOG_DEPENDENCY_DETECTION:
                            logger.info(
                                f"[CROSS-DOMAIN] Dependency: {sq.id} depends on {email_sq.id}"
                            )
        
        # Pattern: "Email about meeting" (using config)
        if re.search(CrossDomainConfig.EMAIL_ABOUT_MEETING_PATTERN, query_lower):
            for sq in sub_queries:
                if sq.domain == Domain.EMAIL:
                    cal_sq = next((s for s in sub_queries if s.domain == Domain.CALENDAR), None)
                    if cal_sq:
                        sq.dependencies.append(cal_sq.id)
                        if CrossDomainConfig.LOG_DEPENDENCY_DETECTION:
                            logger.info(
                                f"[CROSS-DOMAIN] Dependency: {sq.id} depends on {cal_sq.id}"
                            )
        
        # Pattern: "Prepare for meeting" (using config)
        if re.search(CrossDomainConfig.PREPARE_FOR_MEETING_PATTERN, query_lower):
            cal_sq = next((s for s in sub_queries if s.domain == Domain.CALENDAR), None)
            if cal_sq:
                for sq in sub_queries:
                    if sq.domain in [Domain.TASK, Domain.EMAIL] and sq.id != cal_sq.id:
                        sq.dependencies.append(cal_sq.id)
                        if CrossDomainConfig.LOG_DEPENDENCY_DETECTION:
                            logger.info(
                                f"[CROSS-DOMAIN] Dependency: {sq.id} depends on {cal_sq.id}"
                            )
    
    def determine_execution_mode(self, sub_queries: List[SubQuery]) -> ExecutionMode:
        """
        Determine execution mode based on dependencies
        
        Args:
            sub_queries: List of sub-queries
            
        Returns:
            ExecutionMode (PARALLEL, SEQUENTIAL, or DEPENDENT)
        """
        # Check if any sub-queries have dependencies
        has_dependencies = any(sq.dependencies for sq in sub_queries)
        
        if has_dependencies:
            logger.info("[CROSS-DOMAIN] Execution mode: DEPENDENT (has dependencies)")
            return ExecutionMode.DEPENDENT
        
        # If parallel execution is enabled and no dependencies
        if self.enable_parallel_execution:
            logger.info("[CROSS-DOMAIN] Execution mode: PARALLEL")
            return ExecutionMode.PARALLEL
        
        # Default to sequential
        logger.info("[CROSS-DOMAIN] Execution mode: SEQUENTIAL")
        return ExecutionMode.SEQUENTIAL
    
    async def execute_sub_queries(
        self,
        sub_queries: List[SubQuery],
        tools: Dict[str, Any],
        execution_mode: ExecutionMode
    ) -> List[SubQuery]:
        """
        Execute sub-queries according to execution mode
        
        Args:
            sub_queries: List of sub-queries to execute
            tools: Dictionary of available tools
            execution_mode: How to execute (parallel, sequential, dependent)
            
        Returns:
            List of SubQuery objects with results populated
        """
        logger.info(
            f"[CROSS-DOMAIN] Executing {len(sub_queries)} sub-queries "
            f"in {execution_mode.value} mode"
        )
        
        if execution_mode == ExecutionMode.DEPENDENT:
            return await self._execute_dependent(sub_queries, tools)
        elif execution_mode == ExecutionMode.PARALLEL:
            return await self._execute_parallel(sub_queries, tools)
        else:
            return await self._execute_sequential(sub_queries, tools)
    
    async def _execute_dependent(
        self,
        sub_queries: List[SubQuery],
        tools: Dict[str, Any]
    ) -> List[SubQuery]:
        """Execute sub-queries with dependency resolution"""
        executed_ids: Set[str] = set()
        results = []
        
        # Build dependency graph
        dependency_graph = {sq.id: sq for sq in sub_queries}
        
        # Execute in dependency order
        while len(executed_ids) < len(sub_queries):
            made_progress = False
            
            for sq in sub_queries:
                if sq.id in executed_ids:
                    continue
                
                # Check if all dependencies are satisfied
                deps_satisfied = all(dep_id in executed_ids for dep_id in sq.dependencies)
                
                if deps_satisfied:
                    # Execute this sub-query
                    await self._execute_single(sq, tools)
                    executed_ids.add(sq.id)
                    results.append(sq)
                    made_progress = True
                    logger.info(f"[CROSS-DOMAIN] Executed {sq.id}")
            
            if not made_progress:
                # Circular dependency or error
                logger.error("[CROSS-DOMAIN] Circular dependency detected or no progress")
                break
        
        return sub_queries
    
    async def _execute_parallel(
        self,
        sub_queries: List[SubQuery],
        tools: Dict[str, Any]
    ) -> List[SubQuery]:
        """Execute sub-queries in parallel (using asyncio)"""
        import asyncio
        
        tasks = [self._execute_single(sq, tools) for sq in sub_queries]
        await asyncio.gather(*tasks)
        
        return sub_queries
    
    async def _execute_sequential(
        self,
        sub_queries: List[SubQuery],
        tools: Dict[str, Any]
    ) -> List[SubQuery]:
        """Execute sub-queries one after another"""
        for sq in sub_queries:
            await self._execute_single(sq, tools)
        
        return sub_queries
    
    async def _execute_single(self, sub_query: SubQuery, tools: Dict[str, Any]):
        """
        Execute a single sub-query using the appropriate tool and parser
        
        Uses tool parser if available to enhance query understanding before execution.
        """
        tool = tools.get(sub_query.tool_name)
        
        if not tool:
            sub_query.error = f"Tool '{sub_query.tool_name}' not found"
            logger.error(f"[CROSS-DOMAIN] {sub_query.error}")
            return
        
        try:
            # Use tool parser if available to enhance query understanding
            enhanced_action = sub_query.action
            enhanced_query = sub_query.query
            
            if hasattr(tool, 'parser') and tool.parser:
                try:
                    parsed = tool.parser.parse_query_to_params(sub_query.query)
                    if parsed.get('confidence', 0) >= 0.6:
                        # Use parsed action if it's more specific
                        parsed_action = parsed.get('action')
                        if parsed_action and parsed_action != 'search' and parsed_action != 'list':
                            enhanced_action = parsed_action
                            logger.debug(f"[CROSS-DOMAIN] Parser enhanced action for {sub_query.id}: {enhanced_action}")
                except Exception as e:
                    logger.debug(f"[CROSS-DOMAIN] Parser failed for {sub_query.id} (non-critical): {e}")
            
            # Execute tool with query (parser-enhanced if available)
            result = tool._run(
                action=enhanced_action,
                query=enhanced_query
            )
            
            sub_query.result = result
            sub_query.executed = True
            
            logger.info(
                f"[CROSS-DOMAIN] Sub-query executed successfully: {sub_query.id}"
            )
            
        except Exception as e:
            sub_query.error = str(e)
            logger.error(
                f"[CROSS-DOMAIN] Sub-query execution failed: {sub_query.id} - {e}",
                exc_info=True
            )
    
    async def synthesize_results(
        self,
        original_query: str,
        sub_queries: List[SubQuery],
        user_id: Optional[int] = None
    ) -> str:
        """
        Synthesize results from multiple sub-queries into a coherent response
        
        Uses SynthesizerRole if available for enhanced synthesis, otherwise falls back
        to simple concatenation.
        
        Args:
            original_query: Original user query
            sub_queries: List of executed sub-queries with results
            user_id: Optional user ID for personalization
            
        Returns:
            Synthesized response string
        """
        logger.info(f"[CROSS-DOMAIN] Synthesizing results from {len(sub_queries)} sub-queries")
        
        # Collect successful results
        successful_results = [sq for sq in sub_queries if sq.executed and sq.result]
        failed_results = [sq for sq in sub_queries if sq.error]
        
        if not successful_results:
            return "I couldn't retrieve any information. Please try again."
        
        # Use SynthesizerRole if available for enhanced synthesis
        if self.synthesizer_role:
            try:
                # Convert sub-query results to specialist_results format
                specialist_results = {}
                for sq in successful_results:
                    domain = sq.domain.value
                    # Create a simple SpecialistResult-like object
                    class SimpleResult:
                        def __init__(self, data, success=True):
                            self.data = data
                            self.success = success
                    
                    specialist_results[domain] = SimpleResult(
                        data=sq.result,
                        success=True
                    )
                
                # Build context from sub-queries
                context = {
                    'domains': [sq.domain.value for sq in sub_queries],
                    'execution_mode': 'cross_domain',
                    'sub_queries': [sq.to_dict() for sq in sub_queries]
                }
                
                synthesized = await self.synthesizer_role.synthesize(
                    query=original_query,
                    specialist_results=specialist_results,
                    context=context,
                    user_id=user_id
                )
                
                # Add error details if needed
                if failed_results and CrossDomainConfig.INCLUDE_ERROR_DETAILS:
                    error_note = "\n\n**Note:**"
                    for sq in failed_results:
                        error_note += f"\n- Could not retrieve {sq.domain.value} information: {sq.error}"
                    return synthesized.response_text + error_note
                
                return synthesized.response_text
                
            except Exception as e:
                logger.debug(f"[CROSS-DOMAIN] SynthesizerRole synthesis failed: {e}, using fallback")
        
        # Fallback to simple concatenation
        response_parts = []
        
        # Add header
        response_parts.append("Here's what I found:\n")
        
        # Add results by domain (using config)
        if CrossDomainConfig.INCLUDE_DOMAIN_LABELS:
            for sq in successful_results:
                domain_label = sq.domain.value.capitalize()
                response_parts.append(f"\n**{domain_label}:**")
                response_parts.append(str(sq.result))
        else:
            for sq in successful_results:
                response_parts.append(str(sq.result))
        
        # Add warnings for failures (using config)
        if failed_results and CrossDomainConfig.INCLUDE_ERROR_DETAILS:
            response_parts.append("\n\n**Note:**")
            for sq in failed_results:
                response_parts.append(
                    f"- Could not retrieve {sq.domain.value} information: {sq.error}"
                )
        
        return "\n".join(response_parts)
    
    async def handle_cross_domain_query(
        self,
        query: str,
        tools: Dict[str, Any],
        workflow_emitter: Optional[Any] = None,
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Main entry point for handling cross-domain queries
        
        Args:
            query: User's natural language query
            tools: Dictionary of available tools
            workflow_emitter: Optional workflow event emitter for streaming events
            user_id: Optional user ID for personalization
            
        Returns:
            Dictionary with results and metadata
        """
        logger.info(f"[CROSS-DOMAIN] Handling query: '{query}'")
        
        # Emit workflow event for cross-domain query processing
        if workflow_emitter:
            try:
                await workflow_emitter.emit_action_executing(
                    "Processing cross-domain query",
                    data={'query': query}
                )
            except Exception as e:
                logger.debug(f"[CROSS-DOMAIN] Failed to emit workflow event: {e}")
        
        # Use AnalyzerRole if available for enhanced detection
        if self.analyzer_role:
            try:
                analysis = await self.analyzer_role.analyze_query(query)
                # Check if analyzer detected multiple domains
                if len(analysis.domains) >= 2:
                    # Map analyzer domains to Domain enum
                    # Note: Only include data sources with tools, not platforms
                    domain_map = {
                        'email': Domain.EMAIL,
                        'calendar': Domain.CALENDAR,
                        'task': Domain.TASK,
                        'tasks': Domain.TASK,
                        'notion': Domain.NOTION,
                        # Slack is a platform, not a data source
                    }
                    domains = [domain_map.get(d.lower()) for d in analysis.domains if d.lower() in domain_map]
                    domains = [d for d in domains if d is not None]  # Remove None values
                    if len(domains) >= 2:
                        confidence = analysis.confidence
                        is_cross = True
                    else:
                        is_cross, domains, confidence = await self.is_cross_domain_query(query)
                else:
                    is_cross, domains, confidence = await self.is_cross_domain_query(query)
            except Exception as e:
                logger.debug(f"[CROSS-DOMAIN] AnalyzerRole detection failed: {e}, using fallback")
                is_cross, domains, confidence = await self.is_cross_domain_query(query)
        else:
            # Detect if this is a cross-domain query
            is_cross, domains, confidence = await self.is_cross_domain_query(query)
        
        if not is_cross:
            return {
                'is_cross_domain': False,
                'message': 'Not a cross-domain query'
            }
        
        # Decompose into sub-queries
        sub_queries = self.decompose_query(query, domains, tools)
        
        if not sub_queries:
            return {
                'is_cross_domain': True,
                'error': 'Could not decompose query',
                'domains': [d.value for d in domains]
            }
        
        # Determine execution mode
        execution_mode = self.determine_execution_mode(sub_queries)
        
        # Execute sub-queries
        await self.execute_sub_queries(sub_queries, tools, execution_mode)
        
        # Synthesize results (now async)
        final_response = await self.synthesize_results(query, sub_queries, user_id)
        
        # Record cross-domain query in analytics
        successful_count = len([sq for sq in sub_queries if sq.executed and sq.result])
        total_count = len(sub_queries)
        
        if self.analytics:
            # Record each sub-query execution
            for sq in sub_queries:
                if sq.executed:
                    self.analytics.record_routing(
                        query=sq.query,
                        routed_tool=sq.tool_name,
                        detected_domain=sq.domain.value if sq.domain else None,
                        confidence=confidence,
                        outcome=RoutingOutcome.SUCCESS if sq.result else RoutingOutcome.FAILURE,
                        cross_domain=True,
                        error_message=sq.error if sq.error else None,
                        metadata={
                            'sub_query_id': sq.id,
                            'execution_mode': execution_mode.value,
                            'parent_query': query
                        },
                        user_id=user_id
                    )
            
            # Record overall cross-domain query
            self.analytics.record_routing(
                query=query,
                routed_tool='cross_domain',
                detected_domain=','.join([d.value for d in domains]),
                confidence=confidence,
                outcome=RoutingOutcome.SUCCESS if successful_count > 0 else RoutingOutcome.FAILURE,
                cross_domain=True,
                metadata={
                    'domains': [d.value for d in domains],
                    'execution_mode': execution_mode.value,
                    'successful_count': successful_count,
                    'total_count': total_count
                },
                user_id=user_id
            )
        
        return {
            'is_cross_domain': True,
            'domains': [d.value for d in domains],
            'confidence': confidence,
            'execution_mode': execution_mode.value,
            'sub_queries': [sq.to_dict() for sq in sub_queries],
            'result': final_response,
            'successful_count': successful_count,
            'total_count': total_count
        }
