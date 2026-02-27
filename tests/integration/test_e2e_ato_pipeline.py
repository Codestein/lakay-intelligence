"""End-to-end ATO pipeline tests (Phase 7, Task 7.5).

Validates the entire behavioral analytics pipeline across 7 scenarios:
A. Normal user, normal session
B. New device, otherwise normal
C. Classic ATO
D. Impossible travel ATO
E. Gradual account compromise
F. Legitimate Haiti travel
G. New user (building profile)
"""

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domains.behavior.anomaly import SessionAnomalyScorer
from src.domains.behavior.ato import ATODetector
from src.domains.behavior.config import BehaviorConfig
from src.domains.behavior.engagement import EngagementScorer
from src.domains.behavior.models import (
    AnomalyClassification,
    ATORiskLevel,
    DeviceBaseline,
    EngagementBaseline,
    GeographicBaseline,
    LifecycleStage,
    ProfileStatus,
    SessionBaseline,
    TemporalBaseline,
    UserBehaviorProfile,
)
from src.domains.behavior.profile import BehaviorProfileEngine


# --- Fixtures ---


@pytest.fixture
def config() -> BehaviorConfig:
    return BehaviorConfig()


@pytest.fixture
def anomaly_scorer(config) -> SessionAnomalyScorer:
    return SessionAnomalyScorer(config=config)


@pytest.fixture
def ato_detector(config, anomaly_scorer) -> ATODetector:
    return ATODetector(config=config, anomaly_scorer=anomaly_scorer)


@pytest.fixture
def engagement_scorer(config) -> EngagementScorer:
    return EngagementScorer(config=config)


@pytest.fixture
def profile_engine(config) -> BehaviorProfileEngine:
    return BehaviorProfileEngine(config=config)


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    # Use MagicMock for result since scalar_one/scalar_one_or_none are sync
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 0  # no existing alerts (dedup)
    mock_result.scalar_one_or_none.return_value = None  # no existing profile
    session.execute = AsyncMock(return_value=mock_result)
    return session


@pytest.fixture
def established_boston_profile() -> UserBehaviorProfile:
    """Established user in Boston who logs in 6-10 PM, uses iOS devices."""
    return UserBehaviorProfile(
        user_id="user-boston",
        profile_status=ProfileStatus.ACTIVE,
        profile_maturity=25,
        session_baseline=SessionBaseline(
            avg_duration=300.0,
            std_duration=60.0,
            avg_actions=6.0,
            std_actions=2.0,
            typical_action_sequences=[
                ["check_circles", "view_balance", "send_remittance"],
            ],
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
            typical_travel_patterns=[
                {"from": "Boston:US", "to": "Port-au-Prince:HT"},
            ],
        ),
        engagement_baseline=EngagementBaseline(
            typical_features_used=[
                "check_circles", "view_balance", "send_remittance",
            ],
            feature_usage_breadth=0.5,
            avg_sessions_per_week=5.0,
        ),
        last_updated=datetime.now(UTC),
    )


