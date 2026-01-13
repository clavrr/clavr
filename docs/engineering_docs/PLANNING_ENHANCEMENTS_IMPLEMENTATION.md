# Planning Enhancements Implementation Guide

## Overview

This guide provides concrete, implementable enhancements to make the Clavr agent smarter and more autonomous through:
1. Post-execution reflection
2. Enhanced chain-of-thought reasoning
3. Strategic self-criticism
4. Adaptive plan refinement

All implementations maintain simplicity and effectiveness.

## Enhancement 1: Post-Execution Reflection

### Implementation

**File**: `src/agent/orchestration/core/autonomous.py`

Add after `_synthesize_response_node`:

```python
async def _reflect_on_execution_node(self, state: AgentState) -> AgentState:
    """
    Reflect on execution quality and planning effectiveness.
    
    This node analyzes:
    - Whether the plan achieved its goal
    - Efficiency of the execution
    - What could be improved
    - Lessons learned for future queries
    """
    logger.info(f"{LOG_INFO} [REFLECT] Analyzing execution")
    
    try:
        query = state['query']
        results = state.get('results', [])
        steps = state.get('steps', [])
        original_plan = state['context'].get('llm_plan', 'No plan recorded')
        
        # Skip reflection if no results
        if not results:
            state['context']['reflection'] = {
                'skipped': True,
                'reason': 'No results to reflect on'
            }
            return state
        
        # Build reflection prompt
        reflection_prompt = f"""You just executed this query. Reflect on the execution:

Original Query: "{query}"

Original Plan:
{original_plan}

Execution Summary:
- Steps planned: {len(steps)}
- Steps executed: {len(results)}
- Successful steps: {sum(1 for r in results if r.get('success', False))}

Results:
{json.dumps([{
    'step_id': r.get('step_id', 'unknown'),
    'success': r.get('success', False),
    'result_summary': str(r.get('result', ''))[:200] if r.get('result') else 'No result'
} for r in results], indent=2)}

Reflect on:
1. Did the execution achieve the user's goal? (yes/no/partially)
2. Was the plan efficient? Were there unnecessary steps?
3. What worked well?
4. What could be improved?
5. What would you do differently for a similar query?

Return ONLY valid JSON:
{{
    "goal_achieved": true/false/partial,
    "efficiency_score": 0.0-1.0,
    "unnecessary_steps": ["step_id1", "step_id2"] or [],
    "what_worked_well": ["point1", "point2"],
    "improvements": ["suggestion1", "suggestion2"],
    "lessons_learned": "brief summary for future queries"
}}"""
        
        if self.llm_client:
            try:
                from langchain_core.messages import HumanMessage
                response = self.llm_client.invoke([HumanMessage(content=reflection_prompt)])
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                # Extract JSON from response
                reflection_json = self._extract_json_from_response(response_text)
                reflection = json.loads(reflection_json)
                
                # Store reflection in state
                state['context']['reflection'] = reflection
                state['context']['reflection_timestamp'] = datetime.now().isoformat()
                
                # Log key insights
                if reflection.get('improvements'):
                    logger.info(f"{LOG_INFO} [REFLECT] Improvements: {reflection['improvements']}")
                if reflection.get('lessons_learned'):
                    logger.info(f"{LOG_INFO} [REFLECT] Lessons: {reflection['lessons_learned']}")
                
            except Exception as e:
                logger.warning(f"{LOG_WARNING} [REFLECT] LLM reflection failed: {e}")
                state['context']['reflection'] = {'error': str(e)}
        else:
            # Simple heuristic reflection if no LLM
            successful = sum(1 for r in results if r.get('success', False))
            total = len(results)
            state['context']['reflection'] = {
                'goal_achieved': 'partial' if successful < total else 'true',
                'efficiency_score': successful / total if total > 0 else 0.0,
                'improvements': ['Consider simplifying plan'] if total > 3 else []
            }
        
        return state
        
    except Exception as e:
        logger.error(f"{LOG_ERROR} [REFLECT] Failed: {e}")
        state['context']['reflection'] = {'error': str(e)}
        return state
```

**Update workflow graph** to include reflection node:

```python
# In __init__ or _build_workflow method:
self.workflow.add_node("reflect", self._reflect_on_execution_node)

# Add edge from synthesize to reflect:
self.workflow.add_edge("synthesize", "reflect")

# Add edge from reflect to END:
self.workflow.add_edge("reflect", END)
```

## Enhancement 2: Enhanced Chain-of-Thought During Execution

### Implementation

**File**: `src/agent/state.py`

