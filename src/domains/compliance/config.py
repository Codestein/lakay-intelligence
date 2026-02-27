"""Compliance monitoring configuration with regulatory citations.

Every threshold, window, and multiplier is configurable. Each default is
documented with the regulatory basis (CFR section, FinCEN guidance) that
justifies its value.

References:
- 31 CFR § 1010.311 — Filing obligations for currency transaction reports
- 31 CFR § 1010.320 — Reports relating to currency in excess of $10,000
- 31 USC § 5324 — Structuring transactions to evade reporting requirements
- 31 CFR § 1022.320 — SAR filing requirements for MSBs
- FinCEN Advisory FIN-2014-A007 — BSA/AML obligations for MSBs
- FATF Recommendations (2012, updated 2023) — Risk-based approach guidance
"""

import os
from dataclasses import dataclass, field


@dataclass
class CTRThresholdConfig:
    """Rule M-1: CTR threshold monitoring.

    Regulatory basis: 31 CFR § 1010.311 requires filing a CTR for cash
    transactions exceeding $10,000 in a single business day, including
    aggregated transactions by the same person.
    """

    enabled: bool = True
    priority_override: str | None = None

    # The federal reporting threshold — 31 CFR § 1010.311
    ctr_threshold: float = 10_000.0

    # Pre-threshold warning levels.
    # Rationale: 80% and 90% of $10,000 threshold per FinCEN guidance on
    # CTR aggregation monitoring to allow compliance officers to prepare
    # filing before the threshold is crossed.
    pre_threshold_warnings: list[float] = field(
        default_factory=lambda: [8_000.0, 9_000.0]
    )

    # Cash-equivalent transaction types for Trebanx
    cash_equivalent_types: list[str] = field(
        default_factory=lambda: [
            "circle_contribution",
            "circle_payout",
            "remittance_send",
            "remittance_receive",
        ]
    )


@dataclass
class RoundAmountConfig:
    """Rule M-2: Suspicious round-amount patterns.

    Regulatory basis: FinCEN Advisory FIN-2014-A007 — patterns of
    transactions at or just below reporting thresholds may indicate
    structuring (31 USC § 5324).
    """

    enabled: bool = True
    priority_override: str | None = None

    # Amounts at or just below common thresholds that are suspicious
    suspicious_amounts: list[float] = field(
        default_factory=lambda: [9_999.0, 4_999.0, 2_999.0]
    )
    # Tolerance band: flag amounts within this range below the threshold
    # e.g., $9,990-$9,999 when tolerance is $10
    tolerance: float = 10.0

    # Proportion of round-amount transactions that is statistically unusual.
    # Leverages round_amount_ratio_30d from Feast fraud feature set.
    round_amount_ratio_threshold: float = 0.60


@dataclass
class RapidMovementConfig:
    """Rule M-3: Rapid movement patterns (pass-through / layering).

    Regulatory basis: 31 CFR § 1022.320(a)(2) — transactions designed to
    facilitate criminal activity. Rapid fund movement is a classic layering
    typology identified in FinCEN guidance on MSB AML programs.
    """

    enabled: bool = True
    priority_override: str | None = None

    # Time window: funds received and sent within N hours
    time_window_hours: int = 24

    # Transfer ratio: outbound amount >= X% of received amount
    transfer_ratio_threshold: float = 0.80

    # Minimum amount to consider — very small pass-throughs may be benign
    min_amount: float = 1_000.0


@dataclass
class UnusualVolumeConfig:
    """Rule M-4: Unusual transaction volume.

    Regulatory basis: FinCEN Advisory FIN-2014-A007 — MSBs must monitor for
    transaction volumes that significantly deviate from a customer's
    established baseline. 31 CFR § 1022.210(d) — AML program requirement
    to identify unusual activity.
    """

    enabled: bool = True
    priority_override: str | None = None

    # Multiplier: flag when volume exceeds N times the user's 30-day mean.
    # Leverages tx_count_24h, tx_cumulative_7d, tx_amount_mean_30d,
    # tx_amount_std_30d from Feast fraud feature set.
    volume_multiplier_threshold: float = 3.0

    # Minimum baseline transactions before the rule activates
    # (avoid flagging new users with sparse history)
    min_baseline_transactions: int = 5

    # Z-score approach: flag if current amount > mean + N*std
    zscore_threshold: float = 3.0


