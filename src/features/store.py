"""Feature store client wrapper with Feast-first behavior and test fallback backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import structlog

from src.features.definitions.behavior_features import BEHAVIOR_FEATURE_REFS
from src.features.definitions.circle_features import CIRCLE_FEATURE_REFS
from src.features.definitions.fraud_features import FRAUD_FEATURE_REFS

logger = structlog.get_logger()


@dataclass
class FeatureStoreStatus:
    backend: str
    last_materialization: datetime | None = None
    last_apply: datetime | None = None
    freshness_seconds: float | None = None


@dataclass
class _InMemoryBackend:
    online: dict[str, dict[str, Any]] = field(default_factory=dict)
    historical: pd.DataFrame = field(default_factory=pd.DataFrame)


class FeatureStore:
    """Centralized feature store client for online/offline retrieval."""

    def __init__(self, repo_path: str = "src/features/feast_repo") -> None:
        self._repo_path = Path(repo_path)
        self._last_materialization: datetime | None = None
        self._last_apply: datetime | None = None
        self._memory = _InMemoryBackend()
        self._feature_groups = {
            "fraud": FRAUD_FEATURE_REFS,
            "behavior": BEHAVIOR_FEATURE_REFS,
            "circle_health": CIRCLE_FEATURE_REFS,
        }

        self._feast_store = None
        self._backend = "memory"
        try:
            from feast import FeatureStore as FeastFeatureStore

            self._feast_store = FeastFeatureStore(repo_path=str(self._repo_path))
            self._backend = "feast"
        except Exception:
            logger.warning("feast_unavailable_fallback_memory", repo_path=str(self._repo_path))

        logger.info("feature_store_initialized", backend=self._backend)

    def apply(self) -> None:
        """Apply feature repository definitions."""
        if self._feast_store is not None:
            # Definitions are loaded from repo on FeatureStore init; explicit apply is a marker hook.
            logger.info("feast_apply_requested", repo_path=str(self._repo_path))
        self._last_apply = datetime.now(UTC)

    def materialize(self, start: datetime, end: datetime) -> None:
        """Materialize offline features to online store for serving lookup."""
        if self._feast_store is not None:
            self._feast_store.materialize(start, end)
        self._last_materialization = end

    def get_online_features(self, entity_ids: dict[str, list[str]], feature_refs: list[str]) -> dict[str, Any]:
        """Fetch online features for entities."""
        if self._feast_store is not None:
            response = self._feast_store.get_online_features(features=feature_refs, entity_rows=[{k: v[i] for k, v in entity_ids.items()} for i in range(len(next(iter(entity_ids.values()), [])))])
            return response.to_dict()

        result: dict[str, list[Any]] = {ref: [] for ref in feature_refs}
        entity_key, values = next(iter(entity_ids.items()))
        for entity in values:
            payload = self._memory.online.get(f"{entity_key}:{entity}", {})
            for ref in feature_refs:
                result[ref].append(payload.get(ref.split(":", 1)[-1]))
        return result

    def get_historical_features(
        self, entity_df: pd.DataFrame, feature_refs: list[str]
    ) -> pd.DataFrame:
        """Retrieve point-in-time historical feature values."""
        if self._feast_store is not None:
            return self._feast_store.get_historical_features(
                entity_df=entity_df,
                features=feature_refs,
            ).to_df()

        if self._memory.historical.empty:
            return entity_df.copy()

        feature_cols = [ref.split(":", 1)[-1] for ref in feature_refs]
        available = [c for c in feature_cols if c in self._memory.historical.columns]
        merged = entity_df.merge(self._memory.historical[["user_id", "event_timestamp", *available]], on=["user_id", "event_timestamp"], how="left")
        return merged

    def update_memory_features(self, rows: pd.DataFrame, entity_key: str = "user_id") -> None:
        """Seed fallback backend for tests and local development."""
        if rows.empty:
            return
        self._memory.historical = rows.copy()
        for _, row in rows.iterrows():
            key = f"{entity_key}:{row[entity_key]}"
            self._memory.online[key] = row.to_dict()

    async def get_features(self, entity_id: str, feature_group: str) -> dict[str, Any]:
        """Backward-compatible async group-based getter."""
        refs = self._feature_groups.get(feature_group, [])
        response = self.get_online_features({"user_id": [entity_id]}, refs)
        return {k.split(":", 1)[-1]: v[0] if isinstance(v, list) and v else None for k, v in response.items()}

    async def store_features(
        self, entity_id: str, feature_group: str, features: dict[str, Any]
    ) -> None:
        """Backward-compatible async setter for fallback backend."""
        key = f"user_id:{entity_id}"
        self._memory.online[key] = features.copy()

    def status(self) -> FeatureStoreStatus:
        """Get backend health and freshness metadata."""
        freshness = None
        if self._last_materialization:
            freshness = (datetime.now(UTC) - self._last_materialization).total_seconds()

        return FeatureStoreStatus(
            backend=self._backend,
            last_materialization=self._last_materialization,
            last_apply=self._last_apply,
            freshness_seconds=freshness,
        )


feature_store = FeatureStore()
