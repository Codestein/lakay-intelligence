# Drift Monitoring

> Lakay Intelligence -- Phase 10, Task 10.5
> Last updated: 2026-02-27

This document describes how feature drift and model performance drift are
detected, alerted on, and responded to in the Lakay Intelligence system.

---

## 1. Overview

Drift monitoring ensures that the fraud detection model continues to perform
as expected after deployment. Two types of drift are monitored:

| Drift Type | What Changes | Detection Method | Implementation |
|---|---|---|---|
| **Feature drift** | Input feature distributions shift from training data | Population Stability Index (PSI) | `src/serving/drift.py` -- `FeatureDriftDetector` |
| **Prediction drift** | Model output score distributions shift from deployment baseline | Z-score of mean shift | `src/serving/monitoring.py` -- `ModelMonitor` |

Both are exposed through the monitoring API endpoint:
```
GET /api/v1/serving/monitoring
```

---

## 2. Feature Drift Detection

### 2.1 Method: Population Stability Index (PSI)

The system uses PSI as the primary feature drift metric. PSI was chosen over
alternatives (KS-test, KL-divergence) because it produces a single interpretable
number with established thresholds that are well understood in financial model
monitoring and compliance reporting.

**PSI Formula:**

```
PSI = SUM( (current_pct_i - reference_pct_i) * ln(current_pct_i / reference_pct_i) )
```

Where `current_pct_i` and `reference_pct_i` are the proportions of observations
in bin `i` for the current window and the reference (training) distribution.

### 2.2 PSI Thresholds

Configured in `DriftConfig` (`src/serving/drift.py`):

| PSI Value | Severity | Interpretation | Default Action |
|---|---|---|---|
| < 0.10 | None | No significant drift | No action |
| 0.10 - 0.24 | **Warning** | Moderate drift detected | Investigate; check if feature pipeline changed |
| >= 0.25 | **Critical** | Significant drift detected | Retrain recommended; escalate to model owner |

### 2.3 Reference Distribution

The reference distribution is established at model deployment time:

1. When a model is loaded, `FeatureDriftDetector.set_reference_distribution()` is
   called for each feature using the training data distribution.
2. The training data is binned into equal-width histograms (`num_bins=10` by default).
3. Bin proportions are stored as the reference, with a small epsilon (1e-6) added
   to avoid division-by-zero in the PSI calculation.

Alternatively, `set_reference_from_dataframe()` can set all feature references
from a training DataFrame at once.

### 2.4 Monitored Features

All 11 features in the fraud detection model are monitored for drift:

| Feature | Type | Drift Sensitivity |
|---|---|---|
| `amount` | float | High -- transaction amounts may shift with economic conditions |
| `amount_zscore` | float | Medium -- normalized, but user behavior changes affect it |
| `hour_of_day` | int | Low -- temporal patterns are relatively stable |
| `day_of_week` | int | Low -- day-of-week patterns are relatively stable |
| `tx_type_encoded` | int | Medium -- product mix changes affect distribution |
| `balance_delta_sender` | float | Medium -- depends on user balance patterns |
| `balance_delta_receiver` | float | Medium -- depends on receiver behavior |
| `velocity_count_1h` | int | High -- usage patterns directly affect velocity |
| `velocity_count_24h` | int | High -- usage patterns directly affect velocity |
| `velocity_amount_1h` | float | High -- amount patterns directly affect velocity |
| `velocity_amount_24h` | float | High -- amount patterns directly affect velocity |

### 2.5 Observation Collection

- Each scoring request records feature values via
  `FeatureDriftDetector.record_observation()`.
- Observations are stored in a per-feature deque with a maximum size of
  50,000 observations (`max_observations`).
- Drift is checked every 500 observations (`check_interval_observations`).
- A minimum of 100 observations (`min_observations`) are required before PSI
  is computed.

### 2.6 Drift Alert Structure

When drift is detected, a `DriftAlert` is generated containing:

```python
DriftAlert(
    feature_name="amount",           # Which feature drifted
    drift_score=0.32,                # PSI value
    drift_method="psi",              # Detection method
    severity="critical",             # "warning" or "critical"
    window="last_5000_observations", # Observation window
    timestamp="2026-02-27T...",      # ISO-8601 timestamp
    details={                        # Additional context
        "psi_threshold_warning": 0.1,
        "psi_threshold_critical": 0.25,
        "observation_count": 5000,
    },
)
```

Up to 1,000 recent alerts are retained in memory.

---

## 3. Prediction Drift (Score Distribution Monitoring)

### 3.1 Method: Baseline Z-Score Shift

