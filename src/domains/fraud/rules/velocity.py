"""Velocity-based fraud detection rules."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import RawEvent

from ..config import FraudConfig
from ..models import FraudScoreRequest, RiskFactor, RuleResult, TransactionFeatures
from .base import FraudRule


class TransactionFrequencyRule(FraudRule):
    """Triggers when transaction count in 1h exceeds threshold."""

    rule_id = "transaction_frequency"
    category = "velocity"
    default_weight = 0.15

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        threshold = config.velocity.txn_count_1h_max
        count = features.velocity_count_1h
        if count < threshold:
            return self._not_triggered()

        # Scale score 0.3-1.0 based on how far over threshold
        ratio = min(count / threshold, 3.0)
        score = 0.3 + (ratio - 1.0) * 0.35
        score = min(score, 1.0)

        return self._triggered(
            score=score,
            risk_factor=RiskFactor.VELOCITY_COUNT_1H,
            details=f"{count} transactions in last hour (threshold: {threshold})",
            severity="high" if count >= threshold * 2 else "medium",
            confidence=0.85,
            evidence={"count": count, "threshold": threshold, "window": "1h"},
        )


class VelocityCount24hRule(FraudRule):
    """Triggers when transaction count in 24h exceeds threshold."""

    rule_id = "velocity_count_24h"
    category = "velocity"
    default_weight = 0.10

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        threshold = config.velocity.txn_count_24h_max
        count = features.velocity_count_24h
        if count < threshold:
            return self._not_triggered()

        ratio = min(count / threshold, 3.0)
        score = 0.3 + (ratio - 1.0) * 0.35
        score = min(score, 1.0)

        return self._triggered(
            score=score,
            risk_factor=RiskFactor.VELOCITY_COUNT_24H,
            details=f"{count} transactions in last 24h (threshold: {threshold})",
            severity="high" if count >= threshold * 2 else "medium",
            confidence=0.80,
            evidence={"count": count, "threshold": threshold, "window": "24h"},
        )


class VelocityAmount24hRule(FraudRule):
    """Triggers when 24h cumulative amount exceeds threshold."""

    rule_id = "velocity_amount_24h"
    category = "velocity"
    default_weight = 0.12

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        total = features.velocity_amount_24h + request.amount_float
        threshold = config.velocity.txn_amount_24h_max
        if total < threshold:
            return self._not_triggered()

        ratio = min(total / threshold, 5.0)
        score = 0.3 + (ratio - 1.0) * 0.175
        score = min(score, 1.0)

        return self._triggered(
            score=score,
            risk_factor=RiskFactor.VELOCITY_AMOUNT_24H,
            details=f"24h total: ${total:,.2f} (threshold: ${threshold:,.2f})",
            severity="high" if total >= threshold * 2 else "medium",
            confidence=0.85,
            evidence={"total": total, "threshold": threshold, "window": "24h"},
        )


class LoginVelocityRule(FraudRule):
    """Triggers when login count in short window exceeds threshold."""

    rule_id = "login_velocity"
    category = "velocity"
    default_weight = 0.12

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        window_minutes = config.velocity.login_count_window_minutes
        max_logins = config.velocity.login_count_max
        now = request.initiated_at
        if not now:
            from datetime import UTC, datetime

            now = datetime.now(UTC)

        start = now - timedelta(minutes=window_minutes)

        stmt = select(func.count()).where(
            RawEvent.event_type == "session-started",
            RawEvent.payload["payload"]["user_id"].astext == request.user_id,
            RawEvent.received_at >= start,
            RawEvent.received_at < now,
        )
        result = await session.execute(stmt)
        count = result.scalar_one()

        if count < max_logins:
            return self._not_triggered()

        ratio = min(count / max_logins, 3.0)
        score = 0.4 + (ratio - 1.0) * 0.3
        score = min(score, 1.0)

        return self._triggered(
            score=score,
            risk_factor=RiskFactor.LOGIN_VELOCITY,
            details=f"{count} logins in {window_minutes}min (threshold: {max_logins})",
            severity="high",
            confidence=0.90,
            evidence={"count": count, "threshold": max_logins, "window_minutes": window_minutes},
        )


class CircleJoinVelocityRule(FraudRule):
    """Triggers when circle join count in window exceeds threshold."""

    rule_id = "circle_join_velocity"
    category = "velocity"
    default_weight = 0.10

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        window_hours = config.velocity.circle_join_window_hours
        max_joins = config.velocity.circle_join_max
        now = request.initiated_at
        if not now:
            from datetime import UTC, datetime

            now = datetime.now(UTC)

        start = now - timedelta(hours=window_hours)

        stmt = select(func.count()).where(
            RawEvent.event_type == "circle-member-joined",
            RawEvent.payload["payload"]["user_id"].astext == request.user_id,
            RawEvent.received_at >= start,
            RawEvent.received_at < now,
        )
        result = await session.execute(stmt)
        count = result.scalar_one()

        if count < max_joins:
            return self._not_triggered()

        ratio = min(count / max_joins, 3.0)
        score = 0.3 + (ratio - 1.0) * 0.35
        score = min(score, 1.0)

        return self._triggered(
            score=score,
            risk_factor=RiskFactor.CIRCLE_JOIN_VELOCITY,
            details=f"{count} circle joins in {window_hours}h (threshold: {max_joins})",
            severity="medium",
            confidence=0.75,
            evidence={"count": count, "threshold": max_joins, "window_hours": window_hours},
        )


class UnusualHourRule(FraudRule):
    """Triggers for transactions during unusual hours (2-5 AM UTC)."""

    rule_id = "unusual_hour"
    category = "velocity"
    default_weight = 0.05

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        if not request.initiated_at:
            return self._not_triggered()

        hour = request.initiated_at.hour
        if not (2 <= hour < 5):
            return self._not_triggered()

        return self._triggered(
            score=0.3,
            risk_factor=RiskFactor.UNUSUAL_HOUR,
            details=f"Transaction at unusual hour: {hour}:00 UTC",
            severity="low",
            confidence=0.50,
            evidence={"hour_utc": hour},
        )
