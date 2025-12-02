"""
Orchestrator Role: Plan and coordinate execution

Responsible for:
- Creating execution plans from analysis
- Resolving dependencies between steps
- Coordinating tool invocation
- Managing execution flow
- Predictive planning and adaptive optimization
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ...utils.logger import setup_logger

# Import enhanced predictive executor
from ..capabilities.predictive_executor import PredictiveExecutor

logger = setup_logger(__name__)


class ExecutionStepType(str, Enum):
    """Types of execution steps"""
    EMAIL_SEARCH = "email_search"
    EMAIL_ACTION = "email_action"
    CALENDAR_SEARCH = "calendar_search"
    CALENDAR_CREATE = "calendar_create"
    CALENDAR_UPDATE = "calendar_update"
    TASK_SEARCH = "task_search"
    TASK_CREATE = "task_create"
    TASK_UPDATE = "task_update"
    SYNTHESIS = "synthesis"
    CONDITIONAL = "conditional"


@dataclass
class ExecutionStep:
    """A single step in the execution plan"""
    step_id: str
    step_type: ExecutionStepType
    domain: str
    action: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)  # step IDs this depends on
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: int = 30
    
    def __post_init__(self):
        """Validate step"""
        if not self.step_id:
            raise ValueError("step_id cannot be empty")


@dataclass
class ExecutionPlan:
    """Complete plan for executing a user query"""
    plan_id: str
    query: str
    intent: str
    domains: List[str]
    steps: List[ExecutionStep] = field(default_factory=list)
    parallel_execution_possible: bool = False
    estimated_duration_seconds: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    
    def add_step(self, step: ExecutionStep) -> None:
        """Add a step to the plan"""
        self.steps.append(step)
    
    def get_step(self, step_id: str) -> Optional[ExecutionStep]:
        """Get a step by ID"""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None
    
    def get_steps_by_type(self, step_type: ExecutionStepType) -> List[ExecutionStep]:
        """Get all steps of a given type"""
        return [s for s in self.steps if s.step_type == step_type]
    
    def get_step_order(self) -> List[str]:
        """Get the optimal execution order of steps"""
        # Topological sort based on dependencies
        order = []
        visited = set()
        
        def visit(step_id: str):
            if step_id in visited:
                return
            
            step = self.get_step(step_id)
            if step is None:
                return
            
            # Visit dependencies first
            for dep_id in step.dependencies:
                visit(dep_id)
            
            visited.add(step_id)
            order.append(step_id)
        
        for step in self.steps:
            visit(step.step_id)
        
        return order


class OrchestratorRole:
    """
    Orchestrator Role: Plans and coordinates query execution
    
    The Orchestrator takes the analysis from the Analyzer and creates
    a detailed execution plan that can be executed by the Domain Specialists.
    
    Responsibilities:
    - Create execution plans from query analysis
    - Determine execution order and dependencies
    - Identify parallelizable steps
    - Estimate execution time
    - Coordinate tool invocation
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, tools: Optional[List] = None):
        """
        Initialize OrchestratorRole
        
        Args:
            config: Optional configuration dictionary
            tools: Optional list of available tools
        """
        self.config = config or {}
        self.tools = tools or []
        self.plans: Dict[str, ExecutionPlan] = {}
        self.plan_counter = 0
        
        # Initialize predictive executor
        self.predictor = PredictiveExecutor(config)
        
        self.stats = {
            'plans_created': 0,
            'avg_steps_per_plan': 0.0,
            'parallel_plans': 0,
            'sequential_plans': 0,
            'adaptive_optimizations_applied': 0
        }
    
    async def create_plan(
        self,
        query: str,
        intent: str,
        domains: List[str],
        entities: Dict[str, Any]
    ) -> ExecutionPlan:
        """
        Create an execution plan for a query
        
        Args:
            query: Original user query
            intent: Classified intent (search, create, update, delete, analyze)
            domains: List of involved domains (email, calendar, tasks)
            entities: Extracted entities from query
            
        Returns:
            ExecutionPlan with steps and dependencies
        """
        self.plan_counter += 1
        plan_id = f"plan_{self.plan_counter}_{datetime.now().timestamp()}"
        
        plan = ExecutionPlan(
            plan_id=plan_id,
            query=query,
            intent=intent,
            domains=domains
        )
        
        # Build execution steps based on intent and domains
        self._build_execution_steps(plan, intent, domains, entities)
        
        # Optimize the plan (async)
        await self._optimize_plan(plan)
        
        # Store plan
        self.plans[plan_id] = plan
        self.stats['plans_created'] += 1
        
        return plan
    
    def _build_execution_steps(
        self,
        plan: ExecutionPlan,
        intent: str,
        domains: List[str],
        entities: Dict[str, Any]
    ) -> None:
        """Build execution steps from intent and domains"""
        
        step_counter = 0
        
        # Search queries need to execute first
        if intent == 'search':
            # CRITICAL: Filter domains to only include valid ones
            # If query explicitly mentions email, don't create steps for other domains
            query_lower = plan.query.lower() if hasattr(plan, 'query') else ''
            explicit_email_query = any(keyword in query_lower for keyword in [
                'email', 'emails', 'message', 'messages', 'inbox', 'mail', 
                'send email', 'reply', 'forward', 'unread', 'new email', 'new emails'
            ])
            explicit_task_query = any(keyword in query_lower for keyword in [
                'task', 'tasks', 'todo', 'todos', 'reminder', 'deadline'
            ])
            explicit_calendar_query = any(keyword in query_lower for keyword in [
                'calendar', 'meeting', 'meetings', 'event', 'events', 'appointment', 'schedule'
            ])
            
            # Filter domains based on explicit keywords
            filtered_domains = []
            for domain in domains:
                if explicit_email_query and domain == 'email':
                    filtered_domains.append(domain)
                elif explicit_task_query and domain in ['task', 'tasks']:
                    filtered_domains.append(domain)
                elif explicit_calendar_query and domain == 'calendar':
                    filtered_domains.append(domain)
                elif not explicit_email_query and not explicit_task_query and not explicit_calendar_query:
                    # If no explicit keywords, include all detected domains
                    filtered_domains.append(domain)
            
            # Use filtered domains (or original if no filtering occurred)
            domains_to_use = filtered_domains if filtered_domains else domains
            
            # Create search steps for each valid domain
            for domain in domains_to_use:
                step_counter += 1
                step = self._create_search_step(
                    step_id=f"step_{step_counter}",
                    domain=domain,
                    entities=entities
                )
                plan.add_step(step)
        
        # Create/update/delete operations
        elif intent in ['create', 'update', 'delete']:
            # CRITICAL: For 'create' operations, skip the search step - we don't need to search before creating
            # For 'update' and 'delete', we may need to search first to find the item to update/delete
            # But for 'create', we can go straight to creation
            if intent == 'create':
                # Execute the create action directly without searching first
                for domain in domains:
                    step_counter += 1
                    step = self._create_action_step(
                        step_id=f"step_{step_counter}",
                        domain=domain,
                        intent=intent,
                        entities=entities,
                        depends_on=[]  # No dependencies for create operations
                    )
                    plan.add_step(step)
            else:
                # For update/delete, search first to find the item
                if intent != 'delete' or 'id' not in entities:
                    for domain in domains:
                        step_counter += 1
                        step = self._create_search_step(
                            step_id=f"step_{step_counter}",
                            domain=domain,
                            entities=entities
                        )
                        plan.add_step(step)
                
                # Then execute the action
                for domain in domains:
                    step_counter += 1
                    step = self._create_action_step(
                        step_id=f"step_{step_counter}",
                        domain=domain,
                        intent=intent,
                        entities=entities,
                        depends_on=[s.step_id for s in plan.steps if s.domain == domain]
                    )
                    plan.add_step(step)
        
        # Analysis/synthesis requires search then analysis
        elif intent == 'analyze':
            for domain in domains:
                step_counter += 1
                step = self._create_search_step(
                    step_id=f"step_{step_counter}",
                    domain=domain,
                    entities=entities
                )
                plan.add_step(step)
            
            # Add synthesis step
            step_counter += 1
            search_steps = [s.step_id for s in plan.steps if s.step_type == ExecutionStepType.CALENDAR_SEARCH]
            step = ExecutionStep(
                step_id=f"step_{step_counter}",
                step_type=ExecutionStepType.SYNTHESIS,
                domain="system",
                action="synthesize",
                dependencies=search_steps
            )
            plan.add_step(step)
        
        # Default: multi-domain search
        else:
            # CRITICAL: Filter domains to only include valid ones
            # If query explicitly mentions email, don't create steps for other domains
            query_lower = plan.query.lower() if hasattr(plan, 'query') and plan.query else ''
            explicit_email_query = any(keyword in query_lower for keyword in [
                'email', 'emails', 'message', 'messages', 'inbox', 'mail', 
                'send email', 'reply', 'forward', 'unread', 'new email', 'new emails'
            ])
            explicit_task_query = any(keyword in query_lower for keyword in [
                'task', 'tasks', 'todo', 'todos', 'reminder', 'deadline'
            ])
            explicit_calendar_query = any(keyword in query_lower for keyword in [
                'calendar', 'meeting', 'meetings', 'event', 'events', 'appointment', 'schedule'
            ])
            
            # Filter domains based on explicit keywords
            filtered_domains = []
            for domain in domains:
                if explicit_email_query and domain == 'email':
                    filtered_domains.append(domain)
                elif explicit_task_query and domain in ['task', 'tasks']:
                    filtered_domains.append(domain)
                elif explicit_calendar_query and domain == 'calendar':
                    filtered_domains.append(domain)
                elif not explicit_email_query and not explicit_task_query and not explicit_calendar_query:
                    # If no explicit keywords, include all detected domains
                    filtered_domains.append(domain)
            
            # Use filtered domains (or original if no filtering occurred)
            domains_to_use = filtered_domains if filtered_domains else domains
            
            # Create search steps for each valid domain
            for domain in domains_to_use:
                step_counter += 1
                step = self._create_search_step(
                    step_id=f"step_{step_counter}",
                    domain=domain,
                    entities=entities
                )
                plan.add_step(step)
    
    def _create_search_step(
        self,
        step_id: str,
        domain: str,
        entities: Dict[str, Any]
    ) -> ExecutionStep:
        """Create a search execution step"""
        step_type_map = {
            'email': ExecutionStepType.EMAIL_SEARCH,
            'calendar': ExecutionStepType.CALENDAR_SEARCH,
            'tasks': ExecutionStepType.TASK_SEARCH,
        }
        
        # Map domain to correct action name that tools actually support
        # EmailTool: search, list, unread, etc. (NOT search_email)
        # TaskTool: list, search, etc. (NOT search_tasks)
        # CalendarTool: list, search, etc. (NOT search_calendar)
        # For queries like "What new emails do I have", use 'list' instead of 'search'
        action_map = {
            'email': 'list',     # EmailTool: 'list' for viewing emails, 'search' for searching
            'calendar': 'list',  # CalendarTool supports 'list' for viewing events
            'tasks': 'list',     # TaskTool supports 'list' for viewing tasks
            'task': 'list',      # Handle singular form too
        }
        
        # Use 'list' as default for viewing queries, tools can override with parser-detected action
        action = action_map.get(domain, 'list')
        
        return ExecutionStep(
            step_id=step_id,
            step_type=step_type_map.get(domain, ExecutionStepType.EMAIL_SEARCH),
            domain=domain,
            action=action,  # Use correct action name, not f"search_{domain}"
            parameters={'entities': entities}
        )
    
    def _create_action_step(
        self,
        step_id: str,
        domain: str,
        intent: str,
        entities: Dict[str, Any],
        depends_on: Optional[List[str]] = None
    ) -> ExecutionStep:
        """Create an action execution step"""
        
        type_map = {
            ('email', 'create'): ExecutionStepType.EMAIL_ACTION,
            ('email', 'update'): ExecutionStepType.EMAIL_ACTION,
            ('calendar', 'create'): ExecutionStepType.CALENDAR_CREATE,
            ('calendar', 'update'): ExecutionStepType.CALENDAR_UPDATE,
            ('tasks', 'create'): ExecutionStepType.TASK_CREATE,
            ('tasks', 'update'): ExecutionStepType.TASK_UPDATE,
        }
        
        step_type = type_map.get((domain, intent), ExecutionStepType.EMAIL_ACTION)
        
        # CRITICAL: Use just the intent as the action (e.g., 'create', 'update', 'delete')
        # Tools expect actions like 'create', not 'create_calendar' or 'create_tasks'
        # The domain is already specified in the step's domain field
        action = intent
        
        return ExecutionStep(
            step_id=step_id,
            step_type=step_type,
            domain=domain,
            action=action,  # Use just intent, not f"{intent}_{domain}"
            parameters={'entities': entities},
            dependencies=depends_on or []
        )
    
    async def _optimize_plan(self, plan: ExecutionPlan) -> None:
        """Optimize execution plan for parallelization and speed"""
        
        # Find parallelizable steps (steps with no dependencies)
        parallelizable_groups = []
        step_ids = [s.step_id for s in plan.steps]
        
        # Group by domain for parallelization
        email_steps = [s for s in plan.steps if s.domain == 'email']
        calendar_steps = [s for s in plan.steps if s.domain == 'calendar']
        task_steps = [s for s in plan.steps if s.domain == 'tasks']
        
        # Check if steps in different domains can run in parallel
        can_parallelize = True
        for group in [email_steps, calendar_steps, task_steps]:
            if len(group) > 0:
                # Check if any step depends on steps from other groups
                for step in group:
                    for other_group in [email_steps, calendar_steps, task_steps]:
                        if other_group != group and any(d in [s.step_id for s in other_group] for d in step.dependencies):
                            can_parallelize = False
                            break
        
        plan.parallel_execution_possible = can_parallelize
        
        # Use PredictiveExecutor for optimization suggestions if available
        if self.predictor:
            # Convert steps to format expected by predictor
            steps_data = [
                {
                    'step_id': s.step_id,
                    'step_type': s.step_type.value,
                    'domain': s.domain,
                    'action': s.action,
                    'dependencies': s.dependencies
                }
                for s in plan.steps
            ]
            
            # Get adaptation suggestions (async)
            try:
                adaptations = await self.predictor.suggest_adaptations(
                    plan_id=plan.plan_id,
                    steps=steps_data
                )
                
                # Apply high-priority adaptations
                for adaptation in adaptations:
                    if adaptation.priority == 'high' and adaptation.adaptation_type == 'parallelize':
                        # Mark plan as parallelizable if predictor suggests it
                        if not plan.parallel_execution_possible:
                            plan.parallel_execution_possible = True
                            self.stats['adaptive_optimizations_applied'] += 1
            except Exception as e:
                # If async call fails, continue with basic optimization
                logger.debug(f"Could not get predictive adaptations: {e}")
        
        # Update stats
        if can_parallelize:
            self.stats['parallel_plans'] += 1
        else:
            self.stats['sequential_plans'] += 1
        
        # Estimate duration
        steps_per_second = 2  # Rough estimate
        plan.estimated_duration_seconds = len(plan.steps) / steps_per_second
    
    def get_plan(self, plan_id: str) -> Optional[ExecutionPlan]:
        """Retrieve a plan by ID"""
        return self.plans.get(plan_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics"""
        total_plans = self.stats['plans_created']
        if total_plans > 0:
            total_steps = sum(len(p.steps) for p in self.plans.values())
            avg_steps = total_steps / total_plans
            parallel_pct = (self.stats['parallel_plans'] / total_plans) * 100
        else:
            avg_steps = 0
            parallel_pct = 0
        
        return {
            'total_plans': total_plans,
            'parallel_plans': self.stats['parallel_plans'],
            'sequential_plans': self.stats['sequential_plans'],
            'parallel_percentage': f"{parallel_pct:.1f}%",
            'avg_steps_per_plan': f"{avg_steps:.1f}"
        }
    
    async def get_predicted_next_steps(
        self,
        query: str,
        intent: str,
        domains: List[str],
        executed_steps: List[str],
        user_id: Optional[int] = None,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Get predicted next steps using pattern history
        
        Args:
            query: Current query
            intent: Current intent
            domains: Current domains
            executed_steps: Steps already executed
            user_id: Optional user ID for personalization
            limit: Max predictions to return
            
        Returns:
            List of predicted steps with confidence scores
        """
        if not self.predictor:
            return []
        
        predictions = await self.predictor.predict_next_steps(
            query, intent, domains, executed_steps, user_id, limit
        )
        
        return [
            {
                'step_type': p.step_type,
                'domain': p.domain,
                'action': p.action,
                'confidence': p.confidence.value,
                'confidence_score': p.confidence_score,
                'rationale': p.rationale,
                'estimated_duration_ms': p.estimated_duration_ms
            }
            for p in predictions
        ]
    
    async def suggest_plan_adaptations(
        self,
        plan_id: str,
        user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get suggestions for plan optimization/adaptation
        
        Args:
            plan_id: Plan ID
            user_id: Optional user ID
            
        Returns:
            List of suggested adaptations
        """
        if not self.predictor or plan_id not in self.plans:
            return []
        
        plan = self.plans[plan_id]
        steps_data = [
            {
                'step_id': s.step_id,
                'step_type': s.step_type.value,
                'domain': s.domain,
                'action': s.action,
                'dependencies': s.dependencies,
                'parameters': s.parameters
            }
            for s in plan.steps
        ]
        
        adaptations = await self.predictor.suggest_adaptations(
            plan_id, steps_data, user_id
        )
        
        self.stats['adaptive_optimizations_applied'] += len(adaptations)
        
        return [
            {
                'type': a.adaptation_type,
                'affected_steps': a.affected_steps,
                'rationale': a.rationale,
                'estimated_improvement_pct': a.estimated_improvement_pct,
                'priority': a.priority
            }
            for a in adaptations
        ]
    
    async def learn_execution(
        self,
        plan_id: str,
        executed_steps: List[Dict[str, Any]],
        total_duration_ms: float,
        success: bool,
        user_id: Optional[int] = None
    ) -> None:
        """
        Learn from execution for future predictions
        
        Args:
            plan_id: Plan ID
            executed_steps: Steps that were executed
            total_duration_ms: Total execution time
            success: Whether execution succeeded
            user_id: Optional user ID
        """
        if not self.predictor or plan_id not in self.plans:
            return
        
        plan = self.plans[plan_id]
        
        await self.predictor.learn_execution(
            query=plan.query,
            intent=plan.intent,
            domains=plan.domains,
            executed_steps=executed_steps,
            total_duration_ms=total_duration_ms,
            success=success,
            user_id=user_id
        )
