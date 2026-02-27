"""Centralized model serving configuration.

All serving-related settings live here: model identity, feature schema,
scoring thresholds, reload behavior, and hybrid scoring parameters.
"""

from dataclasses import dataclass, field


@dataclass
class ModelConfig:
    """Identity and loading configuration for the served model."""

    name: str = "fraud-detector-v0.2"
    stage: str = "Production"
    fallback_stage: str = "Staging"
    reload_interval_seconds: int = 300
    prediction_timeout_seconds: float = 1.0


@dataclass
class FeatureSpec:
    """Expected input features for the ML model, used for validation."""

    features: list[str] = field(
        default_factory=lambda: [
            "login_count_10m",
            "login_count_1h",
            "tx_count_1h",
            "tx_count_24h",
            "circle_joins_24h",
            "tx_amount_last",
            "tx_amount_mean_30d",
            "tx_amount_std_30d",
            "tx_amount_zscore",
            "tx_cumulative_24h",
            "tx_cumulative_7d",
            "ctr_proximity_score",
            "distinct_countries_7d",
            "max_travel_speed_24h",
            "duplicate_tx_count_1h",
            "same_recipient_tx_sum_24h",
            "round_amount_ratio_30d",
            "tx_time_regularity_score",
        ]
    )
    feature_types: dict[str, str] = field(
        default_factory=lambda: {
            "login_count_10m": "int",
            "login_count_1h": "int",
            "tx_count_1h": "int",
            "tx_count_24h": "int",
            "circle_joins_24h": "int",
            "tx_amount_last": "float",
            "tx_amount_mean_30d": "float",
            "tx_amount_std_30d": "float",
            "tx_amount_zscore": "float",
            "tx_cumulative_24h": "float",
            "tx_cumulative_7d": "float",
            "ctr_proximity_score": "float",
            "distinct_countries_7d": "int",
            "max_travel_speed_24h": "float",
            "duplicate_tx_count_1h": "int",
            "same_recipient_tx_sum_24h": "float",
            "round_amount_ratio_30d": "float",
            "tx_time_regularity_score": "float",
        }
    )


@dataclass
class ScoringThresholds:
    """Scoring thresholds for ML-based scoring, can override Phase 3 rule defaults."""

    low_max: float = 0.3
    medium_max: float = 0.6
    high_max: float = 0.8
    # Above high_max is critical


@dataclass
class HybridScoringConfig:
    """Configuration for combining rule-based and ML model scores.

    Strategy options:
    - 'weighted_average': score = w_rules * rule_score + w_ml * ml_score
    - 'max': score = max(rule_score, ml_score)
    - 'ensemble_vote': both must agree above threshold to flag
    """

    strategy: str = "weighted_average"
    rule_weight: float = 0.6
    ml_weight: float = 0.4
    ml_enabled: bool = True


@dataclass
class ServingConfig:
    """Top-level serving configuration aggregating all sub-configs."""

    model: ModelConfig = field(default_factory=ModelConfig)
    features: FeatureSpec = field(default_factory=FeatureSpec)
    thresholds: ScoringThresholds = field(default_factory=ScoringThresholds)
    hybrid: HybridScoringConfig = field(default_factory=HybridScoringConfig)


default_serving_config = ServingConfig()
