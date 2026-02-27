"""Feature store client wrapping Feast for centralized feature serving.

Provides a unified interface over Feast's online and offline stores. All ML
models in Lakay Intelligence should retrieve features through this client to
guarantee zero training-serving skew.

Online store (Redis): Low-latency lookups at prediction time.
Offline store (PostgreSQL): Point-in-time correct joins for training data.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import structlog

logger = structlog.get_logger()

# Default path to the Feast repository
_DEFAULT_REPO_PATH = str(Path(__file__).parent / "feast_repo")


class FeatureStore:
    """Client wrapper over Feast for the rest of Lakay Intelligence.

    Usage::

        store = FeatureStore()
        # Serving-time lookup (from Redis online store)
        features = store.get_online_features(
            entity_rows=[{"user_id": "u123"}],
            feature_refs=["fraud_features:tx_count_1h", "fraud_features:tx_amount_mean_30d"],
        )

        # Training-time retrieval (from PostgreSQL offline store)
        training_df = store.get_historical_features(
            entity_df=entity_df,
            feature_refs=["fraud_features:tx_count_1h"],
        )
    """

    def __init__(self, repo_path: str | None = None) -> None:
        self._repo_path = repo_path or os.environ.get("FEAST_REPO_PATH", _DEFAULT_REPO_PATH)
        self._store = None
        self._last_materialization: datetime | None = None
        self._materialization_count: int = 0

    def _ensure_store(self):
        """Lazy-initialize the Feast FeatureStore to avoid import overhead."""
        if self._store is not None:
            return
        from feast import FeatureStore as FeastStore

        self._store = FeastStore(repo_path=self._repo_path)
        logger.info("feast_store_initialized", repo_path=self._repo_path)

    @property
    def feast_store(self):
        """Access the underlying Feast FeatureStore for advanced operations."""
        self._ensure_store()
        return self._store

    @property
    def last_materialization_time(self) -> datetime | None:
        return self._last_materialization

    @property
    def materialization_count(self) -> int:
        return self._materialization_count

    def get_online_features(
        self,
        entity_rows: list[dict[str, Any]],
        feature_refs: list[str],
    ) -> dict[str, list[Any]]:
        """Low-latency feature lookup from the Redis online store.

        This is the serving-time path. Features are pre-materialized into Redis
        for sub-millisecond lookups.

        Args:
            entity_rows: List of entity key dicts, e.g. [{"user_id": "u123"}].
            feature_refs: Feature references in "view:feature" format.

        Returns:
            Dictionary mapping feature names to lists of values (one per entity row).
        """
        self._ensure_store()

        response = self._store.get_online_features(
            features=feature_refs,
            entity_rows=entity_rows,
        )

        result = response.to_dict()
        logger.debug(
            "online_features_retrieved",
            entity_count=len(entity_rows),
            feature_count=len(feature_refs),
        )
        return result

    def get_historical_features(
        self,
        entity_df: pd.DataFrame,
        feature_refs: list[str],
    ) -> pd.DataFrame:
        """Point-in-time correct feature retrieval from the PostgreSQL offline store.

        This is the training-time path. Feast performs a point-in-time join to
        ensure that only features available at each entity's event_timestamp are
        returned, preventing future data leakage.

        Args:
            entity_df: DataFrame with entity key columns and an ``event_timestamp`` column.
            feature_refs: Feature references in "view:feature" format.

        Returns:
            DataFrame with entity columns plus requested feature columns.
        """
        self._ensure_store()

        retrieval_job = self._store.get_historical_features(
            entity_df=entity_df,
            features=feature_refs,
        )

        result_df = retrieval_job.to_df()
        logger.info(
            "historical_features_retrieved",
            entity_count=len(entity_df),
            feature_count=len(feature_refs),
            result_shape=result_df.shape,
        )
        return result_df

    def materialize(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> None:
        """Push features from the offline store to the online store (Redis).

        This makes features available for low-latency serving lookups.

        Args:
            start: Start of the materialization window. Defaults to 7 days ago.
            end: End of the materialization window. Defaults to now.
        """
        self._ensure_store()

        end = end or datetime.now(UTC)
        start = start or (end - timedelta(days=7))

        logger.info(
            "materialization_started",
            start=start.isoformat(),
            end=end.isoformat(),
        )

        self._store.materialize(
            start_date=start,
            end_date=end,
        )

        self._last_materialization = datetime.now(UTC)
        self._materialization_count += 1

        logger.info(
            "materialization_completed",
            start=start.isoformat(),
            end=end.isoformat(),
            total_materializations=self._materialization_count,
        )

    def materialize_incremental(self, end: datetime | None = None) -> None:
        """Incrementally materialize features since the last materialization.

        More efficient than full materialization for frequent updates.
        """
        self._ensure_store()

        end = end or datetime.now(UTC)
        logger.info("incremental_materialization_started", end=end.isoformat())

        self._store.materialize_incremental(end_date=end)

        self._last_materialization = datetime.now(UTC)
        self._materialization_count += 1

        logger.info(
            "incremental_materialization_completed",
            end=end.isoformat(),
            total_materializations=self._materialization_count,
        )

    def apply(self) -> None:
        """Apply feature definitions to the registry.

        Run this after any changes to feature views, entities, or data sources.
        """
        self._ensure_store()

        # Import all feature definitions to register them
        from src.features.definitions.behavior_features import (
            behavior_features_source,
            behavior_features_view,
        )
        from src.features.definitions.circle_features import (
            circle_features_source,
            circle_features_view,
        )
        from src.features.definitions.fraud_features import (
            fraud_features_source,
            fraud_features_view,
        )
        from src.features.feast_repo.entities import (
            circle_entity,
            session_entity,
            transaction_entity,
            user_entity,
        )

        objects = [
            user_entity,
            transaction_entity,
            circle_entity,
            session_entity,
            fraud_features_source,
            fraud_features_view,
            behavior_features_source,
            behavior_features_view,
            circle_features_source,
            circle_features_view,
        ]

        self._store.apply(objects)
        logger.info("feast_definitions_applied", object_count=len(objects))

    def get_feature_service_status(self) -> dict[str, Any]:
        """Return status information about the feature store."""
        self._ensure_store()

        feature_views = self._store.list_feature_views()

        return {
            "backend": "feast",
            "repo_path": self._repo_path,
            "feature_views": [fv.name for fv in feature_views],
            "feature_view_count": len(feature_views),
            "last_materialization": (
                self._last_materialization.isoformat() if self._last_materialization else None
            ),
            "materialization_count": self._materialization_count,
        }


# Module-level singleton
_feature_store: FeatureStore | None = None


def get_feature_store(repo_path: str | None = None) -> FeatureStore:
    """Get or create the global FeatureStore singleton."""
    global _feature_store
    if _feature_store is None:
        _feature_store = FeatureStore(repo_path=repo_path)
    return _feature_store
