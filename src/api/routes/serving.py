"""Model serving API endpoints.

Phase 4 additions:
- POST /api/v1/serving/reload     — trigger model hot-reload
- GET  /api/v1/serving/routing    — inspect A/B routing config
- POST /api/v1/serving/routing    — update traffic split
- GET  /api/v1/serving/monitoring — model health metrics
"""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.serving.drift import get_drift_detector
from src.serving.monitoring import get_model_monitor
from src.serving.routing import get_model_router
from src.serving.server import get_model_server

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/serving", tags=["serving"])


class ReloadResponse(BaseModel):
    success: bool
    model_name: str
    model_version: str
    message: str


class RoutingConfigResponse(BaseModel):
    enabled: bool
    champion_pct: float
    challenger_pct: float
    champion_model: str | None
    champion_version: str | None
    challenger_model: str | None
    challenger_version: str | None
    metrics_summary: dict


class RoutingUpdateRequest(BaseModel):
    champion_pct: float = Field(ge=0, le=100)
    challenger_pct: float = Field(ge=0, le=100)


@router.post("/reload")
async def reload_model() -> ReloadResponse:
    """Trigger hot-reload of the production model from MLflow."""
    server = get_model_server()
    success = server.reload_model()

    return ReloadResponse(
        success=success,
        model_name=server.model_name,
        model_version=server.model_version if success else "unknown",
        message="Model reloaded successfully" if success else f"Reload failed: {server.load_error}",
    )


@router.get("/routing")
async def get_routing() -> RoutingConfigResponse:
    """Inspect current A/B routing configuration."""
    router_instance = get_model_router()
    config = router_instance.config

    champion = router_instance.champion
    challenger = router_instance.challenger

    return RoutingConfigResponse(
        enabled=config.enabled,
        champion_pct=config.champion_pct,
        challenger_pct=config.challenger_pct,
        champion_model=champion.model_name if champion else None,
        champion_version=champion.model_version if champion and champion.is_loaded else None,
        challenger_model=challenger.model_name if challenger else None,
        challenger_version=(
            challenger.model_version if challenger and challenger.is_loaded else None
        ),
        metrics_summary=router_instance.get_metrics_summary(),
    )


@router.post("/routing")
async def update_routing(request: RoutingUpdateRequest) -> RoutingConfigResponse:
    """Update traffic split percentages for A/B routing."""
    router_instance = get_model_router()
    router_instance.update_config(
        champion_pct=request.champion_pct,
        challenger_pct=request.challenger_pct,
    )

    logger.info(
        "routing_updated_via_api",
        champion_pct=request.champion_pct,
        challenger_pct=request.challenger_pct,
    )

    return await get_routing()


@router.get("/monitoring")
async def get_monitoring() -> dict:
    """Current model health metrics: scores, latency, drift, alerts."""
    monitor = get_model_monitor()
    detector = get_drift_detector()
    server = get_model_server()

    health = monitor.get_health_report()
    drift = detector.get_drift_report()

    return {
        "model": {
            "name": server.model_name,
            "version": server.model_version if server.is_loaded else None,
            "loaded": server.is_loaded,
            "load_error": server.load_error,
        },
        "scores": health,
        "drift": drift,
        "timestamp": datetime.now(UTC).isoformat(),
    }