@dataclass
class GeographicRiskConfig:
    """Rule M-5: Geographic risk indicators.

    Regulatory basis: 31 CFR § 1022.210(d)(4) — Enhanced monitoring for
    transactions involving high-risk jurisdictions. FATF Recommendations
    (Recommendation 19) — higher-risk countries and territories.
    """

    enabled: bool = True
    priority_override: str | None = None

    # FATF grey list / black list countries (as of 2024 — must be updated regularly).
    # Source: FATF High-Risk Jurisdictions subject to a Call for Action
    # and Jurisdictions under Increased Monitoring.
    high_risk_countries: list[str] = field(
        default_factory=lambda: [
            "IR",  # Iran (FATF blacklist)
            "KP",  # North Korea (FATF blacklist)
            "MM",  # Myanmar (FATF blacklist)
            "SY",  # Syria
            "YE",  # Yemen
            "SO",  # Somalia
            "LY",  # Libya
            "AF",  # Afghanistan
        ]
    )

    # Profile countries: expected transaction origins for Trebanx users.
    # US→Haiti corridor is the primary use case.
    expected_corridor_countries: list[str] = field(
        default_factory=lambda: ["US", "HT"]
    )

    # Flag transactions from countries not in the user's profile
    flag_unexpected_origin: bool = True


@dataclass
class CircleComplianceConfig:
    """Rule M-6: Circle-based compliance concerns.

    Regulatory basis: 31 CFR § 1010.311 — CTR aggregation applies to
    aggregate member activity that constitutes a single business relationship.
    FinCEN guidance on informal value transfer systems (IVTS) — sou-sou
    circles may be classified as IVTS and require monitoring.
    """

    enabled: bool = True
    priority_override: str | None = None

    # Aggregate circle contributions approaching CTR threshold
    circle_aggregate_warning_pct: float = 0.80  # 80% of CTR threshold

    # Flag circles with members under existing compliance alerts
    flag_circles_with_alerted_members: bool = True

    # Maximum circle payout amount before enhanced monitoring
    payout_monitoring_threshold: float = 8_000.0


@dataclass
class StructuringDetectionConfig:
    """Structuring detection thresholds (Task 8.3).

    Regulatory basis: 31 USC § 5324 — Structuring transactions to evade
    reporting requirements is a federal crime. 31 CFR § 1010.311 and
    1010.313 define the reporting obligations being evaded.
    """

    enabled: bool = True
    priority_override: str | None = "elevated"

    # ---- Micro-structuring (within a day) ----
    # 31 USC § 5324(a)(3) — structuring to evade CTR
    micro_min_transactions: int = 3  # same-recipient threshold
    micro_min_total_transactions: int = 5  # any-recipient threshold
    micro_cumulative_proximity_pct: float = 0.80  # within 20% of $10K = 80%+

    # ---- Slow structuring (across days) ----
    slow_lookback_days: int = 30
    slow_min_transactions: int = 3
    slow_amount_range_low: float = 3_000.0
    slow_amount_range_high: float = 9_999.0
    slow_cumulative_threshold: float = 10_000.0

    # ---- Fan-out structuring ----
    fanout_min_recipients: int = 3
    fanout_rolling_window_hours: int = 48
    fanout_cumulative_threshold: float = 10_000.0

    # ---- Funnel structuring ----
    funnel_min_senders: int = 3
    funnel_rolling_window_hours: int = 48
    funnel_cumulative_threshold: float = 10_000.0

    # ---- Confidence thresholds ----
    # Structuring confidence > 0.7 → recommend SAR filing
    sar_confidence_threshold: float = 0.70
    # Structuring confidence 0.4–0.7 → recommend enhanced monitoring
    enhanced_monitoring_confidence_threshold: float = 0.40


@dataclass
class CustomerRiskScoringConfig:
    """Customer risk scoring thresholds (Task 8.5).

    Regulatory basis: 31 CFR § 1022.210(d) — Risk-based AML program
    requirement. FinCEN CDD Rule (31 CFR § 1010.230) — Customer Due
    Diligence requirements for financial institutions.
    """

    enabled: bool = True

    # Risk level thresholds (0.0–1.0 scale)
    low_max: float = 0.30
    medium_max: float = 0.60
    high_max: float = 0.80
    # Above high_max = prohibited

    # Category weights (must sum to 1.0)
    transaction_weight: float = 0.30
    geographic_weight: float = 0.25
    behavioral_weight: float = 0.25
    circle_weight: float = 0.20

    # Review frequency by risk level (days)
    low_review_days: int = 365
    medium_review_days: int = 90
    high_review_days: int = 30

    # Account age thresholds for risk elevation
    new_account_days: int = 90  # accounts younger than this get elevated baseline
    new_account_risk_boost: float = 0.10


