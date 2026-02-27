"""Fraud detection feature set — Feast feature view definitions.

Consolidates all fraud-relevant features previously computed ad-hoc in the
Phase 3 rule engine (``src/domains/fraud/feature_computer.py``) and Phase 4
training pipeline (``src/domains/fraud/ml/features.py``).

Feature dimensions mirror the rule categories: velocity, amount, geographic,
and pattern features.  All features are keyed by ``user_id``.

Batch source: PostgreSQL table ``feast_fraud_features`` populated from
synthetic transaction, session, and circle event streams.
"""

from datetime import timedelta

from feast import (
    FeatureView,
    Field,
    FileSource,
    PushSource,
)
from feast.types import (
    Float64,
    Int64,
    String,
)

from src.features.feast_repo.entities import user_entity

# --------------------------------------------------------------------------- #
# Data source: offline batch source backed by a Parquet file or DB table.
# In production the PostgreSQL offline store handles the underlying queries.
# For development/CI we also support a FileSource pointing at generated
# Parquet files.
# --------------------------------------------------------------------------- #

fraud_features_source = PushSource(
    name="fraud_features_push_source",
    batch_source=FileSource(
        name="fraud_features_batch_source",
        path="data/feast/fraud_features.parquet",
        timestamp_field="event_timestamp",
        created_timestamp_column="created_timestamp",
    ),
)

# --------------------------------------------------------------------------- #
# Feature View — fraud_features
# --------------------------------------------------------------------------- #

fraud_features_view = FeatureView(
    name="fraud_features",
    entities=[user_entity],
    ttl=timedelta(days=90),
    schema=[
        # ----- Velocity features -----
        Field(
            name="login_count_10m",
            dtype=Int64,
            description="Login attempts in the last 10 minutes",
        ),
        Field(
            name="login_count_1h",
            dtype=Int64,
            description="Login attempts in the last hour",
        ),
        Field(
            name="tx_count_1h",
            dtype=Int64,
            description="Transactions initiated in the last hour",
        ),
        Field(
            name="tx_count_24h",
            dtype=Int64,
            description="Transactions initiated in the last 24 hours",
        ),
        Field(
            name="circle_joins_24h",
            dtype=Int64,
            description="Circles joined in the last 24 hours",
        ),
        # ----- Amount features -----
        Field(
            name="tx_amount_last",
            dtype=Float64,
            description="Amount of the most recent transaction",
        ),
        Field(
            name="tx_amount_mean_30d",
            dtype=Float64,
            description="Mean transaction amount over the last 30 days",
        ),
        Field(
            name="tx_amount_std_30d",
            dtype=Float64,
            description="Standard deviation of transaction amounts over 30 days",
        ),
        Field(
            name="tx_amount_zscore",
            dtype=Float64,
            description="Z-score of the current transaction vs. 30-day history",
        ),
        Field(
            name="tx_cumulative_24h",
            dtype=Float64,
            description="Cumulative transaction volume in the last 24 hours",
        ),
        Field(
            name="tx_cumulative_7d",
            dtype=Float64,
            description="Cumulative transaction volume in the last 7 days",
        ),
        Field(
            name="ctr_proximity_score",
            dtype=Float64,
            description="Proximity to the $10,000 CTR threshold (0.0=far, 1.0=at threshold)",
        ),
        # ----- Geographic features -----
        Field(
            name="last_known_country",
            dtype=String,
            description="Country of the most recent authenticated event",
        ),
        Field(
            name="last_known_city",
            dtype=String,
            description="City of the most recent authenticated event",
        ),
        Field(
            name="distinct_countries_7d",
            dtype=Int64,
            description="Number of distinct countries transacted from in 7 days",
        ),
        Field(
            name="max_travel_speed_24h",
            dtype=Float64,
            description="Maximum implied travel speed (km/h) between consecutive events in 24h",
        ),
        # ----- Pattern features -----
        Field(
            name="duplicate_tx_count_1h",
            dtype=Int64,
            description="Near-identical transactions in the last hour",
        ),
        Field(
            name="same_recipient_tx_sum_24h",
            dtype=Float64,
            description="Cumulative amount sent to the same recipient in 24 hours",
        ),
        Field(
            name="round_amount_ratio_30d",
            dtype=Float64,
            description="Ratio of round-amount transactions to total over 30 days",
        ),
        Field(
            name="tx_time_regularity_score",
            dtype=Float64,
            description="User's transaction timing regularity (0=random, 1=periodic)",
        ),
    ],
    source=fraud_features_source,
    online=True,
    tags={
        "domain": "fraud",
        "owner": "lakay-ml",
        "phase": "5",
    },
)


def get_fraud_feature_refs() -> list[str]:
    """Return all fraud feature references in 'view:feature' format."""
    return [f"fraud_features:{f.name}" for f in fraud_features_view.schema]


def get_fraud_feature_names() -> list[str]:
    """Return just the feature names (without the view prefix)."""
    return [f.name for f in fraud_features_view.schema]
