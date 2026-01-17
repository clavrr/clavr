# Clavr Agent Evaluation Framework

Comprehensive evaluation suite for testing all Clavr agent capabilities.

## Overview

This evaluation framework provides systematic testing of:
1. **Intent Classification** - Accuracy of query intent detection
2. **Entity Extraction** - Accuracy of entity extraction from queries
3. **Tool Selection** - Correctness of tool routing
4. **Response Quality** - Quality and correctness of agent responses
5. **Preset Functionality** - Creation, retrieval, and usage of presets
6. **Contact Resolution** - Accuracy of name-to-email resolution
7. **Conversation Memory** - Context retrieval and conversation history
8. **End-to-End** - Complete task completion from query to result

## Structure

```
tests/evals/
├── __init__.py          # Package exports
├── base.py              # Base evaluator classes and utilities
├── intent_eval.py       # Intent classification evaluator
├── entity_eval.py       # Entity extraction evaluator
├── tool_selection_eval.py  # Tool selection evaluator
├── response_eval.py     # Response quality evaluator
├── preset_eval.py       # Preset functionality evaluator
├── contact_eval.py      # Contact resolution evaluator
├── memory_eval.py       # Conversation memory evaluator
├── e2e_eval.py          # End-to-end evaluator
├── datasets.py           # Test case datasets
├── runner.py            # Evaluation orchestrator
├── run_evals.py         # Script to run all evaluations
└── README.md            # This file
```

## Usage

### Running All Evaluations

```bash
# From project root
python tests/evals/run_evals.py
```

### Running Specific Evaluations

```python
from tests.evals import IntentClassificationEvaluator, INTENT_TEST_CASES

evaluator = IntentClassificationEvaluator()
results = await evaluator.evaluate(INTENT_TEST_CASES)
evaluator.print_summary()
```

### Using the Evaluation Runner

```python
from tests.evals.runner import EvaluationRunner

runner = EvaluationRunner(
    agent=agent,
    tools=tools,
    db_session=db_session,
    graph_manager=graph_manager,
    rag_engine=rag_engine,
    email_service=email_service,
    user_id=1,
    output_dir="eval_results"
)

results = await runner.run_all()
```

## Test Datasets

Test cases are defined in `datasets.py`:

- `INTENT_TEST_CASES` - Intent classification test cases
- `ENTITY_TEST_CASES` - Entity extraction test cases
- `TOOL_SELECTION_TEST_CASES` - Tool selection test cases
- `RESPONSE_QUALITY_TEST_CASES` - Response quality test cases
- `PRESET_TEST_CASES` - Preset functionality test cases
- `CONTACT_RESOLUTION_TEST_CASES` - Contact resolution test cases
- `MEMORY_TEST_CASES` - Conversation memory test cases
- `E2E_TEST_CASES` - End-to-end test cases

## Adding New Test Cases

To add new test cases, edit `datasets.py`:

```python
NEW_TEST_CASES: List[TestCase] = [
    TestCase(
        query="Your test query here",
        expected_intent="expected_intent",
        expected_tool="expected_tool",
        expected_entities={"key": "value"},
        expected_response_contains=["required", "terms"],
        expected_response_excludes=["forbidden", "terms"],
        context={"user_id": 1, "session_id": "test"},
        metadata={"custom": "data"}
    ),
]
```

## Evaluation Metrics

Each evaluation returns `EvaluationMetrics` with:

- `accuracy` - Overall accuracy (0.0-1.0)
- `precision` - Precision score
- `recall` - Recall score
- `f1_score` - F1 score
- `total_tests` - Total number of test cases
- `passed_tests` - Number of passed tests
- `failed_tests` - Number of failed tests
- `average_confidence` - Average confidence score
- `average_latency_ms` - Average latency in milliseconds
- `errors` - List of error messages

## Results

Evaluation results are saved to:
- `eval_results/evaluation_results_YYYYMMDD_HHMMSS.json`

The JSON file contains:
- Timestamp
- Overall metrics
- Per-evaluation metrics
- Detailed results for each test case

## Requirements

Evaluations require different components:

- **Intent/Entity/Tool Selection**: No dependencies (can run standalone)
- **Response Quality**: Requires `ClavrAgent` instance
- **Preset Functionality**: Requires PostgreSQL database (uses sync sessions)
- **Contact Resolution**: Requires graph_manager, rag_engine, or email_service
- **Conversation Memory**: Requires PostgreSQL database (uses async sessions)
- **End-to-End**: Requires `ClavrAgent` instance

Evaluations will automatically skip if required components are not available.

### Database Requirements

**PostgreSQL must be running** for preset and memory evaluations.

**Check if PostgreSQL is running:**
```bash
pg_isready -h localhost -p 5432
```

**Start PostgreSQL (macOS with Homebrew):**
```bash
brew services start postgresql@17
# or
brew services start postgresql@16
# or
brew services start postgresql
```

**Verify database connection:**
The evaluation runner will automatically check database connectivity and warn if PostgreSQL is not accessible.

## Best Practices

1. **Run regularly** - Run evaluations after major changes
2. **Track metrics** - Monitor accuracy trends over time
3. **Add test cases** - Continuously add edge cases and real user queries
4. **Review failures** - Analyze failed tests to improve agent
5. **Update datasets** - Keep test cases current with agent capabilities

## Integration with CI/CD

Add to your CI/CD pipeline:

```yaml
# .github/workflows/evals.yml
- name: Run Evaluations
  run: python tests/evals/run_evals.py
```

## Troubleshooting

### "No agent provided" warnings
- Some evaluations require agent/tools/db - this is expected if components aren't available
- These evaluations will be skipped automatically

### Import errors
- Ensure project root is in Python path
- Install all dependencies: `pip install -r requirements.txt`

### Database errors
- Ensure database is running and accessible
- Check database connection settings

## Contributing

When adding new evaluations:

1. Create evaluator class inheriting from `BaseEvaluator`
2. Implement `evaluate()` method
3. Add test cases to `datasets.py`
4. Register in `runner.py`
5. Update this README

