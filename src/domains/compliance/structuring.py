"""Compliance-grade structuring detection (Task 8.3).

Detects four structuring typologies with confidence scoring:

  1. Micro-structuring  — multiple transactions within a single business day
  2. Slow structuring   — patterns across days with amounts just below thresholds
  3. Fan-out structuring — one sender to multiple recipients
  4. Funnel structuring  — multiple senders to one recipient

This module is independent of Phase 3's fraud structuring detection (Task 3.4).
Compliance has stricter rules, longer lookback windows, and different response
obligations mandated by 31 USC § 5324.

All structuring detections are logged regardless of confidence for audit purposes.
"""

import math
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import structlog

from .config import ComplianceConfig, default_config
from .models import (
    AlertPriority,
    AlertStatus,
    AlertType,
    ComplianceAlert,
    ComplianceTransaction,
    RecommendedAction,
    StructuringDetection,
    StructuringTypology,
)

logger = structlog.get_logger()


def _threshold_proximity_score(amount: float, threshold: float = 10_000.0) -> float:
    """Score how close an amount is to a known threshold (0.0–1.0).

    Amounts at exactly $9,999 score higher than amounts at $5,000.
    """
    if amount >= threshold:
        return 0.0  # At or above threshold — not structuring, just over
    ratio = amount / threshold
    # Exponential curve: amounts very close to threshold get much higher scores
    return ratio**3


def _temporal_regularity_score(timestamps: list[datetime]) -> float:
    """Score temporal regularity of transactions (0.0–1.0).

    Clock-like patterns (regular intervals) score higher — indicative of
    automated or deliberate structuring.
    """
    if len(timestamps) < 3:
        return 0.0

    sorted_ts = sorted(timestamps)
    intervals = [
        (sorted_ts[i + 1] - sorted_ts[i]).total_seconds()
        for i in range(len(sorted_ts) - 1)
    ]

    if not intervals:
        return 0.0

    mean_interval = sum(intervals) / len(intervals)
    if mean_interval == 0:
        return 1.0  # All at the same time — highly suspicious

    variance = sum((x - mean_interval) ** 2 for x in intervals) / len(intervals)
    std_dev = math.sqrt(variance)

    # Coefficient of variation: lower = more regular
    cv = std_dev / mean_interval if mean_interval > 0 else 0.0

    # Map CV to score: CV=0 → 1.0, CV>=1.0 → 0.0
    return max(0.0, min(1.0, 1.0 - cv))


# ---------------------------------------------------------------------------
# 1. Micro-Structuring (within a day)
# ---------------------------------------------------------------------------


