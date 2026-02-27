"""Circle health scoring — legacy compatibility wrapper.

This module preserves the original CircleHealthScorer interface used by
existing consumers. It delegates to the new Phase 6 scoring engine.
"""


import structlog

from src.features.store import FeatureStore

from .models import CircleHealthRequest
from .scoring import CircleHealthScorer as ScoringEngine

logger = structlog.get_logger()

_feature_store = FeatureStore()
_scorer = ScoringEngine()


class CircleHealthScorer:
    """Legacy wrapper. Use src.domains.circles.scoring.CircleHealthScorer directly."""

    async def score(self, request: CircleHealthRequest) -> dict:
        logger.info("scoring_circle_health", circle_id=request.circle_id)
        features = await _feature_store.get_features(request.circle_id, "circle_health")
        result = _scorer.score(request.circle_id, features)
        return result.model_dump()
