"""Amount-based fraud detection rules."""

from datetime import timedelta

from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import RawEvent

from ..config import FraudConfig
from ..models import FraudScoreRequest, RiskFactor, RuleResult, TransactionFeatures
from .base import FraudRule


class LargeTransactionRule(FraudRule):
    """Triggers for single transactions above the large-txn threshold."""

    rule_id = "large_transaction"
    category = "amount"
    default_weight = 0.15

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        amount = request.amount_float
        threshold = config.amount.large_txn_min

        if amount < threshold:
            return self._not_triggered()

        # Scale 0.2-1.0 for amounts from threshold to 10x threshold
        ratio = min(amount / threshold, 10.0)
        score = 0.2 + (ratio - 1.0) * 0.089
        score = min(score, 1.0)

        severity = "low"
        if amount >= threshold * 5:
            severity = "critical"
        elif amount >= threshold * 3:
            severity = "high"
        elif amount >= threshold * 1.5:
            severity = "medium"

        return self._triggered(
            score=score,
            risk_factor=RiskFactor.HIGH_AMOUNT,
            details=f"Large transaction: ${amount:,.2f} (threshold: ${threshold:,.2f})",
            severity=severity,
            confidence=0.90,
            evidence={"amount": amount, "threshold": threshold},
        )


class CumulativeAmountRule(FraudRule):
    """Triggers when rolling 24h/7d/30d totals exceed limits."""

    rule_id = "cumulative_amount"
    category = "amount"
    default_weight = 0.15

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        now = request.initiated_at
        if not now:
            from datetime import UTC, datetime

            now = datetime.now(UTC)

        amount_expr = RawEvent.payload["payload"]["amount"].astext.cast(Float)
        base_filter = (
            RawEvent.event_type == "transaction-initiated",
            RawEvent.payload["payload"]["user_id"].astext == request.user_id,
        )

        windows = {
            "24h": (now - timedelta(hours=24), config.amount.cumulative_24h_max),
            "7d": (now - timedelta(days=7), config.amount.cumulative_7d_max),
            "30d": (now - timedelta(days=30), config.amount.cumulative_30d_max),
        }

        breaches = {}
        max_score = 0.0

        for window_name, (start, limit) in windows.items():
            stmt = select(func.coalesce(func.sum(amount_expr), 0)).where(
                *base_filter,
                RawEvent.received_at >= start,
                RawEvent.received_at < now,
            )
            result = await session.execute(stmt)
            total = float(result.scalar_one()) + request.amount_float

            if total >= limit:
                ratio = min(total / limit, 3.0)
                window_score = 0.3 + (ratio - 1.0) * 0.35
                window_score = min(window_score, 1.0)
                breaches[window_name] = {"total": total, "limit": limit}
                max_score = max(max_score, window_score)

        if not breaches:
            return self._not_triggered()

        severity = "critical" if "24h" in breaches else "high"

        return self._triggered(
            score=max_score,
            risk_factor=RiskFactor.CUMULATIVE_AMOUNT,
            details=f"Cumulative limits breached: {', '.join(breaches.keys())}",
            severity=severity,
            confidence=0.85,
            evidence={"breaches": breaches},
        )


class BaselineDeviationRule(FraudRule):
    """Triggers when current txn deviates significantly from user's baseline."""

    rule_id = "baseline_deviation"
    category = "amount"
    default_weight = 0.12

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        avg = features.avg_amount_30d
        stddev = features.stddev_amount_30d
        amount = request.amount_float
        threshold = config.amount.baseline_zscore_threshold

        # Need meaningful baseline (at least some history)
        if avg == 0 or stddev == 0:
            return self._not_triggered()

        zscore = (amount - avg) / stddev

        if zscore < threshold:
            return self._not_triggered()

        # Scale score based on z-score magnitude
        score = min(0.3 + (zscore - threshold) * 0.15, 1.0)

        severity = "high" if zscore > threshold * 2 else "medium"

        return self._triggered(
            score=score,
            risk_factor=RiskFactor.DEVIATION_FROM_BASELINE,
            details=f"Z-score {zscore:.2f} (avg: ${avg:,.2f}, stddev: ${stddev:,.2f})",
            severity=severity,
            confidence=min(0.6 + zscore * 0.05, 0.95),
            evidence={"zscore": zscore, "avg": avg, "stddev": stddev, "amount": amount},
        )


class CTRProximityRule(FraudRule):
    """Triggers for amounts near Currency Transaction Report thresholds.

    Critical for BSA/AML compliance: single txn >= $8k or daily cumulative >= $9k.
    """

    rule_id = "ctr_proximity"
    category = "amount"
    default_weight = 0.20

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        amount = request.amount_float
        single_threshold = config.amount.ctr_single_threshold
        daily_threshold = config.amount.ctr_daily_threshold

        # Check single transaction threshold
        if amount >= single_threshold:
            score = min(0.5 + (amount - single_threshold) / single_threshold * 0.5, 1.0)
            return self._triggered(
                score=score,
                risk_factor=RiskFactor.CTR_PROXIMITY,
                details=f"Single txn ${amount:,.2f} near CTR threshold (${single_threshold:,.2f})",
                severity="critical",
                confidence=0.95,
                evidence={
                    "amount": amount,
                    "threshold": single_threshold,
                    "trigger": "single_transaction",
                },
            )

        # Check daily cumulative
        daily_total = features.velocity_amount_24h + amount
        if daily_total >= daily_threshold:
            score = min(0.5 + (daily_total - daily_threshold) / daily_threshold * 0.5, 1.0)
            return self._triggered(
                score=score,
                risk_factor=RiskFactor.CTR_PROXIMITY,
                details=f"Daily total ${daily_total:,.2f} near CTR threshold",
                severity="critical",
                confidence=0.90,
                evidence={
                    "daily_total": daily_total,
                    "threshold": daily_threshold,
                    "trigger": "daily_cumulative",
                },
            )

        return self._not_triggered()