def detect_micro_structuring(
    user_id: str,
    transactions: list[ComplianceTransaction],
    config: ComplianceConfig = default_config,
) -> list[StructuringDetection]:
    """Detect multiple transactions within a single business day that
    individually fall below $10,000 but cumulatively approach or exceed it.

    Regulatory basis: 31 USC § 5324(a)(3) — structuring to evade CTR filing.
    """
    if not config.structuring.enabled:
        return []

    detections: list[StructuringDetection] = []

    # Group by business date (simplified: use UTC date)
    by_date: dict[str, list[ComplianceTransaction]] = defaultdict(list)
    for tx in transactions:
        date_key = tx.initiated_at.strftime("%Y-%m-%d")
        by_date[date_key].append(tx)

    threshold = config.ctr.ctr_threshold
    proximity_pct = config.structuring.micro_cumulative_proximity_pct

    for date_key, day_txns in by_date.items():
        if len(day_txns) < 2:
            continue

        cumulative = sum(tx.amount for tx in day_txns)

        # All transactions must be individually below threshold
        if any(tx.amount >= threshold for tx in day_txns):
            continue

        # Check if cumulative is within proximity of threshold
        if cumulative < threshold * proximity_pct:
            continue

        # Check per-recipient grouping
        by_recipient: dict[str | None, list[ComplianceTransaction]] = defaultdict(list)
        for tx in day_txns:
            by_recipient[tx.recipient_id].append(tx)

        triggered = False

        # Same-recipient threshold
        for recipient, rtxns in by_recipient.items():
            if len(rtxns) >= config.structuring.micro_min_transactions:
                rcum = sum(tx.amount for tx in rtxns)
                if rcum >= threshold * proximity_pct:
                    triggered = True
                    break

        # Total transaction threshold
        if not triggered and len(day_txns) >= config.structuring.micro_min_total_transactions:
            triggered = True

        if triggered:
            # Calculate confidence
            proximity = _threshold_proximity_score(cumulative, threshold)
            temporal = _temporal_regularity_score(
                [tx.initiated_at for tx in day_txns]
            )
            count_factor = min(1.0, len(day_txns) / 10.0)
            confidence = 0.4 * proximity + 0.3 * temporal + 0.3 * count_factor

            detection = StructuringDetection(
                detection_id=str(uuid.uuid4()),
                user_id=user_id,
                typology=StructuringTypology.MICRO,
                confidence=min(1.0, max(0.0, confidence)),
                transaction_ids=[tx.transaction_id for tx in day_txns],
                amount_total=cumulative,
                description=(
                    f"Micro-structuring detected: {len(day_txns)} transactions "
                    f"on {date_key} totaling ${cumulative:,.2f} "
                    f"({cumulative / threshold:.0%} of CTR threshold). "
                    f"Individual amounts range from "
                    f"${min(tx.amount for tx in day_txns):,.2f} to "
                    f"${max(tx.amount for tx in day_txns):,.2f}."
                ),
                indicators={
                    "transaction_count": len(day_txns),
                    "cumulative_amount": cumulative,
                    "threshold_proximity_pct": cumulative / threshold,
                    "temporal_regularity": temporal,
                    "amounts": [tx.amount for tx in day_txns],
                },
                detected_at=datetime.now(UTC),
            )
            detections.append(detection)
            logger.info(
                "micro_structuring_detected",
                user_id=user_id,
                date=date_key,
                transaction_count=len(day_txns),
                cumulative=cumulative,
                confidence=detection.confidence,
            )

    return detections


# ---------------------------------------------------------------------------
# 2. Slow Structuring (across days)
# ---------------------------------------------------------------------------


def detect_slow_structuring(
    user_id: str,
    transactions: list[ComplianceTransaction],
    historical_avg_amount: float | None = None,
    config: ComplianceConfig = default_config,
) -> list[StructuringDetection]:
    """Detect patterns where a user consistently transacts just below reporting
    thresholds across multiple days.

    Regulatory basis: 31 USC § 5324 — structuring transactions to evade
    reporting requirements.
    """
    if not config.structuring.enabled:
        return []

    sc = config.structuring
    detections: list[StructuringDetection] = []

    # Filter to transactions within the lookback period
    cutoff = datetime.now(UTC) - timedelta(days=sc.slow_lookback_days)
    recent = [tx for tx in transactions if tx.initiated_at >= cutoff]

    # Filter to transactions in the suspicious range
    in_range = [
        tx
        for tx in recent
        if sc.slow_amount_range_low <= tx.amount <= sc.slow_amount_range_high
    ]

    if len(in_range) < sc.slow_min_transactions:
        return detections

    cumulative = sum(tx.amount for tx in in_range)
    if cumulative < sc.slow_cumulative_threshold:
        return detections

    # Calculate confidence
    avg_amount = sum(tx.amount for tx in in_range) / len(in_range)
    proximity_scores = [
        _threshold_proximity_score(tx.amount) for tx in in_range
    ]
    avg_proximity = sum(proximity_scores) / len(proximity_scores)
    temporal = _temporal_regularity_score([tx.initiated_at for tx in in_range])

    # Historical behavior factor: if user always sent this amount, lower confidence
    behavior_factor = 1.0
    if historical_avg_amount is not None and historical_avg_amount > 0:
        # If current pattern is consistent with long-term behavior, reduce confidence
        deviation = abs(avg_amount - historical_avg_amount) / historical_avg_amount
        if deviation < 0.20:  # Within 20% of historical average
            behavior_factor = 0.3  # Heavily reduce confidence — likely normal behavior
        elif deviation < 0.50:
            behavior_factor = 0.7

    count_factor = min(1.0, len(in_range) / 10.0)
    confidence = (
        0.30 * avg_proximity
        + 0.25 * temporal
        + 0.20 * count_factor
        + 0.25 * (cumulative / (sc.slow_cumulative_threshold * 2))
    ) * behavior_factor

    detection = StructuringDetection(
        detection_id=str(uuid.uuid4()),
        user_id=user_id,
        typology=StructuringTypology.SLOW,
        confidence=min(1.0, max(0.0, confidence)),
        transaction_ids=[tx.transaction_id for tx in in_range],
        amount_total=cumulative,
        description=(
            f"Slow structuring detected: {len(in_range)} transactions over "
            f"{sc.slow_lookback_days} days totaling ${cumulative:,.2f}. "
            f"Each transaction in the ${sc.slow_amount_range_low:,.0f}–"
            f"${sc.slow_amount_range_high:,.0f} range (avg: ${avg_amount:,.2f}). "
            f"Cumulative total exceeds the ${sc.slow_cumulative_threshold:,.0f} threshold."
        ),
        indicators={
            "transaction_count": len(in_range),
            "lookback_days": sc.slow_lookback_days,
            "cumulative_amount": cumulative,
            "average_amount": avg_amount,
            "temporal_regularity": temporal,
            "behavior_factor": behavior_factor,
            "amounts": [tx.amount for tx in in_range],
            "dates": [tx.initiated_at.strftime("%Y-%m-%d") for tx in in_range],
        },
        detected_at=datetime.now(UTC),
    )
    detections.append(detection)

    logger.info(
        "slow_structuring_detected",
        user_id=user_id,
        transaction_count=len(in_range),
        cumulative=cumulative,
        confidence=detection.confidence,
    )

    return detections


