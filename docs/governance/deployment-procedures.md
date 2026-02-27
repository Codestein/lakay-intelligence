# Deployment Procedures

> Lakay Intelligence -- Phase 10, Task 10.5
> Last updated: 2026-02-27

This document describes the end-to-end procedures for training, validating,
promoting, A/B testing, and rolling back ML models in the Lakay Intelligence
system.

---

## 1. Overview

The model deployment lifecycle follows this progression:

```
Training -> Registration (None) -> Staging -> Validation -> Production -> Monitoring
                                                                |
                                                          Rollback (if needed)
```

**Key systems involved:**

| System | Role | Implementation |
|---|---|---|
| MLflow | Experiment tracking, model registry, artifact storage | PostgreSQL metadata + MinIO artifacts |
| ModelRegistry | Programmatic interface to MLflow operations | `src/serving/registry.py` |
| DeploymentPipeline | Validation, promotion, rollback orchestration | `src/serving/deploy.py` |
| ModelServer | In-process model loading and prediction serving | `src/serving/server.py` |
| ModelRouter | A/B traffic routing between champion and challenger | `src/serving/routing.py` |
| Serving API | HTTP endpoints for reload, routing, and monitoring | `src/api/routes/serving.py` |

---

## 2. Training Procedure

### 2.1 Prerequisites

- PaySim dataset (or Feast offline store export) available as CSV
- MLflow tracking server running at the configured URI (default: `http://localhost:5000`)
- Python environment with `xgboost`, `scikit-learn`, `mlflow`, `pandas`, `numpy` installed

### 2.2 Training Steps

**Step 1: Prepare the dataset**

The training pipeline reads PaySim-format CSV data and extracts 11 features via
`src/domains/fraud/ml/features.py`. For production retraining, generate a dataset
from the Feast offline store containing labeled transaction data.

**Step 2: Run the training pipeline**

```bash
# Basic training with default hyperparameters
python -m src.domains.fraud.ml.train --dataset data/paysim.csv

# Training with custom config
python -m src.domains.fraud.ml.train --dataset data/paysim.csv --config config.yaml

# Training with downsampled data for faster iteration
python -m src.domains.fraud.ml.train --dataset data/paysim.csv --sample-size 100000

# Specify MLflow tracking URI
python -m src.domains.fraud.ml.train --dataset data/paysim.csv --mlflow-uri http://mlflow:5000
```

**Step 3: What the pipeline does automatically**

1. Loads the CSV and builds the feature matrix (`build_feature_matrix()`)
2. Splits data into 80% train / 20% test (stratified by fraud label)
3. Auto-calculates `scale_pos_weight` from the class imbalance ratio
4. Trains an XGBoost `XGBClassifier` with the configured hyperparameters
5. Evaluates on the held-out test set (AUC-ROC, precision, recall, F1, confusion matrix)
6. Generates a classification report and ML-vs-rules comparison
7. Logs the model, metrics, parameters, and artifacts to MLflow
8. Registers the model in MLflow under the configured name (default: `fraud-detector-v0.1`)
9. Promotes the new model version to **Staging**

**Step 4: Review training results**

After training completes, the pipeline prints key metrics:

```
Training Complete: fraud-detector-v0.2
  Version: 3
  AUC-ROC: 0.9842
  Precision: 0.9521
  Recall: 0.8743
  F1: 0.9115
  Duration: 45.2s
```

Review the full results in the MLflow UI, including:
- The classification report artifact
- The ML-vs-rules comparison artifact
- All logged hyperparameters and metrics

### 2.3 Training Configuration

Default hyperparameters can be overridden via a YAML config file:

