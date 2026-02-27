# Feature Store Architecture (Phase 5)

## Why training-serving skew matters
Training-serving skew happens when feature values used during model training differ from values at prediction time. That can silently degrade fraud detection quality even when model metrics looked good offline.

Lakay prevents this by routing both paths through the same Feast feature definitions:

- **Training path**: `FeatureStore.get_historical_features()` (offline PostgreSQL point-in-time joins)
- **Serving path**: `FeatureStore.get_online_features()` (online Redis lookups)

## Feast topology

- **Offline store**: PostgreSQL (`feast` schema)
- **Online store**: Redis
- **Registry**: local file registry (`src/features/feast_repo/data/registry.db`)
- **Feature repo**: `src/features/feast_repo/`

## Feature sets

- **Fraud features** (`fraud_user_features`): velocity, amount, geo, and transaction pattern features.
- **Behavior features** (`behavior_user_features`): session, engagement, and baseline behavior features.
- **Circle features** (`circle_health_features`): contribution, membership, financial health, and coordination risk features.

## Batch vs on-demand

- **Batch-computed**: rolling counts/sums, means/stddevs, distinct counts, and rates loaded to PostgreSQL and materialized to Redis.
- **On-demand-derived**: features like z-score and session hour deviation can be computed at retrieval time from current event + batch aggregates when needed.

## TTL strategy

- Fraud view TTL: **30 days** to support long windows (7d/30d).
- Behavior view TTL: **30 days** to match behavioral baseline windows.
- Circle health TTL: **60 days** to maintain circle lifecycle continuity.

## Skew validation

`src/features/validation.py` includes reusable skew checks:

```bash
python -m src.features.validation --check-skew
```

CI can run this command to catch regressions and ensure online/offline parity.
