"""Circle health scoring API endpoints — Phase 6."""


import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_session
from src.db.models import (
    CircleAnomalyDB,
    CircleClassificationDB,
    CircleTierChangeDB,
)
from src.db.models import (
    CircleHealth as CircleHealthDB,
)
from src.domains.circles.anomaly import CircleAnomalyDetector
from src.domains.circles.classification import CircleClassifier, publish_tier_change
from src.domains.circles.config import default_config
from src.domains.circles.models import (
    CircleScoreRequest,
    HealthTier,
)
from src.domains.circles.scoring import CircleHealthScorer
from src.features.store import FeatureStore

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/circles", tags=["circles"])

_scorer = CircleHealthScorer()
_anomaly_detector = CircleAnomalyDetector()
_classifier = CircleClassifier()
_feature_store = FeatureStore()


@router.post("/{circle_id}/score")
async def score_circle(
    circle_id: str,
    request: CircleScoreRequest | None = None,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """Compute and return the health score for a specific circle."""
    # Get features from store or request
    if request and request.features:
        features = request.features
    else:
        features = await _feature_store.get_features(circle_id, "circle_health")

    # Score
    health_score = _scorer.score(circle_id, features)

    # Detect anomalies
    anomalies = _anomaly_detector.detect_all(circle_id, features)

    # Classify
    classification = _classifier.classify(health_score, anomalies)

    # Check for tier change
    prev_row = await _get_latest_classification(session, circle_id)
    previous_tier = HealthTier(prev_row.health_tier) if prev_row else None
    tier_change = _classifier.detect_tier_change(
        circle_id=circle_id,
        current_tier=classification.health_tier,
        previous_tier=previous_tier,
        health_score=health_score.health_score,
        reason=classification.classification_reason,
    )

    # Persist health score
    health_row = CircleHealthDB(
        circle_id=circle_id,
        health_score=health_score.health_score,
        health_tier=health_score.health_tier.value,
        trend=health_score.trend.value,
        confidence=health_score.confidence,
        dimension_scores={
            k: v.model_dump() for k, v in health_score.dimension_scores.items()
        },
        factors={},
        scoring_version=health_score.scoring_version,
        computed_at=health_score.last_updated,
    )
    session.add(health_row)

    # Persist anomalies
    for anomaly in anomalies:
        anomaly_row = CircleAnomalyDB(
            anomaly_id=anomaly.anomaly_id,
            circle_id=circle_id,
            anomaly_type=anomaly.anomaly_type.value,
            severity=anomaly.severity.value,
            affected_members=anomaly.affected_members,
            evidence=[e.model_dump() for e in anomaly.evidence],
            detected_at=anomaly.detected_at,
        )
        session.add(anomaly_row)

    # Persist classification
    classification_row = CircleClassificationDB(
        circle_id=circle_id,
        health_tier=classification.health_tier.value,
        health_score=classification.health_score,
        trend=classification.trend.value,
        anomaly_count=classification.anomaly_count,
        recommended_actions=[a.model_dump() for a in classification.recommended_actions],
        classification_reason=classification.classification_reason,
        classified_at=classification.classified_at,
    )
    session.add(classification_row)

    # Persist tier change if any
    if tier_change:
        tier_change_row = CircleTierChangeDB(
            circle_id=circle_id,
            previous_tier=tier_change.previous_tier.value,
            new_tier=tier_change.new_tier.value,
            health_score=tier_change.health_score,
            reason=tier_change.reason,
            changed_at=tier_change.changed_at,
        )
        session.add(tier_change_row)

    await session.commit()

    # Publish tier change to Kafka (after commit)
    if tier_change:
        await publish_tier_change(tier_change, None, default_config.tier_change_topic)

    return {
        "circle_id": circle_id,
        "health_score": health_score.health_score,
        "health_tier": health_score.health_tier.value,
        "trend": health_score.trend.value,
        "confidence": health_score.confidence,
        "dimension_scores": {
            k: v.model_dump() for k, v in health_score.dimension_scores.items()
        },
        "anomaly_count": len(anomalies),
        "classification": {
            "tier": classification.health_tier.value,
            "recommended_actions": [a.model_dump() for a in classification.recommended_actions],
            "reason": classification.classification_reason,
        },
        "tier_change": tier_change.model_dump() if tier_change else None,
        "scoring_version": health_score.scoring_version,
        "computed_at": health_score.last_updated.isoformat(),
    }


@router.get("/{circle_id}/health")
async def get_circle_health(
    circle_id: str,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """Retrieve the most recently computed health score for a circle."""
    stmt = (
        select(CircleHealthDB)
        .where(CircleHealthDB.circle_id == circle_id)
        .order_by(desc(CircleHealthDB.computed_at))
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        return {
            "circle_id": circle_id,
            "health_score": None,
            "message": "No health score computed yet for this circle",
        }

    return {
        "circle_id": row.circle_id,
        "health_score": row.health_score,
        "health_tier": row.health_tier,
        "trend": row.trend,
        "confidence": row.confidence,
        "dimension_scores": row.dimension_scores,
        "scoring_version": row.scoring_version,
        "computed_at": row.computed_at.isoformat(),
    }


@router.get("/health/summary")
async def health_summary(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    tier: str | None = Query(default=None, description="Filter by health tier"),
    sort_by: str = Query(default="health_score", pattern="^(health_score|computed_at)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Return health scores for all active circles, sortable and filterable."""
    # Get latest score per circle using a subquery
    from sqlalchemy import func

    latest_subq = (
        select(
            CircleHealthDB.circle_id,
            func.max(CircleHealthDB.id).label("max_id"),
        )
        .group_by(CircleHealthDB.circle_id)
        .subquery()
    )

    stmt = select(CircleHealthDB).join(
        latest_subq,
        (CircleHealthDB.circle_id == latest_subq.c.circle_id)
        & (CircleHealthDB.id == latest_subq.c.max_id),
    )

    if tier:
        stmt = stmt.where(CircleHealthDB.health_tier == tier)

    # Sort
    if sort_by == "health_score":
        order_col = CircleHealthDB.health_score
    else:
        order_col = CircleHealthDB.computed_at
    stmt = stmt.order_by(desc(order_col) if sort_order == "desc" else order_col)

    # Count total
    from sqlalchemy import func as sqla_func

    count_subq = (
        select(sqla_func.count())
        .select_from(
            select(CircleHealthDB.circle_id)
            .join(
                latest_subq,
                (CircleHealthDB.circle_id == latest_subq.c.circle_id)
                & (CircleHealthDB.id == latest_subq.c.max_id),
            )
        )
    )
    if tier:
        count_subq = count_subq.where(CircleHealthDB.health_tier == tier)
    count_result = await session.execute(count_subq)
    total = count_result.scalar_one()

    # Paginate
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    return {
        "items": [
            {
                "circle_id": r.circle_id,
                "health_score": r.health_score,
                "health_tier": r.health_tier,
                "trend": r.trend,
                "last_updated": r.computed_at.isoformat(),
            }
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{circle_id}/anomalies")
async def get_circle_anomalies(
    circle_id: str,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    anomaly_type: str | None = Query(default=None, description="Filter by anomaly type"),
    severity: str | None = Query(default=None, description="Filter by severity"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Return detected anomalies for a circle, filterable by type and severity."""
    stmt = (
        select(CircleAnomalyDB)
        .where(CircleAnomalyDB.circle_id == circle_id)
    )

    if anomaly_type:
        stmt = stmt.where(CircleAnomalyDB.anomaly_type == anomaly_type)
    if severity:
        stmt = stmt.where(CircleAnomalyDB.severity == severity)

    stmt = stmt.order_by(desc(CircleAnomalyDB.detected_at))

    # Count
    from sqlalchemy import func as sqla_func

    count_stmt = select(sqla_func.count()).select_from(CircleAnomalyDB).where(
        CircleAnomalyDB.circle_id == circle_id
    )
    if anomaly_type:
        count_stmt = count_stmt.where(CircleAnomalyDB.anomaly_type == anomaly_type)
    if severity:
        count_stmt = count_stmt.where(CircleAnomalyDB.severity == severity)
    count_result = await session.execute(count_stmt)
    total = count_result.scalar_one()

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    return {
        "items": [
            {
                "anomaly_id": r.anomaly_id,
                "circle_id": r.circle_id,
                "anomaly_type": r.anomaly_type,
                "severity": r.severity,
                "affected_members": r.affected_members,
                "evidence": r.evidence,
                "detected_at": r.detected_at.isoformat(),
            }
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{circle_id}/classification")
async def get_circle_classification(
    circle_id: str,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict:
    """Current risk tier with recommended actions for a circle."""
    row = await _get_latest_classification(session, circle_id)

    if not row:
        return {
            "circle_id": circle_id,
            "classification": None,
            "message": "No classification computed yet for this circle",
        }

    return {
        "circle_id": row.circle_id,
        "health_tier": row.health_tier,
        "health_score": row.health_score,
        "trend": row.trend,
        "anomaly_count": row.anomaly_count,
        "recommended_actions": row.recommended_actions,
        "classification_reason": row.classification_reason,
        "classified_at": row.classified_at.isoformat(),
    }


@router.get("/at-risk")
async def get_at_risk_circles(
    session: AsyncSession = Depends(get_session),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """List all circles currently classified as At-Risk or Critical, sorted by severity."""
    from sqlalchemy import func as sqla_func

    # Get latest classification per circle
    latest_subq = (
        select(
            CircleClassificationDB.circle_id,
            sqla_func.max(CircleClassificationDB.id).label("max_id"),
        )
        .group_by(CircleClassificationDB.circle_id)
        .subquery()
    )

    stmt = (
        select(CircleClassificationDB)
        .join(
            latest_subq,
            (CircleClassificationDB.circle_id == latest_subq.c.circle_id)
            & (CircleClassificationDB.id == latest_subq.c.max_id),
        )
        .where(
            CircleClassificationDB.health_tier.in_(
                [HealthTier.AT_RISK.value, HealthTier.CRITICAL.value]
            )
        )
        .order_by(CircleClassificationDB.health_score)  # lowest score first
    )

    # Count
    count_stmt = (
        select(sqla_func.count())
        .select_from(
            select(CircleClassificationDB.circle_id)
            .join(
                latest_subq,
                (CircleClassificationDB.circle_id == latest_subq.c.circle_id)
                & (CircleClassificationDB.id == latest_subq.c.max_id),
            )
            .where(
                CircleClassificationDB.health_tier.in_(
                    [HealthTier.AT_RISK.value, HealthTier.CRITICAL.value]
                )
            )
        )
    )
    count_result = await session.execute(count_stmt)
    total = count_result.scalar_one()

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    return {
        "items": [
            {
                "circle_id": r.circle_id,
                "health_tier": r.health_tier,
                "health_score": r.health_score,
                "trend": r.trend,
                "recommended_actions": r.recommended_actions,
                "classified_at": r.classified_at.isoformat(),
            }
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def _get_latest_classification(
    session: AsyncSession, circle_id: str
) -> CircleClassificationDB | None:
    """Get the most recent classification for a circle."""
    stmt = (
        select(CircleClassificationDB)
        .where(CircleClassificationDB.circle_id == circle_id)
        .order_by(desc(CircleClassificationDB.classified_at))
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
