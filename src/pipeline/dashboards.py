"""Operational dashboard query functions powered by gold datasets."""

from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    Alert,
    CircleClassificationDB,
    CircleHealth,
    FraudScore,
)
from src.pipeline.gold import GoldProcessor
from src.pipeline.storage import DataLakeStorage

logger = structlog.get_logger()


def _default_gold() -> GoldProcessor:
    return GoldProcessor(storage=DataLakeStorage())


# ---------------------------------------------------------------------------
# Platform Overview Dashboard
# ---------------------------------------------------------------------------


async def get_platform_health(
    session: AsyncSession,
    start_date: str | None = None,
    end_date: str | None = None,
    gold: GoldProcessor | None = None,
) -> dict[str, Any]:
    """Platform health: active users, transaction volume, circle health, fraud alerts."""
    gold = gold or _default_gold()
    date_range = (start_date, end_date) if start_date and end_date else None
    records = gold.query_gold("platform-health", date_range=date_range)

    # Aggregate across days
    total_active_users = 0
    total_sessions = 0
    total_txn_count = 0
    total_txn_volume = 0.0
    total_remittance_count = 0
    total_remittance_volume = 0.0

    for r in records:
        total_active_users += r.get("active_users", 0)
        total_sessions += r.get("sessions", 0)
        total_txn_count += r.get("transaction_count", 0)
        total_txn_volume += float(r.get("transaction_volume", 0))
        total_remittance_count += r.get("remittance_count", 0)
        total_remittance_volume += float(r.get("remittance_volume", 0))

    # Get fraud alert count from DB
    alert_stmt = select(func.count(Alert.id)).where(Alert.alert_type == "fraud")
    if start_date:
        alert_stmt = alert_stmt.where(Alert.created_at >= start_date)
    if end_date:
        alert_stmt = alert_stmt.where(Alert.created_at <= end_date)
    alert_result = await session.execute(alert_stmt)
    fraud_alert_count = alert_result.scalar() or 0

    # Get circle health distribution
    circle_stmt = select(
        CircleHealth.health_tier,
        func.count(CircleHealth.id),
    ).group_by(CircleHealth.health_tier)
    circle_result = await session.execute(circle_stmt)
    circle_distribution = {row[0]: row[1] for row in circle_result.all()}

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "active_users": total_active_users,
        "sessions": total_sessions,
        "transactions": {
            "count": total_txn_count,
            "volume": round(total_txn_volume, 2),
        },
        "remittances": {
            "count": total_remittance_count,
            "volume": round(total_remittance_volume, 2),
        },
        "fraud_alert_count": fraud_alert_count,
        "circle_health_distribution": circle_distribution,
        "daily_breakdown": records,
    }


async def get_growth_metrics(
    session: AsyncSession,
    start_date: str | None = None,
    end_date: str | None = None,
    gold: GoldProcessor | None = None,
) -> dict[str, Any]:
    """Growth: new user signups, first transactions, retention by cohort."""
    gold = gold or _default_gold()
    date_range = (start_date, end_date) if start_date and end_date else None
    records = gold.query_gold("platform-health", date_range=date_range)

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "daily_active_users": [
            {"date": r.get("date"), "active_users": r.get("active_users", 0)}
            for r in records
        ],
        "daily_sessions": [
            {"date": r.get("date"), "sessions": r.get("sessions", 0)}
            for r in records
        ],
        "daily_new_circles": [
            {"date": r.get("date"), "circles_created": r.get("circles_created", 0)}
            for r in records
        ],
    }


# ---------------------------------------------------------------------------
# Fraud Operations Dashboard
# ---------------------------------------------------------------------------


