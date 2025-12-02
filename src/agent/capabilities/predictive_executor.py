"""
Predictive Planning Module

Provides predictive next-step suggestions and adaptive planning for the OrchestratorRole
based on historical execution patterns and user behavior.
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class PredictionConfidence(str, Enum):
    """Confidence levels for predictions"""
    HIGH = "high"      # >80%
    MEDIUM = "medium"  # 50-80%
    LOW = "low"        # 20-50%
    UNCERTAIN = "uncertain"  # <20%


@dataclass
class PredictedStep:
    """A predicted next step in execution"""
    step_type: str
    domain: str
    action: str
    confidence: PredictionConfidence
    confidence_score: float
    rationale: str
    estimated_duration_ms: float
    parameters_hints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionAdaptation:
    """Suggested adaptation to execution plan"""
    adaptation_type: str  # 'parallelize', 'reorder', 'cache_use', 'resource_allocation'
    affected_steps: List[str]
    rationale: str
    estimated_improvement_pct: float
    priority: str  # 'high', 'medium', 'low'


class PredictiveExecutor:
    """
    Predictive planning and execution optimization
    
    Uses learned execution patterns to:
    - Predict likely next steps
    - Suggest execution optimizations
    - Adapt plans based on real-time feedback
    - Proactively allocate resources
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize predictive executor"""
        self.config = config or {}
        
        # Pattern storage
        self.execution_sequences: Dict[str, List[Dict[str, Any]]] = {}
        self.step_duration_history: Dict[str, List[float]] = {}
        self.domain_correlations: Dict[str, Dict[str, float]] = {}
        
        # User patterns
        self.user_execution_patterns: Dict[int, Dict[str, Any]] = {}
        
        self.stats = {
            'predictions_made': 0,
            'accurate_predictions': 0,
            'adaptations_suggested': 0,
            'adaptations_accepted': 0,
        }
    
    async def predict_next_steps(
        self,
        current_query: str,
        current_intent: str,
        current_domains: List[str],
        executed_steps: List[str],
        user_id: Optional[int] = None,
        limit: int = 3
    ) -> List[PredictedStep]:
        """
        Predict likely next steps based on patterns
        
        Args:
            current_query: Current query
            current_intent: Current intent
            current_domains: Current domains
            executed_steps: Steps already executed
            user_id: Optional user ID for personalization
            limit: Maximum predictions to return
            
        Returns:
            List of predicted next steps
        """
        self.stats['predictions_made'] += 1
        predictions: List[PredictedStep] = []
        
        # Build pattern signature
        signature = self._create_signature(current_intent, current_domains)
        
        # Look for similar past execution sequences
        if signature in self.execution_sequences:
            similar_sequences = self.execution_sequences[signature]
            
            # Find sequences that have executed the same steps
            matching_sequences = [
                seq for seq in similar_sequences
                if all(step in seq for step in executed_steps)
            ]
            
            if matching_sequences:
                # Get next steps from matching sequences
                next_steps_candidates: Dict[str, Dict[str, Any]] = {}
                
                for sequence in matching_sequences:
                    # Find index after all executed steps
                    max_idx = 0
                    for exec_step in executed_steps:
                        try:
                            idx = sequence.index(exec_step)
                            max_idx = max(max_idx, idx)
                        except ValueError:
                            continue
                    
                    # Collect next steps
                    for i in range(max_idx + 1, min(max_idx + limit + 1, len(sequence))):
                        next_step = sequence[i]
                        if next_step['step_id'] not in next_steps_candidates:
                            next_steps_candidates[next_step['step_id']] = {
                                'count': 0,
                                'step': next_step,
                                'total_duration': 0.0
                            }
                        next_steps_candidates[next_step['step_id']]['count'] += 1
                        next_steps_candidates[next_step['step_id']]['total_duration'] += next_step.get('duration_ms', 0)
                
                # Convert to predictions
                for step_id, data in sorted(
                    next_steps_candidates.items(),
                    key=lambda x: x[1]['count'],
                    reverse=True
                )[:limit]:
                    step_data = data['step']
                    occurrence_rate = data['count'] / len(matching_sequences)
                    
                    # Determine confidence
                    if occurrence_rate >= 0.8:
                        confidence = PredictionConfidence.HIGH
                        conf_score = 0.8 + (occurrence_rate - 0.8) * 2
                    elif occurrence_rate >= 0.5:
                        confidence = PredictionConfidence.MEDIUM
                        conf_score = 0.5 + (occurrence_rate - 0.5) * 0.6
                    elif occurrence_rate >= 0.2:
                        confidence = PredictionConfidence.LOW
                        conf_score = 0.2 + (occurrence_rate - 0.2) * 1
                    else:
                        confidence = PredictionConfidence.UNCERTAIN
                        conf_score = occurrence_rate
                    
                    prediction = PredictedStep(
                        step_type=step_data.get('step_type', 'unknown'),
                        domain=step_data.get('domain', 'unknown'),
                        action=step_data.get('action', 'unknown'),
                        confidence=confidence,
                        confidence_score=min(0.95, conf_score),
                        rationale=f"Appears in {data['count']} similar execution sequences",
                        estimated_duration_ms=data['total_duration'] / data['count'],
                        parameters_hints=step_data.get('parameters', {})
                    )
                    predictions.append(prediction)
        
        return predictions
    
    async def suggest_adaptations(
        self,
        plan_id: str,
        steps: List[Dict[str, Any]],
        user_id: Optional[int] = None
    ) -> List[ExecutionAdaptation]:
        """
        Suggest plan adaptations based on patterns
        
        Args:
            plan_id: Plan ID
            steps: Execution steps
            user_id: Optional user ID
            
        Returns:
            List of suggested adaptations
        """
        self.stats['adaptations_suggested'] += 1
        adaptations: List[ExecutionAdaptation] = []
        
        # Check for parallelization opportunities
        parallelizable = self._identify_parallelizable_groups(steps)
        for group in parallelizable:
            if len(group) > 1:
                # Estimate improvement from parallelization
                sequential_time = sum(self._get_avg_duration(s['domain']) for s in group)
                parallel_time = max(self._get_avg_duration(s['domain']) for s in group)
                improvement = ((sequential_time - parallel_time) / sequential_time) * 100
                
                if improvement > 20:  # Only suggest if >20% improvement
                    adaptation = ExecutionAdaptation(
                        adaptation_type='parallelize',
                        affected_steps=[s['step_id'] for s in group],
                        rationale=f"These steps can execute in parallel ({len(group)} independent operations)",
                        estimated_improvement_pct=improvement,
                        priority='high' if improvement > 40 else 'medium'
                    )
                    adaptations.append(adaptation)
        
        # Check for caching opportunities
        # (recheck if we've seen these exact parameters before)
        cache_opportunities = self._identify_cache_opportunities(steps)
        for cache_opp in cache_opportunities:
            adaptation = ExecutionAdaptation(
                adaptation_type='cache_use',
                affected_steps=cache_opp['steps'],
                rationale=cache_opp['rationale'],
                estimated_improvement_pct=cache_opp['improvement'],
                priority='high'
            )
            adaptations.append(adaptation)
        
        # Check for resource allocation
        resource_hints = self._suggest_resource_allocation(steps)
        if resource_hints:
            adaptation = ExecutionAdaptation(
                adaptation_type='resource_allocation',
                affected_steps=[s['step_id'] for s in steps],
                rationale="Preemptively allocate resources based on historical patterns",
                estimated_improvement_pct=15.0,
                priority='medium'
            )
            adaptations.append(adaptation)
        
        return adaptations
    
    async def learn_execution(
        self,
        query: str,
        intent: str,
        domains: List[str],
        executed_steps: List[Dict[str, Any]],
        total_duration_ms: float,
        success: bool,
        user_id: Optional[int] = None
    ) -> None:
        """
        Learn from execution for future predictions
        
        Args:
            query: Query
            intent: Intent
            domains: Domains
            executed_steps: Steps that were executed
            total_duration_ms: Total execution time
            success: Whether execution succeeded
            user_id: Optional user ID
        """
        signature = self._create_signature(intent, domains)
        
        # Store sequence
        if signature not in self.execution_sequences:
            self.execution_sequences[signature] = []
        
        sequence = []
        for step in executed_steps:
            sequence.append({
                'step_id': step.get('step_id', 'unknown'),
                'step_type': step.get('step_type', 'unknown'),
                'domain': step.get('domain', 'unknown'),
                'action': step.get('action', 'unknown'),
                'duration_ms': step.get('execution_time_ms', 0),
                'parameters': step.get('parameters', {})
            })
        
        self.execution_sequences[signature].append(sequence)
        
        # Track step durations
        for step in executed_steps:
            domain = step.get('domain', 'unknown')
            if domain not in self.step_duration_history:
                self.step_duration_history[domain] = []
            self.step_duration_history[domain].append(step.get('execution_time_ms', 0))
        
        # Update user patterns
        if user_id:
            if user_id not in self.user_execution_patterns:
                self.user_execution_patterns[user_id] = {
                    'total_executions': 0,
                    'successful_executions': 0,
                    'preferred_domains': {},
                    'preferred_intents': {},
                    'avg_execution_time': 0.0
                }
            
            user_patterns = self.user_execution_patterns[user_id]
            user_patterns['total_executions'] += 1
            if success:
                user_patterns['successful_executions'] += 1
            
            for domain in domains:
                user_patterns['preferred_domains'][domain] = user_patterns['preferred_domains'].get(domain, 0) + 1
            
            user_patterns['preferred_intents'][intent] = user_patterns['preferred_intents'].get(intent, 0) + 1
            user_patterns['avg_execution_time'] = (
                user_patterns['avg_execution_time'] * 0.8 + total_duration_ms * 0.2
            )
    
    def _create_signature(self, intent: str, domains: List[str]) -> str:
        """Create a signature for an execution pattern"""
        return f"{intent}:{','.join(sorted(domains))}"
    
    def _identify_parallelizable_groups(self, steps: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """
        Identify groups of steps that can be parallelized
        
        Returns list of step groups that don't depend on each other
        """
        groups: Dict[str, List[Dict[str, Any]]] = {}
        
        for step in steps:
            domain = step.get('domain', 'unknown')
            if domain not in groups:
                groups[domain] = []
            groups[domain].append(step)
        
        # Check for independent group dependencies
        parallelizable_groups = []
        for domain, domain_steps in groups.items():
            if len(domain_steps) > 1:
                # Check if steps have dependencies
                has_dependencies = any(
                    len(s.get('dependencies', [])) > 0 for s in domain_steps
                )
                if not has_dependencies:
                    parallelizable_groups.append(domain_steps)
        
        return parallelizable_groups
    
    def _identify_cache_opportunities(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Identify steps that could use caching"""
        opportunities = []
        
        for step in steps:
            if step.get('action', '').endswith('_search'):
                # Search operations are good cache candidates
                opportunities.append({
                    'steps': [step.get('step_id', 'unknown')],
                    'rationale': 'Search operations frequently repeat',
                    'improvement': 75.0
                })
        
        return opportunities
    
    def _suggest_resource_allocation(self, steps: List[Dict[str, Any]]) -> List[str]:
        """Suggest resource allocation based on steps"""
        hints = []
        
        domains_in_plan = set(s.get('domain', 'unknown') for s in steps)
        
        if 'email' in domains_in_plan:
            hints.append('Allocate email service quota')
        if 'calendar' in domains_in_plan:
            hints.append('Allocate calendar API quota')
        if 'tasks' in domains_in_plan:
            hints.append('Allocate tasks API quota')
        
        return hints
    
    def _get_avg_duration(self, domain: str) -> float:
        """Get average execution duration for a domain"""
        if domain not in self.step_duration_history:
            return 100.0  # Default estimate
        
        durations = self.step_duration_history[domain]
        return sum(durations) / len(durations) if durations else 100.0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get predictive executor statistics"""
        total_predictions = self.stats['predictions_made']
        
        if total_predictions > 0:
            accuracy = (self.stats['accurate_predictions'] / total_predictions) * 100
        else:
            accuracy = 0
        
        adaptation_acceptance = 0
        if self.stats['adaptations_suggested'] > 0:
            adaptation_acceptance = (
                self.stats['adaptations_accepted'] / self.stats['adaptations_suggested']
            ) * 100
        
        return {
            'predictions_made': total_predictions,
            'accurate_predictions': self.stats['accurate_predictions'],
            'prediction_accuracy': f"{accuracy:.1f}%",
            'adaptations_suggested': self.stats['adaptations_suggested'],
            'adaptations_accepted': self.stats['adaptations_accepted'],
            'adaptation_acceptance_rate': f"{adaptation_acceptance:.1f}%",
            'learned_sequences': len(self.execution_sequences),
            'users_profiled': len(self.user_execution_patterns)
        }
