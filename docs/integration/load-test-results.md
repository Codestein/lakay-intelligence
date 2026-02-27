# Load Test Results

Phase 10 -- Task 10.5: Load test results document.

**Status:** Template -- populate with actual results after running load tests.

**Harness:** `tests/load/harness.py`

**Run command:**
```bash
# Custom parameters
python tests/load/harness.py --target-rps 100 --duration 60 --ramp-time 30

# Built-in profiles
python tests/load/harness.py --profile throughput
python tests/load/harness.py --profile stress
python tests/load/harness.py --profile burst
python tests/load/harness.py --profile stability --duration 3600

# With output file
python tests/load/harness.py --profile throughput --output results/load-test-$(date +%Y%m%d).json
```

---

## Test Environment

| Component         | Specification                     |
|-------------------|-----------------------------------|
| Application       | Lakay Intelligence v0.1.0         |
| Host              | _[record machine spec]_           |
| CPU               | _[record CPU model and cores]_    |
| Memory            | _[record RAM]_                    |
| Database          | PostgreSQL (asyncpg)              |
| Message Broker    | Apache Kafka                      |
| Cache             | Redis                             |
| Load Driver       | `tests/load/harness.py` (httpx async) |
| Date              | _[record date]_                   |

---

## 1. Throughput Curves

Profile: `throughput` -- Ramp from 100 to 1000 RPS over three phases.

| Phase | Target RPS | Duration (s) | Ramp (s) | Total Events | Avg Achieved RPS | Error Rate |
|-------|-----------|--------------|----------|--------------|-----------------|------------|
| 1     | 100       | 60           | 20       | _[fill]_     | _[fill]_        | _[fill]_   |
| 2     | 500       | 120          | 40       | _[fill]_     | _[fill]_        | _[fill]_   |
| 3     | 1000      | 600          | 60       | _[fill]_     | _[fill]_        | _[fill]_   |

**Throughput curve data points:**

_[Paste throughput_curve array from JSON output, or attach chart]_

---

## 2. Latency Percentiles per Module

### Fraud Scoring (`POST /api/v1/fraud/score`)

| RPS Level | p50 (ms) | p95 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms) | Count  |
|-----------|---------|---------|---------|----------|---------|---------|--------|
| 100       | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ |
| 500       | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ |
| 1000      | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ |

### Session Scoring (`POST /api/v1/behavior/sessions/score`)

| RPS Level | p50 (ms) | p95 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms) | Count  |
|-----------|---------|---------|---------|----------|---------|---------|--------|
| 100       | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ |
| 500       | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ |
| 1000      | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ |

### Circle Health (`POST /api/v1/circles/{id}/score`)

| RPS Level | p50 (ms) | p95 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms) | Count  |
|-----------|---------|---------|---------|----------|---------|---------|--------|
| 100       | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ |
| 500       | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ |
| 1000      | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ |

### Feature Store Lookup

| RPS Level | p50 (ms) | p95 (ms) | p99 (ms) | Mean (ms) | Min (ms) | Max (ms) | Count  |
|-----------|---------|---------|---------|----------|---------|---------|--------|
| 100       | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ |
| 500       | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ |
| 1000      | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ | _[fill]_ |

---

## 3. Breaking Point Analysis

Profile: `stress` -- Push from 1000 to 2500 RPS to find the breaking point.

| Phase | Target RPS | Duration (s) | Achieved Avg RPS | Error Rate | p95 Fraud (ms) | p95 Session (ms) | p95 Circle (ms) | Status     |
|-------|-----------|--------------|-----------------|------------|---------------|-----------------|-----------------|------------|
| 1     | 1000      | 120          | _[fill]_        | _[fill]_   | _[fill]_      | _[fill]_        | _[fill]_        | _[fill]_   |
| 2     | 1500      | 120          | _[fill]_        | _[fill]_   | _[fill]_      | _[fill]_        | _[fill]_        | _[fill]_   |
| 3     | 2000      | 120          | _[fill]_        | _[fill]_   | _[fill]_      | _[fill]_        | _[fill]_        | _[fill]_   |
| 4     | 2500      | 120          | _[fill]_        | _[fill]_   | _[fill]_      | _[fill]_        | _[fill]_        | _[fill]_   |

