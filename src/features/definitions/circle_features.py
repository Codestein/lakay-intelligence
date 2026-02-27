"""Circle health feature set — Feast feature view definitions.

Defines features for Phase 6's circle health scoring. Keyed by ``circle_id``.

Feature dimensions: contribution health, membership stability, financial
health, and risk indicators.

Batch source: PostgreSQL table ``feast_circle_features`` populated from
circle lifecycle simulator events.
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
)

from src.features.feast_repo.entities import circle_entity

# --------------------------------------------------------------------------- #
# Data source
# --------------------------------------------------------------------------- #

circle_features_source = PushSource(
    name="circle_features_push_source",
    batch_source=FileSource(
        name="circle_features_batch_source",
        path="data/feast/circle_features.parquet",
        timestamp_field="event_timestamp",
        created_timestamp_column="created_timestamp",
    ),
)

# --------------------------------------------------------------------------- #
# Feature View — circle_features
# --------------------------------------------------------------------------- #

circle_features_view = FeatureView(
    name="circle_features",
    entities=[circle_entity],
    ttl=timedelta(days=180),
    schema=[
        # ----- Contribution health -----
        Field(
            name="on_time_payment_rate",
            dtype=Float64,
            description="Percentage of contributions received on or before the due date",
        ),
        Field(
            name="avg_days_late",
            dtype=Float64,
            description="Average days late for late contributions",
        ),
        Field(
            name="missed_contribution_count",
            dtype=Int64,
            description="Total missed contributions to date",
        ),
        Field(
            name="consecutive_on_time_streak",
            dtype=Int64,
            description="Current streak of consecutive on-time contributions across all members",
        ),
        # ----- Membership stability -----
        Field(
            name="member_count_current",
            dtype=Int64,
            description="Current number of active members",
        ),
        Field(
            name="member_drop_count",
            dtype=Int64,
            description="Number of members who have dropped out",
        ),
        Field(
            name="member_drop_rate",
            dtype=Float64,
            description="Drop count / original member count",
        ),
        Field(
            name="avg_member_tenure_days",
            dtype=Float64,
            description="Average number of days members have been in the circle",
        ),
        # ----- Financial health -----
        Field(
            name="total_collected_amount",
            dtype=Float64,
            description="Total contributions collected to date",
        ),
        Field(
            name="expected_collected_amount",
            dtype=Float64,
            description="What should have been collected by now per the rotation schedule",
        ),
        Field(
            name="collection_ratio",
            dtype=Float64,
            description="total_collected / expected_collected (1.0 = on track)",
        ),
        Field(
            name="payout_completion_count",
            dtype=Int64,
            description="Number of payouts successfully completed",
        ),
        Field(
            name="payout_completion_rate",
            dtype=Float64,
            description="Payouts completed / payouts expected by now",
        ),
        # ----- Risk indicators -----
        Field(
            name="largest_single_missed_amount",
            dtype=Float64,
            description="The biggest single missed contribution",
        ),
        Field(
            name="late_payment_trend",
            dtype=Float64,
            description="Slope of rolling late rate (positive = deteriorating)",
        ),
        Field(
            name="coordinated_behavior_score",
            dtype=Float64,
            description="Correlated member timing/amounts (0=independent, 1=coordinated)",
        ),
    ],
    source=circle_features_source,
    online=True,
    tags={
        "domain": "circles",
        "owner": "lakay-ml",
        "phase": "5",
    },
)


def get_circle_feature_refs() -> list[str]:
    """Return all circle feature references in 'view:feature' format."""
    return [f"circle_features:{f.name}" for f in circle_features_view.schema]


def get_circle_feature_names() -> list[str]:
    """Return just the feature names (without the view prefix)."""
    return [f.name for f in circle_features_view.schema]
