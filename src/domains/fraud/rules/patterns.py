"""Pattern-based fraud detection rules."""

import statistics
from datetime import timedelta

from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import RawEvent

from ..config import FraudConfig
from ..models import FraudScoreRequest, RiskFactor, RuleResult, TransactionFeatures
from .base import FraudRule


class DuplicateTransactionRule(FraudRule):
    """Triggers when same sender+recipient+amount (within tolerance) appears in short window."""

    rule_id = "duplicate_transaction"
    category = "patterns"
    default_weight = 0.15

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        if not request.recipient_id:
            return self._not_triggered()

        window_minutes = config.patterns.duplicate_window_minutes
        tolerance = config.patterns.duplicate_tolerance_pct
        amount = request.amount_float

        now = request.initiated_at
        if not now:
            from datetime import UTC, datetime

            now = datetime.now(UTC)

        start = now - timedelta(minutes=window_minutes)

        amount_expr = RawEvent.payload["payload"]["amount"].astext.cast(Float)
        lower = amount * (1 - tolerance)
        upper = amount * (1 + tolerance)

        stmt = select(func.count()).where(
            RawEvent.event_type == "transaction-initiated",
            RawEvent.payload["payload"]["user_id"].astext == request.user_id,
            RawEvent.payload["payload"].op("->>")("recipient_id") == request.recipient_id,
            amount_expr >= lower,
            amount_expr <= upper,
            RawEvent.received_at >= start,
            RawEvent.received_at < now,
        )
        result = await session.execute(stmt)
        count = result.scalar_one()

        if count == 0:
            return self._not_triggered()

        score = min(0.5 + count * 0.2, 1.0)

        return self._triggered(
            score=score,
            risk_factor=RiskFactor.DUPLICATE_TRANSACTION,
            details=f"{count} near-duplicate txn(s) to same recipient in {window_minutes}min",
            severity="high" if count >= 2 else "medium",
            confidence=0.85,
            evidence={
                "duplicate_count": count,
                "amount": amount,
                "tolerance_pct": tolerance,
                "recipient_id": request.recipient_id,
                "window_minutes": window_minutes,
            },
        )


class StructuringDetectionRule(FraudRule):
    """Detects structuring: multiple txns summing near BSA reporting thresholds."""

    rule_id = "structuring_detection"
    category = "patterns"
    default_weight = 0.20

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        amount = request.amount_float
        range_3k = config.patterns.structuring_3k_range
        range_10k = config.patterns.structuring_10k_range

        triggered_ranges = []

        # Single-transaction proximity check
        if range_3k[0] <= amount <= range_3k[1]:
            proximity = (amount - range_3k[0]) / (range_3k[1] - range_3k[0])
            triggered_ranges.append(("$3k", proximity, 0.5))
        if range_10k[0] <= amount <= range_10k[1]:
            proximity = (amount - range_10k[0]) / (range_10k[1] - range_10k[0])
            triggered_ranges.append(("$10k", proximity, 0.7))

        # Multi-transaction structuring check: recent txns summing near thresholds
        now = request.initiated_at
        if not now:
            from datetime import UTC, datetime

            now = datetime.now(UTC)

        window_hours = config.patterns.structuring_window_hours
        start = now - timedelta(hours=window_hours)

        amount_expr = RawEvent.payload["payload"]["amount"].astext.cast(Float)
        base_filter = (
            RawEvent.event_type == "transaction-initiated",
            RawEvent.payload["payload"]["user_id"].astext == request.user_id,
            RawEvent.received_at >= start,
            RawEvent.received_at < now,
        )

        stmt = select(
            func.count().label("cnt"),
            func.coalesce(func.sum(amount_expr), 0).label("total"),
        ).where(*base_filter)

        result = await session.execute(stmt)
        row = result.one()
        recent_count = row.cnt
        recent_total = float(row.total) + amount

        # Check if cumulative is near reporting thresholds
        for threshold, label in [(3000.0, "$3k"), (10000.0, "$10k")]:
            lower = threshold * 0.90
            upper = threshold * 1.0
            if lower <= recent_total <= upper and recent_count >= 2:
                proximity = (recent_total - lower) / (upper - lower)
                triggered_ranges.append((f"cumulative-{label}", proximity, 0.6))

        if not triggered_ranges:
            return self._not_triggered()

        # Use highest score among triggered checks
        best = max(triggered_ranges, key=lambda x: x[2])
        score = best[2] + best[1] * 0.3
        score = min(score, 1.0)

        return self._triggered(
            score=score,
            risk_factor=RiskFactor.STRUCTURING_NEAR_10K
            if any("10k" in r[0] for r in triggered_ranges)
            else RiskFactor.STRUCTURING_NEAR_3K,
            details=f"Structuring detected near {', '.join(r[0] for r in triggered_ranges)}",
            severity="critical" if any("10k" in r[0] for r in triggered_ranges) else "high",
            confidence=0.80,
            evidence={
                "triggered_ranges": [{"range": r[0], "proximity": r[1]} for r in triggered_ranges],
                "amount": amount,
                "recent_count": recent_count,
                "recent_total": recent_total,
            },
        )


