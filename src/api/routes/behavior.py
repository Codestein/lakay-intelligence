"""Behavioral analytics API endpoints — Phase 7.

Provides endpoints for user behavioral profiles, session anomaly scoring,
engagement classification, and ATO detection.
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_session
from src.domains.behavior.anomaly import SessionAnomalyScorer
from src.domains.behavior.ato import ATODetector
from src.domains.behavior.engagement import EngagementScorer
from src.domains.behavior.models import (
    ATOAlertUpdate,
    ATOAssessRequest,
    ProfileSummary,
    SessionScoreRequest,
)
from src.domains.behavior.profile import BehaviorProfileEngine
from src.features.store import FeatureStore

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/behavior", tags=["behavior"])

_feature_store = FeatureStore()
_profile_engine = BehaviorProfileEngine(feature_store=_feature_store)
_anomaly_scorer = SessionAnomalyScorer(feature_store=_feature_store)
_engagement_scorer = EngagementScorer(feature_store=_feature_store)
_ato_detector = ATODetector(feature_store=_feature_store, anomaly_scorer=_anomaly_scorer)


# --- Profile Endpoints ---


@router.get("/users/{user_id}/profile")
async def get_user_profile(
    user_id: str,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """Retrieve the user's current behavioral profile with maturity status."""
    profile = await _profile_engine.get_profile(user_id, session)

    if profile is None:
        return {
            "user_id": user_id,
            "profile": None,
            "message": "No behavioral profile found for this user",
        }

    return {
        "user_id": profile.user_id,
        "profile_status": profile.profile_status.value,
        "profile_maturity": profile.profile_maturity,
        "session_baseline": profile.session_baseline.model_dump(),
        "temporal_baseline": profile.temporal_baseline.model_dump(),
        "device_baseline": profile.device_baseline.model_dump(),
        "geographic_baseline": profile.geographic_baseline.model_dump(),
        "engagement_baseline": profile.engagement_baseline.model_dump(),
        "last_updated": profile.last_updated.isoformat(),
        "profile_version": profile.profile_version,
    }


