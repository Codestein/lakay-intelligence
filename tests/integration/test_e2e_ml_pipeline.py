"""End-to-end validation: synthetic event -> features -> model -> score.

Tests the complete ML pipeline from event generation through scoring,
verifying hybrid scoring, fallback behavior, and volume handling.
These tests use mocked external services (Kafka, PostgreSQL, MLflow)
to validate the pipeline logic without requiring a running infrastructure.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.domains.fraud.config import FraudConfig
from src.domains.fraud.models import (
    FraudScoreRequest,
    RiskTier,
    ScoringContext,
    TransactionFeatures,
)
from src.domains.fraud.scorer import FraudScorer
from src.serving.config import HybridScoringConfig, ServingConfig
from src.serving.drift import DriftConfig, FeatureDriftDetector
from src.serving.monitoring import ModelMonitor
from src.serving.routing import ModelRouter, RoutingConfig
from src.serving.server import ModelServer


def _make_request(
    txn_id: str = "txn-e2e-1",
    user_id: str = "user-e2e-1",
    amount: str = "150.00",
) -> FraudScoreRequest:
    return FraudScoreRequest(
        transaction_id=txn_id,
        user_id=user_id,
        amount=amount,
        currency="USD",
        initiated_at=datetime(2026, 1, 15, 14, 30, 0, tzinfo=UTC),
    )


def _make_mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    mock_dedup_result = MagicMock()
    mock_dedup_result.scalar_one.return_value = 0
    session.execute = AsyncMock(return_value=mock_dedup_result)
    return session


def _make_loaded_server(score: float = 0.5) -> ModelServer:
    """Create a ModelServer with a mock model loaded."""
    server = ModelServer()
    mock_model = MagicMock()
    mock_model.predict.return_value = np.array([score])
    server._model = mock_model
    server._model_name = "fraud-detector-v0.1"
    server._model_version = "1"
    return server


class TestHybridScoring:
    """Verify rules + ML hybrid scoring combination."""

    def test_weighted_average_combination(self):
        from src.api.routes.fraud import _compute_hybrid_score

        # Rules = 0.4, ML = 0.8
        hybrid, version = _compute_hybrid_score(0.4, 0.8)
        # weighted: 0.6 * 0.4 + 0.4 * 0.8 = 0.24 + 0.32 = 0.56
        assert abs(hybrid - 0.56) < 0.001
        assert version == "hybrid-v1"

    def test_rules_only_when_ml_unavailable(self):
        from src.api.routes.fraud import _compute_hybrid_score

        hybrid, version = _compute_hybrid_score(0.4, None)
        assert hybrid == 0.4
        assert version == "rules-v2"

    def test_hybrid_capped_at_1(self):
        from src.api.routes.fraud import _compute_hybrid_score

        hybrid, version = _compute_hybrid_score(1.0, 1.0)
        assert hybrid <= 1.0

    def test_max_strategy(self):
        from src.api.routes.fraud import _compute_hybrid_score

        with patch(
            "src.api.routes.fraud.default_serving_config",
            ServingConfig(hybrid=HybridScoringConfig(strategy="max")),
        ):
            hybrid, version = _compute_hybrid_score(0.3, 0.7)
            assert hybrid == 0.7


class TestFallbackBehavior:
    """Verify graceful fallback to rule-based scoring when ML model is unavailable."""

    @pytest.mark.asyncio
    async def test_fallback_when_no_model(self):
        """System should score using rules-only when ML model is not loaded."""
        scorer = FraudScorer(config=FraudConfig())
        request = _make_request(amount="100.00")
        session = _make_mock_session()

        low_ctx = ScoringContext(
            composite_score=0.1,
            risk_tier=RiskTier.LOW,
            triggered_rules=[],
            recommendation="allow",
            scoring_metadata={"confidence": 0.0},
        )

        with (
            patch.object(
                scorer._feature_computer,
                "compute",
                return_value=TransactionFeatures(),
            ),
            patch.object(
                scorer._rules_engine,
                "evaluate",
                return_value=(low_ctx, []),
            ),
        ):
            result = await scorer.score_transaction(request, session)

        assert result.scoring_context is not None
        assert result.scoring_context.composite_score == 0.1

    def test_model_server_fallback(self):
        """ModelServer returns None when no model is loaded."""
        server = ModelServer()
        assert not server.is_loaded
        result = server.predict({"amount": 100.0})
        assert result is None

    def test_model_server_error_returns_none(self):
        """ModelServer returns None on prediction error (not an exception)."""
        server = ModelServer()
        mock_model = MagicMock()
        mock_model.predict.side_effect = RuntimeError("corrupt model")
        server._model = mock_model

        result = server.predict({"amount": 100.0})
        assert result is None


class TestMLPrediction:
    """Verify ML model scoring produces valid results."""

    def test_valid_score_range(self):
        server = _make_loaded_server(score=0.73)
        result = server.predict({"amount": 500.0, "hour_of_day": 2})
        assert result is not None
        assert 0.0 <= result.score <= 1.0

    def test_prediction_latency_recorded(self):
        server = _make_loaded_server()
        result = server.predict({"amount": 100.0})
        assert result is not None
        assert result.prediction_latency_ms > 0

    def test_prediction_metadata(self):
        server = _make_loaded_server()
        result = server.predict({"amount": 100.0})
        assert result is not None
        assert result.model_name == "fraud-detector-v0.1"
        assert result.model_version == "1"
        assert isinstance(result.feature_vector, dict)


class TestVolumeHandling:
    """Verify the pipeline handles volume without dropping events."""

    def test_10k_predictions_all_valid(self):
        """Push 10,000 predictions and verify all scores are valid."""
        server = _make_loaded_server(score=0.5)
        rng = np.random.default_rng(42)

        scores = []
        latencies = []
        for i in range(10000):
            features = {
                "amount": float(rng.lognormal(4.5, 1.2)),
                "hour_of_day": int(rng.integers(0, 24)),
                "velocity_count_1h": int(rng.integers(0, 15)),
            }
            result = server.predict(features)
            assert result is not None, f"Prediction {i} returned None"
            scores.append(result.score)
            latencies.append(result.prediction_latency_ms)

        scores_arr = np.array(scores)

        # All scores valid
        assert not np.any(np.isnan(scores_arr)), "Found NaN scores"
        assert not np.any(np.isinf(scores_arr)), "Found Inf scores"
        assert np.all(scores_arr >= 0), "Found negative scores"
        assert np.all(scores_arr <= 1), "Found scores > 1"

        # No events dropped
        assert len(scores) == 10000

    def test_volume_latency_reasonable(self):
        """Verify prediction latency stays reasonable under volume."""
        server = _make_loaded_server()
        rng = np.random.default_rng(42)

        latencies = []
        for _ in range(1000):
            features = {"amount": float(rng.lognormal(4.5, 1.2))}
            result = server.predict(features)
            if result:
                latencies.append(result.prediction_latency_ms)

        p95 = np.percentile(latencies, 95)
        # Mock model should be very fast; this is a sanity check
        assert p95 < 100, f"p95 latency {p95}ms exceeds threshold"


class TestRoutingIntegration:
    """Test A/B routing with actual prediction flow."""

    def test_routing_produces_valid_predictions(self):
        champion = _make_loaded_server(score=0.3)
        challenger = _make_loaded_server(score=0.7)
        router = ModelRouter(
            champion=champion,
            challenger=challenger,
            config=RoutingConfig(champion_pct=50, challenger_pct=50),
        )

        for i in range(100):
            decision = router.route(f"user-{i}", {"amount": 100.0})
            assert decision.prediction is not None
            assert 0 <= decision.prediction.score <= 1

    def test_routing_metrics_collected(self):
        champion = _make_loaded_server(score=0.3)
        router = ModelRouter(champion=champion)

        for i in range(50):
            router.route(f"user-{i}", {"amount": float(i * 10)})

        summary = router.get_metrics_summary()
        assert summary["total_observations"] == 50
        assert summary["champion"]["count"] == 50


class TestMonitoringIntegration:
    """Test monitoring records predictions correctly."""

    def test_monitoring_records_volume(self):
        monitor = ModelMonitor()
        monitor.set_baseline([0.3, 0.4, 0.5, 0.6, 0.7], model_version="1")

        server = _make_loaded_server(score=0.5)
        for _ in range(200):
            result = server.predict({"amount": 100.0})
            if result:
                monitor.record_prediction(result.score, result.prediction_latency_ms)

        report = monitor.get_health_report()
        assert report["total_predictions"] == 200
        assert report["score_distribution_1h"]["count"] == 200


class TestDriftIntegration:
    """Test drift detection records observations."""

    def test_drift_detection_no_false_positives(self):
        config = DriftConfig(
            min_observations=500,
            check_interval_observations=500,
            num_bins=10,
        )
        detector = FeatureDriftDetector(feature_names=["amount"], config=config)

        rng = np.random.default_rng(42)
        reference = rng.normal(100, 20, 5000)
        detector.set_reference_distribution("amount", reference)

        alerts = []
        for _ in range(1000):
            obs = float(rng.normal(100, 20))
            new_alerts = detector.record_observation({"amount": obs})
            alerts.extend(new_alerts)

        # Same distribution should not trigger alerts with large sample
        assert len(alerts) == 0