@dataclass
class CorridorOverrides:
    """Per-corridor threshold overrides.

    The Haiti corridor has specific characteristics — regular, moderate
    remittances are normal diaspora behavior, not suspicious. Thresholds
    must be calibrated accordingly.
    """

    corridor: str = "US-HT"

    # Higher tolerance for regular small remittances in the Haiti corridor.
    # A user consistently sending $500/week to family is normal behavior.
    regular_remittance_max_amount: float = 2_000.0
    regular_remittance_min_frequency_days: int = 5
    regular_remittance_max_frequency_days: int = 35
    regular_remittance_history_months: int = 6


@dataclass
class ComplianceConfig:
    """Top-level compliance configuration.

    All monitoring rules, thresholds, and detection parameters are
    configurable here. Defaults are documented with regulatory citations.
    """

    ctr: CTRThresholdConfig = field(default_factory=CTRThresholdConfig)
    round_amount: RoundAmountConfig = field(default_factory=RoundAmountConfig)
    rapid_movement: RapidMovementConfig = field(default_factory=RapidMovementConfig)
    unusual_volume: UnusualVolumeConfig = field(default_factory=UnusualVolumeConfig)
    geographic: GeographicRiskConfig = field(default_factory=GeographicRiskConfig)
    circle: CircleComplianceConfig = field(default_factory=CircleComplianceConfig)
    structuring: StructuringDetectionConfig = field(
        default_factory=StructuringDetectionConfig
    )
    risk_scoring: CustomerRiskScoringConfig = field(
        default_factory=CustomerRiskScoringConfig
    )
    corridor_overrides: list[CorridorOverrides] = field(
        default_factory=lambda: [CorridorOverrides()]
    )

    # Kafka topics
    alerts_topic: str = "lakay.compliance.alerts"
    edd_triggers_topic: str = "lakay.compliance.edd-triggers"

    @classmethod
    def from_env(cls) -> "ComplianceConfig":
        """Load config with env var overrides (COMPLIANCE_ prefix)."""
        config = cls()

        # CTR overrides
        if v := os.getenv("COMPLIANCE_CTR_THRESHOLD"):
            config.ctr.ctr_threshold = float(v)
        if v := os.getenv("COMPLIANCE_CTR_ENABLED"):
            config.ctr.enabled = v.lower() in ("true", "1", "yes")

        # Rapid movement overrides
        if v := os.getenv("COMPLIANCE_RAPID_MOVEMENT_HOURS"):
            config.rapid_movement.time_window_hours = int(v)
        if v := os.getenv("COMPLIANCE_RAPID_MOVEMENT_RATIO"):
            config.rapid_movement.transfer_ratio_threshold = float(v)

        # Volume overrides
        if v := os.getenv("COMPLIANCE_VOLUME_MULTIPLIER"):
            config.unusual_volume.volume_multiplier_threshold = float(v)

        # Structuring overrides
        if v := os.getenv("COMPLIANCE_STRUCTURING_LOOKBACK_DAYS"):
            config.structuring.slow_lookback_days = int(v)
        if v := os.getenv("COMPLIANCE_SAR_CONFIDENCE"):
            config.structuring.sar_confidence_threshold = float(v)

        # Risk scoring overrides
        if v := os.getenv("COMPLIANCE_RISK_LOW_MAX"):
            config.risk_scoring.low_max = float(v)
        if v := os.getenv("COMPLIANCE_RISK_HIGH_MAX"):
            config.risk_scoring.high_max = float(v)

        # Kafka topic overrides
        if v := os.getenv("COMPLIANCE_ALERTS_TOPIC"):
            config.alerts_topic = v
        if v := os.getenv("COMPLIANCE_EDD_TRIGGERS_TOPIC"):
            config.edd_triggers_topic = v

        return config


# Module-level default instance
default_config = ComplianceConfig()