The `ModelMonitor` (`src/serving/monitoring.py`) tracks model output scores
over sliding time windows and compares them against a baseline established at
model deployment time.

**Detection formula:**

```
z_shift = |current_mean - baseline_mean| / baseline_std
```

### 3.2 Score Distribution Thresholds

Configured in `MonitoringConfig`:

| Metric | Threshold | Severity | Default Value |
|---|---|---|---|
| Score mean z-shift | > 2.0 std deviations | Warning | `score_shift_std_threshold=2.0` |
| Score mean z-shift | > 3.0 std deviations | Critical | Derived from warning threshold |

### 3.3 Latency SLA Monitoring

Prediction latency is also monitored with SLA thresholds:

| Metric | Threshold | Severity |
|---|---|---|
| P95 latency | > 200ms | Critical (`latency_sla_p95_ms=200.0`) |
| P99 latency | > 500ms | Critical (`latency_sla_p99_ms=500.0`) |

### 3.4 Sliding Time Windows

Score distribution statistics are computed over configurable time windows:

| Window | Purpose |
|---|---|
| 1 hour | Short-term anomaly detection; catches sudden shifts |
| 24 hours | Medium-term trend detection; smooths out hourly noise |
| 7 days | Long-term baseline comparison (available via `get_score_distribution()`) |

### 3.5 Baseline Establishment

When a new model version is deployed:

1. `ModelMonitor.set_baseline()` is called with scores from the validation dataset.
2. The baseline stores: mean, standard deviation, P50, P95, P99, and count.
3. The model version and load timestamp are recorded.

### 3.6 Monitoring Alert Structure

When a monitoring alert is triggered:

```python
MonitoringAlert(
    alert_type="score_distribution_shift",  # or "latency_sla_breach"
    severity="warning",                      # "warning" or "critical"
    metric_name="score_mean",
    current_value=0.42,
    baseline_value=0.28,
    threshold=2.0,
    window="1h",
    timestamp="2026-02-27T...",
    details={"z_shift": 2.5},
)
```

Up to 1,000 recent alerts are retained in memory.

---

## 4. Monitoring API

### 4.1 Endpoint: GET /api/v1/serving/monitoring

Returns a combined view of model status, score health, and drift status.

**Response structure:**

```json
{
  "model": {
    "name": "fraud-detector-v0.2",
    "version": "3",
    "loaded": true,
    "load_error": null
  },
  "scores": {
    "model_version": "3",
    "last_reload_timestamp": "2026-02-27T10:00:00+00:00",
    "total_predictions": 15432,
    "score_distribution_1h": {
      "mean": 0.28,
      "std": 0.15,
      "p50": 0.22,
      "p95": 0.67,
      "count": 342
    },
    "score_distribution_24h": {
      "mean": 0.27,
      "std": 0.14,
      "p50": 0.21,
      "p95": 0.65,
      "count": 8210
    },
    "latency_1h": {
      "p50_ms": 3.2,
      "p95_ms": 12.5,
      "p99_ms": 45.1,
      "count": 342
    },
    "baseline": {
      "mean": 0.26,
      "std": 0.13
    },
    "recent_alerts": []
  },
  "drift": {
    "features": {
      "amount": {
        "status": "ok",
        "psi": 0.04,
        "observation_count": 5000
      },
      "velocity_count_1h": {
        "status": "moderate_drift",
        "psi": 0.15,
        "observation_count": 5000
      }
    },
    "total_observations": 5000,
    "recent_alerts": []
  },
  "timestamp": "2026-02-27T12:00:00+00:00"
}
```

### 4.2 Drift Report Field Reference

Each feature in the drift report has one of these statuses:

| Status | Meaning |
|---|---|
| `ok` | PSI < 0.10; no drift detected |
| `moderate_drift` | 0.10 <= PSI < 0.25; investigation recommended |
| `critical_drift` | PSI >= 0.25; retraining recommended |
| `insufficient_data` | Fewer than 100 observations; cannot compute PSI |
| `no_reference` | No reference distribution set for this feature |

---

## 5. Response Procedures

### 5.1 Warning-Level Drift (PSI 0.10-0.24 or score z-shift 2.0-3.0)

**Timeline:** Investigate within 48 hours.

1. **Identify the cause:**
   - Check if the feature pipeline or data source changed
   - Check if there was a product change affecting transaction patterns
   - Check if it is a seasonal or temporal effect (e.g., holiday spending)
2. **Assess impact:**
   - Review model prediction quality over the affected period
   - Check if false positive or false negative rates changed
3. **Decide action:**
   - If drift is due to a temporary external event (holiday, outage), monitor
     and let it resolve
   - If drift is due to a genuine distribution shift, schedule retraining
   - Document the finding and decision

