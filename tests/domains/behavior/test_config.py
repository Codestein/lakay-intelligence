"""Unit tests for behavioral analytics configuration."""

import pytest

from src.domains.behavior.config import (
    AnomalyWeights,
    BehaviorConfig,
    default_config,
)


class TestAnomalyWeights:
    def test_default_weights_sum_to_one(self):
        w = AnomalyWeights()
        total = w.temporal + w.device + w.geographic + w.behavioral + w.engagement
        assert abs(total - 1.0) < 1e-6

    def test_invalid_weights_raise(self):
        with pytest.raises(ValueError, match="must sum to 1.0"):
            AnomalyWeights(temporal=0.5, device=0.5, geographic=0.5, behavioral=0.5, engagement=0.5)

    def test_custom_valid_weights(self):
        w = AnomalyWeights(temporal=0.2, device=0.2, geographic=0.2, behavioral=0.2, engagement=0.2)
        total = w.temporal + w.device + w.geographic + w.behavioral + w.engagement
        assert abs(total - 1.0) < 1e-6


class TestBehaviorConfig:
    def test_default_config_exists(self):
        assert default_config is not None
        assert isinstance(default_config, BehaviorConfig)

    def test_profile_defaults(self):
        cfg = BehaviorConfig()
        assert cfg.profile.min_sessions_active == 10
        assert cfg.profile.min_days_active == 7
        assert cfg.profile.ema_decay_rate == 0.15
        assert cfg.profile.staleness_threshold_days == 30

    def test_anomaly_thresholds(self):
        cfg = BehaviorConfig()
        assert cfg.anomaly_thresholds.normal_max == 0.3
        assert cfg.anomaly_thresholds.suspicious_max == 0.6
        assert cfg.anomaly_thresholds.high_risk_max == 0.8
        assert cfg.anomaly_thresholds.impossible_travel_speed_kmh == 900.0
        assert "US" in cfg.anomaly_thresholds.corridor_countries
        assert "HT" in cfg.anomaly_thresholds.corridor_countries

    def test_ato_config(self):
        cfg = BehaviorConfig()
        assert cfg.ato.kafka_topic == "lakay.behavior.ato-alerts"
        assert cfg.ato.alert_dedup_window_seconds == 86400
        assert "change_email" in cfg.ato.sensitive_actions
        assert "change_password" in cfg.ato.sensitive_actions

    def test_engagement_config(self):
        cfg = BehaviorConfig()
        assert cfg.engagement.churned_days == 30
        assert cfg.engagement.dormant_days == 14
        total_weights = (
            cfg.engagement.frequency_weight
            + cfg.engagement.recency_weight
            + cfg.engagement.streak_weight
            + cfg.engagement.breadth_weight
            + cfg.engagement.consistency_weight
        )
        assert abs(total_weights - 1.0) < 1e-6
