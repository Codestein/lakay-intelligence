"""Unit tests for the fraud scorer pipeline."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domains.fraud.config import FraudConfig
from src.domains.fraud.models import (
    FraudScoreRequest,
    RiskTier,
    RuleResult,
    ScoringContext,
    TransactionFeatures,
)
from src.domains.fraud.scorer import FraudScorer


CONFIG = FraudConfig()


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def scorer():
    return FraudScorer(config=CONFIG)


def _make_request(**kwargs) -> FraudScoreRequest:
    defaults = {
        "transaction_id": "txn-test-1",
        "user_id": "user-test-1",
        "amount": "100.00",
    }
    defaults.update(kwargs)
    return FraudScoreRequest(**defaults)


def _make_low_scoring_context():
    return ScoringContext(
        composite_score=0.1,
        risk_tier=RiskTier.LOW,
        triggered_rules=[],
        recommendation="allow",
        scoring_metadata={"model_version": "rules-v2", "confidence": 0.0},
    )


def _make_high_scoring_context():
    return ScoringContext(
        composite_score=0.75,
        risk_tier=RiskTier.HIGH,
        triggered_rules=[
            RuleResult(
                rule_name="large_transaction",
                triggered=True,
                score=0.8,
                details="test",
                category="amount",
            ),
        ],
        recommendation="hold",
        scoring_metadata={"model_version": "rules-v2", "confidence": 0.8},
    )


class TestFraudScorer:
    @pytest.mark.asyncio
    async def test_low_risk_no_alert(self, scorer, mock_session):
        request = _make_request(amount="50.00")
        low_ctx = _make_low_scoring_context()

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
            result = await scorer.score_transaction(request, mock_session)

        assert result.scoring_context is not None
        assert result.scoring_context.risk_tier == RiskTier.LOW
        # One call for FraudScore row, no alert
        assert mock_session.add.call_count == 1
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_high_score_creates_alert(self, scorer, mock_session):
        request = _make_request(amount="9700.00")
        high_ctx = _make_high_scoring_context()

        # Mock dedup check to return no existing alerts
        mock_dedup_result = MagicMock()
        mock_dedup_result.scalar_one.return_value = 0
        mock_session.execute.return_value = mock_dedup_result

        with (
            patch.object(
                scorer._feature_computer,
                "compute",
                return_value=TransactionFeatures(),
            ),
            patch.object(
                scorer._rules_engine,
                "evaluate",
                return_value=(high_ctx, high_ctx.triggered_rules),
            ),
        ):
            result = await scorer.score_transaction(request, mock_session)

        assert result.scoring_context is not None
        assert result.scoring_context.risk_tier == RiskTier.HIGH
        # FraudScore + Alert = 2 add calls
        assert mock_session.add.call_count == 2

    @pytest.mark.asyncio
    async def test_scoring_result_has_context(self, scorer, mock_session):
        request = _make_request()
        low_ctx = _make_low_scoring_context()

        with (
            patch.object(
                scorer._feature_computer,
                "compute",
                return_value=TransactionFeatures(velocity_count_1h=3),
            ),
            patch.object(
                scorer._rules_engine,
                "evaluate",
                return_value=(low_ctx, []),
            ),
        ):
            result = await scorer.score_transaction(request, mock_session)

        assert result.features_used is not None
        assert result.features_used.velocity_count_1h == 3
        assert result.scoring_context is not None
        assert result.scoring_context.composite_score == 0.1

    @pytest.mark.asyncio
    async def test_model_version_v2(self, scorer, mock_session):
        request = _make_request()
        low_ctx = _make_low_scoring_context()

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
            result = await scorer.score_transaction(request, mock_session)

        # Check the persisted FraudScore row has v2
        score_row = mock_session.add.call_args_list[0][0][0]
        assert score_row.model_version == "rules-v2"