@router.get("/users/{user_id}/profile/summary")
async def get_user_profile_summary(
    user_id: str,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """Simplified profile view: status, primary device, primary location, typical hours, risk level."""
    profile = await _profile_engine.get_profile(user_id, session)

    if profile is None:
        return {
            "user_id": user_id,
            "summary": None,
            "message": "No behavioral profile found for this user",
        }

    # Format typical hours
    typical_hours_str = ""
    if profile.temporal_baseline.typical_hours:
        sorted_hours = sorted(
            profile.temporal_baseline.typical_hours.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        top_hours = [str(h) for h, _ in sorted_hours[:3]]
        typical_hours_str = f"Peak hours: {', '.join(top_hours)}:00"

    summary = ProfileSummary(
        user_id=profile.user_id,
        profile_status=profile.profile_status,
        profile_maturity=profile.profile_maturity,
        primary_device=profile.device_baseline.primary_device,
        primary_location=profile.geographic_baseline.primary_location,
        typical_hours=typical_hours_str,
        risk_level="low",
        last_updated=profile.last_updated,
    )

    return summary.model_dump()


# --- Session Anomaly Scoring ---


@router.post("/sessions/score")
async def score_session(
    request: SessionScoreRequest,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """Score a session for anomalies in real-time."""
    # Get user profile
    profile = await _profile_engine.get_profile(request.user_id, session)

    # Build session event dict from request
    session_event = {
        "session_id": request.session_id,
        "user_id": request.user_id,
        "device_id": request.device_id,
        "device_type": request.device_type,
        "ip_address": request.ip_address,
        "geo_location": request.geo_location,
        "session_start": request.session_start.isoformat() if request.session_start else None,
        "session_duration_seconds": request.session_duration_seconds,
        "action_count": request.action_count,
        "actions": request.actions or [],
    }

    result = await _anomaly_scorer.score_session(
        session_event, profile, feast_features=request.features
    )

    # Update profile with this session
    if profile or request.features:
        await _profile_engine.update_profile(request.user_id, session_event, session)

    return {
        "session_id": result.session_id,
        "user_id": result.user_id,
        "composite_score": result.composite_score,
        "classification": result.classification.value,
        "dimension_scores": [d.model_dump() for d in result.dimension_scores],
        "profile_maturity": result.profile_maturity,
        "recommended_action": result.recommended_action.value,
        "timestamp": result.timestamp.isoformat(),
    }


# --- Engagement Endpoints ---


@router.get("/users/{user_id}/engagement")
async def get_user_engagement(
    user_id: str,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """Engagement score, lifecycle stage, and churn risk for a user."""
    profile = await _profile_engine.get_profile(user_id, session)

    result = await _engagement_scorer.score_engagement(
        user_id=user_id,
        profile=profile,
    )

    return {
        "user_id": result.user_id,
        "engagement_score": result.engagement_score,
        "lifecycle_stage": result.lifecycle_stage.value,
        "churn_risk": result.churn_risk,
        "churn_risk_level": result.churn_risk_level,
        "engagement_trend": result.engagement_trend,
        "computed_at": result.computed_at.isoformat(),
    }


@router.get("/engagement/summary")
async def get_engagement_summary() -> dict:
    """Distribution of users across lifecycle stages, average engagement by stage.

    Note: In production, this would query aggregated data from the database.
    Currently returns a placeholder as individual user scoring is done on-demand.
    """
    return {
        "total_users": 0,
        "stage_distribution": {},
        "avg_engagement_by_stage": {},
        "message": "Query individual users via /users/{user_id}/engagement. "
        "Batch summary requires aggregated data.",
    }


@router.get("/engagement/at-risk")
async def get_at_risk_users() -> dict:
    """Users in declining stage or with high churn risk.

    Note: In production, this would query users flagged in the database.
    Currently returns a placeholder.
    """
    return {
        "items": [],
        "total": 0,
        "message": "At-risk users are identified during engagement scoring. "
        "Query individual users to check churn risk.",
    }


# --- ATO Detection Endpoints ---


@router.post("/ato/assess")
async def assess_ato(
    request: ATOAssessRequest,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """ATO risk assessment for a session with context."""
    # Get user profile
    profile = await _profile_engine.get_profile(request.user_id, session)

    # Build session event dict
    session_event = {
        "session_id": request.session_id,
        "user_id": request.user_id,
        "device_id": request.device_id,
        "device_type": request.device_type,
        "ip_address": request.ip_address,
        "geo_location": request.geo_location,
        "session_start": request.session_start.isoformat() if request.session_start else None,
        "session_duration_seconds": request.session_duration_seconds,
        "action_count": request.action_count,
        "actions": request.actions or [],
        "failed_login_count_10m": request.failed_login_count_10m,
        "failed_login_count_1h": request.failed_login_count_1h,
        "pending_transactions": request.pending_transactions or [],
    }

    assessment = await _ato_detector.assess(
        session_event=session_event,
        profile=profile,
        db_session=session,
        feast_features=request.features,
    )

    return {
        "session_id": assessment.session_id,
        "user_id": assessment.user_id,
        "ato_risk_score": assessment.ato_risk_score,
        "risk_level": assessment.risk_level.value,
        "contributing_signals": [s.model_dump() for s in assessment.contributing_signals],
        "recommended_response": assessment.recommended_response.value,
        "affected_transactions": assessment.affected_transactions,
        "timestamp": assessment.timestamp.isoformat(),
    }


@router.get("/ato/alerts")
async def list_ato_alerts(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    user_id: str | None = Query(default=None, description="Filter by user ID"),
    status: str | None = Query(default=None, description="Filter by alert status"),
    risk_level: str | None = Query(default=None, description="Filter by risk level (high/critical)"),
    start_date: datetime | None = Query(default=None, description="Filter from date"),
    end_date: datetime | None = Query(default=None, description="Filter to date"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """List ATO alerts, filterable by user, status, risk level, date range."""
    alerts, total = await _ato_detector.get_alerts(
        db_session=session,
        user_id=user_id,
        status=status,
        risk_level=risk_level,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )

    return {
        "items": alerts,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.put("/ato/alerts/{alert_id}")
async def update_ato_alert(
    alert_id: str,
    update: ATOAlertUpdate,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """Update ATO alert status (investigating, confirmed, false_positive, resolved)."""
    result = await _ato_detector.update_alert_status(alert_id, update, session)

    if result is None:
        return {
            "alert_id": alert_id,
            "message": "ATO alert not found",
        }

    return result
