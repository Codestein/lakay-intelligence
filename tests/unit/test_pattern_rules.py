"""Unit tests for pattern-based fraud detection rules."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domains.fraud.config import FraudConfig
from src.domains.fraud.models import FraudScoreRequest, RiskFactor, TransactionFeatures
from src.domains.fraud.rules.patterns import (
    DuplicateTransactionRule,
    RoundAmountClusteringRule,
    StructuringDetectionRule,
    TemporalStructuringRule,
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


class TestDuplicateTransactionRule:
    rule = DuplicateTransactionRule()

    @pytest.mark.asyncio
    async def test_no_recipient(self):
        result = await self.rule.evaluate(
            _make_request(), EMPTY_FEATURES, _mock_session(), CONFIG
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_no_duplicates(self):
        result = await self.rule.evaluate(
            _make_request(recipient_id="recipient-1"),
            EMPTY_FEATURES,
            _mock_session(scalar_value=0),
            CONFIG,
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_single_duplicate(self):
        result = await self.rule.evaluate(
            _make_request(recipient_id="recipient-1"),
            EMPTY_FEATURES,
            _mock_session(scalar_value=1),
            CONFIG,
        )
        assert result.triggered
        assert result.risk_factor == RiskFactor.DUPLICATE_TRANSACTION
        assert result.category == "patterns"

    @pytest.mark.asyncio
    async def test_multiple_duplicates_higher_severity(self):
        result = await self.rule.evaluate(
            _make_request(recipient_id="recipient-1"),
            EMPTY_FEATURES,
            _mock_session(scalar_value=3),
            CONFIG,
        )
        assert result.triggered
        assert result.severity == "high"
        assert result.score > 0.5


class TestStructuringDetectionRule:
    rule = StructuringDetectionRule()

    def _mock_session_structuring(self, count=0, total=0.0):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.cnt = count
        mock_row.total = total
        mock_result.one.return_value = mock_row
        session.execute.return_value = mock_result
        return session

    @pytest.mark.asyncio
    async def test_normal_amount(self):
        session = self._mock_session_structuring(count=1, total=500.0)
        result = await self.rule.evaluate(
            _make_request(amount="100.00"), EMPTY_FEATURES, session, CONFIG
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_near_3k_threshold(self):
        session = self._mock_session_structuring(count=1, total=500.0)
        result = await self.rule.evaluate(
            _make_request(amount="2900.00"), EMPTY_FEATURES, session, CONFIG
        )
        assert result.triggered
        assert result.risk_factor == RiskFactor.STRUCTURING_NEAR_3K

    @pytest.mark.asyncio
    async def test_near_10k_threshold(self):
        session = self._mock_session_structuring(count=1, total=500.0)
        result = await self.rule.evaluate(
            _make_request(amount="9700.00"), EMPTY_FEATURES, session, CONFIG
        )
        assert result.triggered
        assert result.risk_factor == RiskFactor.STRUCTURING_NEAR_10K
        assert result.severity == "critical"

    @pytest.mark.asyncio
    async def test_cumulative_structuring(self):
        # Multiple small txns summing near $3k
        session = self._mock_session_structuring(count=5, total=2600.0)
        result = await self.rule.evaluate(
            _make_request(amount="200.00"), EMPTY_FEATURES, session, CONFIG
        )
        assert result.triggered  # 2600 + 200 = 2800, near $3k


class TestRoundAmountClusteringRule:
    rule = RoundAmountClusteringRule()

    def _mock_session_amounts(self, amounts: list[float]):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(a,) for a in amounts]
        session.execute.return_value = mock_result
        return session

    @pytest.mark.asyncio
    async def test_too_few_transactions(self):
        session = self._mock_session_amounts([100.0])
        result = await self.rule.evaluate(
            _make_request(amount="200.00"), EMPTY_FEATURES, session, CONFIG
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_normal_distribution(self):
        amounts = [123.45, 67.89, 234.56, 89.12, 345.67]
        session = self._mock_session_amounts(amounts)
        result = await self.rule.evaluate(
            _make_request(amount="156.78"), EMPTY_FEATURES, session, CONFIG
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_round_amount_clustering(self):
        amounts = [100.0, 200.0, 300.0, 400.0, 500.0]
        session = self._mock_session_amounts(amounts)
        result = await self.rule.evaluate(
            _make_request(amount="600.00"), EMPTY_FEATURES, session, CONFIG
        )
        assert result.triggered
        assert result.risk_factor == RiskFactor.ROUND_AMOUNT_CLUSTERING
        assert result.evidence["round_pct"] >= 0.60

    @pytest.mark.asyncio
    async def test_mixed_amounts_below_threshold(self):
        amounts = [100.0, 123.45, 200.0, 67.89, 300.0]
        session = self._mock_session_amounts(amounts)
        result = await self.rule.evaluate(
            _make_request(amount="156.78"), EMPTY_FEATURES, session, CONFIG
        )
        # 3 round out of 6 total = 50%, below 60% threshold
        assert not result.triggered


class TestTemporalStructuringRule:
    rule = TemporalStructuringRule()

    def _mock_session_timestamps(self, timestamps: list[datetime]):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(ts,) for ts in timestamps]
        session.execute.return_value = mock_result
        return session

    @pytest.mark.asyncio
    async def test_too_few_transactions(self):
        timestamps = [NOW - timedelta(hours=2), NOW - timedelta(hours=1)]
        session = self._mock_session_timestamps(timestamps)
        result = await self.rule.evaluate(
            _make_request(), EMPTY_FEATURES, session, CONFIG
        )
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_irregular_intervals(self):
        timestamps = [
            NOW - timedelta(hours=10),
            NOW - timedelta(hours=7),
            NOW - timedelta(hours=2),
            NOW - timedelta(minutes=30),
        ]
        session = self._mock_session_timestamps(timestamps)
        result = await self.rule.evaluate(
            _make_request(), EMPTY_FEATURES, session, CONFIG
        )
        assert not result.triggered  # Irregular intervals, high stddev

    @pytest.mark.asyncio
    async def test_clock_like_intervals(self):
        # Transactions exactly every 60 seconds
        timestamps = [
            NOW - timedelta(seconds=240),
            NOW - timedelta(seconds=180),
            NOW - timedelta(seconds=120),
            NOW - timedelta(seconds=60),
        ]
        session = self._mock_session_timestamps(timestamps)
        result = await self.rule.evaluate(
            _make_request(), EMPTY_FEATURES, session, CONFIG
        )
        assert result.triggered
        assert result.risk_factor == RiskFactor.TEMPORAL_STRUCTURING
        assert result.evidence["interval_stddev_seconds"] < 300.0

    @pytest.mark.asyncio
    async def test_near_clock_like_intervals(self):
        # Transactions roughly every 60 seconds with slight variation
        timestamps = [
            NOW - timedelta(seconds=245),
            NOW - timedelta(seconds=182),
            NOW - timedelta(seconds=121),
            NOW - timedelta(seconds=58),
        ]
        session = self._mock_session_timestamps(timestamps)
        result = await self.rule.evaluate(
            _make_request(), EMPTY_FEATURES, session, CONFIG
        )
        assert result.triggered  # stddev ~3s, well below 300s threshold
