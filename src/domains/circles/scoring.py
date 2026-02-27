"""Circle health scoring engine.

Multi-dimensional weighted scoring model that produces a 0-100 health score
from circle features retrieved via the feature store. Each dimension
(contribution reliability, membership stability, financial progress, trust
& integrity) produces a 0-100 sub-score, and the composite health score is
their weighted combination.
"""

from datetime import UTC, datetime
from typing import Any

import structlog

from .config import CircleHealthConfig, default_config
from .models import (
    CircleHealthScore,
    DimensionScore,
    HealthTier,
    TrendDirection,
)

logger = structlog.get_logger()


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _linear_map(
    value: float,
    input_floor: float,
    input_ceil: float,
    out_min: float = 0.0,
    out_max: float = 100.0,
) -> float:
    """Linearly map value from [input_floor, input_ceil] to [out_min, out_max].

    Values below floor map to out_min, above ceil map to out_max.
    Handles inverted output ranges (out_min > out_max) correctly.
    """
    if input_ceil <= input_floor:
        return out_max if value >= input_ceil else out_min
    ratio = (value - input_floor) / (input_ceil - input_floor)
    raw = out_min + ratio * (out_max - out_min)
    lo, hi = min(out_min, out_max), max(out_min, out_max)
    return _clamp(raw, lo, hi)


