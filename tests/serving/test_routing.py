"""Tests for A/B model routing."""

from unittest.mock import MagicMock

import numpy as np
import pytest

from src.serving.routing import (
    AutoPromotionConfig,
    ModelRouter,
    RoutingConfig,
    get_model_router,
)
from src.serving.server import ModelServer


def _make_mock_server(name="test-model", version="1", score=0.5):
    """Create a mock ModelServer that returns a fixed score."""
    server = ModelServer()
    mock_model = MagicMock()
    mock_model.predict.return_value = np.array([score])
    server._model = mock_model
    server._model_name = name
    server._model_version = version
    return server


class TestRoutingConfig:
    def test_defaults(self):
        config = RoutingConfig()
        assert config.champion_pct == 95.0
        assert config.challenger_pct == 5.0

    def test_invalid_split(self):
        with pytest.raises(ValueError, match="must sum to 100"):
            RoutingConfig(champion_pct=80.0, challenger_pct=10.0)


class TestModelRouter:
    def test_deterministic_routing(self):
        """Same user_id always gets same variant."""
        champion = _make_mock_server("champion", "1", 0.3)
        challenger = _make_mock_server("challenger", "2", 0.7)
        router = ModelRouter(
            champion=champion,
            challenger=challenger,
            config=RoutingConfig(champion_pct=50, challenger_pct=50),
        )

        features = {"amount": 100.0}
        results = [router.route("user-123", features) for _ in range(10)]
        # All should be the same variant
        variants = {r.model_variant for r in results}
        assert len(variants) == 1

    def test_champion_only_when_disabled(self):
        champion = _make_mock_server("champion", "1", 0.3)
        challenger = _make_mock_server("challenger", "2", 0.7)
        router = ModelRouter(
            champion=champion,
            challenger=challenger,
            config=RoutingConfig(champion_pct=100, challenger_pct=0),
        )

        result = router.route("user-456", {"amount": 100.0})
        assert result.model_variant == "champion"

    def test_fallback_to_champion_when_challenger_not_loaded(self):
        champion = _make_mock_server("champion", "1", 0.3)
        challenger = ModelServer()  # Not loaded

        router = ModelRouter(
            champion=champion,
            challenger=challenger,
            config=RoutingConfig(champion_pct=0, challenger_pct=100),
        )

        result = router.route("user-789", {"amount": 100.0})
        assert result.model_variant == "champion"

    def test_no_models_returns_none_variant(self):
        router = ModelRouter()
        result = router.route("user-000", {"amount": 100.0})
        assert result.model_variant == "none"
        assert result.prediction is None

    def test_update_config(self):
        router = ModelRouter()
        router.update_config(champion_pct=80.0, challenger_pct=20.0)
        assert router.config.champion_pct == 80.0
        assert router.config.challenger_pct == 20.0

    def test_metrics_collection(self):
        champion = _make_mock_server("champion", "1", 0.3)
        router = ModelRouter(champion=champion)

        for i in range(5):
            router.route(f"user-{i}", {"amount": float(i * 100)})

        summary = router.get_metrics_summary()
        assert summary["total_observations"] == 5
        assert summary["champion"]["count"] == 5
        assert summary["champion"]["mean_score"] == 0.3

    def test_traffic_split_distribution(self):
        """With 50/50 split, large user pool should approach 50/50."""
        champion = _make_mock_server("champion", "1", 0.3)
        challenger = _make_mock_server("challenger", "2", 0.7)
        router = ModelRouter(
            champion=champion,
            challenger=challenger,
            config=RoutingConfig(champion_pct=50, challenger_pct=50),
        )

        variants = []
        for i in range(1000):
            result = router.route(f"user-{i}", {"amount": 100.0})
            variants.append(result.model_variant)

        champion_count = variants.count("champion")
        challenger_count = variants.count("challenger")
        # Should be roughly 50/50 (within 10% tolerance)
        assert abs(champion_count - 500) < 100
        assert abs(challenger_count - 500) < 100

    def test_auto_promotion_disabled(self):
        router = ModelRouter(auto_promotion=AutoPromotionConfig(enabled=False))
        assert router.check_auto_promotion() is False


class TestGetModelRouter:
    def test_singleton(self):
        import src.serving.routing as routing_module

        routing_module._router = None
        r1 = get_model_router()
        r2 = get_model_router()
        assert r1 is r2
        routing_module._router = None