Add to `AgentState`:

```python
reasoning_chain: List[Dict[str, Any]]
"""Chain of reasoning steps. Each entry contains:
- step_number: int
- reasoning: str - Why this decision was made
- alternatives_considered: List[str]
- confidence: float - 0.0-1.0
- timestamp: str
"""
```

**File**: `src/agent/orchestration/core/autonomous.py`

Update `_execute_step_node` to record reasoning:

```python
async def _execute_step_node(self, state: AgentState) -> AgentState:
    """Execute step with reasoning chain"""
    logger.info(f"{LOG_INFO} [EXECUTE] Executing step")
    
    try:
        # Initialize reasoning chain if not present
        if 'reasoning_chain' not in state:
            state['reasoning_chain'] = []
        
        current_step_idx = state.get('current_step', 0)
        steps = state.get('steps', [])
        
        if current_step_idx >= len(steps):
            return state
        
        step = steps[current_step_idx]
        tool_name = step.get('tool_name')
        step_query = step.get('query', state['query'])
        
        # Generate reasoning before execution
        reasoning_prompt = f"""You are about to execute this step:

Step: {current_step_idx + 1}/{len(steps)}
Tool: {tool_name}
Query: "{step_query}"
Original Goal: "{state['query']}"

Explain:
1. Why are you using {tool_name} for this step?
2. What do you expect to achieve?
3. What alternatives did you consider?
4. How confident are you this is the right approach? (0.0-1.0)

Return JSON:
{{
    "reasoning": "explanation of why this tool/approach",
    "expected_outcome": "what you expect to get",
    "alternatives_considered": ["alt1", "alt2"],
    "confidence": 0.0-1.0
}}"""
        
        reasoning_entry = {
            'step_number': current_step_idx + 1,
            'tool_name': tool_name,
            'query': step_query,
            'timestamp': datetime.now().isoformat()
        }
        
        if self.llm_client:
            try:
                from langchain_core.messages import HumanMessage
                response = self.llm_client.invoke([HumanMessage(content=reasoning_prompt)])
                response_text = response.content if hasattr(response, 'content') else str(response)
                reasoning_json = self._extract_json_from_response(response_text)
                reasoning_data = json.loads(reasoning_json)
                
                reasoning_entry.update(reasoning_data)
            except Exception as e:
                logger.debug(f"Reasoning generation failed: {e}")
                reasoning_entry['reasoning'] = f"Executing {tool_name} for step {current_step_idx + 1}"
                reasoning_entry['confidence'] = 0.7
        else:
            reasoning_entry['reasoning'] = f"Executing {tool_name} for step {current_step_idx + 1}"
            reasoning_entry['confidence'] = 0.7
        
        state['reasoning_chain'].append(reasoning_entry)
        
        # Continue with existing execution logic...
        # ... (rest of _execute_step_node implementation)
        
        return state
    except Exception as e:
        logger.error(f"{LOG_ERROR} [EXECUTE] Failed: {e}")
        return state
```

## Enhancement 3: Strategic Self-Criticism

### Implementation

**File**: `src/agent/orchestration/core/autonomous.py`

Add before synthesis:

```python
async def _self_critique_node(self, state: AgentState) -> AgentState:
    """
    Agent critiques its own planning and execution approach.
    
    This helps the agent identify its own mistakes and improve.
    """
    logger.info(f"{LOG_INFO} [CRITIQUE] Self-critiquing approach")
    
    try:
        query = state['query']
        steps = state.get('steps', [])
        results = state.get('results', [])
        reasoning_chain = state.get('reasoning_chain', [])
        
        critique_prompt = f"""Critique your own approach to this query:

Query: "{query}"

Your Plan:
{json.dumps([{
    'step': i+1,
    'tool': s.get('tool_name'),
    'query': s.get('query', '')
} for i, s in enumerate(steps)], indent=2)}

Your Reasoning:
{json.dumps(reasoning_chain, indent=2)}

Execution Results:
{json.dumps([{
    'step': r.get('step_id'),
    'success': r.get('success'),
    'summary': str(r.get('result', ''))[:150]
} for r in results], indent=2)}

Be critical. Ask yourself:
1. Was this the best approach? Could you have done it differently?
2. Did you make any assumptions that were wrong?
3. Were there simpler ways to achieve the goal?
4. What mistakes did you make (if any)?
5. How would an expert approach this differently?

Return JSON:
{{
    "was_best_approach": true/false,
    "mistakes_made": ["mistake1", "mistake2"] or [],
    "simpler_alternatives": ["alt1", "alt2"] or [],
    "expert_advice": "how an expert would approach this",
    "self_rating": 0.0-1.0
}}"""
        
        if self.llm_client:
            try:
                from langchain_core.messages import HumanMessage
                response = self.llm_client.invoke([HumanMessage(content=critique_prompt)])
                response_text = response.content if hasattr(response, 'content') else str(response)
                critique_json = self._extract_json_from_response(response_text)
                critique = json.loads(critique_json)
                
                state['context']['self_critique'] = critique
                
                # Log if mistakes were identified
                if critique.get('mistakes_made'):
                    logger.warning(f"{LOG_WARNING} [CRITIQUE] Identified mistakes: {critique['mistakes_made']}")
                
            except Exception as e:
                logger.debug(f"Self-critique failed: {e}")
                state['context']['self_critique'] = {'error': str(e)}
        else:
            state['context']['self_critique'] = {'skipped': 'No LLM available'}
        
        return state
        
    except Exception as e:
        logger.error(f"{LOG_ERROR} [CRITIQUE] Failed: {e}")
        return state
```

