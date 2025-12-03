"""
Execution Planner - Maps intents to tools and resolves dependencies

Integrates with:
- orchestrator_constants.py: INTENT_TO_TOOL_MAP
- intent_patterns.py: recommend_tools() for intelligent tool selection
- domain_validator.py: Domain validation to prevent misrouting
- routing_analytics.py: Records routing decisions and corrections
"""

from typing import Dict, List, Any, Optional

from ..core.base import ExecutionStep, ToolDependency
from ..config.orchestrator_config import OrchestratorConfig
from ..domain.domain_validator import DomainValidator
from ..domain.tool_domain_config import get_tool_domain_config, Domain
from ..domain.routing_analytics import get_routing_analytics, RoutingOutcome
from ....utils.logger import setup_logger

# Intent patterns and constants - required for intelligent orchestration
from ...intent import recommend_tools, extract_entities
from ..config import INTENT_TO_TOOL_MAP

logger = setup_logger(__name__)


class ExecutionPlanner:
    """Intelligent execution planner with dependency resolution and domain validation"""
    
    def __init__(self, tools: Dict[str, Any], enable_validation: bool = None, strict_validation: bool = None):
        self.tools = tools
        self.tool_capabilities = self._analyze_tool_capabilities()
        
        # Use config defaults if not explicitly set
        self.enable_validation = enable_validation if enable_validation is not None else OrchestratorConfig.ENABLE_DOMAIN_VALIDATION
        strict_mode = strict_validation if strict_validation is not None else OrchestratorConfig.ENABLE_STRICT_VALIDATION
        
        # Initialize domain validator - always available now
        if self.enable_validation:
            # Build tool-to-domain mapping from available tools
            tool_domain_config = get_tool_domain_config()
            tool_to_domain_mapping = tool_domain_config.build_from_available_tools(self.tools)
            
            self.domain_validator = DomainValidator(
                strict_mode=strict_mode,
                tool_to_domain=tool_to_domain_mapping
            )
            logger.info("[PLANNER] Domain validation enabled")
        else:
            self.domain_validator = None
            logger.info("[PLANNER] Domain validation disabled (enable_validation=False)")
        
        # Get global analytics instance
        self.analytics = get_routing_analytics()
    
    def _analyze_tool_capabilities(self) -> Dict[str, Dict[str, Any]]:
        """Analyze tool capabilities for intelligent planning"""
        capabilities = {}
        
        for tool_name, tool in self.tools.items():
            capabilities[tool_name] = {
                'domain': self._extract_tool_domain(tool_name),
                'parallel_safe': True,
                'dependencies': []
            }
        
        return capabilities
    
    def _extract_tool_domain(self, tool_name: str) -> str:
        """Extract domain from tool name using centralized config"""
        tool_domain_config = get_tool_domain_config()
        domain = tool_domain_config.get_domain_for_tool(tool_name)
        
        if domain and domain != Domain.GENERAL:
            return domain.value
        
        return 'general'
    
    async def create_execution_plan(self, 
                                    decomposed_steps: List[Dict[str, Any]],
                                    recommended_tools: List[str] = None,
                                    original_query: str = "",
                                    parsed_results: Optional[Dict[str, Any]] = None) -> List[ExecutionStep]:
        """
        Create execution plan with dependency resolution and domain validation
        
        Args:
            decomposed_steps: Steps from query decomposer
            recommended_tools: Optional list of tools recommended by memory system
            original_query: Original query for intent_patterns analysis
            parsed_results: Optional parser results for validation
        """
        execution_steps = []
        
        # Initialize ToolDomainConfig at the start to avoid UnboundLocalError
        tool_domain_config = get_tool_domain_config()
        
        # Get intelligent tool recommendations from intent_patterns if available
        if original_query and not recommended_tools:
            try:
                recommended_tools = recommend_tools(original_query, tools_dict=self.tools)
            except Exception as e:
                logger.debug(f"[PLANNER] Failed to get intent_patterns recommendations: {e}")
        
        for step_data in decomposed_steps:
            step_query = step_data.get('query', '')
            
            # Use intelligent tool selection with multiple strategies
            tool_name = self._select_best_tool(
                step_query,
                step_data.get('intent', 'general'),
                recommended_tools=recommended_tools
            )
            
            # DOMAIN VALIDATION: Validate routing before creating step
            if self.domain_validator and step_query:
                validation = await self.domain_validator.validate_routing(
                    step_query,
                    tool_name,
                    parsed_result=parsed_results
                )
                
                if not validation.valid:
                    self._log_validation_error(validation, step_query, tool_name)
                    self._record_validation_analytics(validation, step_query, tool_name, valid=False)
                    
                    # Try to correct the routing if possible
                    corrected_tool = self._attempt_routing_correction(
                        validation, tool_name, tool_domain_config
                    )
                    
                    if corrected_tool:
                        tool_name = corrected_tool
                    else:
                        # CRITICAL: Skip this step entirely if we can't correct it
                        detected_domain_value = validation.detected_domain.value if validation.detected_domain else 'unknown'
                        logger.error(
                            f"[PLANNER] Skipping invalid step - cannot auto-correct routing: "
                            f"'{step_query}' → {tool_name} (detected domain: {detected_domain_value})"
                        )
                        continue
                
                elif validation.confidence < OrchestratorConfig.MIN_VALIDATION_CONFIDENCE:
                    logger.warning(
                        f"[PLANNER] Low validation confidence ({validation.confidence:.2f}): "
                        f"'{step_query}' → {tool_name}"
                    )
                    self._record_validation_analytics(validation, step_query, tool_name, valid=True)
                else:
                    self._record_validation_analytics(validation, step_query, tool_name, valid=True)
            
            # Infer domain from tool_name or use provided domain
            step_domain = step_data.get('domain')
            if not step_domain:
                # Try to infer from tool_name using ToolDomainConfig
                domain_enum = tool_domain_config.get_domain_for_tool(tool_name)
                step_domain = domain_enum.value if domain_enum else None
            
            step = ExecutionStep(
                id=step_data.get('id', f"step_{len(execution_steps) + 1}"),
                tool_name=tool_name,
                action=step_data.get('action', 'list'),  # Changed default from 'search' to 'list'
                query=step_query,
                intent=step_data.get('intent', 'general'),
                domain=step_domain,  # Include domain for better tracking
                dependencies=step_data.get('dependencies', []),
                dependency_type=ToolDependency.INDEPENDENT,
                context_requirements=step_data.get('context_requirements', {})
            )
            
            if step.dependencies:
                step.dependency_type = ToolDependency.REQUIRES_DATA
            
            execution_steps.append(step)
        
        # Validate entire execution plan
        if self.domain_validator and original_query and execution_steps:
            plan_validation = await self.domain_validator.validate_execution_plan(
                original_query,
                [{'id': s.id, 'tool_name': s.tool_name, 'query': s.query} for s in execution_steps]
            )
            
            if not plan_validation['overall_valid']:
                logger.error(
                    f"[PLANNER] Execution plan validation FAILED:\n"
                    f"  Errors: {plan_validation['errors']}\n"
                    f"  Warnings: {plan_validation['warnings']}"
                )
            elif plan_validation['warnings']:
                logger.warning(
                    f"[PLANNER] Execution plan has warnings:\n"
                    f"  Warnings: {plan_validation['warnings']}"
                )
            else:
                logger.info(
                    f"[PLANNER] Execution plan validated successfully "
                    f"(confidence: {plan_validation['confidence']:.2f})"
                )
        
        return execution_steps
    
    def _attempt_routing_correction(self, validation, tool_name: str, tool_domain_config) -> Optional[str]:
        """
        Attempt to correct routing based on validation results.
        
        Args:
            validation: Validation result object
            tool_name: Current tool name
            tool_domain_config: ToolDomainConfig instance
            
        Returns:
            Corrected tool name if correction successful, None otherwise
        """
        if not validation.detected_domain:
            return None
        
        detected_domain_value = validation.detected_domain.value
        
        # Use ToolDomainConfig to map domain to tool
        corrected_tool = tool_domain_config.map_domain_to_tool(
            detected_domain_value,
            available_tools=self.tools
        )
        
        if corrected_tool and corrected_tool in self.tools:
            logger.info(f"[PLANNER] Auto-correcting routing: {tool_name} → {corrected_tool}")
            
            # Record correction in analytics
            self.analytics.record_correction(
                decision_id=-1,  # Will be recorded during execution
                original_tool=tool_name,
                corrected_tool=corrected_tool,
                reason=validation.reason,
                validator_confidence=validation.confidence
            )
            
            return corrected_tool
        
        return None
    
    def _log_validation_error(self, validation, step_query: str, tool_name: str):
        """Log validation error with detailed information"""
        logger.error(
            f"[PLANNER] Routing validation failed: {validation.reason}\n"
            f"  Query: '{step_query}'\n"
            f"  Detected domain: {validation.detected_domain.value if validation.detected_domain else 'unknown'}\n"
            f"  Target tool: {tool_name}\n"
            f"  Suggestions: {', '.join(validation.suggestions)}"
        )
    
    def _record_validation_analytics(self, validation, step_query: str, tool_name: str, valid: bool):
        """Record validation result in analytics"""
        self.analytics.record_domain_validation(
            query=step_query,
            detected_domain=validation.detected_domain.value if validation.detected_domain else 'unknown',
            target_tool=tool_name,
            validation_valid=valid,
            validation_confidence=validation.confidence,
            detected_confidence=validation.confidence
        )
    
    def _select_best_tool(self, 
                         step_query: str, 
                         intent: str, 
                         recommended_tools: List[str] = None,
                         parsed_results: Optional[Dict[str, Any]] = None) -> str:
        """
        Select best tool using cascading strategies (configurable).
        
        Default cascade strategy:
        1. Tool parser confidence (if parser available and high confidence)
        2. intent_patterns.recommend_tools() (step-specific analysis)
        3. Memory-recommended tools matching intent
        4. Intent mapping from INTENT_TO_TOOL_MAP constants
        5. Final fallback heuristic mapping
        
        Args:
            step_query: The specific step query
            intent: Intent string
            recommended_tools: Tools recommended by memory system
            parsed_results: Optional parser results from tool parsers
            
        Returns:
            Selected tool name from available tools
        """
        # Strategy 0: Use tool parser if available and high confidence
        if parsed_results and parsed_results.get('confidence', 0) >= OrchestratorConfig.PARSER_HIGH_CONFIDENCE_THRESHOLD:
            parsed_action = parsed_results.get('action')
            parsed_domain = parsed_results.get('metadata', {}).get('parser')
            
            # Map parser domain to tool
            if parsed_domain:
                tool_domain_config = get_tool_domain_config()
                # Try to infer tool from parser name
                parser_name = parsed_domain.replace('_parser', '').lower()
                for tool_name, tool in self.tools.items():
                    if hasattr(tool, 'parser') and tool.parser:
                        parser_type = tool.parser.__class__.__name__.lower().replace('parser', '')
                        if parser_type == parser_name:
                            logger.info(f"[PLANNER] High-confidence parser routing: {tool_name} (confidence: {parsed_results.get('confidence', 0):.2f})")
                            return tool_name
        
        # Strategy 1: Use intelligent parser-based routing (preferred)
        if step_query:
            try:
                # Try to use tool parsers directly for better accuracy
                tool_parser_results = {}
                rejected_tools = []
                for tool_name, tool in self.tools.items():
                    if hasattr(tool, 'parser') and tool.parser:
                        try:
                            parsed = tool.parser.parse_query_to_params(step_query)
                            action = parsed.get('action', '')
                            
                            # CRITICAL: Check for explicit rejections FIRST (before confidence filtering)
                            if action == 'reject':
                                logger.info(f"[PLANNER] Parser for {tool_name} explicitly rejected query: '{step_query[:50]}'")
                                rejected_tools.append(tool_name)
                                continue
                            
                            min_confidence = OrchestratorConfig.PARSER_MIN_CONFIDENCE_THRESHOLD
                            if parsed.get('confidence', 0) >= min_confidence:
                                tool_parser_results[tool_name] = parsed
                        except Exception as e:
                            logger.debug(f"[PLANNER] Parser for {tool_name} failed: {e}")
                
                # If any tools rejected, exclude them from selection
                if rejected_tools:
                    logger.info(f"[PLANNER] Excluding rejected tools from routing: {rejected_tools}")
                    tool_parser_results = {k: v for k, v in tool_parser_results.items() if k not in rejected_tools}
                
                # Select tool with highest parser confidence (excluding rejected tools)
                if tool_parser_results:
                    best_tool = max(tool_parser_results.items(), key=lambda x: x[1].get('confidence', 0))
                    min_confidence = OrchestratorConfig.PARSER_MIN_CONFIDENCE_THRESHOLD
                    if best_tool[1].get('confidence', 0) >= min_confidence:
                        logger.info(f"[PLANNER] Tool parser routing selected: {best_tool[0]} (confidence: {best_tool[1].get('confidence', 0):.2f})")
                        return best_tool[0]
                
                # Fallback to intent_patterns
                parser_recommended = recommend_tools(step_query, tools_dict=self.tools)
                if parser_recommended and parser_recommended[0] in self.tools:
                    logger.info(f"[PLANNER] Intent-patterns routing selected: {parser_recommended[0]} for '{step_query[:50]}'")
                    return parser_recommended[0]
            except Exception as e:
                logger.debug(f"[PLANNER] Parser-based routing failed: {e}")
        
        # Strategy 2: Use memory-recommended tools that match intent
        if recommended_tools:
            intent_lower = intent.lower()
            for recommended_tool in recommended_tools:
                if intent_lower in recommended_tool.lower() or recommended_tool.lower() in intent_lower:
                    if recommended_tool in self.tools:
                        return recommended_tool
        
        # Strategy 3: Fall back to constant-based mapping
        if intent in INTENT_TO_TOOL_MAP:
            tool_name = INTENT_TO_TOOL_MAP[intent]
            if tool_name in self.tools:
                return tool_name
        
        # Strategy 4: Final fallback heuristic mapping using _get_default_tool_for_intent
        return self._get_default_tool_for_intent(intent)
    
    def _get_default_tool_for_intent(self, intent: str) -> str:
        """
        Get default tool for intent using ToolDomainConfig and INTENT_TO_TOOL_MAP.
        
        This is the final fallback when no other strategy succeeds.
        
        Args:
            intent: Intent string
            
        Returns:
            Tool name, or first available tool as last resort
        """
        intent_lower = intent.lower()
        tool_domain_config = get_tool_domain_config()
        
        # Strategy 1: Use INTENT_TO_TOOL_MAP (centralized mapping)
        if intent_lower in INTENT_TO_TOOL_MAP:
            mapped_tool = INTENT_TO_TOOL_MAP[intent_lower]
            if mapped_tool in self.tools:
                return mapped_tool
        
        # Strategy 2: Try to map intent to domain, then domain to tool
        domain_enum = tool_domain_config.normalize_domain_string(intent_lower)
        if domain_enum and domain_enum != Domain.GENERAL:
            mapped_tool = tool_domain_config.map_domain_to_tool(
                domain_enum.value,
                available_tools=self.tools
            )
            if mapped_tool:
                return mapped_tool
        
        # Strategy 3: Check if any tool name matches the intent (case-insensitive)
        for tool_name in self.tools.keys():
            if intent_lower == tool_name.lower():
                return tool_name
        
        # Final fallback: use first available tool
        return list(self.tools.keys())[0] if self.tools else None
