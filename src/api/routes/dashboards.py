"""API routes for operational dashboards."""

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_session
from src.pipeline.dashboards import (
    get_circle_health_overview,
    get_compliance_overview,
    get_corridor_overview,
    get_fraud_overview,
    get_platform_health,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/dashboards", tags=["dashboards"])


@router.get("/platform")
async def platform_dashboard(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Platform health overview dashboard."""
    return await get_platform_health(session, start_date, end_date)


@router.get("/fraud")
async def fraud_dashboard(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Fraud operations overview dashboard."""
    return await get_fraud_overview(session, start_date, end_date)


@router.get("/circles")
async def circles_dashboard(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Circle health overview dashboard."""
    return await get_circle_health_overview(session)


@router.get("/compliance")
async def compliance_dashboard(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Compliance overview dashboard."""
    return await get_compliance_overview(session, start_date, end_date)


@router.get("/corridor")
async def corridor_dashboard(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Haiti corridor analytics dashboard."""
    return await get_corridor_overview(session, start_date, end_date)
