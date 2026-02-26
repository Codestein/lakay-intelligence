"""Circle health scoring. Stub for Phase 3."""

from datetime import UTC, datetime

import structlog

from .models import CircleHealthRequest, CircleHealthResponse

logger = structlog.get_logger()


class CircleHealthScorer:
    async def score(self, request: CircleHealthRequest) -> CircleHealthResponse:
        logger.info("scoring_circle_health", circle_id=request.circle_id)
        return CircleHealthResponse(
            circle_id=request.circle_id,
            score=0.0,
            confidence=0.0,
            factors={},
            model_version="stub",
            computed_at=datetime.now(UTC),
        )