```yaml
model_name: "fraud-detector-v0.2"
random_seed: 42
test_size: 0.2
mlflow_tracking_uri: "http://mlflow:5000"
hyperparams:
  n_estimators: 200
  max_depth: 8
  learning_rate: 0.05
  subsample: 0.8
  colsample_bytree: 0.8
  min_child_weight: 5
  eval_metric: "aucpr"
grid_search:
  enabled: true
  param_grid:
    max_depth: [4, 6, 8]
    learning_rate: [0.05, 0.1]
    n_estimators: [100, 200]
  cv_folds: 3
  scoring: "f1"
```

### 2.4 Reproducibility

Every training run logs these artifacts for full reproducibility:

| Artifact | Purpose |
|---|---|
| `training_dataset_hash` (SHA-256) | Verify exact dataset used |
| `feature_list` (JSON) | Ordered feature names |
| `training_timestamp` (ISO-8601) | When the model was trained |
| `python_version` | Python version for environment reproduction |
| All hyperparameters | Exact configuration used |
| Model artifact (XGBoost native) | Serialized model |
| `classification_report.txt` | Full test set evaluation |
| `ml_vs_rules_comparison.json` | Hybrid approach justification |

---

## 3. Validation Procedure

### 3.1 Automated Validation

Before any model is promoted to Production, the `DeploymentPipeline.validate_model()`
method (`src/serving/deploy.py`) runs the following validation checks:

| Check | Description | Pass Criteria |
|---|---|---|
| `model_loads` | Model can be loaded from MLflow Staging | No exceptions during `mlflow.pyfunc.load_model()` |
| `scores_valid` | All predictions are finite numbers (no NaN, no Inf) | 100% of test predictions are valid |
| `scores_in_range` | All predictions are in the [0, 1] range | 100% of valid predictions are in range |
| `latency_within_sla` | P95 prediction latency meets the SLA | P95 latency <= 200ms (configurable) |

The validation runs against 100 synthetic feature vectors generated by
`_generate_validation_events()`. These vectors cover the realistic range of each
feature using distributions calibrated from PaySim data.

### 3.2 Running Validation Manually

```python
from src.serving.deploy import DeploymentPipeline

pipeline = DeploymentPipeline(tracking_uri="http://mlflow:5000")
result = pipeline.validate_model(
    name="fraud-detector-v0.2",
    version="3",
    latency_sla_ms=200.0,  # optional: override SLA
)

print(f"Passed: {result.passed}")
print(f"Checks: {result.checks}")
print(f"Details: {result.details}")
```

### 3.3 Offline Backtesting

In addition to the automated validation checks, perform offline backtesting
before promoting a new model version:

1. **Obtain a backtesting dataset** from the Feast offline store covering the
   most recent 30 days of transactions with known outcomes.
2. **Score the dataset** using both the current Production model and the candidate
   Staging model.
3. **Compare metrics:**

| Metric | Requirement |
|---|---|
| AUC-ROC | Candidate >= Current (no regression) |
| Precision | Candidate >= Current - 0.02 (within tolerance) |
| Recall | Candidate >= Current - 0.02 (within tolerance) |
| F1 | Candidate >= Current (no regression) |
| False Positive Rate | Candidate <= Current + 0.01 (within tolerance) |

4. **Document the comparison** in the MLflow experiment notes.

---

## 4. Promotion Procedure

### 4.1 MLflow Model Stages

Models transition through these stages:

```
None -> Staging -> Production -> Archived
```

| Stage | Meaning |
|---|---|
| None | Freshly registered; not yet evaluated |
| Staging | Under evaluation; available as challenger in A/B tests |
| Production | Currently serving as the champion model |
| Archived | Previously in Production; retained for rollback |

### 4.2 Promoting to Production

**Step 1: Ensure the model is in Staging and validated**

```python
from src.serving.deploy import DeploymentPipeline

pipeline = DeploymentPipeline(tracking_uri="http://mlflow:5000")
```

**Step 2: Promote with validation**