# ---------------------------------------------------------------------------
# 3. Fan-Out Structuring
# ---------------------------------------------------------------------------


def detect_fan_out_structuring(
    user_id: str,
    transactions: list[ComplianceTransaction],
    config: ComplianceConfig = default_config,
) -> list[StructuringDetection]:
    """Detect one sender distributing funds across multiple recipients
    to stay below thresholds.

    Especially relevant for the remittance corridor: sending to multiple
    "recipients" in Haiti who may be the same ultimate beneficiary.

    Regulatory basis: 31 USC § 5324 — structuring to evade reporting.
    """
    if not config.structuring.enabled:
        return []

    sc = config.structuring
    detections: list[StructuringDetection] = []

    # Group outbound transactions by rolling windows
    window = timedelta(hours=sc.fanout_rolling_window_hours)
    outbound = [tx for tx in transactions if tx.sender_id == user_id or tx.user_id == user_id]

    if not outbound:
        return detections

    outbound_sorted = sorted(outbound, key=lambda tx: tx.initiated_at)

    # Sliding window approach
    for i, anchor in enumerate(outbound_sorted):
        window_end = anchor.initiated_at + window
        window_txns = [
            tx for tx in outbound_sorted[i:]
            if tx.initiated_at <= window_end
        ]

        # Count distinct recipients
        recipients = {tx.recipient_id for tx in window_txns if tx.recipient_id}
        if len(recipients) < sc.fanout_min_recipients:
            continue

        cumulative = sum(tx.amount for tx in window_txns)
        if cumulative < sc.fanout_cumulative_threshold:
            continue

        # All individual amounts below threshold
        if any(tx.amount >= config.ctr.ctr_threshold for tx in window_txns):
            continue

        # Calculate confidence
        proximity_scores = [
            _threshold_proximity_score(tx.amount) for tx in window_txns
        ]
        avg_proximity = sum(proximity_scores) / len(proximity_scores)
        recipient_factor = min(1.0, len(recipients) / 6.0)
        amount_factor = min(1.0, cumulative / (sc.fanout_cumulative_threshold * 1.5))

        confidence = 0.35 * avg_proximity + 0.35 * recipient_factor + 0.30 * amount_factor

        detection = StructuringDetection(
            detection_id=str(uuid.uuid4()),
            user_id=user_id,
            typology=StructuringTypology.FAN_OUT,
            confidence=min(1.0, max(0.0, confidence)),
            transaction_ids=[tx.transaction_id for tx in window_txns],
            amount_total=cumulative,
            description=(
                f"Fan-out structuring detected: user {user_id} sent to "
                f"{len(recipients)} distinct recipients within "
                f"{sc.fanout_rolling_window_hours} hours, totaling "
                f"${cumulative:,.2f}. Individual amounts below CTR threshold."
            ),
            indicators={
                "recipient_count": len(recipients),
                "recipients": list(recipients),
                "transaction_count": len(window_txns),
                "cumulative_amount": cumulative,
                "window_hours": sc.fanout_rolling_window_hours,
                "amounts": [tx.amount for tx in window_txns],
            },
            detected_at=datetime.now(UTC),
        )
        detections.append(detection)

        logger.info(
            "fan_out_structuring_detected",
            user_id=user_id,
            recipient_count=len(recipients),
            cumulative=cumulative,
            confidence=detection.confidence,
        )
        # Only report one detection per anchor — avoid duplicates
        break

    return detections


