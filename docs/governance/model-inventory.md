# Model Inventory

> Lakay Intelligence -- Phase 10, Task 10.5
> Last updated: 2026-02-27

This document catalogs every scoring model in the Lakay Intelligence system,
including the ML-based fraud detector and the rule-based scoring engines used
for circle health, behavioral analytics, and compliance risk assessment.

---

## 1. ML Models

### 1.1 fraud-detector-v0.2

| Field | Value |
|---|---|
| **Model Name** | `fraud-detector-v0.2` |
| **Type** | Gradient Boosted Tree (XGBoost `XGBClassifier`) |
| **Purpose** | Transaction fraud detection for the Trebanx remittance platform |
| **Training Data** | PaySim synthetic dataset (mapped to Trebanx event schema) |
| **Training Pipeline** | `src/domains/fraud/ml/train.py` -- `train_model()` |
| **Feature Engineering** | `src/domains/fraud/ml/features.py` -- `extract_features()` |
| **Evaluation** | `src/domains/fraud/ml/evaluate.py` -- `evaluate_model()` |
| **Owner** | Lakay Intelligence team |
| **Registry** | MLflow (backed by PostgreSQL metadata store + MinIO artifact store) |
| **Deployment** | MLflow model registry, in-process pyfunc serving via `src/serving/server.py` |
| **Serving** | A/B routing (champion/challenger) with weighted hybrid rule+ML scoring |

#### 1.1.1 Feature Schema

The model consumes 11 features, computed in `src/domains/fraud/ml/features.py` and
defined in `src/serving/config.py` (`FeatureSpec`):

| Feature | Type | Description |
|---|---|---|
| `amount` | float | Raw transaction amount |
| `amount_zscore` | float | (amount - user_mean) / user_std over sender history |
| `hour_of_day` | int | Hour extracted from transaction timestamp (0-23) |
| `day_of_week` | int | Day of week (0=Monday, 6=Sunday) |
| `tx_type_encoded` | int | Label-encoded transaction type (0-9, see `TX_TYPE_MAP`) |
| `balance_delta_sender` | float | oldbalanceOrg - newbalanceOrig |
| `balance_delta_receiver` | float | newbalanceDest - oldbalanceDest |
| `velocity_count_1h` | int | Transaction count in rolling 1-hour window per user |
| `velocity_count_24h` | int | Transaction count in rolling 24-hour window per user |
| `velocity_amount_1h` | float | Sum of amounts in rolling 1-hour window per user |
| `velocity_amount_24h` | float | Sum of amounts in rolling 24-hour window per user |

#### 1.1.2 Performance Metrics

Metrics are logged to MLflow at training time and include:

| Metric | Description |
|---|---|
| `auc_roc` | Area Under the ROC Curve |
| `precision` | Precision on the held-out test set |
| `recall` | Recall on the held-out test set |
| `f1_score` | F1 score (harmonic mean of precision and recall) |
| `true_positives` | Confusion matrix: true positives |
| `false_positives` | Confusion matrix: false positives |
| `true_negatives` | Confusion matrix: true negatives |
| `false_negatives` | Confusion matrix: false negatives |

A classification report and ML-vs-rules comparison report are also logged as
MLflow artifacts with each training run.

#### 1.1.3 Hyperparameters

Default training hyperparameters (configurable via YAML override):

| Parameter | Default | Description |
|---|---|---|
| `n_estimators` | 100 | Number of boosting rounds |
| `max_depth` | 6 | Maximum tree depth |
| `learning_rate` | 0.1 | Boosting learning rate |
| `subsample` | 0.8 | Row subsampling ratio |
| `colsample_bytree` | 0.8 | Column subsampling ratio per tree |
| `min_child_weight` | 5 | Minimum sum of instance weights in a leaf |
| `scale_pos_weight` | auto | Auto-calculated from class imbalance ratio |
| `eval_metric` | `aucpr` | Evaluation metric during training |
| `test_size` | 0.2 | Held-out test fraction |
| `random_seed` | 42 | Random seed for reproducibility |

