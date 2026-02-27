"""Circle health scoring configuration with sensible defaults.

All dimension weights and scoring curves are configurable. Defaults are
documented with rationale drawn from real sou-sou circle dynamics.
"""

import os
from dataclasses import dataclass, field


@dataclass
class ContributionReliabilityConfig:
    """Dimension 1 — Contribution Reliability (default weight: 0.35).

    This is the single most important signal. In a real sou-sou, if members
    stop paying, the circle dies — everything else is secondary. A circle with
    perfect on-time payments can survive member turnover; one where half the
    members are late cannot.
    """

    weight: float = 0.35

    # on_time_payment_rate mapping: linear from [floor, 1.0] -> [0, 100]
    # Below floor => score 0.  100% on-time => score 100.
    on_time_rate_floor: float = 0.70  # below this, score is 0

    # avg_days_late penalty: each day late reduces score proportionally
    # 0 days = no penalty, >=max_days = full penalty (score component = 0)
    late_days_max_penalty: int = 7

    # consecutive_on_time_streak bonus: bonus points added for long streaks
    streak_bonus_threshold: int = 3  # streaks above this get a bonus
    streak_bonus_max: float = 10.0  # max bonus points (added to raw score before capping)

    # missed_contribution_count step penalties (cumulative deductions from 100)
    missed_penalty_first: float = 10.0  # 1st miss
    missed_penalty_second: float = 20.0  # 2nd miss
    missed_penalty_third_plus: float = 30.0  # 3rd+ miss each


@dataclass
class MembershipStabilityConfig:
    """Dimension 2 — Membership Stability (default weight: 0.25).

    A circle bleeding members is dying. Member drops destroy trust and reduce
    the payout pool, making remaining members less motivated to continue.
    """

    weight: float = 0.25

    # member_drop_rate mapping: 0% = 100 score, >=critical_rate = 0 score
    critical_drop_rate: float = 0.30

    # size_shrinkage: if current/original < threshold, heavy penalty
    shrinkage_warning_ratio: float = 0.75  # below this ratio, start penalizing
    shrinkage_critical_ratio: float = 0.50  # below this, score component = 0

    # avg_member_tenure_days bonus: longer tenure = more stable
    tenure_good_days: int = 90  # above this, full tenure bonus
    tenure_bonus_max: float = 10.0


@dataclass
class FinancialProgressConfig:
    """Dimension 3 — Financial Progress (default weight: 0.25).

    Is the circle on track to complete its full rotation? If the collection
    ratio is falling, the circle may not survive to the end.
    """

    weight: float = 0.25

    # collection_ratio mapping: 1.0 = 100, <=floor = 0
    collection_ratio_floor: float = 0.60

    # payout_completion_rate mapping: 1.0 = 100, <=floor = 0
    payout_rate_floor: float = 0.50

    # Weights within this dimension (must sum to 1.0)
    collection_sub_weight: float = 0.50
    payout_sub_weight: float = 0.30
    trajectory_sub_weight: float = 0.20


@dataclass
class TrustIntegrityConfig:
    """Dimension 4 — Trust & Integrity (default weight: 0.15).

    Detects manipulation and collusion. Lower weight because these are rare
    but high-impact events — a single coordinated fraud can kill a circle.
    """

    weight: float = 0.15

    # coordinated_behavior_score: higher = more suspicious. >threshold = max penalty
    coordinated_threshold: float = 0.70

    # largest_single_missed relative to contribution: ratio above this is suspicious
    missed_amount_ratio_threshold: float = 2.0  # 2x the typical contribution

    # Pattern consistency penalty: post-payout disengagement score (0-1)
    # Above this threshold, start penalizing
    disengagement_threshold: float = 0.30


@dataclass
class TrendConfig:
    """Configuration for trend calculation."""

    # Points change threshold for trend classification
    improving_threshold: float = 5.0  # score up >5 pts = improving
    deteriorating_threshold: float = -5.0  # score down >5 pts = deteriorating
    # Weights for 1-cycle-ago vs 3-cycles-ago comparison
    recent_weight: float = 0.6  # weight for 1-cycle-ago comparison
    historical_weight: float = 0.4  # weight for 3-cycles-ago comparison


@dataclass
class CircleHealthConfig:
    """Top-level circle health scoring configuration.

    All dimension weights must sum to 1.0. Validation is performed at
    construction time.
    """

    contribution: ContributionReliabilityConfig = field(
        default_factory=ContributionReliabilityConfig
    )
    membership: MembershipStabilityConfig = field(default_factory=MembershipStabilityConfig)
    financial: FinancialProgressConfig = field(default_factory=FinancialProgressConfig)
    trust: TrustIntegrityConfig = field(default_factory=TrustIntegrityConfig)
    trend: TrendConfig = field(default_factory=TrendConfig)

    scoring_version: str = "circle-health-v1"

    # Kafka topic for tier change events
    tier_change_topic: str = "lakay.circles.tier-changes"

    def __post_init__(self) -> None:
        total = (
            self.contribution.weight
            + self.membership.weight
            + self.financial.weight
            + self.trust.weight
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Dimension weights must sum to 1.0, got {total:.4f}. "
                f"Contribution={self.contribution.weight}, "
                f"Membership={self.membership.weight}, "
                f"Financial={self.financial.weight}, "
                f"Trust={self.trust.weight}"
            )

    @classmethod
    def from_env(cls) -> "CircleHealthConfig":
        """Load config with environment variable overrides (CIRCLE_ prefix)."""
        config = cls()

        if v := os.getenv("CIRCLE_CONTRIBUTION_WEIGHT"):
            config.contribution.weight = float(v)
        if v := os.getenv("CIRCLE_MEMBERSHIP_WEIGHT"):
            config.membership.weight = float(v)
        if v := os.getenv("CIRCLE_FINANCIAL_WEIGHT"):
            config.financial.weight = float(v)
        if v := os.getenv("CIRCLE_TRUST_WEIGHT"):
            config.trust.weight = float(v)
        if v := os.getenv("CIRCLE_TIER_CHANGE_TOPIC"):
            config.tier_change_topic = v

        # Re-validate after overrides
        config.__post_init__()
        return config


default_config = CircleHealthConfig()