# ---------------------------------------------------------------------------
# 4. Funnel Structuring
# ---------------------------------------------------------------------------


def detect_funnel_structuring(
    recipient_id: str,
    transactions: list[ComplianceTransaction],
    config: ComplianceConfig = default_config,
) -> list[StructuringDetection]:
    """Detect multiple senders funneling funds to a single recipient.

    Relevant for circle abuse: members colluding to channel funds through
    the payout mechanism.

    Regulatory basis: 31 USC § 5324 — structuring to evade reporting.
    """
    if not config.structuring.enabled:
        return []

    sc = config.structuring
    detections: list[StructuringDetection] = []

    # Filter to inbound transactions for this recipient
    inbound = [
        tx for tx in transactions
        if tx.recipient_id == recipient_id
    ]

    if not inbound:
        return detections

    inbound_sorted = sorted(inbound, key=lambda tx: tx.initiated_at)
    window = timedelta(hours=sc.funnel_rolling_window_hours)

    for i, anchor in enumerate(inbound_sorted):
        window_end = anchor.initiated_at + window
        window_txns = [
            tx for tx in inbound_sorted[i:]
            if tx.initiated_at <= window_end
        ]

        # Count distinct senders
        senders = {tx.user_id for tx in window_txns if tx.user_id}
        # Exclude the recipient from the sender list
        senders.discard(recipient_id)

        if len(senders) < sc.funnel_min_senders:
            continue

        cumulative = sum(tx.amount for tx in window_txns)
        if cumulative < sc.funnel_cumulative_threshold:
            continue

        # All individual amounts below threshold
        if any(tx.amount >= config.ctr.ctr_threshold for tx in window_txns):
            continue

        # Calculate confidence
        proximity_scores = [
            _threshold_proximity_score(tx.amount) for tx in window_txns
        ]
        avg_proximity = sum(proximity_scores) / len(proximity_scores)
        sender_factor = min(1.0, len(senders) / 6.0)
        amount_factor = min(1.0, cumulative / (sc.funnel_cumulative_threshold * 1.5))

        confidence = 0.35 * avg_proximity + 0.35 * sender_factor + 0.30 * amount_factor

        detection = StructuringDetection(
            detection_id=str(uuid.uuid4()),
            user_id=recipient_id,
            typology=StructuringTypology.FUNNEL,
            confidence=min(1.0, max(0.0, confidence)),
            transaction_ids=[tx.transaction_id for tx in window_txns],
            amount_total=cumulative,
            description=(
                f"Funnel structuring detected: {len(senders)} distinct senders "
                f"sent to recipient {recipient_id} within "
                f"{sc.funnel_rolling_window_hours} hours, totaling "
                f"${cumulative:,.2f}. Individual amounts below CTR threshold."
            ),
            indicators={
                "sender_count": len(senders),
                "senders": list(senders),
                "transaction_count": len(window_txns),
                "cumulative_amount": cumulative,
                "window_hours": sc.funnel_rolling_window_hours,
                "amounts": [tx.amount for tx in window_txns],
            },
            detected_at=datetime.now(UTC),
        )
        detections.append(detection)

        logger.info(
            "funnel_structuring_detected",
            recipient_id=recipient_id,
            sender_count=len(senders),
            cumulative=cumulative,
            confidence=detection.confidence,
        )
        break

    return detections


