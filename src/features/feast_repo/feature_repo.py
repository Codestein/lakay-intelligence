"""Feast repository objects for Lakay feature store."""

from datetime import timedelta

try:
    from feast import Entity, FeatureView, Field
    from feast.infra.offline_stores.contrib.postgres_offline_store.postgres_source import (
        PostgreSQLSource,
    )
    from feast.types import Float64, Int64, String
except Exception:  # pragma: no cover
    Entity = FeatureView = Field = PostgreSQLSource = None  # type: ignore[assignment]
    Float64 = Int64 = String = None  # type: ignore[assignment]

from src.features.definitions.behavior_features import BEHAVIOR_FEATURES
from src.features.definitions.circle_features import CIRCLE_FEATURES
from src.features.definitions.fraud_features import FRAUD_FEATURES

if Entity is not None:
    user = Entity(name="user", join_keys=["user_id"], description="Lakay user")
    transaction = Entity(name="transaction", join_keys=["transaction_id"], description="Transaction")
    circle = Entity(name="circle", join_keys=["circle_id"], description="Savings circle")
    session = Entity(name="session", join_keys=["session_id"], description="User session")

    fraud_source = PostgreSQLSource(
        name="fraud_features_source",
        query="SELECT * FROM feast.fraud_features",
        timestamp_field="event_timestamp",
        created_timestamp_column="created_at",
    )
    behavior_source = PostgreSQLSource(
        name="behavior_features_source",
        query="SELECT * FROM feast.behavior_features",
        timestamp_field="event_timestamp",
        created_timestamp_column="created_at",
    )
    circle_source = PostgreSQLSource(
        name="circle_features_source",
        query="SELECT * FROM feast.circle_features",
        timestamp_field="event_timestamp",
        created_timestamp_column="created_at",
    )

    fraud_user_features = FeatureView(
        name="fraud_user_features",
        entities=[user],
        ttl=timedelta(days=30),
        schema=[Field(name=f["name"], dtype=Float64 if "Float" in f["dtype"] else Int64 if "Int" in f["dtype"] else String) for f in FRAUD_FEATURES],
        source=fraud_source,
        online=True,
    )

    behavior_user_features = FeatureView(
        name="behavior_user_features",
        entities=[user],
        ttl=timedelta(days=30),
        schema=[Field(name=f["name"], dtype=Float64 if "Float" in f["dtype"] else Int64) for f in BEHAVIOR_FEATURES],
        source=behavior_source,
        online=True,
    )

    circle_health_features = FeatureView(
        name="circle_health_features",
        entities=[circle],
        ttl=timedelta(days=60),
        schema=[Field(name=f["name"], dtype=Float64 if "Float" in f["dtype"] else Int64) for f in CIRCLE_FEATURES],
        source=circle_source,
        online=True,
    )
