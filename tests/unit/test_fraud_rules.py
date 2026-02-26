"""Unit tests for individual fraud detection rules."""

from src.domains.fraud.models import RiskFactor, TransactionFeatures
from src.domains.fraud.rules import (
    HighAmountRule,
    ImpossibleTravelRule,
    NewDeviceRule,
    NewGeolocationRule,
    StructuringNear3kRule,
    StructuringNear10kRule,
    UnusualHourEvaluator,
    VelocityAmount24hRule,
    VelocityCount1hRule,
    VelocityCount24hRule,
    haversine,
)

EMPTY_FEATURES = TransactionFeatures()


class TestHaversine:
    def test_same_point(self):
        assert haversine(0, 0, 0, 0) == 0

    def test_known_distance(self):
        # NYC to London ~5570 km
        d = haversine(40.7128, -74.0060, 51.5074, -0.1278)
        assert 5500 < d < 5650


class TestHighAmountRule:
    rule = HighAmountRule()

    def test_below_threshold(self):
        result = self.rule.evaluate(4999, EMPTY_FEATURES)
        assert not result.triggered
        assert result.score == 0.0

    def test_at_threshold(self):
        result = self.rule.evaluate(5000, EMPTY_FEATURES)
        assert result.triggered
        assert result.score == 10
        assert result.risk_factor == RiskFactor.HIGH_AMOUNT

    def test_high_amount_scales(self):
        result = self.rule.evaluate(20000, EMPTY_FEATURES)
        assert result.triggered
        assert 10 < result.score <= 40

    def test_very_high_amount_caps(self):
        result = self.rule.evaluate(100000, EMPTY_FEATURES)
        assert result.triggered
        assert result.score == 40


class TestStructuringNear3kRule:
    rule = StructuringNear3kRule()

    def test_below_range(self):
        result = self.rule.evaluate(2799, EMPTY_FEATURES)
        assert not result.triggered

    def test_above_range(self):
        result = self.rule.evaluate(3000, EMPTY_FEATURES)
        assert not result.triggered

    def test_at_lower_bound(self):
        result = self.rule.evaluate(2800, EMPTY_FEATURES)
        assert result.triggered
        assert result.score == 25
        assert result.risk_factor == RiskFactor.STRUCTURING_NEAR_3K

    def test_near_upper_bound(self):
        result = self.rule.evaluate(2999, EMPTY_FEATURES)
        assert result.triggered
        assert result.score == 40


class TestStructuringNear10kRule:
    rule = StructuringNear10kRule()

    def test_below_range(self):
        result = self.rule.evaluate(9499, EMPTY_FEATURES)
        assert not result.triggered

    def test_above_range(self):
        result = self.rule.evaluate(10000, EMPTY_FEATURES)
        assert not result.triggered

    def test_at_lower_bound(self):
        result = self.rule.evaluate(9500, EMPTY_FEATURES)
        assert result.triggered
        assert result.score == 30
        assert result.risk_factor == RiskFactor.STRUCTURING_NEAR_10K

    def test_near_upper_bound(self):
        result = self.rule.evaluate(9999, EMPTY_FEATURES)
        assert result.triggered
        assert result.score == 50


class TestVelocityCount1hRule:
    rule = VelocityCount1hRule()

    def test_below_threshold(self):
        features = TransactionFeatures(velocity_count_1h=4)
        result = self.rule.evaluate(100, features)
        assert not result.triggered

    def test_at_threshold(self):
        features = TransactionFeatures(velocity_count_1h=5)
        result = self.rule.evaluate(100, features)
        assert result.triggered
        assert result.score == 15
        assert result.risk_factor == RiskFactor.VELOCITY_COUNT_1H

    def test_high_velocity_caps(self):
        features = TransactionFeatures(velocity_count_1h=20)
        result = self.rule.evaluate(100, features)
        assert result.triggered
        assert result.score == 50


class TestVelocityCount24hRule:
    rule = VelocityCount24hRule()

    def test_below_threshold(self):
        features = TransactionFeatures(velocity_count_24h=19)
        result = self.rule.evaluate(100, features)
        assert not result.triggered

    def test_at_threshold(self):
        features = TransactionFeatures(velocity_count_24h=20)
        result = self.rule.evaluate(100, features)
        assert result.triggered
        assert result.score == 15
        assert result.risk_factor == RiskFactor.VELOCITY_COUNT_24H


class TestVelocityAmount24hRule:
    rule = VelocityAmount24hRule()

    def test_below_threshold(self):
        features = TransactionFeatures(velocity_amount_24h=5000)
        result = self.rule.evaluate(4999, features)
        assert not result.triggered

    def test_at_threshold(self):
        features = TransactionFeatures(velocity_amount_24h=5000)
        result = self.rule.evaluate(5000, features)
        assert result.triggered
        assert result.score == 15
        assert result.risk_factor == RiskFactor.VELOCITY_AMOUNT_24H

    def test_high_amount(self):
        features = TransactionFeatures(velocity_amount_24h=40000)
        result = self.rule.evaluate(10000, features)
        assert result.triggered
        assert result.score == 45


class TestNewDeviceRule:
    rule = NewDeviceRule()

    def test_known_device(self):
        features = TransactionFeatures(is_new_device=False)
        result = self.rule.evaluate(100, features)
        assert not result.triggered

    def test_new_device(self):
        features = TransactionFeatures(is_new_device=True)
        result = self.rule.evaluate(100, features)
        assert result.triggered
        assert result.score == 15
        assert result.risk_factor == RiskFactor.NEW_DEVICE


class TestNewGeolocationRule:
    rule = NewGeolocationRule()

    def test_known_country(self):
        features = TransactionFeatures(is_new_country=False)
        result = self.rule.evaluate(100, features)
        assert not result.triggered

    def test_new_country(self):
        features = TransactionFeatures(is_new_country=True)
        result = self.rule.evaluate(100, features)
        assert result.triggered
        assert result.score == 20
        assert result.risk_factor == RiskFactor.NEW_GEOLOCATION


class TestImpossibleTravelRule:
    rule = ImpossibleTravelRule()

    def test_no_previous_location(self):
        result = self.rule.evaluate(100, EMPTY_FEATURES)
        assert not result.triggered

    def test_reasonable_speed(self):
        features = TransactionFeatures(
            last_geo_location={
                "current_lat": 40.7128,
                "current_lon": -74.0060,
                "prev_lat": 42.3601,
                "prev_lon": -71.0589,
            },
            time_since_last_txn_seconds=3600,  # 1 hour for ~300km
        )
        result = self.rule.evaluate(100, features)
        assert not result.triggered

    def test_impossible_speed(self):
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
        result = self.rule.evaluate(100, features)
        assert result.triggered
        assert result.score == 35
        assert result.risk_factor == RiskFactor.IMPOSSIBLE_TRAVEL


class TestUnusualHourEvaluator:
    def test_normal_hour(self):
        result = UnusualHourEvaluator.evaluate(10)
        assert not result.triggered

    def test_unusual_hour_2am(self):
        result = UnusualHourEvaluator.evaluate(2)
        assert result.triggered
        assert result.score == 10
        assert result.risk_factor == RiskFactor.UNUSUAL_HOUR

    def test_unusual_hour_4am(self):
        result = UnusualHourEvaluator.evaluate(4)
        assert result.triggered

    def test_boundary_5am_not_unusual(self):
        result = UnusualHourEvaluator.evaluate(5)
        assert not result.triggered