Grid search is available but disabled by default. When enabled, it searches
over `max_depth`, `learning_rate`, and `n_estimators` with 3-fold CV,
capped at 10 hyperparameter combinations.

#### 1.1.4 Serving Architecture

- **Loading**: `ModelServer` (`src/serving/server.py`) loads the Production-stage
  model from MLflow via `mlflow.pyfunc.load_model()`.
- **Inference**: Single-transaction scoring via `ModelServer.predict()`. Features
  are assembled into a Pandas DataFrame in the canonical order defined by `FeatureSpec`.
  Output scores are clamped to [0, 1].
- **Hot reload**: `POST /api/v1/serving/reload` triggers `ModelServer.reload_model()`,
  which re-fetches the current Production model from MLflow.
- **A/B routing**: `ModelRouter` (`src/serving/routing.py`) splits traffic between
  champion (Production) and challenger (Staging) models using deterministic
  `sha256(user_id) % 100` hashing. Default split: 95% champion / 5% challenger.
- **Hybrid scoring**: Final fraud score combines rule-based and ML scores using
  a configurable strategy (`HybridScoringConfig` in `src/serving/config.py`).
  Default: weighted average with 60% rule weight, 40% ML weight.

#### 1.1.5 Reproducibility

Each training run logs the following to MLflow for full reproducibility:

- `training_dataset_hash`: SHA-256 hash of the input CSV file
- `feature_list`: JSON-serialized ordered list of feature names
- `training_timestamp`: ISO-8601 timestamp of the training run
- `python_version`: Python version used during training
- All hyperparameters as MLflow params
- Trained model artifact (XGBoost native format via `mlflow.xgboost`)

---

## 2. Rule-Based Scoring Models

The following scoring engines are deterministic, rule-based systems. They do not
use trained ML models but apply configurable weighted scoring formulas.

### 2.1 Circle Health Scorer v1

| Field | Value |
|---|---|
| **Model Name** | Circle Health Scorer v1 |
| **Type** | Multi-dimensional weighted scoring (rule-based) |
| **Purpose** | Assess the health and sustainability of savings circles (sou-sou / min) |
| **Output Range** | 0-100 composite health score |
| **Output Tiers** | Healthy (>=70), At-Risk (40-69), Critical (<40) |
| **Implementation** | `src/domains/circles/scoring.py` -- `CircleHealthScorer` |
| **Configuration** | `src/domains/circles/config.py` -- `CircleHealthConfig` |
| **Owner** | Lakay Intelligence team |

**Scoring Dimensions:**

| Dimension | Default Weight | Description |
|---|---|---|
| Contribution Reliability | 0.35 | On-time payment rate, lateness penalty, streak bonus, missed contributions |
| Membership Stability | 0.25 | Member drop rate, size shrinkage, average tenure |
| Financial Progress | 0.25 | Collection ratio, payout completion rate, late payment trajectory |
| Trust & Integrity | 0.15 | Coordinated behavior detection, large missed amounts, post-payout disengagement |

**Data Source:** Features retrieved from the Feast feature store via `FeatureStore.get_features()`.

**Confidence Score:** Scales with data availability (cycles completed, member count).
New circles receive low confidence (0.2); 6+ completed cycles reach full confidence.

**Trend Detection:** Compares current score against 1-cycle-ago and 3-cycles-ago
historical scores to classify trend as Improving, Stable, or Deteriorating.

---

### 2.2 Behavioral Anomaly Scorer v1

| Field | Value |
|---|---|
| **Model Name** | Behavioral Anomaly Scorer v1 |
| **Type** | 5-dimension session anomaly scoring (rule-based) |
| **Purpose** | Detect anomalous user sessions for account takeover and fraud prevention |
| **Output Range** | 0.0-1.0 composite anomaly score |
| **Output Classes** | Normal, Suspicious, High Risk, Critical |
| **Implementation** | `src/domains/behavior/anomaly.py` -- `SessionAnomalyScorer` |
| **Configuration** | `src/domains/behavior/config.py` -- `BehaviorConfig` |
| **Owner** | Lakay Intelligence team |

