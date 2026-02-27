"""Feature store operations endpoints."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.features.store import feature_store

router = APIRouter(prefix="/api/v1/features", tags=["features"])


class MaterializeRequest(BaseModel):
    lookback_minutes: int = Field(default=15, ge=1, le=60 * 24 * 30)


@router.post("/materialize")
async def materialize_features(request: MaterializeRequest) -> dict:
    end = datetime.now(UTC)
    start = end - timedelta(minutes=request.lookback_minutes)
    feature_store.materialize(start=start, end=end)
    return {
        "status": "ok",
        "materialized_from": start.isoformat(),
        "materialized_to": end.isoformat(),
    }


@router.get("/status")
async def get_feature_status() -> dict:
    status = feature_store.status()
    return {
        "backend": status.backend,
        "last_apply": status.last_apply.isoformat() if status.last_apply else None,
        "last_materialization": (
            status.last_materialization.isoformat() if status.last_materialization else None
        ),
        "freshness_seconds": status.freshness_seconds,
    }
