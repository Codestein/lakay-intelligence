# Feature Store Architecture

## Why Training-Serving Skew Matters

Training-serving skew is the #1 cause of silent ML failures in production.
It occurs when the features used to train a model differ from the features
served at prediction time. The consequences are subtle and dangerous:

- **Silent degradation**: The model produces scores, but on wrong inputs
- **Hard to debug**: No errors are thrown — the predictions are just wrong
- **Cumulative impact**: Skew in one feature can cascade through the model

Common causes of skew include:
- Different code paths for batch (training) and real-time (serving) computation
- Timestamp handling differences (timezone mismatches, rounding)
- Missing feature values handled differently between training and serving
- Data pipeline delays causing stale features at serving time

## How Feast Prevents Skew

Feast is deployed as the **single source of truth** for all ML features in
Lakay Intelligence. The architecture guarantees zero skew through:

### Single Feature Definition

Every feature is defined exactly once in a Feast `FeatureView`. The definition
specifies the feature name, type, data source, and TTL. Both the training and
serving code paths reference these same definitions.

```
src/features/definitions/
├── fraud_features.py      # 20 fraud detection features
├── behavior_features.py   # 12 user behavior features
└── circle_features.py     # 16 circle health features
```

### Dual-Store Architecture

```
                    ┌──────────────┐
                    │  Event Data  │
                    │ (Generators/ │
                    │   Kafka)     │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  PostgreSQL  │  ← Offline Store
                    │  (Historical │    (Point-in-time correct joins
                    │   features)  │     for training data)
                    └──────┬───────┘
                           │ materialize()
                    ┌──────▼───────┐
                    │    Redis     │  ← Online Store
                    │  (Latest     │    (Low-latency lookups
                    │   features)  │     for serving)
                    └──────────────┘
```

- **Offline store (PostgreSQL)**: Stores the full history of feature values.
  Used by `get_historical_features()` during training to perform point-in-time
  correct joins — this prevents future data leakage by only returning features
  that were available at each entity's event timestamp.

- **Online store (Redis)**: Stores the most recent feature values for each
  entity. Used by `get_online_features()` at serving time for sub-millisecond
  lookups.

- **Materialization**: A scheduled job (`materialize()`) pushes the latest
  feature values from the offline store to the online store. This can be
  triggered via the `/api/v1/features/materialize` endpoint or run on a
  schedule.

### Zero-Skew Guarantee

Because both training and serving retrieve features from Feast (just different
stores with identical values), the features are guaranteed to be identical:

| Path | Store | API | Use Case |
|------|-------|-----|----------|
| Training | PostgreSQL (offline) | `get_historical_features()` | Point-in-time correct joins |
| Serving | Redis (online) | `get_online_features()` | Low-latency prediction |

After materialization, the online store contains the same values as the offline
store. The skew validation framework (`src/features/validation.py`) proves this
by comparing features from both paths and asserting zero difference.

## Feature Sets

### Fraud Detection Features (20 features)

Entity: `user` (keyed by `user_id`)

| Category | Feature | Type | TTL Rationale |
|----------|---------|------|---------------|
| **Velocity** | `login_count_10m` | Int64 | Short window, needs frequent refresh |
| | `login_count_1h` | Int64 | Short window |
| | `tx_count_1h` | Int64 | Short window |
| | `tx_count_24h` | Int64 | Daily window |
| | `circle_joins_24h` | Int64 | Daily window |
| **Amount** | `tx_amount_last` | Float64 | Latest value |
| | `tx_amount_mean_30d` | Float64 | Monthly aggregate |
| | `tx_amount_std_30d` | Float64 | Monthly aggregate |
| | `tx_amount_zscore` | Float64 | Computed from current + history |
| | `tx_cumulative_24h` | Float64 | Daily aggregate |
| | `tx_cumulative_7d` | Float64 | Weekly aggregate |
| | `ctr_proximity_score` | Float64 | Derived from cumulative |
| **Geographic** | `last_known_country` | String | Latest value |
| | `last_known_city` | String | Latest value |
| | `distinct_countries_7d` | Int64 | Weekly window |
| | `max_travel_speed_24h` | Float64 | Daily window |
| **Pattern** | `duplicate_tx_count_1h` | Int64 | Short window |
| | `same_recipient_tx_sum_24h` | Float64 | Daily window |
| | `round_amount_ratio_30d` | Float64 | Monthly aggregate |
| | `tx_time_regularity_score` | Float64 | Behavioral pattern |

