"""Unit tests for the rules engine weighted aggregation logic."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domains.fraud.config import FraudConfig
from src.domains.fraud.models import FraudScoreRequest, RiskTier, TransactionFeatures
from src.domains.fraud.rules_engine import RulesEngine

CONFIG = FraudConfig()
NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)


def _make_request(**kwargs) -> FraudScoreRequest:
    defaults = {
        "transaction_id": "txn-1",
        "user_id": "user-1",
        "amount": "100.00",
        "initiated_at": NOW,
    }
    defaults.update(kwargs)
    return FraudScoreRequest(**defaults)


def _mock_session(scalar_value=0):
    """Mock session that returns a scalar for single-value queries
    and empty fetchall for multi-row queries."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = scalar_value
    mock_result.fetchall.return_value = []

    # For queries that use .one() (like velocity)
    mock_row = MagicMock()
    mock_row.cnt = 0
    mock_row.total = 0.0
    mock_result.one.return_value = mock_row

    session.execute.return_value = mock_result
    return session


class TestRulesEngine:
    @pytest.mark.asyncio
    async def test_low_risk_transaction(self):
        engine = RulesEngine(config=CONFIG)
        request = _make_request(amount="50.00")
        features = TransactionFeatures()
        session = _mock_session()

        scoring_ctx, results = await engine.evaluate(request, features, session)

        assert scoring_ctx.composite_score == 0.0
        assert scoring_ctx.risk_tier == RiskTier.LOW
        assert scoring_ctx.recommendation == "allow"
        assert len(scoring_ctx.triggered_rules) == 0

    @pytest.mark.asyncio
    async def test_composite_score_bounded(self):
        engine = RulesEngine(config=CONFIG)
        request = _make_request(amount="50.00")
        features = TransactionFeatures()
        session = _mock_session()

        scoring_ctx, _ = await engine.evaluate(request, features, session)

        assert 0.0 <= scoring_ctx.composite_score <= 1.0

    @pytest.mark.asyncio
    async def test_model_version_v2(self):
        engine = RulesEngine(config=CONFIG)
        request = _make_request(amount="50.00")
        features = TransactionFeatures()
        session = _mock_session()

        scoring_ctx, _ = await engine.evaluate(request, features, session)

        assert scoring_ctx.scoring_metadata["model_version"] == "rules-v2"

    @pytest.mark.asyncio
    async def test_unusual_hour_triggers(self):
        engine = RulesEngine(config=CONFIG)
        request = _make_request(
            amount="100.00",
            initiated_at=datetime(2026, 1, 15, 3, 0, 0, tzinfo=UTC),
        )
        features = TransactionFeatures()
        session = _mock_session()

        scoring_ctx, _ = await engine.evaluate(request, features, session)

        rule_names = [r.rule_name for r in scoring_ctx.triggered_rules]
        assert "unusual_hour" in rule_names

    @pytest.mark.asyncio
    async def test_risk_tier_classification(self):
        engine = RulesEngine(config=CONFIG)
        # Low risk
        request = _make_request(amount="50.00")
        ctx, _ = await engine.evaluate(request, TransactionFeatures(), _mock_session())
        assert ctx.risk_tier == RiskTier.LOW

    @pytest.mark.asyncio
    async def test_category_scores_in_metadata(self):
        engine = RulesEngine(config=CONFIG)
        request = _make_request(amount="50.00")
        ctx, _ = await engine.evaluate(request, TransactionFeatures(), _mock_session())
        assert "category_scores" in ctx.scoring_metadata
        assert "triggered_count" in ctx.scoring_metadata

    @pytest.mark.asyncio
    async def test_large_amount_triggers_amount_rules(self):
        engine = RulesEngine(config=CONFIG)
        request = _make_request(amount="5000.00")
        features = TransactionFeatures()
        session = _mock_session()

        scoring_ctx, results = await engine.evaluate(request, features, session)

        triggered_categories = {r.category for r in scoring_ctx.triggered_rules}
        assert "amount" in triggered_categories

    @pytest.mark.asyncio
    async def test_confidence_zero_when_no_triggers(self):
        engine = RulesEngine(config=CONFIG)
        request = _make_request(amount="50.00")
        ctx, _ = await engine.evaluate(request, TransactionFeatures(), _mock_session())
        assert ctx.scoring_metadata["confidence"] == 0.0
