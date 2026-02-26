"""Session anomaly detection. Stub for Phase 3."""

from datetime import UTC, datetime

import structlog

from .models import AnomalyDetectionRequest, AnomalyDetectionResponse

logger = structlog.get_logger()


class AnomalyDetector:
    async def detect(self, request: AnomalyDetectionRequest) -> AnomalyDetectionResponse:
        logger.info("detecting_anomaly", session_id=request.session_id, user_id=request.user_id)
        return AnomalyDetectionResponse(
            anomaly_score=0.0,
            is_anomalous=False,
            anomaly_types=[],
            model_version="stub",
            computed_at=datetime.now(UTC),
        )