class RoundAmountClusteringRule(FraudRule):
    """Triggers when >60% of user's recent transactions are round amounts."""

    rule_id = "round_amount_clustering"
    category = "patterns"
    default_weight = 0.08

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

        lookback_days = config.patterns.round_amount_lookback_days
        start = now - timedelta(days=lookback_days)
        pct_threshold = config.patterns.round_amount_pct_threshold

        amount_expr = RawEvent.payload["payload"]["amount"].astext.cast(Float)
        base_filter = (
            RawEvent.event_type == "transaction-initiated",
            RawEvent.payload["payload"]["user_id"].astext == request.user_id,
            RawEvent.received_at >= start,
            RawEvent.received_at < now,
        )

        stmt = select(amount_expr).where(*base_filter)
        result = await session.execute(stmt)
        amounts = [float(row[0]) for row in result.fetchall()]

        # Include current transaction
        amounts.append(request.amount_float)

        if len(amounts) < 3:
            return self._not_triggered()

        # Count round amounts (divisible by 100)
        round_count = sum(1 for a in amounts if a % 100 == 0)
        pct = round_count / len(amounts)

        if pct < pct_threshold:
            return self._not_triggered()

        score = min(0.3 + (pct - pct_threshold) * 2.0, 0.8)

        return self._triggered(
            score=score,
            risk_factor=RiskFactor.ROUND_AMOUNT_CLUSTERING,
            details=f"{pct:.0%} round amounts in last {lookback_days}d"
            f" ({round_count}/{len(amounts)})",
            severity="medium",
            confidence=0.65,
            evidence={
                "round_pct": pct,
                "round_count": round_count,
                "total_count": len(amounts),
                "threshold": pct_threshold,
            },
        )


class TemporalStructuringRule(FraudRule):
    """Detects clock-like regularity in transaction timing (low std dev of intervals)."""

    rule_id = "temporal_structuring"
    category = "patterns"
    default_weight = 0.10

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

        lookback_days = config.patterns.temporal_lookback_days
        min_txns = config.patterns.temporal_min_txns
        stddev_threshold = config.patterns.temporal_stddev_threshold_seconds

        start = now - timedelta(days=lookback_days)

        stmt = (
            select(RawEvent.received_at)
            .where(
                RawEvent.event_type == "transaction-initiated",
                RawEvent.payload["payload"]["user_id"].astext == request.user_id,
                RawEvent.received_at >= start,
                RawEvent.received_at < now,
            )
            .order_by(RawEvent.received_at.asc())
        )
        result = await session.execute(stmt)
        timestamps = [row[0] for row in result.fetchall()]

        if len(timestamps) < min_txns:
            return self._not_triggered()

        # Calculate intervals in seconds
        intervals = []
        for i in range(1, len(timestamps)):
            diff = (timestamps[i] - timestamps[i - 1]).total_seconds()
            intervals.append(diff)

        if len(intervals) < 2:
            return self._not_triggered()

        stddev = statistics.stdev(intervals)
        mean_interval = statistics.mean(intervals)

        if stddev > stddev_threshold:
            return self._not_triggered()

        # Lower stddev = more suspicious (more clock-like)
        score = min(0.4 + (1.0 - stddev / stddev_threshold) * 0.5, 0.9)

        return self._triggered(
            score=score,
            risk_factor=RiskFactor.TEMPORAL_STRUCTURING,
            details=f"Clock-like intervals: mean={mean_interval:.0f}s, stddev={stddev:.0f}s",
            severity="high",
            confidence=0.75,
            evidence={
                "interval_stddev_seconds": stddev,
                "interval_mean_seconds": mean_interval,
                "threshold_seconds": stddev_threshold,
                "txn_count": len(timestamps),
            },
        )