# ---------------------------------------------------------------------------
# Compliance Response
# ---------------------------------------------------------------------------


def structuring_to_alert(
    detection: StructuringDetection,
    config: ComplianceConfig = default_config,
) -> ComplianceAlert:
    """Convert a structuring detection into a compliance alert.

    - confidence > 0.7 → recommended_action = file_sar
    - confidence 0.4–0.7 → recommended_action = enhanced_monitoring
    - confidence < 0.4 → still logged, recommended_action = enhanced_monitoring
    """
    sc = config.structuring

    if detection.confidence >= sc.sar_confidence_threshold:
        action = RecommendedAction.FILE_SAR
        priority = AlertPriority.URGENT
    elif detection.confidence >= sc.enhanced_monitoring_confidence_threshold:
        action = RecommendedAction.ENHANCED_MONITORING
        priority = AlertPriority.ELEVATED
    else:
        action = RecommendedAction.ENHANCED_MONITORING
        priority = AlertPriority.ROUTINE

    # Apply priority override if configured
    if sc.priority_override:
        try:
            priority = AlertPriority(sc.priority_override)
        except ValueError:
            pass

    return ComplianceAlert(
        alert_id=str(uuid.uuid4()),
        alert_type=AlertType.STRUCTURING,
        user_id=detection.user_id,
        transaction_ids=detection.transaction_ids,
        amount_total=detection.amount_total,
        description=(
            f"Structuring detection ({detection.typology.value}): "
            f"{detection.description} "
            f"Confidence: {detection.confidence:.2f}."
        ),
        regulatory_basis=(
            "31 USC § 5324 — Structuring transactions to evade reporting "
            "requirements is a federal crime. "
            "31 CFR § 1010.311 — CTR reporting threshold. "
            "31 CFR § 1022.320 — SAR filing requirement for MSBs."
        ),
        recommended_action=action,
        priority=priority,
        status=AlertStatus.NEW,
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class StructuringDetector:
    """Orchestrates all four structuring detection typologies."""

    def __init__(self, config: ComplianceConfig | None = None) -> None:
        self.config = config or default_config
        # Audit log of all detections regardless of confidence
        self._detection_log: list[StructuringDetection] = []

    def analyze(
        self,
        user_id: str,
        transactions: list[ComplianceTransaction],
        historical_avg_amount: float | None = None,
    ) -> tuple[list[StructuringDetection], list[ComplianceAlert]]:
        """Run all structuring detection typologies for a user.

        Returns (detections, alerts). All detections are logged for audit
        regardless of confidence.
        """
        all_detections: list[StructuringDetection] = []
        all_alerts: list[ComplianceAlert] = []

        # 1. Micro-structuring
        micro = detect_micro_structuring(user_id, transactions, self.config)
        all_detections.extend(micro)

        # 2. Slow structuring
        slow = detect_slow_structuring(
            user_id, transactions, historical_avg_amount, self.config
        )
        all_detections.extend(slow)

        # 3. Fan-out structuring
        fan_out = detect_fan_out_structuring(user_id, transactions, self.config)
        all_detections.extend(fan_out)

        # 4. Funnel structuring — check if this user is a recipient
        recipient_txns = [tx for tx in transactions if tx.recipient_id == user_id]
        if recipient_txns:
            funnel = detect_funnel_structuring(user_id, transactions, self.config)
            all_detections.extend(funnel)

        # Log all detections for audit
        self._detection_log.extend(all_detections)

        # Convert to alerts
        for detection in all_detections:
            alert = structuring_to_alert(detection, self.config)
            all_alerts.append(alert)

        if all_detections:
            logger.info(
                "structuring_analysis_complete",
                user_id=user_id,
                detection_count=len(all_detections),
                typologies=[d.typology.value for d in all_detections],
                max_confidence=max(d.confidence for d in all_detections),
            )

        return all_detections, all_alerts

    @property
    def audit_log(self) -> list[StructuringDetection]:
        """Full audit log of all structuring detections."""
        return list(self._detection_log)