```python
record = pipeline.promote_to_production(
    name="fraud-detector-v0.2",
    version="3",
    triggered_by="engineer_name",
)

if record.success:
    print(f"Promoted version {record.model_version} to Production")
    print(f"Previous version {record.previous_version} archived")
else:
    print(f"Promotion blocked: {record.validation_result.checks}")
```

The `promote_to_production()` method:
1. Retrieves the current Production version (for rollback tracking)
2. Runs the full validation suite (unless `skip_validation=True`)
3. If validation passes: transitions the model to Production in MLflow
4. The previous Production version is automatically moved to Archived
5. Records a `DeploymentRecord` in the deployment history

**Step 3: Reload the serving layer**

After promotion, trigger a hot-reload so the serving layer picks up the new model:

```bash
curl -X POST http://localhost:8000/api/v1/serving/reload
```

Or programmatically:

```python
from src.serving.server import get_model_server

server = get_model_server()
success = server.reload_model()
```

**Step 4: Verify the new model is serving**

```bash
curl http://localhost:8000/api/v1/serving/monitoring
```

Confirm the response shows the new model version under `model.version`.

### 4.3 Approval Requirements

| Model Type | Approval Required | Approver |
|---|---|---|
| Fraud detection model | ML engineer + team lead | Team lead sign-off |
| Compliance-affecting model changes | ML engineer + BSA officer | BSA officer sign-off |
| Scoring threshold changes | ML engineer + BSA officer | BSA officer sign-off |
| Rule weight changes (hybrid scoring) | ML engineer + team lead | Team lead sign-off |

**BSA officer sign-off is required when:**
- The model directly impacts regulatory compliance (fraud detection, compliance scoring)
- Scoring thresholds are changed (affects CTR filing triggers, SAR recommendations)
- The hybrid scoring weights are adjusted (changes the balance between rule-based and ML scoring)

---

## 5. A/B Testing Procedure

### 5.1 Overview

The `ModelRouter` (`src/serving/routing.py`) enables A/B testing between a
champion (Production) and challenger (Staging) model. Routing is deterministic:
the same `user_id` always receives the same model variant within an experiment,
preventing score flickering.

### 5.2 Setting Up an A/B Test

**Step 1: Ensure both models are loaded**

- Champion: Production-stage model (loaded by default)
- Challenger: Staging-stage model (loaded manually or by configuring a second `ModelServer`)

**Step 2: Configure the traffic split**

Via the API:

```bash
curl -X POST http://localhost:8000/api/v1/serving/routing \
  -H "Content-Type: application/json" \
  -d '{"champion_pct": 90.0, "challenger_pct": 10.0}'
```

The percentages must sum to 100. Common configurations:

| Phase | Champion % | Challenger % | Duration |
|---|---|---|---|
| Initial canary | 95 | 5 | 24-48 hours |
| Ramp-up | 80 | 20 | 3-5 days |
| Equal split | 50 | 50 | 7+ days (for statistical significance) |
| Full rollout | 0 | 100 | After promotion |

**Step 3: Monitor the experiment**

Check routing metrics:

```bash
curl http://localhost:8000/api/v1/serving/routing
```

The response includes per-variant metrics:

```json
{
  "enabled": true,
  "champion_pct": 90.0,
  "challenger_pct": 10.0,
  "champion_model": "fraud-detector-v0.2",
  "champion_version": "2",
  "challenger_model": "fraud-detector-v0.2",
  "challenger_version": "3",
  "metrics_summary": {
    "total_observations": 10000,
    "champion": {
      "count": 9000,
      "mean_score": 0.27,
      "mean_latency_ms": 3.2,
      "p95_latency_ms": 12.1
    },
    "challenger": {
      "count": 1000,
      "mean_score": 0.25,
      "mean_latency_ms": 3.5,
      "p95_latency_ms": 13.4
    }
  }
}
```

### 5.3 Evaluating A/B Test Results

Compare the following metrics between champion and challenger:

