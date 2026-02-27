"""Unit tests for amount-based fraud detection rules."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domains.fraud.config import FraudConfig
from src.domains.fraud.models import FraudScoreRequest, RiskFactor, TransactionFeatures
from src.domains.fraud.rules.amount import (
    BaselineDeviationRule,
    CTRProximityRule,
    CumulativeAmountRule,
    LargeTransactionRule,
)

CONFIG = FraudConfig()
NOW = datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)
EMPTY_FEATURES = TransactionFeatures()


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
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = scalar_value
    session.execute.return_value = mock_result
    return session


def _mock_session_cumulative(total_24h=0.0, total_7d=0.0, total_30d=0.0):
    """Mock session that returns different values for sequential cumulative queries."""
    session = AsyncMock()
    results = [total_24h, total_7d, total_30d]
    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        mock_result = MagicMock()
        idx = min(call_count, len(results) - 1)
        mock_result.scalar_one.return_value = results[idx]
        call_count += 1
        return mock_result

    session.execute = mock_execute
    return session


class TestLargeTransactionRule:
    rule = LargeTransactionRule()

    @pytest.mark.asyncio
    async def test_below_threshold(self):
        result = await self.rule.evaluate(
            _make_request(amount="2999"), EMPTY_FEATURES, _mock_session(), CONFIG
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_at_threshold(self):
        result = await self.rule.evaluate(
            _make_request(amount="3000"), EMPTY_FEATURES, _mock_session(), CONFIG
        )
        assert result.triggered
        assert result.risk_factor == RiskFactor.HIGH_AMOUNT
        assert result.category == "amount"
        assert 0.0 < result.score <= 1.0

    @pytest.mark.asyncio
    async def test_very_large_amount(self):
        result = await self.rule.evaluate(
            _make_request(amount="50000"), EMPTY_FEATURES, _mock_session(), CONFIG
        )
        assert result.triggered
        assert result.severity in ("high", "critical")
        assert result.score > 0.5

    @pytest.mark.asyncio
    async def test_score_caps_at_1(self):
        result = await self.rule.evaluate(
            _make_request(amount="100000"), EMPTY_FEATURES, _mock_session(), CONFIG
        )
        assert result.score <= 1.0

    @pytest.mark.asyncio
    async def test_configurable_threshold(self):
        custom_config = FraudConfig()
        custom_config.amount.large_txn_min = 5000.0
        result = await self.rule.evaluate(
            _make_request(amount="4999"), EMPTY_FEATURES, _mock_session(), custom_config
        )
        assert not result.triggered


class TestCumulativeAmountRule:
    rule = CumulativeAmountRule()

    @pytest.mark.asyncio
    async def test_below_all_thresholds(self):
        session = _mock_session_cumulative(1000.0, 5000.0, 10000.0)
        result = await self.rule.evaluate(
            _make_request(amount="100"), EMPTY_FEATURES, session, CONFIG
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_24h_breach(self):
        session = _mock_session_cumulative(7500.0, 10000.0, 20000.0)
        result = await self.rule.evaluate(
            _make_request(amount="1000"), EMPTY_FEATURES, session, CONFIG
        )
        assert result.triggered
        assert result.risk_factor == RiskFactor.CUMULATIVE_AMOUNT
        assert result.severity == "critical"

    @pytest.mark.asyncio
    async def test_7d_breach_only(self):
        session = _mock_session_cumulative(2000.0, 24500.0, 40000.0)
        result = await self.rule.evaluate(
            _make_request(amount="1000"), EMPTY_FEATURES, session, CONFIG
        )
        assert result.triggered
        assert "7d" in result.details or "breached" in result.details.lower()


class TestBaselineDeviationRule:
    rule = BaselineDeviationRule()

    @pytest.mark.asyncio
    async def test_no_baseline(self):
        result = await self.rule.evaluate(
            _make_request(amount="5000"), EMPTY_FEATURES, _mock_session(), CONFIG
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_within_baseline(self):
        features = TransactionFeatures(avg_amount_30d=200.0, stddev_amount_30d=50.0)
        result = await self.rule.evaluate(
            _make_request(amount="300"), features, _mock_session(), CONFIG
        )
        assert not result.triggered  # z-score = 2.0, threshold = 2.5

    @pytest.mark.asyncio
    async def test_above_baseline(self):
        features = TransactionFeatures(avg_amount_30d=200.0, stddev_amount_30d=50.0)
        result = await self.rule.evaluate(
            _make_request(amount="400"), features, _mock_session(), CONFIG
        )
        assert result.triggered  # z-score = 4.0
        assert result.risk_factor == RiskFactor.DEVIATION_FROM_BASELINE
        assert "zscore" in result.evidence

    @pytest.mark.asyncio
    async def test_extreme_deviation(self):
        features = TransactionFeatures(avg_amount_30d=100.0, stddev_amount_30d=20.0)
        result = await self.rule.evaluate(
            _make_request(amount="500"), features, _mock_session(), CONFIG
        )
        assert result.triggered
        assert result.severity == "high"  # z-score = 20.0 (extreme)


class TestCTRProximityRule:
    rule = CTRProximityRule()

    @pytest.mark.asyncio
    async def test_below_thresholds(self):
        result = await self.rule.evaluate(
            _make_request(amount="5000"), EMPTY_FEATURES, _mock_session(), CONFIG
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_single_txn_above_threshold(self):
        result = await self.rule.evaluate(
            _make_request(amount="8500"), EMPTY_FEATURES, _mock_session(), CONFIG
        )
        assert result.triggered
        assert result.risk_factor == RiskFactor.CTR_PROXIMITY
        assert result.severity == "critical"
        assert result.evidence["trigger"] == "single_transaction"

    @pytest.mark.asyncio
    async def test_daily_cumulative_above_threshold(self):
        features = TransactionFeatures(velocity_amount_24h=8000)
        result = await self.rule.evaluate(
            _make_request(amount="1500"), features, _mock_session(), CONFIG
        )
        assert result.triggered
        assert result.evidence["trigger"] == "daily_cumulative"

    @pytest.mark.asyncio
    async def test_score_within_bounds(self):
        result = await self.rule.evaluate(
            _make_request(amount="9000"), EMPTY_FEATURES, _mock_session(), CONFIG
        )
        assert result.triggered
        assert 0.0 < result.score <= 1.0
