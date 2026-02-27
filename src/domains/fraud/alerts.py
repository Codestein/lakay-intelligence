"""Fraud alert pipeline: creation, deduplication, and Kafka publishing."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Alert as AlertDB

from .config import FraudConfig
from .models import FraudScoreRequest, ScoringContext

logger = structlog.get_logger()


async def check_dedup(
    user_id: str,
    rule_ids: list[str],
    session: AsyncSession,
    suppression_window_seconds: int = 3600,
) -> bool:
    """Check if a similar alert already exists within the suppression window.

    Returns True if a duplicate exists (should suppress).
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=suppression_window_seconds)

    stmt = select(func.count()).where(
        AlertDB.user_id == user_id,
        AlertDB.status.in_(["open", "new", "acknowledged", "investigating"]),
        AlertDB.created_at >= cutoff,
    )
    result = await session.execute(stmt)
    count = result.scalar_one()

    if count > 0:
        logger.info(
            "alert_deduplicated",
            user_id=user_id,
            existing_alerts=count,
            rule_ids=rule_ids,
        )
        return True

    return False


async def create_alert(
    scoring_context: ScoringContext,
    request: FraudScoreRequest,
    session: AsyncSession,
    config: FraudConfig,
) -> AlertDB | None:
    """Create a fraud alert if score warrants it and no dedup suppression."""
    from .models import RiskTier

    if scoring_context.risk_tier not in (RiskTier.HIGH, RiskTier.CRITICAL):
        return None

    rule_ids = [r.rule_name for r in scoring_context.triggered_rules]

    # Check deduplication
    is_dup = await check_dedup(
        user_id=request.user_id,
        rule_ids=rule_ids,
        session=session,
        suppression_window_seconds=config.alerts.suppression_window_seconds,
    )
    if is_dup:
        return None

    severity = "critical" if scoring_context.risk_tier == RiskTier.CRITICAL else "high"

    alert = AlertDB(
        alert_id=str(uuid.uuid4()),
        user_id=request.user_id,
        alert_type="fraud_score",
        severity=severity,
        details={
            "transaction_id": request.transaction_id,
            "composite_score": scoring_context.composite_score,
            "risk_tier": scoring_context.risk_tier.value,
            "recommendation": scoring_context.recommendation,
            "triggered_rules": [
                {
                    "rule_name": r.rule_name,
                    "score": r.score,
                    "severity": r.severity,
                    "details": r.details,
                    "category": r.category,
                }
                for r in scoring_context.triggered_rules
            ],
            "model_version": scoring_context.scoring_metadata.get("model_version", "rules-v2"),
        },
        status="new",
        created_at=datetime.now(UTC),
    )
    session.add(alert)

    logger.warning(
        "fraud_alert_created",
        alert_id=alert.alert_id,
        user_id=request.user_id,
        transaction_id=request.transaction_id,
        composite_score=scoring_context.composite_score,
        severity=severity,
        risk_tier=scoring_context.risk_tier.value,
    )

    return alert


async def publish_alert(alert: AlertDB, producer) -> None:
    """Publish alert to Kafka topic for downstream consumption.

    Args:
        alert: The alert DB record to publish.
        producer: An aiokafka AIOKafkaProducer instance.
    """
    if producer is None:
        logger.debug("kafka_producer_not_available", alert_id=alert.alert_id)
        return

    topic = "lakay.fraud.alerts"
    payload = {
        "alert_id": alert.alert_id,
        "user_id": alert.user_id,
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "details": alert.details,
        "status": alert.status,
        "created_at": alert.created_at.isoformat(),
    }

    try:
        await producer.send_and_wait(
            topic,
            value=json.dumps(payload).encode("utf-8"),
            key=alert.user_id.encode("utf-8"),
        )
        logger.info("alert_published_to_kafka", alert_id=alert.alert_id, topic=topic)
    except Exception:
        logger.exception("alert_publish_failed", alert_id=alert.alert_id, topic=topic)
