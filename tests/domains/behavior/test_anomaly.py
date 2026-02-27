"""Unit tests for session anomaly scoring."""

from datetime import UTC, datetime, timedelta

import pytest

from src.domains.behavior.anomaly import SessionAnomalyScorer, _haversine
from src.domains.behavior.config import BehaviorConfig
from src.domains.behavior.models import (
    AnomalyClassification,
    DeviceBaseline,
    EngagementBaseline,
    GeographicBaseline,
    ProfileStatus,
    RecommendedAction,
    SessionBaseline,
    TemporalBaseline,
    UserBehaviorProfile,
)


@pytest.fixture
def scorer() -> SessionAnomalyScorer:
    return SessionAnomalyScorer()


@pytest.fixture
def established_profile() -> UserBehaviorProfile:
    """Profile for an established user in Boston who logs in 6-10 PM."""
    return UserBehaviorProfile(
        user_id="user-boston",
        profile_status=ProfileStatus.ACTIVE,
        profile_maturity=25,
        session_baseline=SessionBaseline(
            avg_duration=300.0,
            std_duration=60.0,
            avg_actions=6.0,
            std_actions=2.0,
            typical_action_sequences=[["check_circles", "view_balance", "send_remittance"]],
        ),
        temporal_baseline=TemporalBaseline(
            typical_hours={18: 0.3, 19: 0.35, 20: 0.25, 21: 0.1},
            typical_days={0: 0.2, 1: 0.2, 2: 0.15, 3: 0.15, 4: 0.15, 5: 0.1, 6: 0.05},
            typical_frequency_mean=5.0,
            typical_frequency_std=1.5,
        ),
        device_baseline=DeviceBaseline(
            known_devices=["device-iphone-14", "device-ipad"],
            primary_device="device-iphone-14",
            device_switch_rate=0.15,
            device_platforms=["ios"],
        ),
        geographic_baseline=GeographicBaseline(
            known_locations=[
                {"city": "Boston", "country": "US"},
                {"city": "Port-au-Prince", "country": "HT"},
            ],
            primary_location={"city": "Boston", "country": "US"},
        ),
        engagement_baseline=EngagementBaseline(
            typical_features_used=["check_circles", "view_balance", "send_remittance"],
            feature_usage_breadth=0.5,
            avg_sessions_per_week=5.0,
        ),
        last_updated=datetime.now(UTC),
    )


@pytest.fixture
def building_profile() -> UserBehaviorProfile:
    """Profile for a new user with only 3 sessions."""
    return UserBehaviorProfile(
        user_id="user-new",
        profile_status=ProfileStatus.BUILDING,
        profile_maturity=3,
        session_baseline=SessionBaseline(avg_duration=200.0, std_duration=50.0),
        temporal_baseline=TemporalBaseline(typical_hours={14: 0.5, 15: 0.5}),
        device_baseline=DeviceBaseline(
            known_devices=["device-android-1"],
            primary_device="device-android-1",
            device_platforms=["android"],
        ),
        geographic_baseline=GeographicBaseline(
            known_locations=[{"city": "Miami", "country": "US"}],
            primary_location={"city": "Miami", "country": "US"},
        ),
        last_updated=datetime.now(UTC),
    )


def _normal_session(user_id: str = "user-boston") -> dict:
    """A perfectly normal session for the established user."""
    return {
        "session_id": "session-normal",
        "user_id": user_id,
        "device_id": "device-iphone-14",
        "device_type": "ios",
        "ip_address": "10.0.1.50",
        "geo_location": {"city": "Boston", "country": "US", "lat": 42.36, "lon": -71.06},
        "session_start": datetime(2026, 1, 15, 19, 0, tzinfo=UTC).isoformat(),
        "session_duration_seconds": 320,
        "action_count": 5,
        "actions": ["check_circles", "view_balance", "send_remittance"],
    }


def _anomalous_session() -> dict:
    """A classic ATO session: new device, new location, unusual hour, sensitive actions."""
    return {
        "session_id": "session-ato",
        "user_id": "user-boston",
        "device_id": "device-unknown-android",
        "device_type": "android",
        "ip_address": "195.22.33.44",
        "geo_location": {"city": "Lagos", "country": "NG", "lat": 6.52, "lon": 3.38},
        "session_start": datetime(2026, 1, 15, 3, 0, tzinfo=UTC).isoformat(),
        "session_duration_seconds": 45,
        "action_count": 12,
        "actions": [
            "change_email", "change_phone", "add_payment_method",
            "initiate_large_transaction", "update_security_settings",
        ],
    }


