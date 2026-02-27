"""Circle anomaly detection.

Detects coordinated or manipulative behavior within circles:
- Coordinated late payment detection
- Post-payout disengagement pattern
- Free-rider detection
- Sudden behavior change detection
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from .models import (
    AnomalyEvidence,
    AnomalySeverity,
    AnomalyType,
    CircleAnomaly,
)

logger = structlog.get_logger()


@dataclass
class AnomalyConfig:
    """Configuration for anomaly detection thresholds."""

    # Coordinated late payment
    coordinated_late_min_members: int = 3  # min members late in same cycle
    coordinated_late_probability_threshold: float = 0.05  # p-value-like threshold
    coordinated_late_base_rate: float = 0.10  # baseline late rate per member

    # Post-payout disengagement
    disengagement_reliability_drop: float = 0.30  # 30% drop in reliability post-payout
    disengagement_min_members: int = 2  # minimum affected members to flag circle

    # Free-rider
    free_rider_balance_threshold: float = -0.50  # negative balance > 50% of expected

    # Behavioral shift
    behavioral_zscore_threshold: float = 2.5  # default z-score for anomaly
    behavioral_min_cycles: int = 3  # minimum cycles before establishing baseline


default_anomaly_config = AnomalyConfig()


def _binomial_probability(n: int, k: int, p: float) -> float:
    """Compute P(X >= k) for Binomial(n, p) using simple summation.

    For small n (typical circle sizes 5-20), direct computation is fine.
    """
    from math import comb

    prob_at_least_k = 0.0
    for i in range(k, n + 1):
        prob_at_least_k += comb(n, i) * (p**i) * ((1 - p) ** (n - i))
    return prob_at_least_k


class CircleAnomalyDetector:
    """Detects anomalies within circles from member-level features."""

    def __init__(self, config: AnomalyConfig | None = None) -> None:
        self._config = config or default_anomaly_config

    def detect_all(
        self,
        circle_id: str,
        circle_features: dict[str, Any],
        member_features: list[dict[str, Any]] | None = None,
    ) -> list[CircleAnomaly]:
        """Run all anomaly detectors and return any findings.

        Args:
            circle_id: The circle being analyzed.
            circle_features: Circle-level features from the feature store.
            member_features: Per-member feature dicts (optional, enables deeper analysis).

        Returns:
            List of detected anomalies.
        """
        anomalies: list[CircleAnomaly] = []

        anomalies.extend(self._detect_coordinated_late(circle_id, circle_features, member_features))
        anomalies.extend(
            self._detect_post_payout_disengagement(circle_id, circle_features, member_features)
        )
        anomalies.extend(self._detect_free_riders(circle_id, circle_features, member_features))
        anomalies.extend(
            self._detect_behavioral_shift(circle_id, circle_features, member_features)
        )

        if anomalies:
            logger.info(
                "circle_anomalies_detected",
                circle_id=circle_id,
                anomaly_count=len(anomalies),
                types=[a.anomaly_type.value for a in anomalies],
            )

        return anomalies

    def _detect_coordinated_late(
        self,
        circle_id: str,
        circle_features: dict[str, Any],
        member_features: list[dict[str, Any]] | None,
    ) -> list[CircleAnomaly]:
        """Detect coordinated late payments within a circle.

        Flags when multiple members of the same circle begin paying late in the
        same cycle. Uses a statistical test: if the probability of N members
        independently becoming late exceeds a threshold, it's flagged as
        potentially coordinated.
        """
        cfg = self._config

        # Use member-level data if available
        if member_features:
            late_members = [
                m for m in member_features if m.get("is_late_current_cycle", False)
            ]
            total_members = len(member_features)
            late_count = len(late_members)
            affected_ids = [m.get("user_id", "unknown") for m in late_members]
        else:
            # Fall back to circle-level approximation
            late_count = int(circle_features.get("late_members_current_cycle", 0))
            total_members = int(circle_features.get("member_count_current", 0))
            affected_ids = []

        if total_members < 2 or late_count < cfg.coordinated_late_min_members:
            return []

        # Statistical test: P(X >= late_count) under independent model
        base_rate = circle_features.get("historical_late_rate", cfg.coordinated_late_base_rate)
        p_value = _binomial_probability(total_members, late_count, base_rate)

        if p_value > cfg.coordinated_late_probability_threshold:
            return []

        # Determine severity based on the number of late members and p-value
        late_fraction = late_count / total_members
        if late_fraction >= 0.5 or p_value < 0.01:
            severity = AnomalySeverity.HIGH
        elif late_fraction >= 0.3 or p_value < 0.03:
            severity = AnomalySeverity.MEDIUM
        else:
            severity = AnomalySeverity.LOW

        return [
            CircleAnomaly(
                anomaly_id=str(uuid.uuid4()),
                circle_id=circle_id,
                anomaly_type=AnomalyType.COORDINATED_LATE,
                severity=severity,
                affected_members=affected_ids,
                evidence=[
                    AnomalyEvidence(
                        metric_name="late_member_count",
                        observed_value=float(late_count),
                        threshold=float(cfg.coordinated_late_min_members),
                        description=(
                            f"{late_count} of {total_members} members are late this cycle"
                        ),
                    ),
                    AnomalyEvidence(
                        metric_name="independence_probability",
                        observed_value=round(p_value, 6),
                        threshold=cfg.coordinated_late_probability_threshold,
                        description=(
                            f"Probability of {late_count}+ members independently "
                            f"being late is {p_value:.4f} "
                            f"(threshold: {cfg.coordinated_late_probability_threshold})"
                        ),
                    ),
                ],
                detected_at=datetime.now(UTC),
            )
        ]

    def _detect_post_payout_disengagement(
        self,
        circle_id: str,
        circle_features: dict[str, Any],
        member_features: list[dict[str, Any]] | None,
    ) -> list[CircleAnomaly]:
        """Detect post-payout disengagement — the classic sou-sou scam.

        Tracks whether members' contribution behavior degrades after they've
        received their payout rotation. Flags circles where a statistically
        significant number of members show post-payout degradation.
        """
        cfg = self._config

        if member_features:
            disengaged = []
            for m in member_features:
                pre = m.get("pre_payout_reliability", None)
                post = m.get("post_payout_reliability", None)
                has_received = m.get("has_received_payout", False)
                if pre is not None and post is not None and has_received and pre > 0:
                    drop = (pre - post) / pre
                    if drop >= cfg.disengagement_reliability_drop:
                        disengaged.append(m)
            affected_ids = [m.get("user_id", "unknown") for m in disengaged]
            disengaged_count = len(disengaged)
        else:
            disengagement_rate = circle_features.get("post_payout_disengagement_rate", 0.0)
            total_paid_out = int(circle_features.get("members_paid_out", 0))
            disengaged_count = int(disengagement_rate * total_paid_out)
            affected_ids = []

        if disengaged_count < cfg.disengagement_min_members:
            return []

        total_paid_out = int(circle_features.get("members_paid_out", 0))
        if total_paid_out == 0:
            return []

        disengagement_rate = disengaged_count / total_paid_out

        if disengagement_rate >= 0.5:
            severity = AnomalySeverity.HIGH
        elif disengagement_rate >= 0.3:
            severity = AnomalySeverity.MEDIUM
        else:
            severity = AnomalySeverity.LOW

        return [
            CircleAnomaly(
                anomaly_id=str(uuid.uuid4()),
                circle_id=circle_id,
                anomaly_type=AnomalyType.POST_PAYOUT_DISENGAGEMENT,
                severity=severity,
                affected_members=affected_ids,
                evidence=[
                    AnomalyEvidence(
                        metric_name="disengaged_member_count",
                        observed_value=float(disengaged_count),
                        threshold=float(cfg.disengagement_min_members),
                        description=(
                            f"{disengaged_count} of {total_paid_out} members who received "
                            "payouts show significantly reduced contribution behavior afterward"
                        ),
                    ),
                    AnomalyEvidence(
                        metric_name="disengagement_rate",
                        observed_value=round(disengagement_rate, 4),
                        threshold=cfg.disengagement_reliability_drop,
                        description=(
                            f"Post-payout disengagement rate: {disengagement_rate:.0%} "
                            "of paid-out members"
                        ),
                    ),
                ],
                detected_at=datetime.now(UTC),
            )
        ]

    def _detect_free_riders(
        self,
        circle_id: str,
        circle_features: dict[str, Any],
        member_features: list[dict[str, Any]] | None,
    ) -> list[CircleAnomaly]:
        """Detect free-riders: members with large negative contribution balance.

        A free-rider has received a payout but contributed significantly less than
        expected by this point in the rotation.
        """
        cfg = self._config

        if not member_features:
            # Cannot detect free-riders without member-level data
            return []

        free_riders = []
        for m in member_features:
            contributed = m.get("total_contributed", 0.0)
            expected = m.get("expected_contributed", 0.0)
            has_received = m.get("has_received_payout", False)

            if expected <= 0:
                continue

            balance_ratio = (contributed - expected) / expected

            if has_received and balance_ratio < cfg.free_rider_balance_threshold:
                free_riders.append(
                    {
                        "user_id": m.get("user_id", "unknown"),
                        "balance_ratio": balance_ratio,
                        "contributed": contributed,
                        "expected": expected,
                    }
                )

        if not free_riders:
            return []

        # Severity scales with the number of free-riders and how bad their balance is
        worst_ratio = min(fr["balance_ratio"] for fr in free_riders)
        if len(free_riders) >= 3 or worst_ratio < -0.80:
            severity = AnomalySeverity.HIGH
        elif len(free_riders) >= 2 or worst_ratio < -0.60:
            severity = AnomalySeverity.MEDIUM
        else:
            severity = AnomalySeverity.LOW

        return [
            CircleAnomaly(
                anomaly_id=str(uuid.uuid4()),
                circle_id=circle_id,
                anomaly_type=AnomalyType.FREE_RIDER,
                severity=severity,
                affected_members=[fr["user_id"] for fr in free_riders],
                evidence=[
                    AnomalyEvidence(
                        metric_name="free_rider_count",
                        observed_value=float(len(free_riders)),
                        threshold=1.0,
                        description=(
                            f"{len(free_riders)} member(s) have received payouts but "
                            "contributed significantly less than expected"
                        ),
                    ),
                    AnomalyEvidence(
                        metric_name="worst_balance_ratio",
                        observed_value=round(worst_ratio, 4),
                        threshold=cfg.free_rider_balance_threshold,
                        description=(
                            f"Worst contribution balance: {worst_ratio:.0%} of expected "
                            "(negative means under-contribution)"
                        ),
                    ),
                ],
                detected_at=datetime.now(UTC),
            )
        ]

    def _detect_behavioral_shift(
        self,
        circle_id: str,
        circle_features: dict[str, Any],
        member_features: list[dict[str, Any]] | None,
    ) -> list[CircleAnomaly]:
        """Detect sudden behavioral changes deviating from circle baseline.

        Establishes baselines over the first few cycles and flags when any
        metric deviates significantly (configurable Z-score threshold).
        """
        cfg = self._config

        cycles_completed = int(circle_features.get("cycles_completed", 0))
        if cycles_completed < cfg.behavioral_min_cycles:
            return []

        anomalies: list[CircleAnomaly] = []

        # Check circle-wide behavioral shifts
        metrics_to_check = [
            ("avg_payment_timing_zscore", "payment timing"),
            ("amount_consistency_zscore", "payment amount consistency"),
            ("activity_level_zscore", "member activity level"),
        ]

        shifted_metrics: list[AnomalyEvidence] = []
        for metric_key, metric_label in metrics_to_check:
            zscore = circle_features.get(metric_key, 0.0)
            if abs(zscore) >= cfg.behavioral_zscore_threshold:
                shifted_metrics.append(
                    AnomalyEvidence(
                        metric_name=metric_key,
                        observed_value=round(zscore, 2),
                        threshold=cfg.behavioral_zscore_threshold,
                        description=(
                            f"Circle-wide {metric_label} has shifted "
                            f"significantly (Z-score: {zscore:.2f}, "
                            f"threshold: ±{cfg.behavioral_zscore_threshold})"
                        ),
                    )
                )

        # Also check individual member shifts if available
        affected_members: list[str] = []
        if member_features:
            for m in member_features:
                member_zscore = m.get("behavior_change_zscore", 0.0)
                if abs(member_zscore) >= cfg.behavioral_zscore_threshold:
                    affected_members.append(m.get("user_id", "unknown"))

        if not shifted_metrics and not affected_members:
            return []

        # Determine if this is a circle-wide or individual shift
        total_members = int(circle_features.get("member_count_current", 1))
        is_circle_wide = len(affected_members) >= total_members * 0.5 or len(shifted_metrics) > 0

        if is_circle_wide and len(shifted_metrics) >= 2:
            severity = AnomalySeverity.HIGH
        elif is_circle_wide or len(affected_members) >= 3:
            severity = AnomalySeverity.MEDIUM
        else:
            severity = AnomalySeverity.LOW

        evidence = shifted_metrics.copy()
        if affected_members:
            evidence.append(
                AnomalyEvidence(
                    metric_name="members_with_behavioral_shift",
                    observed_value=float(len(affected_members)),
                    threshold=1.0,
                    description=(
                        f"{len(affected_members)} member(s) show significant behavioral change"
                    ),
                )
            )

        anomalies.append(
            CircleAnomaly(
                anomaly_id=str(uuid.uuid4()),
                circle_id=circle_id,
                anomaly_type=AnomalyType.BEHAVIORAL_SHIFT,
                severity=severity,
                affected_members=affected_members,
                evidence=evidence,
                detected_at=datetime.now(UTC),
            )
        )

        return anomalies