class CircleHealthScorer:
    """Orchestrates multi-dimensional health scoring for a circle."""

    def __init__(self, config: CircleHealthConfig | None = None) -> None:
        self._config = config or default_config

    def score(self, circle_id: str, features: dict[str, Any]) -> CircleHealthScore:
        """Compute health score from circle features.

        Args:
            circle_id: The circle identifier.
            features: Dict of feature name -> value from the feature store.

        Returns:
            CircleHealthScore with composite score, dimension breakdown, and tier.
        """
        cfg = self._config

        # Compute each dimension
        contribution_dim = self._score_contribution_reliability(features)
        membership_dim = self._score_membership_stability(features)
        financial_dim = self._score_financial_progress(features)
        trust_dim = self._score_trust_integrity(features)

        # Weighted composite
        composite = (
            contribution_dim.score * cfg.contribution.weight
            + membership_dim.score * cfg.membership.weight
            + financial_dim.score * cfg.financial.weight
            + trust_dim.score * cfg.trust.weight
        )
        composite = _clamp(composite)

        # Determine tier from score
        health_tier = self._score_to_tier(composite)

        # Determine confidence based on data availability
        confidence = self._compute_confidence(features)

        # Determine trend
        trend = self._compute_trend(features)

        score = CircleHealthScore(
            circle_id=circle_id,
            health_score=round(composite, 2),
            health_tier=health_tier,
            dimension_scores={
                "contribution_reliability": contribution_dim,
                "membership_stability": membership_dim,
                "financial_progress": financial_dim,
                "trust_integrity": trust_dim,
            },
            trend=trend,
            confidence=confidence,
            last_updated=datetime.now(UTC),
            scoring_version=cfg.scoring_version,
        )

        logger.info(
            "circle_health_scored",
            circle_id=circle_id,
            health_score=score.health_score,
            health_tier=score.health_tier.value,
            trend=score.trend.value,
            confidence=score.confidence,
        )

        return score

    def _score_contribution_reliability(self, features: dict[str, Any]) -> DimensionScore:
        """Dimension 1: Contribution Reliability (weight: configurable, default 0.35).

        The most important signal. Combines on-time rate, lateness penalty,
        streak bonus, and missed contribution step penalties.
        """
        cfg = self._config.contribution
        factors: list[str] = []

        on_time_rate = features.get("on_time_payment_rate", 1.0)
        avg_days_late = features.get("avg_days_late", 0.0)
        streak = features.get("consecutive_on_time_streak", 0)
        missed_count = features.get("missed_contribution_count", 0)

        # 1. On-time rate: linear from [floor, 1.0] -> [0, 100]
        rate_score = _linear_map(on_time_rate, cfg.on_time_rate_floor, 1.0)
        if on_time_rate >= 0.95:
            factors.append(f"Excellent on-time payment rate ({on_time_rate:.0%})")
        elif on_time_rate < cfg.on_time_rate_floor:
            factors.append(
                f"On-time payment rate critically low ({on_time_rate:.0%}, "
                f"below {cfg.on_time_rate_floor:.0%} threshold)"
            )
        elif on_time_rate < 0.85:
            factors.append(f"On-time payment rate concerning ({on_time_rate:.0%})")

        # 2. Late days penalty: proportional reduction
        if avg_days_late > 0:
            late_penalty_ratio = min(avg_days_late / cfg.late_days_max_penalty, 1.0)
            late_penalty = late_penalty_ratio * 30  # max 30-point penalty
            rate_score -= late_penalty
            if avg_days_late <= 2:
                factors.append(
                    f"Minor lateness (avg {avg_days_late:.1f} days) — "
                    "culturally acceptable for sou-sou circles"
                )
            else:
                factors.append(f"Average payment lateness: {avg_days_late:.1f} days")

        # 3. Streak bonus
        if streak > cfg.streak_bonus_threshold:
            bonus = min(
                (streak - cfg.streak_bonus_threshold) * 2.0,
                cfg.streak_bonus_max,
            )
            rate_score += bonus
            factors.append(f"Positive momentum: {streak} consecutive on-time payments")

        # 4. Missed contribution step penalties
        if missed_count > 0:
            penalty = 0.0
            if missed_count >= 1:
                penalty += cfg.missed_penalty_first
            if missed_count >= 2:
                penalty += cfg.missed_penalty_second
            if missed_count >= 3:
                penalty += cfg.missed_penalty_third_plus * (missed_count - 2)
            rate_score -= penalty
            factors.append(
                f"{missed_count} missed contribution(s) — "
                "each miss erodes trust among circle members"
            )

        final_score = _clamp(rate_score)

        return DimensionScore(
            dimension_name="contribution_reliability",
            score=round(final_score, 2),
            weight=cfg.weight,
            contributing_factors=factors,
        )

    def _score_membership_stability(self, features: dict[str, Any]) -> DimensionScore:
        """Dimension 2: Membership Stability (weight: configurable, default 0.25).

        A circle losing members is dying. Combines drop rate, size shrinkage,
        and member tenure.
        """
        cfg = self._config.membership
        factors: list[str] = []

        drop_rate = features.get("member_drop_rate", 0.0)
        current_count = features.get("member_count_current", 0)
        original_count = features.get("member_count_original", current_count)
        avg_tenure = features.get("avg_member_tenure_days", 0.0)

        # 1. Drop rate: 0% = 100, >=critical = 0
        drop_score = _linear_map(drop_rate, 0.0, cfg.critical_drop_rate, 100.0, 0.0)
        if drop_rate == 0:
            factors.append("No members have left the circle")
        elif drop_rate >= cfg.critical_drop_rate:
            factors.append(
                f"Critical member dropout rate ({drop_rate:.0%}) — "
                "circle may not survive"
            )
        elif drop_rate > 0.10:
            factors.append(f"Elevated member dropout rate ({drop_rate:.0%})")

        # 2. Size shrinkage
        if original_count > 0:
            size_ratio = current_count / original_count
            if size_ratio < cfg.shrinkage_critical_ratio:
                drop_score *= 0.3  # severe penalty
                factors.append(
                    f"Circle has shrunk to {current_count}/{original_count} members — "
                    "below critical threshold"
                )
            elif size_ratio < cfg.shrinkage_warning_ratio:
                drop_score *= 0.7  # moderate penalty
                factors.append(
                    f"Circle membership declining ({current_count}/{original_count})"
                )

        # 3. Tenure bonus
        if avg_tenure >= cfg.tenure_good_days:
            bonus = cfg.tenure_bonus_max
            drop_score += bonus
            factors.append(
                f"Strong member relationships (avg tenure: {avg_tenure:.0f} days)"
            )
        elif avg_tenure > 0:
            bonus = (avg_tenure / cfg.tenure_good_days) * cfg.tenure_bonus_max
            drop_score += bonus

        final_score = _clamp(drop_score)

        return DimensionScore(
            dimension_name="membership_stability",
            score=round(final_score, 2),
            weight=cfg.weight,
            contributing_factors=factors,
        )

    def _score_financial_progress(self, features: dict[str, Any]) -> DimensionScore:
        """Dimension 3: Financial Progress (weight: configurable, default 0.25).

        Is the circle on track to complete its rotation? Combines collection
        ratio, payout completion rate, and trajectory.
        """
        cfg = self._config.financial
        factors: list[str] = []

        collection_ratio = features.get("collection_ratio", 1.0)
        payout_rate = features.get("payout_completion_rate", 1.0)
        late_trend = features.get("late_payment_trend", 0.0)  # positive = worsening

        # 1. Collection ratio: [floor, 1.0] -> [0, 100]
        coll_score = _linear_map(collection_ratio, cfg.collection_ratio_floor, 1.0)
        if collection_ratio >= 0.95:
            factors.append(
                f"Collection on track ({collection_ratio:.0%} of expected)"
            )
        elif collection_ratio < cfg.collection_ratio_floor:
            factors.append(
                f"Collection critically behind ({collection_ratio:.0%} of expected)"
            )
        elif collection_ratio < 0.85:
            factors.append(f"Collection falling behind ({collection_ratio:.0%} of expected)")

        # 2. Payout completion rate: [floor, 1.0] -> [0, 100]
        payout_score = _linear_map(payout_rate, cfg.payout_rate_floor, 1.0)
        if payout_rate >= 0.95:
            factors.append("All scheduled payouts completed on time")
        elif payout_rate < cfg.payout_rate_floor:
            factors.append(
                f"Payout completion critically low ({payout_rate:.0%})"
            )

        # 3. Trajectory: late_payment_trend > 0 means worsening
        # Map to 0-100 where 0 trend = 100 score, strong negative trend = 0
        if late_trend <= 0:
            trajectory_score = 100.0  # stable or improving
            if late_trend < -0.1:
                factors.append("Late payment trend improving")
        elif late_trend < 0.2:
            trajectory_score = 70.0
            factors.append("Slight increase in late payments")
        elif late_trend < 0.5:
            trajectory_score = 40.0
            factors.append("Late payment trend worsening")
        else:
            trajectory_score = 10.0
            factors.append("Late payment trend sharply worsening")

        # Weighted sub-dimensions
        combined = (
            coll_score * cfg.collection_sub_weight
            + payout_score * cfg.payout_sub_weight
            + trajectory_score * cfg.trajectory_sub_weight
        )

        final_score = _clamp(combined)

        return DimensionScore(
            dimension_name="financial_progress",
            score=round(final_score, 2),
            weight=cfg.weight,
            contributing_factors=factors,
        )

    def _score_trust_integrity(self, features: dict[str, Any]) -> DimensionScore:
        """Dimension 4: Trust & Integrity (weight: configurable, default 0.15).

        Detects manipulation and collusion. Combines coordinated behavior
        score, large missed amounts, and post-payout disengagement.
        """
        cfg = self._config.trust
        factors: list[str] = []

        coord_score = features.get("coordinated_behavior_score", 0.0)
        largest_missed = features.get("largest_single_missed_amount", 0.0)
        contribution_amount = features.get("contribution_amount", 100.0)
        post_payout_disengagement = features.get("post_payout_disengagement_rate", 0.0)

        # Start at 100 and deduct
        trust_score = 100.0

        # 1. Coordinated behavior: higher = more suspicious
        if coord_score > cfg.coordinated_threshold:
            ratio = (coord_score - cfg.coordinated_threshold) / (1.0 - cfg.coordinated_threshold)
            penalty = min(ratio * 50, 50)
            trust_score -= penalty
            factors.append(
                f"Elevated coordinated behavior detected (score: {coord_score:.2f}) — "
                "may indicate collusion"
            )
        elif coord_score > 0.3:
            penalty = (coord_score / cfg.coordinated_threshold) * 15
            trust_score -= penalty
            factors.append(f"Moderate coordination patterns (score: {coord_score:.2f})")

        # 2. Large single missed amount relative to contribution
        if contribution_amount > 0 and largest_missed > 0:
            missed_ratio = largest_missed / contribution_amount
            if missed_ratio > cfg.missed_amount_ratio_threshold:
                penalty = min(missed_ratio / cfg.missed_amount_ratio_threshold * 20, 30)
                trust_score -= penalty
                factors.append(
                    f"Large single missed amount (${largest_missed:.0f}) "
                    f"is {missed_ratio:.1f}x the typical contribution — "
                    "possible payout-and-abandon pattern"
                )

        # 3. Post-payout disengagement
        if post_payout_disengagement > cfg.disengagement_threshold:
            penalty = min(
                (post_payout_disengagement - cfg.disengagement_threshold)
                / (1.0 - cfg.disengagement_threshold)
                * 40,
                40,
            )
            trust_score -= penalty
            factors.append(
                f"Post-payout disengagement detected ({post_payout_disengagement:.0%} "
                "of members show reduced participation after receiving their payout)"
            )

        final_score = _clamp(trust_score)

        return DimensionScore(
            dimension_name="trust_integrity",
            score=round(final_score, 2),
            weight=cfg.weight,
            contributing_factors=factors,
        )

    def _score_to_tier(self, score: float) -> HealthTier:
        """Map composite score to health tier."""
        if score >= 70:
            return HealthTier.HEALTHY
        elif score >= 40:
            return HealthTier.AT_RISK
        else:
            return HealthTier.CRITICAL

    def _compute_confidence(self, features: dict[str, Any]) -> float:
        """Compute confidence based on data availability.

        A brand-new circle with 1 cycle of data gets low confidence.
        More cycles = more confidence.
        """
        cycles_completed = features.get("cycles_completed", 0)
        member_count = features.get("member_count_current", 0)

        # Base confidence scales with cycles: 1 cycle = 0.3, 3+ = 0.7, 6+ = 1.0
        if cycles_completed <= 0:
            cycle_conf = 0.2
        elif cycles_completed <= 2:
            cycle_conf = 0.3 + (cycles_completed - 1) * 0.2
        elif cycles_completed <= 5:
            cycle_conf = 0.5 + (cycles_completed - 2) * 0.1
        else:
            cycle_conf = min(0.8 + (cycles_completed - 5) * 0.05, 1.0)

        # Small circles have lower confidence (2 members = 0.5 multiplier)
        if member_count <= 2:
            size_factor = 0.5
        elif member_count <= 4:
            size_factor = 0.7
        else:
            size_factor = 1.0

        return round(min(cycle_conf * size_factor, 1.0), 2)

    def _compute_trend(self, features: dict[str, Any]) -> TrendDirection:
        """Compute trend from historical scores.

        Compares current score against 1-cycle-ago and 3-cycles-ago scores.
        """
        cfg = self._config.trend
        score_1_cycle_ago = features.get("health_score_1_cycle_ago")
        score_3_cycles_ago = features.get("health_score_3_cycles_ago")
        current_score = features.get("current_health_score")

        if current_score is None or (score_1_cycle_ago is None and score_3_cycles_ago is None):
            return TrendDirection.STABLE

        delta = 0.0
        total_weight = 0.0

        if score_1_cycle_ago is not None:
            delta += (current_score - score_1_cycle_ago) * cfg.recent_weight
            total_weight += cfg.recent_weight

        if score_3_cycles_ago is not None:
            delta += (current_score - score_3_cycles_ago) * cfg.historical_weight
            total_weight += cfg.historical_weight

        if total_weight > 0:
            delta /= total_weight

        if delta > cfg.improving_threshold:
            return TrendDirection.IMPROVING
        elif delta < cfg.deteriorating_threshold:
            return TrendDirection.DETERIORATING
        else:
            return TrendDirection.STABLE