| Metric | How to Compare | Source |
|---|---|---|
| Mean score | Should be similar unless model is more/less aggressive | Routing metrics |
| Score distribution | Plot distributions; look for systematic shifts | Monitoring API |
| P95 latency | Challenger must meet SLA | Routing metrics |
| False positive rate | Requires investigation outcome data | Manual analysis |
| Fraud detection rate | Requires labeled data over the test period | Manual analysis |

### 5.4 Concluding an A/B Test

**If the challenger wins:**
1. Promote the challenger to Production (see Section 4)
2. Reset the traffic split to 100/0

**If the challenger loses or is inconclusive:**
1. Reset the traffic split to 100/0 (all traffic to champion)
2. Archive or retrain the challenger

```bash
# Reset to champion-only
curl -X POST http://localhost:8000/api/v1/serving/routing \
  -H "Content-Type: application/json" \
  -d '{"champion_pct": 100.0, "challenger_pct": 0.0}'
```

### 5.5 Auto-Promotion (Placeholder)

The `AutoPromotionConfig` in `src/serving/routing.py` defines the interface for
automatic promotion based on statistical significance testing. This is currently
a placeholder (always returns False) and will be implemented when sufficient
production data is available for proper A/B test analysis.

Configuration fields (for future implementation):

| Field | Default | Description |
|---|---|---|
| `enabled` | False | Enable auto-promotion |
| `min_observations` | 1,000 | Minimum observations per variant |
| `metric` | "precision" | Primary metric for comparison |
| `improvement_threshold` | 0.05 | Minimum improvement to trigger promotion |
| `confidence_level` | 0.95 | Required statistical confidence |

---

## 6. Rollback Procedure

### 6.1 When to Rollback

Rollback should be initiated when:

| Condition | Severity | Response Time |
|---|---|---|
| Critical drift detected across multiple features | High | Within 4 hours |
| Score distribution shift > 3 standard deviations | High | Within 4 hours |
| Increase in false positive rate > 20% | High | Within 24 hours |
| Model producing NaN/Inf scores | Critical | Immediate |
| Latency SLA breach not resolved by infrastructure | Medium | Within 24 hours |
| BSA officer requests rollback | Critical | Immediate |

### 6.2 Rollback Steps

**Option A: Via the DeploymentPipeline (recommended)**

```python
from src.serving.deploy import DeploymentPipeline

pipeline = DeploymentPipeline(tracking_uri="http://mlflow:5000")
record = pipeline.rollback(
    name="fraud-detector-v0.2",
    triggered_by="engineer_name",
)

if record.success:
    print(f"Rolled back to version {record.model_version}")
    print(f"From version {record.previous_version}")
else:
    print("Rollback failed: no archived version available")
```

The rollback method:
1. Identifies the current Production version
2. Finds the most recent Archived version (highest version number)
3. Archives the current Production version
4. Promotes the rollback target to Production
5. Records a `DeploymentRecord` with `action="rollback"`

**Option B: Manual MLflow stage transition**

If the deployment pipeline is unavailable:

```python
from src.serving.registry import ModelRegistry

registry = ModelRegistry(tracking_uri="http://mlflow:5000")

# Archive the broken version
registry.promote_model("fraud-detector-v0.2", version="3", stage="Archived")

# Restore the previous version
registry.promote_model("fraud-detector-v0.2", version="2", stage="Production")
```

**Step 2: Reload the serving layer**

After rollback, trigger a reload:

```bash
curl -X POST http://localhost:8000/api/v1/serving/reload
```

**Step 3: Verify the rollback**

```bash
curl http://localhost:8000/api/v1/serving/monitoring
```

Confirm the model version in the response matches the expected rollback target.

### 6.3 Emergency Fallback: Disable ML Scoring

If no archived model version is available or the rollback itself fails, disable
ML scoring entirely and rely solely on rule-based scoring:

1. Update `HybridScoringConfig.ml_enabled = False` in the serving configuration
2. The system will use only rule-based scoring (Phase 3 rules engine)
3. This is a safe fallback: rule-based scoring has been validated independently