**Breaking point identified at:** _[fill]_ RPS

**Failure mode at breaking point:**
- _[describe: timeout? error spike? latency degradation?]_

### Burst Test Results

Profile: `burst` -- Baseline 200 RPS, spike to 2000 RPS for 60s, return to baseline.

| Phase     | Target RPS | Duration (s) | Error Rate | p95 Fraud (ms) | Recovery Time (s) |
|-----------|-----------|--------------|------------|---------------|-------------------|
| Baseline  | 200       | 60           | _[fill]_   | _[fill]_      | N/A               |
| Burst     | 2000      | 60           | _[fill]_   | _[fill]_      | N/A               |
| Recovery  | 200       | 60           | _[fill]_   | _[fill]_      | _[fill]_          |

---

## 4. Resource Utilization Profiles

_Record resource utilization at each RPS level using system monitoring tools._

### CPU Utilization

| RPS Level | API Process (%) | DB Process (%) | Kafka (%) | Redis (%) | System Total (%) |
|-----------|----------------|---------------|-----------|-----------|-----------------|
| 100       | _[fill]_       | _[fill]_      | _[fill]_  | _[fill]_  | _[fill]_        |
| 500       | _[fill]_       | _[fill]_      | _[fill]_  | _[fill]_  | _[fill]_        |
| 1000      | _[fill]_       | _[fill]_      | _[fill]_  | _[fill]_  | _[fill]_        |
| 1500      | _[fill]_       | _[fill]_      | _[fill]_  | _[fill]_  | _[fill]_        |
| 2000      | _[fill]_       | _[fill]_      | _[fill]_  | _[fill]_  | _[fill]_        |

### Memory Utilization

| RPS Level | API Process (MB) | DB Process (MB) | Kafka (MB) | Redis (MB) | System Total (MB) |
|-----------|-----------------|----------------|-----------|------------|------------------|
| 100       | _[fill]_        | _[fill]_       | _[fill]_  | _[fill]_   | _[fill]_         |
| 500       | _[fill]_        | _[fill]_       | _[fill]_  | _[fill]_   | _[fill]_         |
| 1000      | _[fill]_        | _[fill]_       | _[fill]_  | _[fill]_   | _[fill]_         |
| 1500      | _[fill]_        | _[fill]_       | _[fill]_  | _[fill]_   | _[fill]_         |
| 2000      | _[fill]_        | _[fill]_       | _[fill]_  | _[fill]_   | _[fill]_         |

### Database Connection Pool

| RPS Level | Active Connections | Idle Connections | Pool Exhaustion Events | Avg Query Time (ms) |
|-----------|-------------------|-----------------|----------------------|---------------------|
| 100       | _[fill]_          | _[fill]_        | _[fill]_             | _[fill]_            |
| 500       | _[fill]_          | _[fill]_        | _[fill]_             | _[fill]_            |
| 1000      | _[fill]_          | _[fill]_        | _[fill]_             | _[fill]_            |

---

## 5. Bottleneck Identification

_Identify the primary bottleneck at each load level._

| RPS Level | Primary Bottleneck      | Evidence                          | Mitigation                        |
|-----------|------------------------|-----------------------------------|-----------------------------------|
| 100       | _[fill]_               | _[fill]_                          | _[fill]_                          |
| 500       | _[fill]_               | _[fill]_                          | _[fill]_                          |
| 1000      | _[fill]_               | _[fill]_                          | _[fill]_                          |
| 1500      | _[fill]_               | _[fill]_                          | _[fill]_                          |
| 2000+     | _[fill]_               | _[fill]_                          | _[fill]_                          |

**Common bottleneck categories to check:**
- Database query latency (especially feature store lookups)
- Connection pool exhaustion (asyncpg pool size)
- Kafka producer backpressure
- Redis latency under load
- CPU saturation in scoring logic
- Memory pressure from in-flight requests
- Network I/O limits

