# Clavr Agent Evaluation Framework

## Overview

A comprehensive evaluation framework for systematically testing and measuring the performance of the Clavr agent across all its capabilities.

## Evaluation Areas

### 1. Intent Classification
**Purpose**: Verify the agent correctly identifies user query intents.

**Metrics**:
- Accuracy: % of correctly classified intents
- Precision: True positives / (True positives + False positives)
- Recall: True positives / (True positives + False negatives)
- F1 Score: Harmonic mean of precision and recall

**Test Cases**: Email, calendar, task, and multi-step query intents

### 2. Entity Extraction
**Purpose**: Verify the agent correctly extracts entities (dates, people, locations, etc.) from queries.

**Metrics**:
- Entity-level accuracy
- Precision and recall per entity type
- Confidence scores

**Test Cases**: Attendees, recipients, dates, times, keywords, locations

### 3. Tool Selection
**Purpose**: Verify the agent routes queries to the correct tools.

**Metrics**:
- Tool selection accuracy
- Tool ranking correctness
- Fallback behavior

**Test Cases**: Email, calendar, and task tool routing

### 4. Response Quality
**Purpose**: Verify agent responses are correct, complete, and helpful.

**Metrics**:
- Response completeness
- Required term presence
- Forbidden term absence
- Response length

**Test Cases**: Various query types with expected response criteria

### 5. Preset Functionality
**Purpose**: Verify preset creation, retrieval, and usage works correctly.

**Metrics**:
- Preset CRUD operation success
- Preset expansion accuracy
- Variable substitution correctness

**Test Cases**: Calendar, task, and email preset operations

### 6. Contact Resolution
**Purpose**: Verify the agent correctly resolves contact names to email addresses.

**Metrics**:
- Resolution accuracy
- Multi-tier resolution success (Neo4j → RAG → Email search)
- Email validation correctness

**Test Cases**: Known contacts with expected email addresses

### 7. Conversation Memory
**Purpose**: Verify conversation history is stored and retrieved correctly.

**Metrics**:
- Message storage success
- Context retrieval accuracy
- Conversation listing correctness

**Test Cases**: Message storage, retrieval, and conversation listing

### 8. End-to-End
**Purpose**: Verify complete task completion from query to final result.

**Metrics**:
- Task completion success rate
- Response quality
- Entity presence in responses
- Error rate

**Test Cases**: Real-world scenarios with full expectations

### 9. Multi-Step Query Evaluation
**Purpose**: Verify the agent correctly handles complex multi-step queries.

**Metrics**:
- Step decomposition accuracy
- Correct step count
- Correct step ordering
- Dependency detection accuracy
- Cross-domain transition success
- Parallel execution correctness
- Context passing between steps

**Test Cases**: 
- Simple 2-step queries (same domain)
- Cross-domain 2-step queries
- 3+ step queries with dependencies
- Sequential vs parallel execution
- Context passing scenarios

**Examples**:
- "Find emails from John and send him a reply" (2 steps: search → send)
- "Find budget emails from last week and schedule a review meeting" (2 steps: email → calendar)
- "Find emails about the project, summarize them, then schedule a meeting" (3 steps with dependencies)

### 10. Autonomy Evaluation
**Purpose**: Verify the agent's autonomous decision-making and execution capabilities.

**Metrics**:
- Autonomous execution rate
- Appropriate clarification rate
- Error recovery success rate
- Partial result handling quality
- Context resolution accuracy
- Plan adaptation success rate
- Confidence-based decision accuracy

**Test Cases**:
- High confidence queries (should execute autonomously)
- Medium confidence queries (should use context/memory)
- Low confidence queries (should ask for clarification)
- Error recovery scenarios
- Partial success handling
- Context-aware multi-turn scenarios
- Adaptive planning scenarios

**Examples**:
- "Schedule a meeting with John tomorrow at 3pm" (high confidence, autonomous)
- "Schedule something with that person we met last week" (medium confidence, uses context)
- "Do that thing we talked about" (low confidence, should clarify)
- "Schedule meetings with John, Sarah, and invalid@email.com" (error recovery, partial success)

## Architecture

```
BaseEvaluator (Abstract)
├── IntentClassificationEvaluator
├── EntityExtractionEvaluator
├── ToolSelectionEvaluator
├── ResponseQualityEvaluator
├── PresetFunctionalityEvaluator
├── ContactResolutionEvaluator
├── ConversationMemoryEvaluator
├── EndToEndEvaluator
├── MultiStepEvaluator
└── AutonomyEvaluator

EvaluationRunner
└── Orchestrates all 10 evaluations
    └── Generates comprehensive reports
```

