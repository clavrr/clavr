# Performance Testing Guide

This directory contains performance and load tests using [Locust](https://locust.io/).

## Prerequisites

```bash
pip install locust>=2.20.0
```

## Quick Start

### 1. Start the API Server

```bash
# In one terminal
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### 2. Run Basic Load Test

```bash
# In another terminal
cd tests/performance
locust -f locustfile.py --host http://localhost:8000
```

Then open http://localhost:8089 in your browser to configure and start the test.

## Test Scenarios

### Standard Load Test
Tests normal user behavior with mixed API calls.

```bash
locust -f locustfile.py \
    --host http://localhost:8000 \
    --users 50 \
    --spawn-rate 5 \
    --run-time 5m \
    --headless
```

### Cache Performance Test
Tests cache hit/miss performance with repeated queries.

```bash
locust -f locustfile.py \
    --host http://localhost:8000 \
    --users 20 \
    --spawn-rate 2 \
    --run-time 3m \
    --headless \
    CacheWarmupUser
```

### Spike Test
Tests system resilience under sudden traffic spikes.

```bash
locust -f load_shapes.py \
    --host http://localhost:8000 \
    --headless \
    SpikeLoadUser
```

### Step Load Test
Gradually increases load to find breaking points.

```bash
locust -f load_shapes.py \
    --host http://localhost:8000 \
    --headless \
    --shape StepLoadShape
```

### Wave Pattern Test
Simulates natural traffic with wave patterns.

```bash
locust -f load_shapes.py \
    --host http://localhost:8000 \
    --headless \
    --shape WaveLoadShape
```

## Key Metrics to Monitor

### Response Times
- **P50 (Median)**: Should be < 500ms for most endpoints
- **P95**: Should be < 2s
- **P99**: Should be < 5s

### Throughput
- **Requests/sec**: Monitor for degradation under load
- **Target**: > 100 req/s for standard queries

### Error Rate
- **Target**: < 1% under normal load
- **Alert**: > 5% indicates serious issues

### Cache Performance
- **Hit Rate**: Should be > 60% with caching enabled
- **Cache Response Time**: < 50ms for hits

## Load Test Profiles

### Light Load (Development)
```bash
--users 10 --spawn-rate 2 --run-time 2m
```

### Medium Load (Staging)
```bash
--users 50 --spawn-rate 5 --run-time 5m
```

### Heavy Load (Pre-Production)
```bash
--users 200 --spawn-rate 10 --run-time 10m
```

### Stress Test (Find Limits)
```bash
--users 500 --spawn-rate 20 --run-time 10m
```

## Output Formats

### CSV Report
```bash
locust -f locustfile.py \
    --host http://localhost:8000 \
    --users 50 \
    --spawn-rate 5 \
    --run-time 5m \
    --headless \
    --csv=results/test_results
```

### HTML Report
```bash
locust -f locustfile.py \
    --host http://localhost:8000 \
    --users 50 \
    --spawn-rate 5 \
    --run-time 5m \
    --headless \
    --html=results/test_report.html
```

## Distributed Testing

For very high load, run Locust in distributed mode:

### Master Node
```bash
locust -f locustfile.py \
    --host http://localhost:8000 \
    --master
```

### Worker Nodes (run on multiple machines)
```bash
locust -f locustfile.py \
    --host http://localhost:8000 \
    --worker \
    --master-host <master-ip>
```

## Best Practices

### 1. Warm Up Period
Always include a warm-up period before measuring:
```bash
--run-time 10m  # First 2-3 minutes are warm-up
```

### 2. Monitor System Resources
Watch these during tests:
- CPU usage
- Memory usage
- Database connections
- Redis connections
- Network I/O

### 3. Baseline Testing
Run tests before and after changes:
```bash
# Before changes
locust -f locustfile.py --host http://localhost:8000 --headless --csv=before

# After changes
locust -f locustfile.py --host http://localhost:8000 --headless --csv=after

# Compare results
diff before_stats.csv after_stats.csv
```

### 4. Test in Isolation
- Disable other services during tests
- Use dedicated test database
- Clear caches between runs

## Performance Targets

### Health Endpoint
- **P50**: < 10ms
- **P95**: < 50ms
- **Throughput**: > 1000 req/s

### Chat Endpoint (with LLM)
- **P50**: < 2s
- **P95**: < 5s
- **P99**: < 10s
- **Throughput**: > 10 req/s

### Email List (with caching)
- **P50**: < 100ms (cache hit), < 500ms (cache miss)
- **P95**: < 300ms (cache hit), < 1s (cache miss)
- **Throughput**: > 50 req/s

### Calendar List (with caching)
- **P50**: < 200ms
- **P95**: < 500ms
- **Throughput**: > 30 req/s

## Troubleshooting

### High Error Rates
- Check server logs for exceptions
- Verify database connection pool size
- Check rate limiting settings

### Slow Response Times
- Enable caching
- Check database query performance
- Monitor external API latency
- Review circuit breaker states

### Connection Errors
- Increase server worker count
- Adjust connection pool sizes
- Check network bandwidth

## CI/CD Integration

### GitHub Actions Example
```yaml
- name: Run Performance Tests
  run: |
    pip install locust
    locust -f tests/performance/locustfile.py \
        --host http://localhost:8000 \
        --users 20 \
        --spawn-rate 2 \
        --run-time 2m \
        --headless \
        --csv=results/perf_test
        
- name: Check Performance
  run: |
    python scripts/check_performance.py results/perf_test_stats.csv
```

## Advanced Scenarios

### Testing Specific Endpoints
```python
# In locustfile.py
class EmailOnlyUser(HttpUser):
    @task
    def list_emails(self):
        self.client.get("/emails?page=1&page_size=20")
```

### Custom Metrics
```python
from locust import events

@events.request.add_listener
def on_request(request_type, name, response_time, **kwargs):
    if response_time > 1000:
        print(f"Slow request: {name} - {response_time}ms")
```

## Resources

- [Locust Documentation](https://docs.locust.io/)
- [Performance Testing Best Practices](https://locust.io/best-practices)
- [Distributed Load Testing](https://docs.locust.io/en/stable/running-distributed.html)

## Results Interpretation

### Good Performance
```
Response times:
  P50: 200ms
  P95: 500ms
  P99: 1000ms
Requests/sec: 100
Failure rate: 0.1%
```

### Needs Optimization
```
Response times:
  P50: 1000ms
  P95: 5000ms
  P99: 10000ms
Requests/sec: 20
Failure rate: 5%
```

### Critical Issues
```
Response times:
  P50: > 5000ms
  P95: > 10000ms
  P99: Timeout
Requests/sec: < 10
Failure rate: > 10%
```
