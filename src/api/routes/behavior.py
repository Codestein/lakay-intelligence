"""Behavior anomaly detection endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/behavior", tags=["behavior"])


class AnomalyRequest(BaseModel):
    session_id: str
    user_id: str
    events: list[dict] | None = None


@router.post("/anomaly")
async def detect_anomaly(request: AnomalyRequest) -> dict:
    return {
        "anomaly_score": 0.0,
        "is_anomalous": False,
        "anomaly_types": [],
        "model_version": "stub",
        "computed_at": datetime.now(UTC).isoformat(),
    }