## Usage

### Quick Start

```bash
# Run all evaluations
python tests/evals/run_evals.py
```

### Programmatic Usage

```python
from tests.evals.runner import run_evaluations

results = await run_evaluations(
    agent=agent,
    tools=tools,
    db_session=db_session,
    graph_manager=graph_manager,
    rag_engine=rag_engine,
    email_service=email_service,
    user_id=1
)
```

### Individual Evaluations

```python
from tests.evals import IntentClassificationEvaluator, INTENT_TEST_CASES

evaluator = IntentClassificationEvaluator()
metrics = await evaluator.evaluate(INTENT_TEST_CASES)
evaluator.print_summary()
```

## Test Datasets

Test cases are organized by evaluation type in `tests/evals/datasets.py`:

- **INTENT_TEST_CASES**: 10+ intent classification test cases
- **ENTITY_TEST_CASES**: 5+ entity extraction test cases
- **TOOL_SELECTION_TEST_CASES**: 5+ tool routing test cases
- **RESPONSE_QUALITY_TEST_CASES**: 2+ response quality test cases
- **PRESET_TEST_CASES**: 3+ preset functionality test cases
- **CONTACT_RESOLUTION_TEST_CASES**: 2+ contact resolution test cases
- **MEMORY_TEST_CASES**: 1+ conversation memory test case
- **E2E_TEST_CASES**: 3+ end-to-end test cases
- **MULTISTEP_TEST_CASES**: 10+ multi-step query test cases
- **AUTONOMY_TEST_CASES**: 12+ autonomy evaluation test cases

## Results Format

### Metrics Output

```json
{
  "accuracy": 0.95,
  "precision": 0.93,
  "recall": 0.97,
  "f1_score": 0.95,
  "total_tests": 20,
  "passed_tests": 19,
  "failed_tests": 1,
  "average_confidence": 0.92,
  "average_latency_ms": 45.3,
  "error_count": 1
}
```

### Detailed Results

Each test case result includes:
- Query
- Expected vs. Predicted values
- Pass/Fail status
- Confidence score
- Latency
- Error messages (if any)
- Detailed metrics

## Integration

### CI/CD Integration

Add to `.github/workflows/evals.yml`:

```yaml
name: Run Evaluations
on: [push, pull_request]
jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
      - run: pip install -r requirements.txt
      - run: python tests/evals/run_evals.py
      - uses: actions/upload-artifact@v3
        with:
          name: eval-results
          path: eval_results/
```

### Monitoring

Track evaluation metrics over time:
- Set up automated daily/weekly runs
- Store results in time-series database
- Create dashboards for trend analysis
- Set up alerts for accuracy drops

## Best Practices

1. **Run Regularly**: After major changes, before releases
2. **Expand Test Cases**: Add real user queries and edge cases
3. **Track Trends**: Monitor accuracy over time
4. **Fix Failures**: Address failing tests promptly
5. **Update Datasets**: Keep test cases current with agent capabilities

## Extending the Framework

### Adding New Evaluations

1. Create evaluator class inheriting from `BaseEvaluator`
2. Implement `evaluate()` method
3. Add test cases to `datasets.py`
4. Register in `runner.py`
5. Update documentation

### Adding Test Cases

Edit `tests/evals/datasets.py`:

```python
NEW_TEST_CASES: List[TestCase] = [
    TestCase(
        query="Your test query",
        expected_intent="expected_intent",
        expected_tool="expected_tool",
        expected_entities={"key": "value"},
        expected_response_contains=["required"],
        expected_response_excludes=["forbidden"],
        context={"user_id": 1},
        metadata={"custom": "data"}
    ),
]
```

## Troubleshooting

### Common Issues

**"No agent provided" warnings**
- Some evaluations require agent/tools/db
- These will be skipped automatically if not available
- This is expected behavior

**Database connection errors**
- Ensure database is running
- Check connection settings
- Verify user permissions

**Import errors**
- Ensure project root is in Python path
- Install all dependencies
- Check for circular imports

## Future Enhancements

- [x] Multi-step query evaluation
- [x] Autonomy evaluation
- [ ] Automated test case generation from production logs
- [ ] A/B testing framework integration
- [ ] Performance benchmarking
- [ ] Regression detection
- [ ] Visual dashboards
- [ ] Real-time evaluation monitoring
- [ ] Workflow pattern evaluation (conditional execution, iterative operations)
- [ ] Advanced dependency tracking and validation

