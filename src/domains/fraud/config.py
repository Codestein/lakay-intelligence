"""Fraud detection configuration with sensible defaults."""

import os
from dataclasses import dataclass, field


@dataclass
class VelocityThresholds:
    login_count_window_minutes: int = 10
    login_count_max: int = 5
    txn_count_1h_max: int = 10
    txn_count_24h_max: int = 20
    txn_amount_24h_max: float = 10_000.0
    circle_join_window_hours: int = 24
    circle_join_max: int = 3


@dataclass
class AmountThresholds:
    large_txn_min: float = 3_000.0
    cumulative_24h_max: float = 8_000.0
    cumulative_7d_max: float = 25_000.0
    cumulative_30d_max: float = 50_000.0
    baseline_zscore_threshold: float = 2.5
    ctr_single_threshold: float = 8_000.0
    ctr_daily_threshold: float = 9_000.0


@dataclass
class GeoThresholds:
    impossible_travel_speed_kmh: float = 900.0
    home_countries: tuple[str, ...] = ("US", "HT")


@dataclass
class PatternThresholds:
    duplicate_tolerance_pct: float = 0.05
    duplicate_window_minutes: int = 10
    structuring_3k_range: tuple[float, float] = (2_800.0, 2_999.0)
    structuring_10k_range: tuple[float, float] = (9_500.0, 9_999.0)
    structuring_window_hours: int = 24
    round_amount_pct_threshold: float = 0.60
    round_amount_lookback_days: int = 30
    temporal_stddev_threshold_seconds: float = 300.0
    temporal_min_txns: int = 4
    temporal_lookback_days: int = 7


@dataclass
class ScoringWeights:
    velocity_cap: float = 0.35
    amount_cap: float = 0.30
    geo_cap: float = 0.25
    patterns_cap: float = 0.30


@dataclass
class AlertSettings:
    high_threshold: float = 0.6
    critical_threshold: float = 0.8
    suppression_window_seconds: int = 3600
    kafka_topic: str = "lakay.fraud.alerts"


@dataclass
class FraudConfig:
    velocity: VelocityThresholds = field(default_factory=VelocityThresholds)
    amount: AmountThresholds = field(default_factory=AmountThresholds)
    geo: GeoThresholds = field(default_factory=GeoThresholds)
    patterns: PatternThresholds = field(default_factory=PatternThresholds)
    scoring: ScoringWeights = field(default_factory=ScoringWeights)
    alerts: AlertSettings = field(default_factory=AlertSettings)

    @classmethod
    def from_env(cls) -> "FraudConfig":
        """Load config with env var overrides. Env vars use FRAUD_ prefix."""
        config = cls()

        # Velocity overrides
        if v := os.getenv("FRAUD_LOGIN_COUNT_MAX"):
            config.velocity.login_count_max = int(v)
        if v := os.getenv("FRAUD_TXN_COUNT_1H_MAX"):
            config.velocity.txn_count_1h_max = int(v)
        if v := os.getenv("FRAUD_TXN_AMOUNT_24H_MAX"):
            config.velocity.txn_amount_24h_max = float(v)

        # Amount overrides
        if v := os.getenv("FRAUD_LARGE_TXN_MIN"):
            config.amount.large_txn_min = float(v)
        if v := os.getenv("FRAUD_CTR_SINGLE_THRESHOLD"):
            config.amount.ctr_single_threshold = float(v)
        if v := os.getenv("FRAUD_CTR_DAILY_THRESHOLD"):
            config.amount.ctr_daily_threshold = float(v)

        # Alert overrides
        if v := os.getenv("FRAUD_HIGH_THRESHOLD"):
            config.alerts.high_threshold = float(v)
        if v := os.getenv("FRAUD_CRITICAL_THRESHOLD"):
            config.alerts.critical_threshold = float(v)
        if v := os.getenv("FRAUD_ALERT_KAFKA_TOPIC"):
            config.alerts.kafka_topic = v

        return config


# Module-level default instance
default_config = FraudConfig()
