"""Centralized model serving configuration.

All serving-related settings live here: model identity, feature schema,
scoring thresholds, reload behavior, and hybrid scoring parameters.
"""

from dataclasses import dataclass, field


@dataclass
class ModelConfig:
    """Identity and loading configuration for the served model."""

    name: str = "fraud-detector-v0.1"
    stage: str = "Production"
    fallback_stage: str = "Staging"
    reload_interval_seconds: int = 300
    prediction_timeout_seconds: float = 1.0


@dataclass
class FeatureSpec:
    """Expected input features for the ML model, used for validation."""

    features: list[str] = field(
        default_factory=lambda: [
            "amount",
            "amount_zscore",
            "hour_of_day",
            "day_of_week",
            "tx_type_encoded",
            "balance_delta_sender",
            "balance_delta_receiver",
            "velocity_count_1h",
            "velocity_count_24h",
            "velocity_amount_1h",
            "velocity_amount_24h",
        ]
    )
    feature_types: dict[str, str] = field(
        default_factory=lambda: {
            "amount": "float",
            "amount_zscore": "float",
            "hour_of_day": "int",
            "day_of_week": "int",
            "tx_type_encoded": "int",
            "balance_delta_sender": "float",
            "balance_delta_receiver": "float",
            "velocity_count_1h": "int",
            "velocity_count_24h": "int",
            "velocity_amount_1h": "float",
            "velocity_amount_24h": "float",
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