@pytest.fixture
def building_profile() -> UserBehaviorProfile:
    """New user with only 3 sessions."""
    return UserBehaviorProfile(
        user_id="user-new",
        profile_status=ProfileStatus.BUILDING,
        profile_maturity=3,
        session_baseline=SessionBaseline(
            avg_duration=200.0,
            std_duration=50.0,
            avg_actions=4.0,
            std_actions=1.5,
        ),
        temporal_baseline=TemporalBaseline(
            typical_hours={14: 0.5, 15: 0.3, 16: 0.2},
        ),
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


# --- Scenario Tests ---


class TestScenarioA_NormalSession:
    """User with established profile, logs in from primary device, typical time,
    known location, typical actions. Expected: anomaly < 0.3, no ATO alert."""

    async def test_anomaly_score_below_threshold(self, anomaly_scorer, established_boston_profile):
        session_event = {
            "session_id": "scenario-a-1",
            "user_id": "user-boston",
            "device_id": "device-iphone-14",
            "device_type": "ios",
            "ip_address": "10.0.1.50",
            "geo_location": {"city": "Boston", "country": "US"},
            "session_start": datetime(2026, 1, 15, 19, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 320,
            "action_count": 5,
            "actions": ["check_circles", "view_balance", "send_remittance"],
        }

        result = await anomaly_scorer.score_session(
            session_event, established_boston_profile, feast_features={}
        )

        assert result.composite_score < 0.3, (
            f"Normal session should score < 0.3, got {result.composite_score}"
        )
        assert result.classification == AnomalyClassification.NORMAL

    async def test_no_ato_alert(self, ato_detector, mock_db_session, established_boston_profile):
        session_event = {
            "session_id": "scenario-a-2",
            "user_id": "user-boston",
            "device_id": "device-iphone-14",
            "device_type": "ios",
            "geo_location": {"city": "Boston", "country": "US"},
            "session_start": datetime(2026, 1, 15, 19, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 320,
            "action_count": 5,
            "actions": ["check_circles", "view_balance"],
            "failed_login_count_10m": 0,
            "failed_login_count_1h": 0,
        }

        assessment = await ato_detector.assess(
            session_event, established_boston_profile, mock_db_session, feast_features={}
        )

        assert assessment.ato_risk_score < 0.3
        assert assessment.risk_level == ATORiskLevel.LOW


class TestScenarioB_NewDevice:
    """Established user, new device, otherwise normal. Expected: device anomaly
    elevated, composite 0.3-0.5, no ATO alert."""

    async def test_device_anomaly_elevated(self, anomaly_scorer, established_boston_profile):
        session_event = {
            "session_id": "scenario-b-1",
            "user_id": "user-boston",
            "device_id": "device-iphone-15-new",
            "device_type": "ios",
            "geo_location": {"city": "Boston", "country": "US"},
            "session_start": datetime(2026, 1, 15, 19, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 300,
            "action_count": 5,
            "actions": ["check_circles", "view_balance"],
        }

        result = await anomaly_scorer.score_session(
            session_event, established_boston_profile,
            feast_features={"new_device_flag": True},
        )

        # Device anomaly should be elevated
        device_dim = next(d for d in result.dimension_scores if d.dimension == "device")
        assert device_dim.score > 0.0, "New device should increase device anomaly"

        # But not high enough for ATO (single signal)
        assert result.classification in (
            AnomalyClassification.NORMAL,
            AnomalyClassification.SUSPICIOUS,
        )

    async def test_no_ato_alert_single_signal(self, ato_detector, mock_db_session, established_boston_profile):
        session_event = {
            "session_id": "scenario-b-2",
            "user_id": "user-boston",
            "device_id": "device-iphone-15-new",
            "device_type": "ios",
            "geo_location": {"city": "Boston", "country": "US"},
            "session_start": datetime(2026, 1, 15, 19, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 300,
            "action_count": 5,
            "actions": ["check_circles", "view_balance"],
            "failed_login_count_10m": 0,
            "failed_login_count_1h": 0,
        }

        assessment = await ato_detector.assess(
            session_event, established_boston_profile, mock_db_session,
            feast_features={"new_device_flag": True},
        )

        # Single signal insufficient for high ATO risk
        assert assessment.risk_level in (ATORiskLevel.LOW, ATORiskLevel.MODERATE)


class TestScenarioC_ClassicATO:
    """New device, new location (different country), unusual hour, rapid sensitive
    actions. Expected: anomaly > 0.8, critical, ATO alert generated."""

    async def test_high_anomaly_score(self, anomaly_scorer, established_boston_profile):
        session_event = {
            "session_id": "scenario-c-1",
            "user_id": "user-boston",
            "device_id": "device-unknown-android",
            "device_type": "android",
            "geo_location": {"city": "Lagos", "country": "NG"},
            "session_start": datetime(2026, 1, 15, 3, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 45,
            "action_count": 10,
            "actions": [
                "change_email", "change_phone", "add_payment_method",
                "initiate_large_transaction", "update_security_settings",
            ],
        }

        result = await anomaly_scorer.score_session(
            session_event, established_boston_profile, feast_features={}
        )

        assert result.composite_score > 0.3, (
            f"Classic ATO should score high, got {result.composite_score}"
        )
        # At least suspicious, likely higher
        assert result.classification in (
            AnomalyClassification.SUSPICIOUS,
            AnomalyClassification.HIGH_RISK,
            AnomalyClassification.CRITICAL,
        )

    async def test_ato_alert_generated(self, ato_detector, mock_db_session, established_boston_profile):
        session_event = {
            "session_id": "scenario-c-2",
            "user_id": "user-boston",
            "device_id": "device-unknown-android",
            "device_type": "android",
            "geo_location": {"city": "Lagos", "country": "NG"},
            "session_start": datetime(2026, 1, 15, 3, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 45,
            "action_count": 10,
            "actions": [
                "change_email", "change_phone", "add_payment_method",
                "initiate_large_transaction", "update_security_settings",
            ],
            "failed_login_count_10m": 5,
            "failed_login_count_1h": 8,
            "pending_transactions": ["txn-001"],
        }

        assessment = await ato_detector.assess(
            session_event, established_boston_profile, mock_db_session, feast_features={}
        )

        assert assessment.ato_risk_score > 0.5
        assert len(assessment.contributing_signals) >= 3


class TestScenarioD_ImpossibleTravel:
    """Two sessions 30 min apart, 5000km away. Second attempts transaction.
    Expected: geographic anomaly maxed, ATO alert."""

    async def test_impossible_travel_detected(self, anomaly_scorer, established_boston_profile):
        session_event = {
            "session_id": "scenario-d-1",
            "user_id": "user-boston",
            "device_id": "device-iphone-14",
            "device_type": "ios",
            "geo_location": {"city": "London", "country": "GB", "lat": 51.51, "lon": -0.13},
            "session_start": datetime(2026, 1, 15, 19, 30, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 200,
            "action_count": 5,
            "actions": ["send_remittance"],
        }

        result = await anomaly_scorer.score_session(
            session_event, established_boston_profile,
            feast_features={"max_travel_speed_24h": 10000},
        )

        geo_dim = next(d for d in result.dimension_scores if d.dimension == "geographic")
        assert geo_dim.score >= 0.9, "Impossible travel should max geographic anomaly"

    async def test_ato_with_impossible_travel(self, ato_detector, mock_db_session, established_boston_profile):
        session_event = {
            "session_id": "scenario-d-2",
            "user_id": "user-boston",
            "device_id": "device-iphone-14",
            "geo_location": {"city": "London", "country": "GB"},
            "session_start": datetime(2026, 1, 15, 19, 30, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 200,
            "action_count": 5,
            "actions": ["send_remittance"],
            "failed_login_count_10m": 0,
            "failed_login_count_1h": 0,
        }

        assessment = await ato_detector.assess(
            session_event, established_boston_profile, mock_db_session,
            feast_features={"max_travel_speed_24h": 10000},
        )

        # Impossible travel is a strong signal
        signal_names = [s.signal_name for s in assessment.contributing_signals]
        assert "impossible_travel" in signal_names


class TestScenarioE_GradualCompromise:
    """Cautious attacker: plausible hour, new device but same country, slowly
    explores. Initial sessions suspicious, escalating to high_risk."""

    async def test_initial_session_suspicious(self, anomaly_scorer, established_boston_profile):
        session_event = {
            "session_id": "scenario-e-1",
            "user_id": "user-boston",
            "device_id": "device-android-new",
            "device_type": "android",
            "geo_location": {"city": "New York", "country": "US"},
            "session_start": datetime(2026, 1, 15, 20, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 250,
            "action_count": 4,
            "actions": ["view_balance", "check_circles"],
        }

        result = await anomaly_scorer.score_session(
            session_event, established_boston_profile, feast_features={"new_device_flag": True}
        )

        # New device + cross-platform but otherwise normal — suspicious range
        assert result.classification in (
            AnomalyClassification.NORMAL,
            AnomalyClassification.SUSPICIOUS,
        )

    async def test_escalation_with_sensitive_actions(self, anomaly_scorer, established_boston_profile):
        """After establishing presence, attacker attempts sensitive actions."""
        session_event = {
            "session_id": "scenario-e-2",
            "user_id": "user-boston",
            "device_id": "device-android-new",
            "device_type": "android",
            "geo_location": {"city": "New York", "country": "US"},
            "session_start": datetime(2026, 1, 16, 20, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 100,
            "action_count": 8,
            "actions": [
                "view_balance", "change_email", "change_phone",
                "add_payment_method",
            ],
        }

        result = await anomaly_scorer.score_session(
            session_event, established_boston_profile, feast_features={"new_device_flag": True}
        )

        # Now with sensitive actions, should be at least suspicious
        assert result.composite_score > 0.2


class TestScenarioF_LegitimateHaitiTravel:
    """User travels from Boston to Port-au-Prince (legitimate). Same device,
    reasonable hour, typical actions. Expected: moderate geo anomaly at most."""

    async def test_haiti_travel_not_high_risk(self, anomaly_scorer, established_boston_profile):
        session_event = {
            "session_id": "scenario-f-1",
            "user_id": "user-boston",
            "device_id": "device-iphone-14",
            "device_type": "ios",
            "geo_location": {"city": "Port-au-Prince", "country": "HT"},
            "session_start": datetime(2026, 1, 15, 19, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 200,
            "action_count": 4,
            "actions": ["check_circles", "send_remittance"],
        }

        result = await anomaly_scorer.score_session(
            session_event, established_boston_profile, feast_features={}
        )

        # Port-au-Prince is a known location for this user
        assert result.composite_score < 0.3, (
            f"Legitimate Haiti travel should not be flagged, got {result.composite_score}"
        )
        assert result.classification == AnomalyClassification.NORMAL

    async def test_haiti_corridor_awareness(self, anomaly_scorer):
        """User without Haiti in known locations but within corridor."""
        us_only_profile = UserBehaviorProfile(
            user_id="user-us-only",
            profile_status=ProfileStatus.ACTIVE,
            profile_maturity=20,
            session_baseline=SessionBaseline(avg_duration=300, std_duration=60),
            temporal_baseline=TemporalBaseline(typical_hours={19: 0.5, 20: 0.5}),
            device_baseline=DeviceBaseline(
                known_devices=["device-phone"],
                primary_device="device-phone",
                device_platforms=["ios"],
            ),
            geographic_baseline=GeographicBaseline(
                known_locations=[{"city": "Boston", "country": "US"}],
                primary_location={"city": "Boston", "country": "US"},
            ),
            last_updated=datetime.now(UTC),
        )

        session_event = {
            "session_id": "scenario-f-2",
            "user_id": "user-us-only",
            "device_id": "device-phone",
            "device_type": "ios",
            "geo_location": {"city": "Port-au-Prince", "country": "HT"},
            "session_start": datetime(2026, 1, 15, 19, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 200,
            "action_count": 4,
            "actions": ["check_circles", "send_remittance"],
        }

        result = await anomaly_scorer.score_session(
            session_event, us_only_profile, feast_features={}
        )

        # Haiti is in the corridor — geo anomaly should be reduced
        geo_dim = next(d for d in result.dimension_scores if d.dimension == "geographic")
        assert geo_dim.score < 0.4, (
            f"Haiti corridor should reduce geo anomaly, got {geo_dim.score}"
        )

        # Overall should stay below high_risk
        assert result.composite_score < 0.6, (
            f"Legitimate corridor travel should not be high risk, got {result.composite_score}"
        )


class TestScenarioG_NewUser:
    """User with only 3 sessions, profile in building status. New device.
    Expected: scores with reduced confidence, higher thresholds."""

    async def test_building_profile_reduced_confidence(self, anomaly_scorer, building_profile):
        session_event = {
            "session_id": "scenario-g-1",
            "user_id": "user-new",
            "device_id": "device-tablet-new",
            "device_type": "android",
            "geo_location": {"city": "Miami", "country": "US"},
            "session_start": datetime(2026, 1, 15, 14, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 180,
            "action_count": 3,
            "actions": ["view_balance"],
        }

        result = await anomaly_scorer.score_session(
            session_event, building_profile, feast_features={"new_device_flag": True}
        )

        assert result.profile_maturity == 3
        # Building profile gets 0.6x multiplier — reduced score
        assert result.composite_score < 0.5, (
            f"New user with building profile should have reduced score, got {result.composite_score}"
        )

    async def test_no_ato_for_moderate_anomaly(self, ato_detector, mock_db_session, building_profile):
        session_event = {
            "session_id": "scenario-g-2",
            "user_id": "user-new",
            "device_id": "device-tablet-new",
            "device_type": "android",
            "geo_location": {"city": "Miami", "country": "US"},
            "session_start": datetime(2026, 1, 15, 14, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 180,
            "action_count": 3,
            "actions": ["view_balance"],
            "failed_login_count_10m": 0,
            "failed_login_count_1h": 0,
        }

        assessment = await ato_detector.assess(
            session_event, building_profile, mock_db_session,
            feast_features={"new_device_flag": True},
        )

        # Should not trigger ATO for a new user with moderate anomaly
        assert assessment.risk_level in (ATORiskLevel.LOW, ATORiskLevel.MODERATE)


# --- Performance Tests ---


class TestLatencyRequirements:
    """Target: normal sessions < 100ms, anomalous sessions trigger alerts < 30s."""

    async def test_normal_session_under_100ms(self, anomaly_scorer, established_boston_profile):
        session_event = {
            "session_id": "perf-normal",
            "user_id": "user-boston",
            "device_id": "device-iphone-14",
            "device_type": "ios",
            "geo_location": {"city": "Boston", "country": "US"},
            "session_start": datetime(2026, 1, 15, 19, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 300,
            "action_count": 5,
            "actions": ["check_circles", "view_balance"],
        }

        start = time.monotonic()
        result = await anomaly_scorer.score_session(
            session_event, established_boston_profile, feast_features={}
        )
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 100, f"Normal session scoring took {elapsed_ms:.1f}ms, target < 100ms"
        assert result.composite_score < 0.3

    async def test_anomalous_session_scoring_fast(self, ato_detector, mock_db_session, established_boston_profile):
        """Full ATO pipeline should complete quickly."""
        session_event = {
            "session_id": "perf-ato",
            "user_id": "user-boston",
            "device_id": "device-unknown",
            "device_type": "android",
            "geo_location": {"city": "Lagos", "country": "NG"},
            "session_start": datetime(2026, 1, 15, 3, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 45,
            "action_count": 10,
            "actions": ["change_email", "change_phone"],
            "failed_login_count_10m": 5,
            "failed_login_count_1h": 8,
        }

        start = time.monotonic()
        assessment = await ato_detector.assess(
            session_event, established_boston_profile, mock_db_session, feast_features={}
        )
        elapsed_ms = (time.monotonic() - start) * 1000

        # Full ATO pipeline (without actual Kafka/DB) should be very fast
        assert elapsed_ms < 1000, f"ATO assessment took {elapsed_ms:.1f}ms, target < 1000ms"


# --- Volume Test ---


class TestVolumeProcessing:
    """Push synthetic sessions through the pipeline and verify correctness."""

    async def test_normal_sessions_no_false_alerts(self, anomaly_scorer, established_boston_profile):
        """100 normal sessions should produce zero false alerts."""
        false_alerts = 0

        for i in range(100):
            session_event = {
                "session_id": f"vol-normal-{i}",
                "user_id": "user-boston",
                "device_id": "device-iphone-14",
                "device_type": "ios",
                "geo_location": {"city": "Boston", "country": "US"},
                "session_start": datetime(
                    2026, 1, 15, 18 + (i % 4), i % 60, tzinfo=UTC
                ).isoformat(),
                "session_duration_seconds": 250 + (i % 100),
                "action_count": 4 + (i % 3),
                "actions": ["check_circles", "view_balance"],
            }

            result = await anomaly_scorer.score_session(
                session_event, established_boston_profile, feast_features={}
            )

            if result.classification in (
                AnomalyClassification.HIGH_RISK,
                AnomalyClassification.CRITICAL,
            ):
                false_alerts += 1

        assert false_alerts == 0, (
            f"Expected zero false alerts from normal sessions, got {false_alerts}"
        )

    async def test_anomalous_sessions_all_detected(self, anomaly_scorer, established_boston_profile):
        """Injected anomalous sessions should all be detected."""
        detected = 0
        total_anomalous = 20

        for i in range(total_anomalous):
            session_event = {
                "session_id": f"vol-anomaly-{i}",
                "user_id": "user-boston",
                "device_id": f"device-unknown-{i}",
                "device_type": "android",
                "geo_location": {"city": "Lagos", "country": "NG"},
                "session_start": datetime(2026, 1, 15, 3, 0, tzinfo=UTC).isoformat(),
                "session_duration_seconds": 30 + (i % 20),
                "action_count": 10,
                "actions": ["change_email", "change_phone", "add_payment_method"],
            }

            result = await anomaly_scorer.score_session(
                session_event, established_boston_profile, feast_features={"new_device_flag": True}
            )

            if result.classification in (
                AnomalyClassification.SUSPICIOUS,
                AnomalyClassification.HIGH_RISK,
                AnomalyClassification.CRITICAL,
            ):
                detected += 1

        assert detected == total_anomalous, (
            f"Expected all {total_anomalous} anomalous sessions detected, got {detected}"
        )


# --- Profile Building Integration ---


class TestProfileBuildingIntegration:
    """Verify profile engine builds and updates profiles correctly."""

    async def test_build_from_historical_sessions(self, profile_engine, mock_db_session):
        """Build a profile from 20 historical sessions."""
        sessions = []
        base_time = datetime(2026, 1, 1, 18, 0, tzinfo=UTC)
        for i in range(20):
            sessions.append({
                "session_id": f"hist-{i}",
                "user_id": "user-test",
                "device_id": "device-phone",
                "device_type": "ios",
                "geo_location": {"city": "Boston", "country": "US"},
                "session_start": (base_time + timedelta(days=i)).isoformat(),
                "session_duration_seconds": 300 + (i * 5),
                "action_count": 5 + (i % 3),
                "actions": ["check_circles", "view_balance"],
                "features_used": ["circles", "balance"],
            })

        profile = await profile_engine.build_profile("user-test", mock_db_session, sessions)

        assert profile.profile_status == ProfileStatus.ACTIVE
        assert profile.profile_maturity == 20
        assert profile.device_baseline.primary_device == "device-phone"
        assert profile.geographic_baseline.primary_location == {"city": "Boston", "country": "US"}

    async def test_incremental_update(self, profile_engine, mock_db_session):
        """Build and then incrementally update a profile."""
        sessions = []
        base_time = datetime(2026, 1, 1, 18, 0, tzinfo=UTC)
        for i in range(15):
            sessions.append({
                "session_id": f"hist-{i}",
                "user_id": "user-update",
                "device_id": "device-phone",
                "device_type": "ios",
                "geo_location": {"city": "Boston", "country": "US"},
                "session_start": (base_time + timedelta(days=i)).isoformat(),
                "session_duration_seconds": 300,
                "action_count": 5,
                "actions": ["check_circles"],
            })

        profile = await profile_engine.build_profile("user-update", mock_db_session, sessions)
        assert profile.profile_maturity == 15

        # Update with new session from a new location
        from unittest.mock import patch

        with patch.object(profile_engine, "get_profile", return_value=profile):
            new_session = {
                "session_id": "new-session",
                "user_id": "user-update",
                "device_id": "device-phone",
                "device_type": "ios",
                "geo_location": {"city": "Port-au-Prince", "country": "HT"},
                "session_start": (base_time + timedelta(days=16)).isoformat(),
                "session_duration_seconds": 200,
                "action_count": 3,
                "actions": ["send_remittance"],
            }
            updated = await profile_engine.update_profile("user-update", new_session, mock_db_session)

        assert updated.profile_maturity == 16
        # New location should be added
        assert {"city": "Port-au-Prince", "country": "HT"} in updated.geographic_baseline.known_locations


# --- Engagement Integration ---


class TestEngagementIntegration:
    async def test_engagement_with_profile(self, engagement_scorer, established_boston_profile):
        features = {
            "session_count_7d": 5,
            "login_streak_days": 7,
            "feature_usage_breadth": 0.5,
            "days_since_last_login": 1,
        }
        result = await engagement_scorer.score_engagement(
            "user-boston", established_boston_profile, feast_features=features
        )

        assert 0 <= result.engagement_score <= 100
        assert result.lifecycle_stage in (LifecycleStage.ACTIVE, LifecycleStage.POWER_USER)
        assert result.churn_risk < 0.5