**Update workflow**:

```python
# Add critique node before synthesis
self.workflow.add_node("critique", self._self_critique_node)
self.workflow.add_edge("validate", "critique")
self.workflow.add_edge("critique", "synthesize")
```

## Enhancement 4: Adaptive Plan Refinement

### Implementation

**File**: `src/agent/orchestration/core/autonomous.py`

Add after each step execution:

```python
async def _refine_plan_node(self, state: AgentState) -> AgentState:
    """
    Refine remaining plan based on execution results.
    
    This allows the agent to adapt its plan as it learns from execution.
    """
    logger.info(f"{LOG_INFO} [REFINE] Refining plan based on results")
    
    try:
        current_step = state.get('current_step', 0)
        steps = state.get('steps', [])
        results = state.get('results', [])
        
        # Only refine if there are remaining steps
        if current_step >= len(steps) - 1:
            return state
        
        # Get results so far
        completed_results = results[:current_step + 1]
        remaining_steps = steps[current_step + 1:]
        
        if not remaining_steps:
            return state
        
        refinement_prompt = f"""You've executed some steps. Refine your remaining plan:

Original Query: "{state['query']}"

Completed Steps & Results:
{json.dumps([{
    'step': i+1,
    'tool': steps[i].get('tool_name'),
    'result_summary': str(r.get('result', ''))[:200] if r.get('result') else 'No result',
    'success': r.get('success', False)
} for i, r in enumerate(completed_results)], indent=2)}

Remaining Planned Steps:
{json.dumps([{
    'step': current_step + 2 + i,
    'tool': s.get('tool_name'),
    'query': s.get('query', '')
} for i, s in enumerate(remaining_steps)], indent=2)}

Based on what you've learned:
1. Do the remaining steps still make sense?
2. Should any steps be modified based on results?
3. Are there new steps needed?
4. Can any steps be skipped?

Return JSON:
{{
    "plan_needs_refinement": true/false,
    "steps_to_modify": [
        {{"step_number": 2, "new_query": "modified query", "reason": "why"}}
    ] or [],
    "steps_to_add": [
        {{"tool": "tool_name", "query": "new step query", "reason": "why"}}
    ] or [],
    "steps_to_skip": [2, 3] or [],
    "refined_plan": "brief explanation of changes"
}}"""
        
        if self.llm_client:
            try:
                from langchain_core.messages import HumanMessage
                response = self.llm_client.invoke([HumanMessage(content=refinement_prompt)])
                response_text = response.content if hasattr(response, 'content') else str(response)
                refinement_json = self._extract_json_from_response(response_text)
                refinement = json.loads(refinement_json)
                
                if refinement.get('plan_needs_refinement'):
                    # Apply refinements
                    if refinement.get('steps_to_modify'):
                        for mod in refinement['steps_to_modify']:
                            step_num = mod['step_number'] - 1  # Convert to 0-based
                            if 0 <= step_num < len(steps):
                                steps[step_num]['query'] = mod.get('new_query', steps[step_num].get('query'))
                                logger.info(f"{LOG_INFO} [REFINE] Modified step {step_num + 1}")
                    
                    if refinement.get('steps_to_add'):
                        for add in refinement['steps_to_add']:
                            new_step = {
                                'id': f'step_{len(steps) + 1}',
                                'tool_name': add.get('tool'),
                                'query': add.get('query'),
                                'intent': 'general',
                                'action': 'execute',
                                'dependencies': [f'step_{current_step + 1}'],
                                'status': 'pending'
                            }
                            steps.append(new_step)
                            logger.info(f"{LOG_INFO} [REFINE] Added new step: {add.get('query')}")
                    
                    if refinement.get('steps_to_skip'):
                        # Mark steps to skip
                        for skip_num in refinement['steps_to_skip']:
                            step_idx = skip_num - 1
                            if 0 <= step_idx < len(steps):
                                steps[step_idx]['status'] = 'skipped'
                                logger.info(f"{LOG_INFO} [REFINE] Skipped step {skip_num}")
                    
                    state['steps'] = steps
                    state['context']['plan_refined'] = True
                    state['context']['refinement_reason'] = refinement.get('refined_plan', '')
                
            except Exception as e:
                logger.debug(f"Plan refinement failed: {e}")
        
        return state
        
    except Exception as e:
        logger.error(f"{LOG_ERROR} [REFINE] Failed: {e}")
        return state
```