### 5.2 Critical-Level Drift (PSI >= 0.25 or score z-shift > 3.0)

**Timeline:** Investigate within 4 hours.

1. **Immediate assessment:**
   - Determine which features are drifting and by how much
   - Check if the drift is correlated across features (suggesting a systemic change)
2. **Risk evaluation:**
   - Estimate the impact on fraud detection accuracy
   - Check recent fraud alert volumes and false positive rates
3. **Decide action:**
   - If model performance has degraded: increase rule-based scoring weight
     (adjust `HybridScoringConfig.rule_weight` upward)
   - If multiple features are critically drifted: trigger emergency retraining
   - If the model is producing clearly unreliable scores: disable ML scoring
     temporarily by setting `HybridScoringConfig.ml_enabled = False`
4. **Escalation:**
   - Notify the Lakay Intelligence team lead
   - For compliance-impacting drift, notify the BSA officer
   - Document the incident and response

### 5.3 Latency SLA Breach

**Timeline:** Investigate within 1 hour.

1. **Check infrastructure:**
   - Model server resource utilization (CPU, memory)
   - MLflow registry availability
   - Feature store latency
2. **Mitigate:**
   - If the model is oversized: consider a lighter model version
   - If infrastructure is the issue: scale resources
   - If the issue persists: evaluate caching frequently-used predictions

### 5.4 Decision Matrix

| Condition | Action | Who |
|---|---|---|
| Single feature warning drift | Monitor for 48h, document | ML engineer |
| Multiple features warning drift | Investigate within 24h | ML engineer + team lead |
| Single feature critical drift | Investigate within 4h | ML engineer |
| Multiple features critical drift | Emergency retraining | ML engineer + team lead |
| Score distribution shift (warning) | Investigate within 48h | ML engineer |
| Score distribution shift (critical) | Increase rule weight; investigate within 4h | ML engineer + team lead |
| Latency SLA breach | Investigate within 1h | ML engineer + infrastructure |

---

## 6. Recommended Monitoring Schedule

### 6.1 Automated Checks

| Check | Frequency | Implementation |
|---|---|---|
| Feature drift (PSI) | Every 500 observations | Automatic via `FeatureDriftDetector.record_observation()` |
| Score distribution shift | Every 100 predictions | Automatic via `ModelMonitor.record_prediction()` |
| Latency SLA | Every 100 predictions | Automatic via `ModelMonitor._check_alerts()` |
| Monitoring API poll | Every 5 minutes | External monitoring system (recommended) |

### 6.2 Manual Reviews

| Review | Frequency | Responsibility |
|---|---|---|
| Drift report review | Weekly | ML engineer |
| Score distribution trending | Weekly | ML engineer |
| Feature distribution deep-dive | Monthly | ML engineer + data scientist |
| Model performance vs. baseline | Monthly | ML engineer + BSA officer (for compliance models) |
| Full monitoring system audit | Quarterly | Team lead |

### 6.3 Retraining Triggers

The model should be retrained when any of the following conditions are met:

| Trigger | Priority | Notes |
|---|---|---|
| Critical drift in 3+ features for > 7 days | High | Systematic distribution shift |
| Score distribution z-shift > 3.0 for > 24 hours | High | Model predictions are unreliable |
| False positive rate increases by > 20% relative | High | Measured via investigation outcomes |
| New transaction types added to the platform | Medium | Model has no training data for new types |
| Quarterly scheduled retraining | Medium | Even without drift, periodic retraining ensures freshness |
| New training data available (labeled fraud cases) | Medium | Real fraud labels improve model quality |

---

## 7. Configuration Reference

### 7.1 DriftConfig (src/serving/drift.py)

| Parameter | Default | Description |
|---|---|---|
| `psi_warning_threshold` | 0.1 | PSI value that triggers a warning alert |
| `psi_critical_threshold` | 0.25 | PSI value that triggers a critical alert |
| `num_bins` | 10 | Number of histogram bins for PSI calculation |
| `min_observations` | 100 | Minimum observations before drift check |
| `check_interval_observations` | 500 | Check drift every N observations |
| `max_observations` | 50,000 | Maximum observations stored per feature |

### 7.2 MonitoringConfig (src/serving/monitoring.py)

| Parameter | Default | Description |
|---|---|---|
| `score_shift_std_threshold` | 2.0 | Z-score threshold for score distribution shift alert |
| `latency_sla_p95_ms` | 200.0 | P95 latency SLA in milliseconds |
| `latency_sla_p99_ms` | 500.0 | P99 latency SLA in milliseconds |
| `max_observations` | 100,000 | Maximum score/latency observations stored |