---

## 6. Stability Test Results

Profile: `stability` -- 500 RPS sustained for 1 hour.

| Metric                        | Value      |
|-------------------------------|------------|
| Duration                      | _[fill]_ s |
| Total events sent             | _[fill]_   |
| Average RPS (sustained)       | _[fill]_   |
| Overall error rate            | _[fill]_ % |
| Memory growth over duration   | _[fill]_ MB |
| p95 latency at start (0-5m)  | _[fill]_ ms |
| p95 latency at end (55-60m)  | _[fill]_ ms |
| Latency drift                 | _[fill]_ ms |

**Memory leak indicators:** _[fill: any monotonic memory growth?]_

**Latency degradation:** _[fill: does p95 increase over time?]_

---

## 7. SLA Compliance

Defined in `tests/load/harness.py` as `SLA_TARGETS`.

| SLA Metric                    | Target (ms) | Actual p95 (ms) | Pass/Fail |
|-------------------------------|------------|----------------|-----------|
| Fraud scoring p95             | 200        | _[fill]_       | _[fill]_  |
| Session scoring p95           | 100        | _[fill]_       | _[fill]_  |
| Feature store lookup p95      | 10         | _[fill]_       | _[fill]_  |
| Circle health p95             | 500        | _[fill]_       | _[fill]_  |

**Overall SLA compliance:** _[PASS / FAIL]_

### SLA at Different Load Levels

| Load Level | Fraud (200ms) | Session (100ms) | Feature Store (10ms) | Circle (500ms) | Overall |
|------------|--------------|----------------|---------------------|---------------|---------|
| 100 RPS    | _[fill]_     | _[fill]_       | _[fill]_            | _[fill]_      | _[fill]_ |
| 500 RPS    | _[fill]_     | _[fill]_       | _[fill]_            | _[fill]_      | _[fill]_ |
| 1000 RPS   | _[fill]_     | _[fill]_       | _[fill]_            | _[fill]_      | _[fill]_ |
| 1500 RPS   | _[fill]_     | _[fill]_       | _[fill]_            | _[fill]_      | _[fill]_ |

---

## 8. Event Type Mix

The load test uses the following event type distribution (configurable in harness):

| Event Type   | Weight | Target Endpoint                              |
|--------------|--------|----------------------------------------------|
| Transaction  | 0.40   | `POST /api/v1/fraud/score`                   |
| Session      | 0.30   | `POST /api/v1/behavior/sessions/score`       |
| Circle       | 0.15   | `POST /api/v1/circles/{id}/score`            |
| Remittance   | 0.15   | `POST /api/v1/fraud/score` (as remittance type) |

Fraud injection rate: 5% of events carry fraud signals (configurable via `--fraud-pct`).

---

## 9. Recommendations

_Fill in after analyzing results._

### Performance Optimizations
1. _[fill]_
2. _[fill]_
3. _[fill]_

### Scaling Recommendations
1. _[fill]_
2. _[fill]_

### Configuration Tuning
1. _[fill]_
2. _[fill]_

---

## Appendix: Running the Tests

```bash
# Ensure infrastructure is running
docker-compose up -d

# Run throughput profile and save results
python tests/load/harness.py \
  --profile throughput \
  --base-url http://localhost:8000 \
  --fraud-pct 0.05 \
  --max-concurrent 200 \
  --output results/throughput-$(date +%Y%m%d-%H%M%S).json

# Run stress profile
python tests/load/harness.py \
  --profile stress \
  --output results/stress-$(date +%Y%m%d-%H%M%S).json

# Run burst profile
python tests/load/harness.py \
  --profile burst \
  --output results/burst-$(date +%Y%m%d-%H%M%S).json

# Run 1-hour stability profile
python tests/load/harness.py \
  --profile stability \
  --duration 3600 \
  --output results/stability-$(date +%Y%m%d-%H%M%S).json
```
