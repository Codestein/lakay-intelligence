"""API routes for compliance reporting pipeline."""

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_session
from src.pipeline.compliance_reports import (
    generate_audit_report,
    generate_compliance_summary,
    generate_ctr_report,
    generate_sar_report,
    get_report,
    list_reports,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/pipeline/compliance-reports", tags=["compliance-reports"])


class DateRangeRequest(BaseModel):
    start_date: str
    end_date: str


class SummaryRequest(BaseModel):
    period: str = "monthly"


@router.post("/ctr")
async def generate_ctr(
    request: DateRangeRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Generate CTR report for a date range."""
    start = datetime.fromisoformat(request.start_date)
    end = datetime.fromisoformat(request.end_date)
    report = await generate_ctr_report(session, start, end)
    return report.to_dict()


@router.post("/sar")
async def generate_sar(
    request: DateRangeRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Generate SAR report for a date range."""
    start = datetime.fromisoformat(request.start_date)
    end = datetime.fromisoformat(request.end_date)
    report = await generate_sar_report(session, start, end)
    return report.to_dict()


@router.post("/summary")
async def generate_summary(
    request: SummaryRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Generate compliance summary."""
    summary = await generate_compliance_summary(session, request.period)
    return summary.to_dict()


@router.post("/audit")
async def generate_audit(
    request: DateRangeRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Generate audit readiness report."""
    start = datetime.fromisoformat(request.start_date)
    end = datetime.fromisoformat(request.end_date)
    report = await generate_audit_report(session, start, end)
    return report.to_dict()


@router.get("")
async def list_compliance_reports(
    report_type: str | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List generated compliance reports."""
    sd = datetime.fromisoformat(start_date) if start_date else None
    ed = datetime.fromisoformat(end_date) if end_date else None
    reports = await list_reports(session, report_type, sd, ed)
    return {"reports": reports, "count": len(reports)}


@router.get("/{report_id}")
async def get_compliance_report(
    report_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Retrieve a specific generated report."""
    report = await get_report(session, report_id)
    if not report:
        return {"error": "report_not_found", "report_id": report_id}
    return report