**Update workflow** to refine after each step:

```python
# Add conditional edge from execute to refine
self.workflow.add_node("refine_plan", self._refine_plan_node)
self.workflow.add_conditional_edges(
    "execute",
    lambda s: "refine_plan" if s.get('current_step', 0) < len(s.get('steps', [])) - 1 else "validate",
    {
        "refine_plan": "refine_plan",
        "validate": "validate"
    }
)
self.workflow.add_edge("refine_plan", "validate")
```

## Helper Methods

Add these helper methods to `AutonomousOrchestrator`:

```python
def _extract_json_from_response(self, response_text: str) -> str:
    """Extract JSON from LLM response, handling markdown code blocks"""
    response_text = response_text.strip()
    
    # Try to extract JSON from markdown code blocks
    if '```json' in response_text:
        start_idx = response_text.find('```json') + 7
        end_idx = response_text.find('```', start_idx)
        if end_idx != -1:
            return response_text[start_idx:end_idx].strip()
    elif '```' in response_text:
        start_idx = response_text.find('```') + 3
        end_idx = response_text.find('```', start_idx)
        if end_idx != -1:
            return response_text[start_idx:end_idx].strip()
    
    # Try to find JSON object
    start_idx = response_text.find('{')
    end_idx = response_text.rfind('}')
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        return response_text[start_idx:end_idx + 1]
    
    return response_text
```

## Integration with Memory System

**File**: `src/agent/roles/memory_role.py`

Update `learn_from_execution` to include reflection:

```python
async def learn_from_execution(
    self,
    query: str,
    intent: str,
    domains: List[str],
    execution_time_ms: float,
    success: bool,
    user_id: Optional[int] = None,
    reflection: Optional[Dict[str, Any]] = None,  # NEW
    self_critique: Optional[Dict[str, Any]] = None  # NEW
) -> None:
    """Learn from execution, including reflection and critique"""
    # ... existing learning logic ...
    
    # Store reflection insights
    if reflection:
        # Learn from improvements suggested
        if reflection.get('improvements'):
            # Store improvements for similar queries
            pass
    
    # Store critique insights
    if self_critique:
        # Learn from mistakes identified
        if self_critique.get('mistakes_made'):
            # Store mistakes to avoid in future
            pass
```

## Testing

Create test cases:

```python
# tests/test_planning_enhancements.py

async def test_reflection_node():
    """Test that reflection node analyzes execution"""
    # ... test implementation

async def test_reasoning_chain():
    """Test that reasoning chain is recorded"""
    # ... test implementation

async def test_self_critique():
    """Test that self-critique identifies issues"""
    # ... test implementation

async def test_plan_refinement():
    """Test that plan is refined based on results"""
    # ... test implementation
```

## Configuration

Add to `src/agent/orchestration/config/autonomous_config.py`:

```python
class AutonomousOrchestratorConfig:
    # ... existing config ...
    
    # Planning enhancements
    ENABLE_REFLECTION = True
    ENABLE_REASONING_CHAIN = True
    ENABLE_SELF_CRITIQUE = True
    ENABLE_PLAN_REFINEMENT = True
    
    # Reflection thresholds
    REFLECTION_MIN_STEPS = 2  # Only reflect if 2+ steps
    REFLECTION_QUALITY_THRESHOLD = 0.7  # Reflect if quality below this
```

## Summary

These enhancements add:
1. **Reflection**: Agent learns from its execution
2. **Reasoning Chain**: Explicit reasoning trail
3. **Self-Criticism**: Agent identifies its own mistakes
4. **Plan Refinement**: Adaptive planning during execution

All while maintaining simplicity and avoiding over-engineering.

