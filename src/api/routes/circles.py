"""Circle health endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/circles", tags=["circles"])


class CircleHealthRequest(BaseModel):
    circle_id: str


@router.post("/health")
async def circle_health(request: CircleHealthRequest) -> dict:
    return {
        "circle_id": request.circle_id,
        "score": 0.0,
        "confidence": 0.0,
        "factors": {},
        "model_version": "stub",
        "computed_at": datetime.now(UTC).isoformat(),
    }