class TestSessionAnomalyScorer:
    async def test_normal_session_low_score(self, scorer, established_profile):
        result = await scorer.score_session(
            _normal_session(), established_profile, feast_features={}
        )
        assert result.composite_score < 0.3
        assert result.classification == AnomalyClassification.NORMAL
        assert result.recommended_action == RecommendedAction.NONE

    async def test_anomalous_session_high_score(self, scorer, established_profile):
        result = await scorer.score_session(
            _anomalous_session(), established_profile, feast_features={}
        )
        assert result.composite_score > 0.3
        assert result.classification in (
            AnomalyClassification.SUSPICIOUS,
            AnomalyClassification.HIGH_RISK,
            AnomalyClassification.CRITICAL,
        )

    async def test_no_profile_graceful(self, scorer):
        result = await scorer.score_session(
            _normal_session(), None, feast_features={}
        )
        assert result.composite_score >= 0.0
        assert result.profile_maturity == 0

    async def test_building_profile_reduced_score(self, scorer, building_profile):
        session = _anomalous_session()
        session["user_id"] = "user-new"

        result = await scorer.score_session(
            session, building_profile, feast_features={}
        )
        # Building profiles get 0.6x multiplier on composite score
        assert result.composite_score <= 0.6 * 1.0

    async def test_dimension_scores_present(self, scorer, established_profile):
        result = await scorer.score_session(
            _normal_session(), established_profile, feast_features={}
        )
        dimensions = {d.dimension for d in result.dimension_scores}
        assert "temporal" in dimensions
        assert "device" in dimensions
        assert "geographic" in dimensions
        assert "behavioral" in dimensions
        assert "engagement" in dimensions

    async def test_dimension_scores_bounded(self, scorer, established_profile):
        result = await scorer.score_session(
            _anomalous_session(), established_profile, feast_features={}
        )
        for dim in result.dimension_scores:
            assert 0.0 <= dim.score <= 1.0


class TestTemporalScoring:
    async def test_normal_hour(self, scorer, established_profile):
        session = _normal_session()
        session["session_start"] = datetime(2026, 1, 15, 19, 0, tzinfo=UTC).isoformat()
        result = scorer._score_temporal(session, established_profile, {})
        assert result.score < 0.3

    async def test_unusual_hour(self, scorer, established_profile):
        session = _normal_session()
        session["session_start"] = datetime(2026, 1, 15, 3, 0, tzinfo=UTC).isoformat()
        result = scorer._score_temporal(session, established_profile, {})
        assert result.score > 0.3

    async def test_feast_features_used(self, scorer, established_profile):
        features = {
            "current_session_hour_deviation": 4.0,
            "typical_login_hour_mean": 19.0,
            "typical_login_hour_std": 1.0,
        }
        result = scorer._score_temporal(_normal_session(), established_profile, features)
        assert result.score > 0.5  # 4 std deviations = highly anomalous


class TestDeviceScoring:
    async def test_known_device(self, scorer, established_profile):
        session = _normal_session()
        result = scorer._score_device(session, established_profile, {})
        assert result.score == 0.0

    async def test_new_device_same_platform(self, scorer, established_profile):
        session = _normal_session()
        session["device_id"] = "device-iphone-15"
        session["device_type"] = "ios"
        result = scorer._score_device(session, established_profile, {"new_device_flag": True})
        assert 0.3 <= result.score <= 0.7

    async def test_new_device_cross_platform(self, scorer, established_profile):
        session = _normal_session()
        session["device_id"] = "device-android-unknown"
        session["device_type"] = "android"
        result = scorer._score_device(session, established_profile, {"new_device_flag": True})
        # Cross-platform switch should boost the score
        assert result.score > 0.5

    async def test_multi_device_user_reduced_anomaly(self, scorer, established_profile):
        session = _normal_session()
        session["device_id"] = "device-new"
        result = scorer._score_device(
            session, established_profile, {"new_device_flag": True, "distinct_devices_30d": 5}
        )
        # User who regularly uses 5+ devices — new device is less anomalous
        simple_result = scorer._score_device(
            session, established_profile, {"new_device_flag": True, "distinct_devices_30d": 1}
        )
        assert result.score < simple_result.score


