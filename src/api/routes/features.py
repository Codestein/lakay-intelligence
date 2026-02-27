"""Feature store management API endpoints.

Provides endpoints for:
- Triggering on-demand feature materialization
- Checking feature store status and freshness
"""

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.features.store import get_feature_store

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/features", tags=["features"])


class MaterializeRequest(BaseModel):
    """Request body for manual materialization trigger."""

    start_days_ago: int = 7
    end_time: str | None = None  # ISO 8601 timestamp; defaults to now


class MaterializeResponse(BaseModel):
    """Response from materialization endpoint."""

    success: bool
    message: str
    start: str
    end: str
    materialization_count: int


@router.post("/materialize")
async def trigger_materialization(
    request: MaterializeRequest | None = None,
) -> MaterializeResponse:
    """Trigger on-demand feature materialization.

    Pushes features from the offline store (PostgreSQL) to the online store
    (Redis) for low-latency serving.
    """
    request = request or MaterializeRequest()

    try:
        store = get_feature_store()
        end = datetime.now(UTC)
        if request.end_time:
            end = datetime.fromisoformat(request.end_time)
        start = end - timedelta(days=request.start_days_ago)

        store.materialize(start=start, end=end)

        return MaterializeResponse(
            success=True,
            message="Materialization completed successfully",
            start=start.isoformat(),
            end=end.isoformat(),
            materialization_count=store.materialization_count,
        )

    except Exception as e:
        logger.error("materialization_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Materialization failed: {e}",
        ) from e


@router.get("/status")
async def feature_store_status() -> dict:
    """Return feature store status, freshness, and entity counts."""
    try:
        store = get_feature_store()
        status = store.get_feature_service_status()

        return {
            "status": "healthy",
            **status,
        }

    except Exception as e:
        logger.error("feature_status_check_failed", error=str(e))
        return {
            "status": "degraded",
            "error": str(e),
            "backend": "feast",
        }
