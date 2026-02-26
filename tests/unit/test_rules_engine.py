"""Unit tests for the rules engine aggregation logic."""

from datetime import UTC, datetime

from src.domains.fraud.models import FraudScoreRequest, TransactionFeatures
from src.domains.fraud.rules_engine import RulesEngine

engine = RulesEngine()


def _make_request(**kwargs) -> FraudScoreRequest:
    defaults = {
        "transaction_id": "txn-1",
        "user_id": "user-1",
        "amount": "100.00",
    }
    defaults.update(kwargs)
    return FraudScoreRequest(**defaults)


class TestRulesEngine:
    def test_low_risk_transaction(self):
        request = _make_request(amount="50.00")
        features = TransactionFeatures()
        response, results = engine.evaluate(request, features)
        assert response.score == 0
        assert response.risk_factors == []
        assert response.model_version == "rules-v1"

    def test_high_amount_triggers(self):
        request = _make_request(amount="10000.00")
        features = TransactionFeatures()
        response, results = engine.evaluate(request, features)
        assert response.score > 0
        assert "high_amount" in response.risk_factors

    def test_multiple_rules_sum(self):
        request = _make_request(amount="9700.00")
        features = TransactionFeatures(velocity_count_1h=6)
        response, results = engine.evaluate(request, features)
        triggered = [r for r in results if r.triggered]
        assert len(triggered) >= 2
        # Score should be sum of individual scores
        assert response.score == min(sum(r.score for r in triggered), 100)

    def test_score_caps_at_100(self):
        request = _make_request(amount="9900.00")
        features = TransactionFeatures(
            velocity_count_1h=15,
            velocity_count_24h=25,
            velocity_amount_24h=40000,
            is_new_device=True,
            is_new_country=True,
        )
        response, results = engine.evaluate(request, features)
        assert response.score <= 100

    def test_unusual_hour_with_initiated_at(self):
        request = _make_request(
            amount="100.00",
            initiated_at=datetime(2026, 1, 15, 3, 0, 0, tzinfo=UTC),
        )
        features = TransactionFeatures()
        response, results = engine.evaluate(request, features)
        assert "unusual_hour" in response.risk_factors
        assert response.score == 10

    def test_confidence_scales_with_triggered_count(self):
        # 0 triggers = 0 confidence
        request = _make_request(amount="50.00")
        response, _ = engine.evaluate(request, TransactionFeatures())
        assert response.confidence == 0.0

        # 5+ triggers = 1.0 confidence
        request2 = _make_request(
            amount="9700.00",
            initiated_at=datetime(2026, 1, 15, 3, 0, 0, tzinfo=UTC),
        )
        features = TransactionFeatures(
            velocity_count_1h=10,
            is_new_device=True,
            is_new_country=True,
        )
        response2, _ = engine.evaluate(request2, features)
        assert response2.confidence == 1.0
