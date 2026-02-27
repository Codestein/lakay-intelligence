"""Behavioral analytics configuration with sensible defaults.

All thresholds, weights, and parameters for the behavioral profile engine,
anomaly scoring, engagement classification, and ATO detection pipeline.
"""

import os
from dataclasses import dataclass, field


@dataclass
class ProfileConfig:
    """Per-user behavioral profile parameters."""

    # Minimum sessions before profile is considered "active"
    min_sessions_active: int = 10
    # Minimum number of distinct days with sessions
    min_days_active: int = 7
    # Exponential moving average decay rate (alpha).
    # Higher = faster adaptation. 0.1 = slow, 0.3 = fast.
    ema_decay_rate: float = 0.15
    # Days of inactivity before profile becomes "stale"
    staleness_threshold_days: int = 30
    # Tolerance multiplier for stale profiles (wider bands)
    stale_tolerance_multiplier: float = 1.5
    # Tolerance multiplier for building profiles (wider bands)
    building_tolerance_multiplier: float = 2.0
    # Max known devices to track per user
    max_known_devices: int = 20
    # Max known locations to track per user
    max_known_locations: int = 30


@dataclass
class AnomalyWeights:
    """Weights for composite anomaly scoring dimensions."""

    temporal: float = 0.15
    device: float = 0.25
    geographic: float = 0.25
    behavioral: float = 0.25
    engagement: float = 0.10

    def __post_init__(self) -> None:
        total = self.temporal + self.device + self.geographic + self.behavioral + self.engagement
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Anomaly dimension weights must sum to 1.0, got {total:.4f}"
            )


@dataclass
class AnomalyThresholds:
    """Thresholds for anomaly classification."""

    normal_max: float = 0.3
    suspicious_max: float = 0.6
    high_risk_max: float = 0.8
    # Above high_risk_max is "critical"

    # Temporal anomaly: z-score threshold for unusual login hour
    temporal_zscore_high: float = 2.0
    temporal_zscore_critical: float = 3.0

    # Device anomaly: score for new device
    new_device_score: float = 0.5
    # Score boost for cross-platform device switch (e.g., iOS -> Android)
    cross_platform_boost: float = 0.3

    # Geographic anomaly: impossible travel speed (km/h)
    impossible_travel_speed_kmh: float = 900.0
    # US <-> Haiti corridor countries (reduced anomaly for these)
    corridor_countries: tuple[str, ...] = ("US", "HT")
    # Score reduction for corridor travel
    corridor_reduction: float = 0.4

    # Behavioral anomaly: z-score threshold for session duration/actions
    behavioral_zscore_high: float = 2.5
    # Minimum actions per second considered bot-like
    bot_actions_per_second: float = 3.0

    # Engagement anomaly: days since last login to trigger concern
    dormancy_days_warning: int = 14
    dormancy_days_critical: int = 30


@dataclass
class EngagementConfig:
    """Engagement scoring and lifecycle classification parameters."""

    # Lifecycle stage thresholds
    new_max_sessions: int = 5
    new_max_days: int = 14
    onboarding_max_sessions: int = 15
    dormant_days: int = 14
    churned_days: int = 30

    # Engagement score component weights (must sum to 1.0)
    frequency_weight: float = 0.30
    recency_weight: float = 0.25
    streak_weight: float = 0.15
    breadth_weight: float = 0.20
    consistency_weight: float = 0.10

    # Churn risk thresholds
    churn_score_drop_threshold: float = 20.0  # points dropped over window
    churn_window_weeks: int = 3


@dataclass
class ATOConfig:
    """Account takeover detection parameters."""

    # Signal weights for ATO risk scoring
    anomaly_score_weight: float = 0.30
    failed_logins_weight: float = 0.15
    new_device_location_weight: float = 0.20
    sensitive_actions_weight: float = 0.20
    impossible_travel_weight: float = 0.15

    # Correlation multipliers: when multiple signals co-occur
    two_signal_multiplier: float = 1.5
    three_signal_multiplier: float = 2.0

    # ATO risk thresholds
    low_max: float = 0.3
    moderate_max: float = 0.5
    high_max: float = 0.8
    # Above high_max is "critical"

    # Alert deduplication window (seconds) — 24 hours
    alert_dedup_window_seconds: int = 86400

    # Kafka topic for ATO alerts
    kafka_topic: str = "lakay.behavior.ato-alerts"

    # Sensitive actions that indicate potential ATO
    sensitive_actions: tuple[str, ...] = (
        "change_email",
        "change_phone",
        "change_password",
        "add_payment_method",
        "remove_payment_method",
        "initiate_large_transaction",
        "update_security_settings",
        "change_mfa_settings",
    )

    # Failed login thresholds
    failed_logins_10m_warning: int = 3
    failed_logins_1h_warning: int = 5


@dataclass
class BehaviorConfig:
    """Top-level behavioral analytics configuration."""

    profile: ProfileConfig = field(default_factory=ProfileConfig)
    anomaly_weights: AnomalyWeights = field(default_factory=AnomalyWeights)
    anomaly_thresholds: AnomalyThresholds = field(default_factory=AnomalyThresholds)
    engagement: EngagementConfig = field(default_factory=EngagementConfig)
    ato: ATOConfig = field(default_factory=ATOConfig)

    @classmethod
    def from_env(cls) -> "BehaviorConfig":
        """Load config with env var overrides. Env vars use BEHAVIOR_ prefix."""
        config = cls()

        # Profile overrides
        if v := os.getenv("BEHAVIOR_MIN_SESSIONS_ACTIVE"):
            config.profile.min_sessions_active = int(v)
        if v := os.getenv("BEHAVIOR_EMA_DECAY_RATE"):
            config.profile.ema_decay_rate = float(v)
        if v := os.getenv("BEHAVIOR_STALENESS_DAYS"):
            config.profile.staleness_threshold_days = int(v)

        # Anomaly weight overrides
        if v := os.getenv("BEHAVIOR_TEMPORAL_WEIGHT"):
            config.anomaly_weights.temporal = float(v)
        if v := os.getenv("BEHAVIOR_DEVICE_WEIGHT"):
            config.anomaly_weights.device = float(v)
        if v := os.getenv("BEHAVIOR_GEO_WEIGHT"):
            config.anomaly_weights.geographic = float(v)

        # ATO overrides
        if v := os.getenv("BEHAVIOR_ATO_DEDUP_WINDOW"):
            config.ato.alert_dedup_window_seconds = int(v)
        if v := os.getenv("BEHAVIOR_ATO_KAFKA_TOPIC"):
            config.ato.kafka_topic = v

        return config


# Module-level default instance
default_config = BehaviorConfig()