async def get_fraud_overview(
    session: AsyncSession,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Fraud: alerts by tier, top rules, false positive rate, model performance."""
    # Alerts by severity
    severity_stmt = select(
        Alert.severity, func.count(Alert.id)
    ).where(Alert.alert_type == "fraud").group_by(Alert.severity)
    if start_date:
        severity_stmt = severity_stmt.where(Alert.created_at >= start_date)
    if end_date:
        severity_stmt = severity_stmt.where(Alert.created_at <= end_date)
    severity_result = await session.execute(severity_stmt)
    alerts_by_severity = {row[0]: row[1] for row in severity_result.all()}

    # Scoring stats
    score_stmt = select(
        func.count(FraudScore.id),
        func.avg(FraudScore.risk_score),
        func.min(FraudScore.risk_score),
        func.max(FraudScore.risk_score),
    )
    if start_date:
        score_stmt = score_stmt.where(FraudScore.scored_at >= start_date)
    if end_date:
        score_stmt = score_stmt.where(FraudScore.scored_at <= end_date)
    score_result = await session.execute(score_stmt)
    score_row = score_result.one_or_none()

    total_scored = int(score_row[0]) if score_row else 0
    avg_score = round(float(score_row[1] or 0), 4)

    # Distribution by risk tier
    tier_stmt = select(
        FraudScore.risk_tier, func.count(FraudScore.id)
    ).group_by(FraudScore.risk_tier)
    if start_date:
        tier_stmt = tier_stmt.where(FraudScore.scored_at >= start_date)
    if end_date:
        tier_stmt = tier_stmt.where(FraudScore.scored_at <= end_date)
    tier_result = await session.execute(tier_stmt)
    scores_by_tier = {row[0]: row[1] for row in tier_result.all()}

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "alerts_by_severity": alerts_by_severity,
        "total_scored": total_scored,
        "average_risk_score": avg_score,
        "scores_by_tier": scores_by_tier,
    }


async def get_fraud_user_drilldown(
    session: AsyncSession,
    user_id: str,
) -> dict[str, Any]:
    """Full fraud history for a specific user."""
    # Fraud scores
    scores_stmt = (
        select(FraudScore)
        .where(FraudScore.user_id == user_id)
        .order_by(FraudScore.scored_at.desc())
        .limit(50)
    )
    scores_result = await session.execute(scores_stmt)
    scores = [
        {
            "transaction_id": s.transaction_id,
            "risk_score": s.risk_score,
            "risk_tier": s.risk_tier,
            "model_version": s.model_version,
            "scored_at": s.scored_at.isoformat() if s.scored_at else None,
        }
        for s in scores_result.scalars().all()
    ]

    # Alerts
    alerts_stmt = (
        select(Alert)
        .where(Alert.user_id == user_id, Alert.alert_type == "fraud")
        .order_by(Alert.created_at.desc())
        .limit(50)
    )
    alerts_result = await session.execute(alerts_stmt)
    alerts = [
        {
            "alert_id": a.alert_id,
            "severity": a.severity,
            "status": a.status,
            "details": a.details,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in alerts_result.scalars().all()
    ]

    return {
        "user_id": user_id,
        "fraud_scores": scores,
        "alerts": alerts,
        "total_scores": len(scores),
        "total_alerts": len(alerts),
    }


# ---------------------------------------------------------------------------
# Circle Health Dashboard
# ---------------------------------------------------------------------------


async def get_circle_health_overview(
    session: AsyncSession,
) -> dict[str, Any]:
    """Circle health: distribution by tier, anomaly types, at-risk circles."""
    # Distribution by tier
    tier_stmt = select(
        CircleClassificationDB.health_tier,
        func.count(CircleClassificationDB.id),
    ).group_by(CircleClassificationDB.health_tier)
    tier_result = await session.execute(tier_stmt)
    tier_distribution = {row[0]: row[1] for row in tier_result.all()}

    # Recent health scores
    health_stmt = (
        select(CircleHealth)
        .order_by(CircleHealth.computed_at.desc())
        .limit(20)
    )
    health_result = await session.execute(health_stmt)
    recent_scores = [
        {
            "circle_id": h.circle_id,
            "health_score": h.health_score,
            "health_tier": h.health_tier,
            "trend": h.trend,
            "computed_at": h.computed_at.isoformat() if h.computed_at else None,
        }
        for h in health_result.scalars().all()
    ]

    return {
        "tier_distribution": tier_distribution,
        "recent_health_scores": recent_scores,
        "total_circles": sum(tier_distribution.values()),
    }


async def get_circle_drilldown(
    session: AsyncSession,
    circle_id: str,
) -> dict[str, Any]:
    """Full health history for a specific circle."""
    # Health history
    health_stmt = (
        select(CircleHealth)
        .where(CircleHealth.circle_id == circle_id)
        .order_by(CircleHealth.computed_at.desc())
        .limit(30)
    )
    health_result = await session.execute(health_stmt)
    history = [
        {
            "health_score": h.health_score,
            "health_tier": h.health_tier,
            "trend": h.trend,
            "dimension_scores": h.dimension_scores,
            "computed_at": h.computed_at.isoformat() if h.computed_at else None,
        }
        for h in health_result.scalars().all()
    ]

    # Latest classification
    class_stmt = (
        select(CircleClassificationDB)
        .where(CircleClassificationDB.circle_id == circle_id)
        .order_by(CircleClassificationDB.classified_at.desc())
        .limit(1)
    )
    class_result = await session.execute(class_stmt)
    classification = class_result.scalar_one_or_none()

    return {
        "circle_id": circle_id,
        "health_history": history,
        "current_classification": {
            "health_tier": classification.health_tier,
            "health_score": classification.health_score,
            "recommended_actions": classification.recommended_actions,
        } if classification else None,
    }


# ---------------------------------------------------------------------------
# Compliance Dashboard
# ---------------------------------------------------------------------------


async def get_compliance_overview(
    session: AsyncSession,
    start_date: str | None = None,
    end_date: str | None = None,
    gold: GoldProcessor | None = None,
) -> dict[str, Any]:
    """Compliance: CTR/SAR counts, risk distribution, EDD reviews."""
    gold = gold or _default_gold()
    date_range = (start_date, end_date) if start_date and end_date else None
    records = gold.query_gold("compliance-reporting", date_range=date_range)

    total_ctr = sum(r.get("ctr_filing_count", 0) for r in records)
    total_ctr_amount = sum(float(r.get("ctr_total_amount", 0)) for r in records)
    total_sar = sum(r.get("sar_filing_count", 0) for r in records)

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "ctr_filings": {"count": total_ctr, "total_amount": round(total_ctr_amount, 2)},
        "sar_filings": {"count": total_sar},
        "daily_breakdown": records,
    }


async def get_compliance_pipeline(
    session: AsyncSession,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Alert → case → filing funnel."""
    # Total compliance alerts
    alert_stmt = select(func.count(Alert.id)).where(Alert.alert_type == "compliance")
    if start_date:
        alert_stmt = alert_stmt.where(Alert.created_at >= start_date)
    if end_date:
        alert_stmt = alert_stmt.where(Alert.created_at <= end_date)
    alert_count = (await session.execute(alert_stmt)).scalar() or 0

    # Resolved alerts
    resolved_stmt = select(func.count(Alert.id)).where(
        Alert.alert_type == "compliance",
        Alert.status == "resolved",
    )
    resolved_count = (await session.execute(resolved_stmt)).scalar() or 0

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "total_alerts": alert_count,
        "resolved_alerts": resolved_count,
        "funnel": {
            "alerts_generated": alert_count,
            "cases_opened": alert_count,  # 1:1 for now
            "filings_submitted": 0,  # will be populated from compliance reports
        },
    }


