"""Fraud detection endpoints."""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_session
from src.db.models import Alert as AlertDB
from src.db.models import FraudScore as FraudScoreDB
from src.domains.fraud.models import FraudScoreRequest
from src.domains.fraud.scorer import FraudScorer

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/fraud", tags=["fraud"])

_scorer = FraudScorer()


@router.post("/score")
async def score_fraud(
    request: FraudScoreRequest,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    # Check if already scored
    stmt = select(FraudScoreDB).where(
        FraudScoreDB.transaction_id == request.transaction_id
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        return {
            "transaction_id": existing.transaction_id,
            "score": existing.risk_score,
            "confidence": min(len(existing.rules_triggered.get("risk_factors", [])) / 5, 1.0),
            "risk_factors": existing.rules_triggered.get("risk_factors", []),
            "model_version": existing.model_version,
            "computed_at": existing.scored_at.isoformat(),
        }

    scoring_result = await _scorer.score_transaction(request, session)

    return {
        "transaction_id": request.transaction_id,
        "score": scoring_result.final_score,
        "confidence": min(
            len([r for r in scoring_result.rule_results if r.triggered]) / 5, 1.0
        ),
        "risk_factors": [
            r.risk_factor.value
            for r in scoring_result.rule_results
            if r.triggered and r.risk_factor
        ],
        "model_version": "rules-v1",
        "computed_at": datetime.now(UTC).isoformat(),
    }


@router.get("/alerts")
async def list_alerts(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    severity: str | None = None,
    status: str | None = None,
) -> dict:
    # Build query
    stmt = select(AlertDB)
    count_stmt = select(func.count()).select_from(AlertDB)

    if severity:
        stmt = stmt.where(AlertDB.severity == severity)
        count_stmt = count_stmt.where(AlertDB.severity == severity)
    if status:
        stmt = stmt.where(AlertDB.status == status)
        count_stmt = count_stmt.where(AlertDB.status == status)

    # Get total count
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    # Get paginated results
    stmt = stmt.order_by(AlertDB.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    alerts = result.scalars().all()

    return {
        "items": [
            {
                "alert_id": a.alert_id,
                "user_id": a.user_id,
                "alert_type": a.alert_type,
                "severity": a.severity,
                "details": a.details,
                "status": a.status,
                "created_at": a.created_at.isoformat(),
                "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
            }
            for a in alerts
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
