"""Tests for model serving configuration."""

from src.serving.config import (
    FeatureSpec,
    HybridScoringConfig,
    ModelConfig,
    ScoringThresholds,
    ServingConfig,
    default_serving_config,
)


class TestModelConfig:
    def test_defaults(self):
        config = ModelConfig()
        assert config.name == "fraud-detector-v0.1"
        assert config.stage == "Production"
        assert config.fallback_stage == "Staging"
        assert config.reload_interval_seconds == 300

    def test_custom_values(self):
        config = ModelConfig(name="test-model", stage="Staging")
        assert config.name == "test-model"
        assert config.stage == "Staging"


class TestFeatureSpec:
    def test_default_feature_count(self):
        spec = FeatureSpec()
        assert len(spec.features) == 11
        assert "amount" in spec.features
        assert "velocity_count_1h" in spec.features

    def test_feature_types_match(self):
        spec = FeatureSpec()
        for feature in spec.features:
            assert feature in spec.feature_types


class TestHybridScoringConfig:
    def test_defaults(self):
        config = HybridScoringConfig()
        assert config.strategy == "weighted_average"
        assert config.rule_weight == 0.6
        assert config.ml_weight == 0.4
        assert config.ml_enabled is True

    def test_weights_sum_to_one(self):
        config = HybridScoringConfig()
        assert abs(config.rule_weight + config.ml_weight - 1.0) < 0.001


class TestServingConfig:
    def test_default_singleton(self):
        assert default_serving_config is not None
        assert default_serving_config.model.name == "fraud-detector-v0.1"

    def test_nested_configs(self):
        config = ServingConfig()
        assert isinstance(config.model, ModelConfig)
        assert isinstance(config.features, FeatureSpec)
        assert isinstance(config.thresholds, ScoringThresholds)
        assert isinstance(config.hybrid, HybridScoringConfig)