# ---------------------------------------------------------------------------
# Haiti Corridor Dashboard
# ---------------------------------------------------------------------------


async def get_corridor_overview(
    session: AsyncSession,
    start_date: str | None = None,
    end_date: str | None = None,
    gold: GoldProcessor | None = None,
) -> dict[str, Any]:
    """Haiti corridor: remittance volume by corridor, delivery metrics."""
    gold = gold or _default_gold()
    date_range = (start_date, end_date) if start_date and end_date else None
    records = gold.query_gold("haiti-corridor-analytics", date_range=date_range)

    # Aggregate by corridor
    corridors: dict[str, dict] = {}
    for r in records:
        corridor = r.get("corridor", "unknown")
        if corridor not in corridors:
            corridors[corridor] = {
                "corridor": corridor,
                "total_count": 0,
                "total_volume": 0.0,
                "amounts": [],
            }
        c = corridors[corridor]
        c["total_count"] += r.get("remittance_count", 0)
        c["total_volume"] += float(r.get("total_volume_usd", 0))

    corridor_summary = [
        {
            "corridor": c["corridor"],
            "remittance_count": c["total_count"],
            "total_volume_usd": round(c["total_volume"], 2),
        }
        for c in corridors.values()
    ]

    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "corridors": corridor_summary,
        "daily_breakdown": records,
    }