**Scoring Dimensions:**

| Dimension | Description |
|---|---|
| Temporal | Login hour deviation from user's typical pattern (z-score based) |
| Device | New device detection, cross-platform switching, device diversity |
| Geographic | Unknown locations, Haiti corridor awareness, impossible travel detection |
| Behavioral | Session duration anomaly, action count anomaly, bot-like speed, sensitive actions |
| Engagement | Dormancy reactivation, unfamiliar feature usage |

**Trebanx-Specific Adjustments:**
- Haiti corridor awareness: US-HT travel patterns are treated as lower anomaly
  because they are normal for Haitian diaspora users.
- Profile maturity adjustment: Immature profiles (building phase) receive a 0.6x
  score multiplier; stale profiles receive 0.8x.

**Recommended Actions:** Normal=None, Suspicious=Monitor, High Risk=Challenge,
Critical=Terminate session.

---

### 2.3 Compliance Risk Scorer v1

| Field | Value |
|---|---|
| **Model Name** | Compliance Risk Scorer v1 |
| **Type** | Weighted factor scoring (rule-based) |
| **Purpose** | Dynamic customer risk assessment for Enhanced Due Diligence (EDD) |
| **Output Range** | 0.0-1.0 composite risk score |
| **Risk Levels** | Low (0.0-0.3), Medium (0.3-0.6), High (0.6-0.8), Prohibited (0.8-1.0) |
| **Implementation** | `src/domains/compliance/risk_scoring.py` -- `compute_risk_score()` |
| **Configuration** | `src/domains/compliance/config.py` -- `ComplianceConfig` |
| **Regulatory Basis** | 31 CFR 1022.210(d), 31 CFR 1010.230 (CDD Rule), FinCEN Advisory FIN-2014-A007 |
| **Owner** | Lakay Intelligence team |

**Factor Categories:**

| Category | Weight | Factors |
|---|---|---|
| Transaction Behavior | 30% | CTR filing history, compliance alert history, structuring history, transaction volume anomaly |
| Geographic Factors | 25% | High-risk jurisdiction transactions, third-country transactions, geographic diversity |
| Behavioral Factors | 25% | Account age, profile completeness, fraud score average, ATO alert history, dormant reactivation |
| Circle Participation | 20% | Excessive circle membership, flagged circle membership, large payouts, payout-to-contribution imbalance |

**Review Frequencies:**
- Low risk: Annual review
- Medium risk: Quarterly review (enhanced monitoring)
- High risk: Monthly review (EDD required)
- Prohibited: Immediate investigation, account restricted

**EDD Triggers:** When a customer's risk level escalates to High or Prohibited,
a `ComplianceAlert` of type `EDD_TRIGGER` is generated with priority CRITICAL,
recommending escalation to the BSA officer.

---

## 3. Model Registry Summary

| Model | Type | Registry | Current Version |
|---|---|---|---|
| fraud-detector-v0.2 | ML (XGBoost GBT) | MLflow (PostgreSQL + MinIO) | See MLflow UI |
| Circle Health Scorer v1 | Rule-based | Code-versioned (`src/domains/circles/scoring.py`) | v1 |
| Behavioral Anomaly Scorer v1 | Rule-based | Code-versioned (`src/domains/behavior/anomaly.py`) | v1 |
| Compliance Risk Scorer v1 | Rule-based | Code-versioned (`src/domains/compliance/risk_scoring.py`) | v1 |

---

## 4. Governance Cross-References

| Topic | Document |
|---|---|
| Bias auditing methodology | [bias-audit-template.md](./bias-audit-template.md) |
| Feature and model drift monitoring | [drift-monitoring.md](./drift-monitoring.md) |
| Deployment, promotion, and rollback procedures | [deployment-procedures.md](./deployment-procedures.md) |
| Architecture decisions | [../architecture-decisions/](../architecture-decisions/) |
