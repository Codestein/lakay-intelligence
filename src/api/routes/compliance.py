"""Compliance intelligence API endpoints (Phase 8).

Provides endpoints for CTR tracking, compliance alerts, cases, SAR drafts,
and customer risk scoring.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from src.domains.compliance.config import default_config
from src.domains.compliance.ctr import CTRTracker
from src.domains.compliance.models import (
    AlertPriority,
    AlertStatus,
    AlertType,
    CaseStatus,
    ComplianceAlert,
    ComplianceCase,
    RiskLevel,
    SARDraftStatus,
)
from src.domains.compliance.risk_scoring import CustomerRiskManager
from src.domains.compliance.sar import SARDraftManager

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])

# Module-level singletons (would be dependency-injected in production)
_ctr_tracker = CTRTracker()
_risk_manager = CustomerRiskManager()
_sar_manager = SARDraftManager()

# In-memory stores for alerts and cases
_alerts: dict[str, ComplianceAlert] = {}
_cases: dict[str, ComplianceCase] = {}


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class AlertUpdateRequest(BaseModel):
    status: AlertStatus
    reviewed_by: str | None = None
    resolution_notes: str | None = None


class CaseCreateRequest(BaseModel):
    user_id: str
    alert_ids: list[str] = Field(default_factory=list)
    case_type: str = ""
    assigned_to: str | None = None


class CaseUpdateRequest(BaseModel):
    status: CaseStatus
    assigned_to: str | None = None
    filing_reference: str | None = None
    narrative: str | None = None


class RiskAssessmentRequest(BaseModel):
    user_id: str
    ctr_filing_count: int = 0
    compliance_alert_count: int = 0
    structuring_flag_count: int = 0
    tx_volume_vs_baseline: float = 1.0
    high_risk_country_transactions: int = 0
    third_country_transactions: int = 0
    distinct_countries_30d: int = 1
    account_age_days: int = 365
    profile_complete: bool = True
    fraud_score_avg: float = 0.0
    ato_alert_count: int = 0
    is_dormant_reactivated: bool = False
    circle_count: int = 0
    flagged_circle_count: int = 0
    max_payout_amount: float = 0.0
    payout_to_contribution_ratio: float = 1.0


class RiskReviewRequest(BaseModel):
    reviewer: str
    notes: str
    new_risk_level: RiskLevel | None = None


class SARDraftUpdateRequest(BaseModel):
    status: SARDraftStatus
    reviewed_by: str | None = None


# ---------------------------------------------------------------------------
# CTR Endpoints
# ---------------------------------------------------------------------------


@router.get("/ctr/daily/{user_id}")
async def get_ctr_daily_total(user_id: str) -> dict:
    """Current business day cumulative total for a user."""
    daily = _ctr_tracker.get_daily_total(user_id)
    return {
        "user_id": daily.user_id,
        "business_date": daily.business_date,
        "cumulative_amount": daily.cumulative_amount,
        "transaction_count": len(daily.transaction_ids),
        "transaction_ids": daily.transaction_ids,
        "threshold_met": daily.threshold_met,
        "alert_generated": daily.alert_generated,
        "ctr_threshold": default_config.ctr.ctr_threshold,
    }


@router.get("/ctr/pending")
async def get_pending_ctr_obligations() -> dict:
    """All users with pending CTR obligations (threshold met, not yet filed)."""
    pending = _ctr_tracker.get_pending_obligations()
    return {
        "items": [
            {
                "package_id": pkg.package_id,
                "user_id": pkg.user_id,
                "business_date": pkg.business_date,
                "total_amount": pkg.total_amount,
                "transaction_count": pkg.transaction_count,
                "status": pkg.status,
                "assembled_at": pkg.assembled_at.isoformat(),
                "filing_deadline": pkg.filing_metadata.get("filing_deadline"),
            }
            for pkg in pending
        ],
        "total": len(pending),
    }


@router.get("/ctr/filings")
async def get_ctr_filing_history() -> dict:
    """CTR filing history with status."""
    history = _ctr_tracker.get_filing_history()
    return {
        "items": [
            {
                "package_id": pkg.package_id,
                "user_id": pkg.user_id,
                "business_date": pkg.business_date,
                "total_amount": pkg.total_amount,
                "transaction_count": pkg.transaction_count,
                "status": pkg.status,
                "assembled_at": pkg.assembled_at.isoformat(),
                "filed_at": pkg.filed_at.isoformat() if pkg.filed_at else None,
                "filing_reference": pkg.filing_reference,
            }
            for pkg in history
        ],
        "total": len(history),
    }


# ---------------------------------------------------------------------------
# Alert Endpoints
# ---------------------------------------------------------------------------


@router.get("/alerts")
async def list_compliance_alerts(
    alert_type: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    user_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """All compliance alerts (filterable by type, priority, status)."""
    items = list(_alerts.values())

    if alert_type:
        items = [a for a in items if a.alert_type.value == alert_type]
    if priority:
        items = [a for a in items if a.priority.value == priority]
    if status:
        items = [a for a in items if a.status.value == status]
    if user_id:
        items = [a for a in items if a.user_id == user_id]

    # Sort by created_at descending
    items.sort(key=lambda a: a.created_at, reverse=True)
    total = len(items)
    items = items[offset : offset + limit]

    return {
        "items": [a.model_dump(mode="json") for a in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.put("/alerts/{alert_id}")
async def update_alert(alert_id: str, request: AlertUpdateRequest) -> dict:
    """Update alert status with review notes."""
    alert = _alerts.get(alert_id)
    if not alert:
        return {"error": "Alert not found", "alert_id": alert_id}

    alert.status = request.status
    if request.reviewed_by:
        alert.reviewed_by = request.reviewed_by
        alert.reviewed_at = datetime.now(UTC)
    if request.resolution_notes:
        alert.resolution_notes = request.resolution_notes

    return alert.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Case Endpoints
# ---------------------------------------------------------------------------


@router.get("/cases")
async def list_compliance_cases(
    status: str | None = None,
    user_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Compliance cases (filterable)."""
    items = list(_cases.values())

    if status:
        items = [c for c in items if c.status.value == status]
    if user_id:
        items = [c for c in items if c.user_id == user_id]

    items.sort(key=lambda c: c.opened_at, reverse=True)
    total = len(items)
    items = items[offset : offset + limit]

    return {
        "items": [c.model_dump(mode="json") for c in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/cases")
async def create_compliance_case(request: CaseCreateRequest) -> dict:
    """Create a compliance case from grouped alerts."""
    import uuid

    case = ComplianceCase(
        case_id=str(uuid.uuid4()),
        user_id=request.user_id,
        alert_ids=request.alert_ids,
        case_type=request.case_type,
        assigned_to=request.assigned_to,
        opened_at=datetime.now(UTC),
    )
    _cases[case.case_id] = case
    return case.model_dump(mode="json")


@router.put("/cases/{case_id}")
async def update_compliance_case(case_id: str, request: CaseUpdateRequest) -> dict:
    """Update case status."""
    case = _cases.get(case_id)
    if not case:
        return {"error": "Case not found", "case_id": case_id}

    case.status = request.status
    if request.assigned_to:
        case.assigned_to = request.assigned_to
    if request.filing_reference:
        case.filing_reference = request.filing_reference
    if request.narrative:
        case.narrative = request.narrative
    if request.status == CaseStatus.CLOSED:
        case.closed_at = datetime.now(UTC)

    return case.model_dump(mode="json")


# ---------------------------------------------------------------------------
# SAR Draft Endpoints
# ---------------------------------------------------------------------------


@router.post("/sar/draft/{case_id}")
async def generate_sar_draft(case_id: str) -> dict:
    """Generate a SAR narrative draft for a case."""
    case = _cases.get(case_id)
    if not case:
        return {"error": "Case not found", "case_id": case_id}

    # Gather alerts for this case
    case_alerts = [_alerts[aid] for aid in case.alert_ids if aid in _alerts]

    draft = _sar_manager.generate_draft(case, case_alerts)
    return draft.model_dump(mode="json")


@router.get("/sar/drafts")
async def list_sar_drafts() -> dict:
    """List all pending SAR drafts."""
    drafts = _sar_manager.get_pending_drafts()
    return {
        "items": [d.model_dump(mode="json") for d in drafts],
        "total": len(drafts),
    }


@router.put("/sar/drafts/{draft_id}")
async def update_sar_draft(draft_id: str, request: SARDraftUpdateRequest) -> dict:
    """Update SAR draft status (draft/reviewed/approved/filed/rejected)."""
    draft = _sar_manager.update_status(
        draft_id, request.status, request.reviewed_by
    )
    if not draft:
        return {"error": "Draft not found", "draft_id": draft_id}
    return draft.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Risk Scoring Endpoints
# ---------------------------------------------------------------------------


@router.get("/risk/{user_id}")
async def get_customer_risk(user_id: str) -> dict:
    """Current customer risk profile with all contributing factors."""
    profile = _risk_manager.get_profile(user_id)
    if not profile:
        return {
            "user_id": user_id,
            "risk_level": "low",
            "risk_score": 0.0,
            "risk_factors": [],
            "edd_required": False,
            "message": "No risk assessment on record. Run POST /risk/{user_id}/review to assess.",
        }
    return profile.model_dump(mode="json")


@router.get("/risk/high")
async def get_high_risk_customers() -> dict:
    """All high-risk and prohibited customers."""
    high_risk = _risk_manager.get_high_risk_customers()
    return {
        "items": [p.model_dump(mode="json") for p in high_risk],
        "total": len(high_risk),
    }


@router.get("/risk/{user_id}/history")
async def get_risk_history(user_id: str) -> dict:
    """Risk score history over time."""
    history = _risk_manager.get_history(user_id)
    return {
        "items": [h.model_dump(mode="json") for h in history],
        "total": len(history),
    }


@router.post("/risk/{user_id}/review")
async def review_customer_risk(user_id: str, request: RiskReviewRequest) -> dict:
    """Record a compliance officer's review of a customer's risk level."""
    profile = _risk_manager.record_review(
        user_id=user_id,
        reviewer=request.reviewer,
        notes=request.notes,
        new_risk_level=request.new_risk_level,
    )
    if not profile:
        return {"error": "No risk profile found", "user_id": user_id}
    return {
        "profile": profile.model_dump(mode="json"),
        "reviews": _risk_manager.get_reviews(user_id),
    }


# ---------------------------------------------------------------------------
# Backward-compatible risk endpoint (from stub)
# ---------------------------------------------------------------------------


class LegacyComplianceRiskRequest(BaseModel):
    user_id: str


@router.post("/risk")
async def assess_risk_legacy(request: LegacyComplianceRiskRequest) -> dict:
    """Backward-compatible risk assessment endpoint."""
    assessment, alerts = _risk_manager.assess_risk(user_id=request.user_id)

    # Store generated alerts
    for alert in alerts:
        _alerts[alert.alert_id] = alert

    return {
        "user_id": assessment.user_id,
        "risk_level": assessment.risk_level.value,
        "risk_score": assessment.risk_score,
        "factors": {f.factor_name: f.score for f in assessment.factor_details},
        "edd_required": assessment.edd_required,
        "model_version": "compliance-v1",
        "computed_at": assessment.assessed_at.isoformat(),
    }
