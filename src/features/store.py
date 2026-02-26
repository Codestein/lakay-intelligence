"""Feature store interface. Will integrate with Feast in later phases."""

from typing import Any

import structlog

logger = structlog.get_logger()


class FeatureStore:
    """Interface to the feature store for retrieving computed features."""

    def __init__(self) -> None:
        logger.info("feature_store_initialized", backend="stub")

    async def get_features(self, entity_id: str, feature_group: str) -> dict[str, Any]:
        logger.debug("get_features", entity_id=entity_id, feature_group=feature_group)
        return {}

    async def store_features(
        self, entity_id: str, feature_group: str, features: dict[str, Any]
    ) -> None:
        logger.debug("store_features", entity_id=entity_id, feature_group=feature_group)