class TestGeographicScoring:
    async def test_known_location(self, scorer, established_profile):
        session = _normal_session()
        result = scorer._score_geographic(session, established_profile, {})
        assert result.score == 0.0

    async def test_haiti_corridor_reduced_anomaly(self, scorer, established_profile):
        """US <-> HT travel should have reduced anomaly for Trebanx users."""
        session = _normal_session()
        session["geo_location"] = {"city": "Port-au-Prince", "country": "HT"}
        result = scorer._score_geographic(session, established_profile, {})
        # Haiti is a known location for this user, so should be 0
        assert result.score == 0.0

    async def test_new_haiti_location_corridor_aware(self, scorer):
        """User who's only been in US, now in HT — corridor reduces anomaly."""
        us_only_profile = UserBehaviorProfile(
            user_id="user-us",
            profile_status=ProfileStatus.ACTIVE,
            profile_maturity=20,
            geographic_baseline=GeographicBaseline(
                known_locations=[{"city": "Boston", "country": "US"}],
                primary_location={"city": "Boston", "country": "US"},
            ),
            last_updated=datetime.now(UTC),
        )
        session = _normal_session()
        session["geo_location"] = {"city": "Cap-Haitien", "country": "HT"}
        result = scorer._score_geographic(session, us_only_profile, {})
        # New HT location but within corridor — reduced anomaly
        assert result.score < 0.4

    async def test_third_country_high_anomaly(self, scorer, established_profile):
        """Session from unexpected third country (not US or HT)."""
        session = _normal_session()
        session["geo_location"] = {"city": "Lagos", "country": "NG"}
        result = scorer._score_geographic(session, established_profile, {})
        assert result.score >= 0.5

    async def test_impossible_travel(self, scorer, established_profile):
        session = _normal_session()
        session["geo_location"] = {"city": "Tokyo", "country": "JP"}
        result = scorer._score_geographic(
            session, established_profile, {"max_travel_speed_24h": 2000}
        )
        assert result.score >= 0.9


class TestBehavioralScoring:
    async def test_normal_duration_and_actions(self, scorer, established_profile):
        session = _normal_session()
        result = scorer._score_behavioral(session, established_profile, {})
        assert result.score < 0.3

    async def test_sensitive_actions_elevated(self, scorer, established_profile):
        session = _normal_session()
        session["actions"] = ["change_email", "change_phone", "change_password"]
        result = scorer._score_behavioral(session, established_profile, {})
        assert result.score > 0.3

    async def test_bot_like_speed(self, scorer, established_profile):
        session = _normal_session()
        session["session_duration_seconds"] = 5  # 5 seconds
        session["action_count"] = 20  # 4 actions/sec
        result = scorer._score_behavioral(session, established_profile, {})
        assert result.score >= 0.7


class TestEngagementScoring:
    async def test_normal_activity(self, scorer, established_profile):
        result = scorer._score_engagement(
            _normal_session(), established_profile, {"days_since_last_login": 1}
        )
        assert result.score < 0.3

    async def test_return_from_dormancy(self, scorer, established_profile):
        result = scorer._score_engagement(
            _normal_session(), established_profile, {"days_since_last_login": 35}
        )
        assert result.score >= 0.5

    async def test_unfamiliar_features(self, scorer, established_profile):
        session = _normal_session()
        session["actions"] = ["admin_panel", "export_data", "api_key_management"]
        result = scorer._score_engagement(
            session, established_profile, {"days_since_last_login": 1}
        )
        assert result.score > 0.3


class TestClassification:
    async def test_normal_classification(self, scorer):
        thresholds = scorer._config.anomaly_thresholds
        assert scorer._classify(0.1, thresholds) == AnomalyClassification.NORMAL
        assert scorer._classify(0.29, thresholds) == AnomalyClassification.NORMAL

    async def test_suspicious_classification(self, scorer):
        thresholds = scorer._config.anomaly_thresholds
        assert scorer._classify(0.35, thresholds) == AnomalyClassification.SUSPICIOUS
        assert scorer._classify(0.59, thresholds) == AnomalyClassification.SUSPICIOUS

    async def test_high_risk_classification(self, scorer):
        thresholds = scorer._config.anomaly_thresholds
        assert scorer._classify(0.65, thresholds) == AnomalyClassification.HIGH_RISK
        assert scorer._classify(0.79, thresholds) == AnomalyClassification.HIGH_RISK

    async def test_critical_classification(self, scorer):
        thresholds = scorer._config.anomaly_thresholds
        assert scorer._classify(0.85, thresholds) == AnomalyClassification.CRITICAL
        assert scorer._classify(1.0, thresholds) == AnomalyClassification.CRITICAL


class TestRecommendedAction:
    def test_action_mapping(self, scorer):
        assert scorer._recommend_action(AnomalyClassification.NORMAL) == RecommendedAction.NONE
        assert scorer._recommend_action(AnomalyClassification.SUSPICIOUS) == RecommendedAction.MONITOR
        assert scorer._recommend_action(AnomalyClassification.HIGH_RISK) == RecommendedAction.CHALLENGE
        assert scorer._recommend_action(AnomalyClassification.CRITICAL) == RecommendedAction.TERMINATE


class TestHaversine:
    def test_same_point(self):
        assert _haversine(42.36, -71.06, 42.36, -71.06) == 0.0

    def test_known_distance(self):
        # Boston to New York ~305 km
        dist = _haversine(42.36, -71.06, 40.71, -74.01)
        assert 280 < dist < 340

    def test_boston_to_port_au_prince(self):
        # Boston to Port-au-Prince ~2,500 km
        dist = _haversine(42.36, -71.06, 18.54, -72.34)
        assert 2400 < dist < 2700
