"""Unit tests for geography-based fraud detection rules."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domains.fraud.config import FraudConfig
from src.domains.fraud.models import FraudScoreRequest, RiskFactor, TransactionFeatures
from src.domains.fraud.rules.geo import (
    ImpossibleTravelRule,
    NewDeviceRule,
    NewGeographyRule,
    ThirdCountrySenderRule,
    haversine,
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


def _mock_session():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    session.execute.return_value = mock_result
    return session


def _mock_session_with_countries(countries: list[str]):
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [(c,) for c in countries]
    session.execute.return_value = mock_result
    return session


class TestHaversine:
    def test_same_point(self):
        assert haversine(0, 0, 0, 0) == 0

    def test_known_distance(self):
        # NYC to London ~5570 km
        d = haversine(40.7128, -74.0060, 51.5074, -0.1278)
        assert 5500 < d < 5650

    def test_antipodal(self):
        d = haversine(0, 0, 0, 180)
        assert 20000 < d < 20100  # ~half circumference


class TestImpossibleTravelRule:
    rule = ImpossibleTravelRule()

    @pytest.mark.asyncio
    async def test_no_previous_location(self):
        result = await self.rule.evaluate(_make_request(), EMPTY_FEATURES, _mock_session(), CONFIG)
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_reasonable_speed(self):
        features = TransactionFeatures(
            last_geo_location={
                "current_lat": 40.7128,
                "current_lon": -74.0060,
                "prev_lat": 42.3601,
                "prev_lon": -71.0589,
            },
            time_since_last_txn_seconds=3600,  # 1 hour for ~300km
        )
        result = await self.rule.evaluate(_make_request(), features, _mock_session(), CONFIG)
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_impossible_speed(self):
        # NYC to London in 1 hour = ~5570 km/h
        features = TransactionFeatures(
            last_geo_location={
                "current_lat": 51.5074,
                "current_lon": -0.1278,
                "prev_lat": 40.7128,
                "prev_lon": -74.0060,
            },
            time_since_last_txn_seconds=3600,
        )
        result = await self.rule.evaluate(_make_request(), features, _mock_session(), CONFIG)
        assert result.triggered
        assert result.risk_factor == RiskFactor.IMPOSSIBLE_TRAVEL
        assert result.severity == "critical"
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_score_scales_with_speed(self):
        # Very fast (extreme)
        features = TransactionFeatures(
            last_geo_location={
                "current_lat": 51.5074,
                "current_lon": -0.1278,
                "prev_lat": 40.7128,
                "prev_lon": -74.0060,
            },
            time_since_last_txn_seconds=600,  # 10 minutes
        )
        result = await self.rule.evaluate(_make_request(), features, _mock_session(), CONFIG)
        assert result.triggered
        assert result.score > 0.5

    @pytest.mark.asyncio
    async def test_missing_coords(self):
        features = TransactionFeatures(
            last_geo_location={"current_lat": 40.0},
            time_since_last_txn_seconds=3600,
        )
        result = await self.rule.evaluate(_make_request(), features, _mock_session(), CONFIG)
        assert not result.triggered


class TestNewGeographyRule:
    rule = NewGeographyRule()

    @pytest.mark.asyncio
    async def test_known_country(self):
        features = TransactionFeatures(is_new_country=False)
        result = await self.rule.evaluate(_make_request(), features, _mock_session(), CONFIG)
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_new_country(self):
        features = TransactionFeatures(is_new_country=True)
        request = _make_request(geo_location={"country": "BR"})
        result = await self.rule.evaluate(request, features, _mock_session(), CONFIG)
        assert result.triggered
        assert result.risk_factor == RiskFactor.NEW_GEOLOCATION
        assert result.evidence["country"] == "BR"


class TestThirdCountrySenderRule:
    rule = ThirdCountrySenderRule()

    @pytest.mark.asyncio
    async def test_no_geo_location(self):
        result = await self.rule.evaluate(_make_request(), EMPTY_FEATURES, _mock_session(), CONFIG)
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_home_country_us(self):
        request = _make_request(geo_location={"country": "US"})
        result = await self.rule.evaluate(request, EMPTY_FEATURES, _mock_session(), CONFIG)
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_home_country_ht(self):
        request = _make_request(geo_location={"country": "HT"})
        result = await self.rule.evaluate(request, EMPTY_FEATURES, _mock_session(), CONFIG)
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_third_country_with_home_history(self):
        request = _make_request(geo_location={"country": "BR"})
        session = _mock_session_with_countries(["US", "HT"])
        result = await self.rule.evaluate(request, EMPTY_FEATURES, session, CONFIG)
        assert result.triggered
        assert result.risk_factor == RiskFactor.THIRD_COUNTRY_SENDER
        assert result.severity == "high"

    @pytest.mark.asyncio
    async def test_third_country_no_home_history(self):
        request = _make_request(geo_location={"country": "BR"})
        session = _mock_session_with_countries(["FR", "DE"])
        result = await self.rule.evaluate(request, EMPTY_FEATURES, session, CONFIG)
        assert not result.triggered  # No US/HT history


class TestNewDeviceRule:
    rule = NewDeviceRule()

    @pytest.mark.asyncio
    async def test_known_device(self):
        features = TransactionFeatures(is_new_device=False)
        result = await self.rule.evaluate(_make_request(), features, _mock_session(), CONFIG)
        assert not result.triggered

    @pytest.mark.asyncio
    async def test_new_device(self):
        features = TransactionFeatures(is_new_device=True)
        request = _make_request(device_id="new-device-123")
        result = await self.rule.evaluate(request, features, _mock_session(), CONFIG)
        assert result.triggered
        assert result.risk_factor == RiskFactor.NEW_DEVICE
        assert result.severity == "low"
        assert result.score == 0.3
