"""Fraud detection endpoints with hybrid rules + ML scoring."""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_session
from src.db.models import Alert as AlertDB
from src.db.models import FraudScore as FraudScoreDB
from src.domains.fraud.config import default_config
from src.domains.fraud.models import FraudScoreRequest
from src.domains.fraud.rules import ALL_RULES
from src.domains.fraud.scorer import FraudScorer
from src.serving.config import default_serving_config
from src.serving.monitoring import get_model_monitor
from src.serving.server import get_model_server

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/fraud", tags=["fraud"])

_scorer = FraudScorer()


def _compute_hybrid_score(
    rule_score: float,
    ml_score: float | None,
) -> tuple[float, str]:
    """Combine rule-based and ML scores using the configured strategy.

    Returns (hybrid_score, model_version_string).

    Strategy (from serving config):
    - 'weighted_average': w_rules * rule + w_ml * ml
    - 'max': max(rule, ml)
    - 'ensemble_vote': both must agree
    """
    config = default_serving_config.hybrid

    if not config.ml_enabled or ml_score is None:
        return rule_score, "rules-v2"

    strategy = config.strategy
    if strategy == "weighted_average":
        hybrid = config.rule_weight * rule_score + config.ml_weight * ml_score
    elif strategy == "max":
        hybrid = max(rule_score, ml_score)
    else:
        # ensemble_vote: average when both flag, otherwise take the higher
        hybrid = (rule_score + ml_score) / 2

    return min(hybrid, 1.0), "hybrid-v1"


@router.post("/score")
async def score_fraud(
    request: FraudScoreRequest,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    # Check if already scored
    stmt = select(FraudScoreDB).where(FraudScoreDB.transaction_id == request.transaction_id)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        scoring_ctx = existing.rules_triggered.get("scoring_context", {})
        return {
            "transaction_id": existing.transaction_id,
            "score": existing.risk_score,
            "composite_score": scoring_ctx.get("composite_score", existing.risk_score / 100),
            "risk_tier": getattr(existing, "risk_tier", scoring_ctx.get("risk_tier", "low")),
            "recommendation": scoring_ctx.get("recommendation", "allow"),
            "confidence": getattr(existing, "confidence", 0.0),
            "risk_factors": existing.rules_triggered.get("risk_factors", []),
            "model_version": existing.model_version,
            "computed_at": existing.scored_at.isoformat(),
        }

    scoring_result = await _scorer.score_transaction(request, session)
    ctx = scoring_result.scoring_context
    rule_score = ctx.composite_score if ctx else 0.0

    # Attempt ML scoring (graceful fallback if unavailable)
    ml_score = None
    ml_details = None
    server = get_model_server()
    if server.is_loaded:
        try:
            features_for_ml = {
                "amount": request.amount_float,
                "amount_zscore": 0.0,
                "hour_of_day": (request.initiated_at.hour if request.initiated_at else 0),
                "day_of_week": (request.initiated_at.weekday() if request.initiated_at else 0),
                "tx_type_encoded": 0,
                "balance_delta_sender": 0.0,
                "balance_delta_receiver": 0.0,
                "velocity_count_1h": (
                    scoring_result.features_used.velocity_count_1h
                    if scoring_result.features_used
                    else 0
                ),
                "velocity_count_24h": (
                    scoring_result.features_used.velocity_count_24h
                    if scoring_result.features_used
                    else 0
                ),
                "velocity_amount_1h": (
                    scoring_result.features_used.velocity_amount_1h
                    if scoring_result.features_used
                    else 0.0
                ),
                "velocity_amount_24h": (
                    scoring_result.features_used.velocity_amount_24h
                    if scoring_result.features_used
                    else 0.0
                ),
            }
            prediction = server.predict(features_for_ml)
            if prediction:
                ml_score = prediction.score
                ml_details = {
                    "ml_score": prediction.score,
                    "ml_model": prediction.model_name,
                    "ml_version": prediction.model_version,
                    "ml_latency_ms": prediction.prediction_latency_ms,
                }
                # Record for monitoring
                monitor = get_model_monitor()
                monitor.record_prediction(prediction.score, prediction.prediction_latency_ms)
        except Exception:
            logger.warning(
                "ml_scoring_fallback",
                transaction_id=request.transaction_id,
                exc_info=True,
            )

    # Compute hybrid score
    hybrid_score, model_version = _compute_hybrid_score(rule_score, ml_score)

    response = {
        "transaction_id": request.transaction_id,
        "score": scoring_result.final_score,
        "composite_score": hybrid_score,
        "rule_score": rule_score,
        "ml_score": ml_score,
        "risk_tier": ctx.risk_tier.value if ctx else "low",
        "recommendation": ctx.recommendation if ctx else "allow",
        "confidence": ctx.scoring_metadata.get("confidence", 0.0) if ctx else 0.0,
        "risk_factors": [
            r.risk_factor.value
            for r in scoring_result.rule_results
            if r.triggered and r.risk_factor
        ],
        "model_version": model_version,
        "computed_at": datetime.now(UTC).isoformat(),
    }

    if ml_details:
        response["ml_details"] = ml_details

    return response


@router.get("/rules")
async def list_rules() -> dict:
    """Return current rule configurations, thresholds, weights, and model version."""
    config = default_config
    rules_info = []
    for rule in ALL_RULES:
        rules_info.append(
            {
                "rule_id": rule.rule_id,
                "category": rule.category,
                "default_weight": rule.default_weight,
            }
        )

    return {
        "model_version": "rules-v2",
        "rule_count": len(ALL_RULES),
        "rules": rules_info,
        "category_caps": {
            "velocity": config.scoring.velocity_cap,
            "amount": config.scoring.amount_cap,
            "geo": config.scoring.geo_cap,
            "patterns": config.scoring.patterns_cap,
        },
        "alert_thresholds": {
            "high": config.alerts.high_threshold,
            "critical": config.alerts.critical_threshold,
        },
    }


@router.get("/alerts")
async def list_alerts(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    severity: str | None = None,
    status: str | None = None,
    user_id: str | None = None,
    risk_tier: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort_by: str = Query(default="created_at", pattern="^(created_at|severity)$"),
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
    if user_id:
        stmt = stmt.where(AlertDB.user_id == user_id)
        count_stmt = count_stmt.where(AlertDB.user_id == user_id)
    if risk_tier:
        stmt = stmt.where(AlertDB.details["risk_tier"].astext == risk_tier)
        count_stmt = count_stmt.where(AlertDB.details["risk_tier"].astext == risk_tier)
    if date_from:
        stmt = stmt.where(AlertDB.created_at >= date_from)
        count_stmt = count_stmt.where(AlertDB.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AlertDB.created_at <= date_to)
        count_stmt = count_stmt.where(AlertDB.created_at <= date_to)

    # Get total count
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    # Sort
    if sort_by == "severity":
        stmt = stmt.order_by(AlertDB.severity.desc(), AlertDB.created_at.desc())
    else:
        stmt = stmt.order_by(AlertDB.created_at.desc())

    # Paginate
    stmt = stmt.offset(offset).limit(limit)
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