### User Behavior Features (12 features)

Entity: `user` (keyed by `user_id`)

| Category | Feature | Type |
|----------|---------|------|
| **Session** | `avg_session_duration_30d` | Float64 |
| | `session_count_7d` | Int64 |
| | `avg_actions_per_session_30d` | Float64 |
| | `distinct_devices_30d` | Int64 |
| | `distinct_ips_7d` | Int64 |
| | `new_device_flag` | Bool |
| **Engagement** | `days_since_last_login` | Float64 |
| | `login_streak_days` | Int64 |
| | `feature_usage_breadth` | Int64 |
| **Baseline** | `typical_login_hour_mean` | Float64 |
| | `typical_login_hour_std` | Float64 |
| | `current_session_hour_deviation` | Float64 |

### Circle Health Features (16 features)

Entity: `circle` (keyed by `circle_id`)

| Category | Feature | Type |
|----------|---------|------|
| **Contribution** | `on_time_payment_rate` | Float64 |
| | `avg_days_late` | Float64 |
| | `missed_contribution_count` | Int64 |
| | `consecutive_on_time_streak` | Int64 |
| **Membership** | `member_count_current` | Int64 |
| | `member_drop_count` | Int64 |
| | `member_drop_rate` | Float64 |
| | `avg_member_tenure_days` | Float64 |
| **Financial** | `total_collected_amount` | Float64 |
| | `expected_collected_amount` | Float64 |
| | `collection_ratio` | Float64 |
| | `payout_completion_count` | Int64 |
| | `payout_completion_rate` | Float64 |
| **Risk** | `largest_single_missed_amount` | Float64 |
| | `late_payment_trend` | Float64 |
| | `coordinated_behavior_score` | Float64 |

## TTL Strategy

Feature Time-To-Live (TTL) determines how long a feature value remains valid
in the online store. Our TTL strategy is:

- **90 days** for fraud and behavior features: covers 30-day aggregate windows
  with buffer for late-arriving data and historical lookback
- **180 days** for circle features: circles have longer lifecycles (months) and
  we need to track full rotation periods

These TTLs are set in the FeatureView definitions and apply to both offline
(point-in-time join window) and online (expiry) stores.

## Batch vs. On-Demand Computation

| Computation Type | Features | Reason |
|-----------------|----------|--------|
| **Batch** (materialized) | All 48 features | Pre-computed for low-latency serving |
| **On-demand** (future) | `tx_amount_zscore`, `current_session_hour_deviation` | Depend on both real-time event data and historical aggregates |

Currently all features use batch computation via `PushSource`. On-demand
feature views (Feast `OnDemandFeatureView`) will be added when real-time
event streaming is integrated, allowing features like Z-scores to be computed
from a combination of the current event value and historical statistics.

## Skew Validation

The skew validation framework (`src/features/validation.py`) provides:

1. **`compare_values()`**: Type-appropriate comparison with configurable
   tolerance (1e-6 for floats, exact match for strings/booleans)
2. **`compare_features()`**: Batch comparison across entities and features
3. **`SkewValidator`**: Orchestrates full offline-vs-online comparison
4. **CLI**: `python -m src.features.validation --check-skew`

The test suite (`tests/features/test_skew.py`) validates:
- Perfect matches (zero skew)
- Float tolerance boundary behavior
- String/categorical exact matching
- None/NaN handling
- Missing features detection
- Empty entity edge cases

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/features/materialize` | Trigger on-demand materialization |
| GET | `/api/v1/features/status` | Feature store health and freshness |