### 6.4 Post-Rollback Checklist

- [ ] Verify the correct model version is serving (check monitoring endpoint)
- [ ] Confirm score distributions are back to normal (monitor for 1 hour)
- [ ] Confirm latency SLA is met
- [ ] Reset A/B routing to 100/0 if an experiment was in progress
- [ ] Document the incident: what went wrong, when it was detected, when rollback was executed
- [ ] Notify the team and BSA officer (if compliance-impacting)
- [ ] Create a post-mortem if the rollback was due to a production incident

---

## 7. Deployment History and Audit Trail

### 7.1 Deployment Records

Every promotion and rollback action creates a `DeploymentRecord` stored in
the `DeploymentPipeline.history` property:

```python
DeploymentRecord(
    model_name="fraud-detector-v0.2",
    model_version="3",
    previous_version="2",
    action="promote",           # "promote", "rollback", or "archive"
    triggered_by="engineer_name",
    validation_result=ValidationResult(...),
    timestamp="2026-02-27T10:00:00+00:00",
    success=True,
)
```

### 7.2 MLflow Audit Trail

MLflow maintains a complete audit trail of model versions and stage transitions:

- All model versions with their training parameters and metrics
- Stage transition history (None -> Staging -> Production -> Archived)
- Run metadata including timestamps and user identity
- Artifact storage (trained models, evaluation reports)

### 7.3 Compliance Audit Requirements

For regulatory compliance, maintain records of:

| Record | Retention Period | Storage |
|---|---|---|
| Model training runs (MLflow) | 5 years | MLflow + PostgreSQL |
| Model validation results | 5 years | DeploymentPipeline history + PostgreSQL |
| Promotion/rollback events | 5 years | DeploymentPipeline history + PostgreSQL |
| A/B test configurations and results | 5 years | Application logs |
| BSA officer approval records | 5 years | Compliance documentation |
| Bias audit results | 5 years | Governance documentation |

---

## 8. Quick Reference

### 8.1 API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/serving/reload` | POST | Trigger model hot-reload from MLflow |
| `/api/v1/serving/routing` | GET | Inspect current A/B routing configuration |
| `/api/v1/serving/routing` | POST | Update traffic split (`champion_pct`, `challenger_pct`) |
| `/api/v1/serving/monitoring` | GET | Model health metrics, score distributions, drift status |

### 8.2 CLI Commands

```bash
# Train a new model
python -m src.domains.fraud.ml.train --dataset data/paysim.csv

# Train with custom config
python -m src.domains.fraud.ml.train --dataset data/paysim.csv --config config.yaml

# Train with downsampled data
python -m src.domains.fraud.ml.train --dataset data/paysim.csv --sample-size 50000

# Reload model (via API)
curl -X POST http://localhost:8000/api/v1/serving/reload

# Check model health
curl http://localhost:8000/api/v1/serving/monitoring

# Set A/B routing
curl -X POST http://localhost:8000/api/v1/serving/routing \
  -H "Content-Type: application/json" \
  -d '{"champion_pct": 95.0, "challenger_pct": 5.0}'

# Check A/B routing status
curl http://localhost:8000/api/v1/serving/routing
```

### 8.3 Common Scenarios

| Scenario | Steps |
|---|---|
| Deploy a new model version | Train -> Review metrics in MLflow -> Validate -> Promote -> Reload -> Monitor |
| Run an A/B test | Load challenger -> Set traffic split -> Monitor for 7+ days -> Evaluate -> Promote or revert |
| Emergency rollback | Rollback via pipeline -> Reload -> Verify -> Disable A/B routing -> Document |
| Scheduled retraining | Generate fresh dataset -> Train -> Compare against current -> Promote if better |
| BSA-required model change | Get BSA approval -> Train -> Validate -> Promote with approval record -> Notify BSA |
