"""Unit tests for velocity-based fraud detection rules."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domains.fraud.config import FraudConfig
from src.domains.fraud.models import FraudScoreRequest, RiskFactor, TransactionFeatures
from src.domains.fraud.rules.velocity import (
    CircleJoinVelocityRule,
    LoginVelocityRule,
    TransactionFrequencyRule,
    UnusualHourRule,
    VelocityAmount24hRule,
    VelocityCount24hRule,
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


class TestTransactionFrequencyRule:
    rule = TransactionFrequencyRule()

    @pytest.mark.asyncio
    async def test_below_threshold(self):
        features = TransactionFeatures(velocity_count_1h=3)
        result = await self.rule.evaluate(_make_request(), features, _mock_session(), CONFIG)
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_at_threshold(self):
        features = TransactionFeatures(velocity_count_1h=10)
        result = await self.rule.evaluate(_make_request(), features, _mock_session(), CONFIG)
        assert result.triggered
        assert result.risk_factor == RiskFactor.VELOCITY_COUNT_1H
        assert result.category == "velocity"
        assert 0.0 < result.score <= 1.0

    @pytest.mark.asyncio
    async def test_high_velocity(self):
        features = TransactionFeatures(velocity_count_1h=30)
        result = await self.rule.evaluate(_make_request(), features, _mock_session(), CONFIG)
        assert result.triggered
        assert result.severity == "high"
        assert result.score > 0.5

    @pytest.mark.asyncio
    async def test_evidence_populated(self):
        features = TransactionFeatures(velocity_count_1h=15)
        result = await self.rule.evaluate(_make_request(), features, _mock_session(), CONFIG)
        assert result.triggered
        assert "count" in result.evidence
        assert "threshold" in result.evidence


class TestVelocityCount24hRule:
    rule = VelocityCount24hRule()

    @pytest.mark.asyncio
    async def test_below_threshold(self):
        features = TransactionFeatures(velocity_count_24h=19)
        result = await self.rule.evaluate(_make_request(), features, _mock_session(), CONFIG)
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_at_threshold(self):
        features = TransactionFeatures(velocity_count_24h=20)
        result = await self.rule.evaluate(_make_request(), features, _mock_session(), CONFIG)
        assert result.triggered
        assert result.risk_factor == RiskFactor.VELOCITY_COUNT_24H

    @pytest.mark.asyncio
    async def test_score_scales(self):
        features_low = TransactionFeatures(velocity_count_24h=20)
        features_high = TransactionFeatures(velocity_count_24h=50)
        r1 = await self.rule.evaluate(_make_request(), features_low, _mock_session(), CONFIG)
        r2 = await self.rule.evaluate(_make_request(), features_high, _mock_session(), CONFIG)
        assert r2.score > r1.score


class TestVelocityAmount24hRule:
    rule = VelocityAmount24hRule()

    @pytest.mark.asyncio
    async def test_below_threshold(self):
        features = TransactionFeatures(velocity_amount_24h=5000)
        result = await self.rule.evaluate(
            _make_request(amount="4999"), features, _mock_session(), CONFIG
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_at_threshold(self):
        features = TransactionFeatures(velocity_amount_24h=5000)
        result = await self.rule.evaluate(
            _make_request(amount="5000"), features, _mock_session(), CONFIG
        )
        assert result.triggered
        assert result.risk_factor == RiskFactor.VELOCITY_AMOUNT_24H

    @pytest.mark.asyncio
    async def test_high_amount_caps(self):
        features = TransactionFeatures(velocity_amount_24h=40000)
        result = await self.rule.evaluate(
            _make_request(amount="10000"), features, _mock_session(), CONFIG
        )
        assert result.triggered
        assert result.score <= 1.0


class TestLoginVelocityRule:
    rule = LoginVelocityRule()

    @pytest.mark.asyncio
    async def test_below_threshold(self):
        result = await self.rule.evaluate(
            _make_request(), EMPTY_FEATURES, _mock_session(scalar_value=3), CONFIG
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_at_threshold(self):
        result = await self.rule.evaluate(
            _make_request(), EMPTY_FEATURES, _mock_session(scalar_value=5), CONFIG
        )
        assert result.triggered
        assert result.risk_factor == RiskFactor.LOGIN_VELOCITY
        assert result.severity == "high"

    @pytest.mark.asyncio
    async def test_high_count(self):
        result = await self.rule.evaluate(
            _make_request(), EMPTY_FEATURES, _mock_session(scalar_value=15), CONFIG
        )
        assert result.triggered
        assert result.score > 0.5


class TestCircleJoinVelocityRule:
    rule = CircleJoinVelocityRule()

    @pytest.mark.asyncio
    async def test_below_threshold(self):
        result = await self.rule.evaluate(
            _make_request(), EMPTY_FEATURES, _mock_session(scalar_value=2), CONFIG
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_at_threshold(self):
        result = await self.rule.evaluate(
            _make_request(), EMPTY_FEATURES, _mock_session(scalar_value=3), CONFIG
        )
        assert result.triggered
        assert result.risk_factor == RiskFactor.CIRCLE_JOIN_VELOCITY

    @pytest.mark.asyncio
    async def test_configurable_threshold(self):
        custom_config = FraudConfig()
        custom_config.velocity.circle_join_max = 5
        result = await self.rule.evaluate(
            _make_request(), EMPTY_FEATURES, _mock_session(scalar_value=4), custom_config
        )
        assert not result.triggered


class TestUnusualHourRule:
    rule = UnusualHourRule()

    @pytest.mark.asyncio
    async def test_normal_hour(self):
        result = await self.rule.evaluate(
            _make_request(initiated_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)),
            EMPTY_FEATURES,
            _mock_session(),
            CONFIG,
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_unusual_hour_3am(self):
        result = await self.rule.evaluate(
            _make_request(initiated_at=datetime(2026, 1, 15, 3, 0, 0, tzinfo=UTC)),
            EMPTY_FEATURES,
            _mock_session(),
            CONFIG,
        )
        assert result.triggered
        assert result.risk_factor == RiskFactor.UNUSUAL_HOUR
        assert result.severity == "low"

    @pytest.mark.asyncio
    async def test_boundary_5am_not_unusual(self):
        result = await self.rule.evaluate(
            _make_request(initiated_at=datetime(2026, 1, 15, 5, 0, 0, tzinfo=UTC)),
            EMPTY_FEATURES,
            _mock_session(),
            CONFIG,
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_no_initiated_at(self):
        result = await self.rule.evaluate(
            _make_request(initiated_at=None), EMPTY_FEATURES, _mock_session(), CONFIG
        )
        assert not result.triggered
