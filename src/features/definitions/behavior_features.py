"""User behavior feature set — Feast feature view definitions.

Defines behavioral analytics features for Phase 7's ATO (Account Takeover)
detection. Built now so the feature store is comprehensive from the start.

Feature dimensions: session characteristics, engagement patterns, and
behavioral baselines. All features keyed by ``user_id``.

Batch source: PostgreSQL table ``feast_behavior_features`` populated from
the session behavior generator events.
"""

from datetime import timedelta

from feast import (
    FeatureView,
    Field,
    FileSource,
    PushSource,
)
from feast.types import (
    Bool,
    Float64,
    Int64,
)

from src.features.feast_repo.entities import user_entity

# --------------------------------------------------------------------------- #
# Data source
# --------------------------------------------------------------------------- #

behavior_features_source = PushSource(
    name="behavior_features_push_source",
    batch_source=FileSource(
        name="behavior_features_batch_source",
        path="data/feast/behavior_features.parquet",
        timestamp_field="event_timestamp",
        created_timestamp_column="created_timestamp",
    ),
)

# --------------------------------------------------------------------------- #
# Feature View — behavior_features
# --------------------------------------------------------------------------- #

behavior_features_view = FeatureView(
    name="behavior_features",
    entities=[user_entity],
    ttl=timedelta(days=90),
    schema=[
        # ----- Session features -----
        Field(
            name="avg_session_duration_30d",
            dtype=Float64,
            description="Mean session duration in seconds over 30 days",
        ),
        Field(
            name="session_count_7d",
            dtype=Int64,
            description="Number of sessions in the last 7 days",
        ),
        Field(
            name="avg_actions_per_session_30d",
            dtype=Float64,
            description="Mean actions per session over 30 days",
        ),
        Field(
            name="distinct_devices_30d",
            dtype=Int64,
            description="Number of distinct devices used in 30 days",
        ),
        Field(
            name="distinct_ips_7d",
            dtype=Int64,
            description="Number of distinct IP addresses in 7 days",
        ),
        Field(
            name="new_device_flag",
            dtype=Bool,
            description="Whether the current session is from a previously unseen device",
        ),
        # ----- Engagement features -----
        Field(
            name="days_since_last_login",
            dtype=Float64,
            description="Days since the user's most recent login",
        ),
        Field(
            name="login_streak_days",
            dtype=Int64,
            description="Consecutive days with at least one login",
        ),
        Field(
            name="feature_usage_breadth",
            dtype=Int64,
            description="Number of distinct platform features used in 30 days",
        ),
        # ----- Behavioral baseline -----
        Field(
            name="typical_login_hour_mean",
            dtype=Float64,
            description="Mean login hour (0-23) over 30 days",
        ),
        Field(
            name="typical_login_hour_std",
            dtype=Float64,
            description="Standard deviation of login hour",
        ),
        Field(
            name="current_session_hour_deviation",
            dtype=Float64,
            description="Std devs of the current session hour from the user's typical pattern",
        ),
    ],
    source=behavior_features_source,
    online=True,
    tags={
        "domain": "behavior",
        "owner": "lakay-ml",
        "phase": "5",
    },
)


def get_behavior_feature_refs() -> list[str]:
    """Return all behavior feature references in 'view:feature' format."""
    return [f"behavior_features:{f.name}" for f in behavior_features_view.schema]


def get_behavior_feature_names() -> list[str]:
    """Return just the feature names (without the view prefix)."""
    return [f.name for f in behavior_features_view.schema]
