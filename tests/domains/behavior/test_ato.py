"""Unit tests for ATO detection pipeline."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domains.behavior.ato import ATODetector
from src.domains.behavior.config import BehaviorConfig
from src.domains.behavior.models import (
    AnomalyClassification,
    ATOAlertStatus,
    ATOAlertUpdate,
    ATORiskLevel,
    ATOResponseAction,
    ATOSignal,
    DeviceBaseline,
    DimensionAnomalyScore,
    GeographicBaseline,
    ProfileStatus,
    RecommendedAction,
    SessionAnomalyResult,
    UserBehaviorProfile,
)


@pytest.fixture
def detector() -> ATODetector:
    return ATODetector()


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    # Dedup check: no existing alerts
    # Use MagicMock for result since scalar_one() is sync
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 0
    session.execute = AsyncMock(return_value=mock_result)
    return session


@pytest.fixture
def established_profile() -> UserBehaviorProfile:
    return UserBehaviorProfile(
        user_id="user-boston",
        profile_status=ProfileStatus.ACTIVE,
        profile_maturity=25,
        device_baseline=DeviceBaseline(
            known_devices=["device-iphone-14"],
            primary_device="device-iphone-14",
            device_platforms=["ios"],
        ),
        geographic_baseline=GeographicBaseline(
            known_locations=[{"city": "Boston", "country": "US"}],
            primary_location={"city": "Boston", "country": "US"},
        ),
        last_updated=datetime.now(UTC),
    )


@pytest.fixture
def normal_anomaly_result() -> SessionAnomalyResult:
    return SessionAnomalyResult(
        session_id="session-normal",
        user_id="user-boston",
        composite_score=0.1,
        classification=AnomalyClassification.NORMAL,
        dimension_scores=[],
        profile_maturity=25,
        recommended_action=RecommendedAction.NONE,
        timestamp=datetime.now(UTC),
    )


@pytest.fixture
def high_anomaly_result() -> SessionAnomalyResult:
    return SessionAnomalyResult(
        session_id="session-ato",
        user_id="user-boston",
        composite_score=0.85,
        classification=AnomalyClassification.CRITICAL,
        dimension_scores=[
            DimensionAnomalyScore(dimension="device", score=0.9, details="New device"),
            DimensionAnomalyScore(dimension="geographic", score=0.9, details="New location"),
            DimensionAnomalyScore(dimension="temporal", score=0.7, details="Unusual hour"),
        ],
        profile_maturity=25,
        recommended_action=RecommendedAction.TERMINATE,
        timestamp=datetime.now(UTC),
    )


class TestATOSignalAggregation:
    def test_normal_session_few_signals(self, detector, established_profile, normal_anomaly_result):
        session_event = {
            "session_id": "session-normal",
            "user_id": "user-boston",
            "device_id": "device-iphone-14",
            "geo_location": {"city": "Boston", "country": "US"},
            "actions": ["check_circles", "view_balance"],
            "failed_login_count_10m": 0,
            "failed_login_count_1h": 0,
        }
        signals = detector._aggregate_signals(
            session_event, established_profile, normal_anomaly_result, {}
        )
        # Normal session should produce minimal signals
        active_signals = [s for s in signals if s.score > 0]
        assert len(active_signals) <= 1

    def test_ato_session_multiple_signals(self, detector, established_profile, high_anomaly_result):
        session_event = {
            "session_id": "session-ato",
            "user_id": "user-boston",
            "device_id": "device-unknown-android",
            "device_type": "android",
            "geo_location": {"city": "Lagos", "country": "NG"},
            "actions": ["change_email", "change_phone", "initiate_large_transaction"],
            "failed_login_count_10m": 5,
            "failed_login_count_1h": 8,
        }
        signals = detector._aggregate_signals(
            session_event, established_profile, high_anomaly_result, {}
        )
        active_signals = [s for s in signals if s.score > 0]
        assert len(active_signals) >= 3

    def test_new_device_and_location_combined_signal(self, detector, established_profile, high_anomaly_result):
        session_event = {
            "session_id": "session-ato",
            "user_id": "user-boston",
            "device_id": "device-unknown",
            "geo_location": {"city": "Lagos", "country": "NG"},
            "actions": [],
            "failed_login_count_10m": 0,
            "failed_login_count_1h": 0,
        }
        signals = detector._aggregate_signals(
            session_event, established_profile, high_anomaly_result, {}
        )
        signal_names = [s.signal_name for s in signals]
        assert "new_device_and_location" in signal_names

    def test_sensitive_actions_signal(self, detector, established_profile, normal_anomaly_result):
        session_event = {
            "session_id": "session-suspect",
            "user_id": "user-boston",
            "device_id": "device-iphone-14",
            "geo_location": {"city": "Boston", "country": "US"},
            "actions": ["change_email", "change_phone", "change_password"],
            "failed_login_count_10m": 0,
            "failed_login_count_1h": 0,
        }
        signals = detector._aggregate_signals(
            session_event, established_profile, normal_anomaly_result, {}
        )
        signal_names = [s.signal_name for s in signals]
        assert "sensitive_actions" in signal_names

    def test_impossible_travel_signal(self, detector, established_profile, normal_anomaly_result):
        session_event = {
            "session_id": "session-travel",
            "user_id": "user-boston",
            "device_id": "device-iphone-14",
            "geo_location": {"city": "Boston", "country": "US"},
            "actions": [],
            "failed_login_count_10m": 0,
            "failed_login_count_1h": 0,
        }
        features = {"max_travel_speed_24h": 2000}
        signals = detector._aggregate_signals(
            session_event, established_profile, normal_anomaly_result, features
        )
        signal_names = [s.signal_name for s in signals]
        assert "impossible_travel" in signal_names


class TestATORiskScoring:
    def test_no_signals_zero_score(self, detector):
        score = detector._compute_ato_risk_score([])
        assert score == 0.0

    def test_single_moderate_signal(self, detector):
        signals = [ATOSignal(signal_name="new_device", score=0.3, details="")]
        score = detector._compute_ato_risk_score(signals)
        assert 0.0 < score < 0.5

    def test_two_signals_boosted(self, detector):
        single = [ATOSignal(signal_name="new_device", score=0.5, details="")]
        double = [
            ATOSignal(signal_name="new_device", score=0.5, details=""),
            ATOSignal(signal_name="sensitive_actions", score=0.5, details=""),
        ]
        single_score = detector._compute_ato_risk_score(single)
        double_score = detector._compute_ato_risk_score(double)
        # Two signals should be boosted (1.5x multiplier)
        assert double_score > single_score

    def test_three_signals_heavily_boosted(self, detector):
        signals = [
            ATOSignal(signal_name="session_anomaly", score=0.8, details=""),
            ATOSignal(signal_name="new_device_and_location", score=0.7, details=""),
            ATOSignal(signal_name="sensitive_actions", score=0.6, details=""),
        ]
        score = detector._compute_ato_risk_score(signals)
        assert score > 0.5  # Heavily boosted

    def test_score_capped_at_one(self, detector):
        signals = [
            ATOSignal(signal_name="session_anomaly", score=1.0, details=""),
            ATOSignal(signal_name="impossible_travel", score=1.0, details=""),
            ATOSignal(signal_name="sensitive_actions", score=1.0, details=""),
            ATOSignal(signal_name="failed_logins", score=1.0, details=""),
        ]
        score = detector._compute_ato_risk_score(signals)
        assert score <= 1.0


class TestATORiskClassification:
    def test_low_risk(self, detector):
        assert detector._classify_risk(0.1) == ATORiskLevel.LOW
        assert detector._classify_risk(0.29) == ATORiskLevel.LOW

    def test_moderate_risk(self, detector):
        assert detector._classify_risk(0.35) == ATORiskLevel.MODERATE
        assert detector._classify_risk(0.49) == ATORiskLevel.MODERATE

    def test_high_risk(self, detector):
        assert detector._classify_risk(0.55) == ATORiskLevel.HIGH
        assert detector._classify_risk(0.79) == ATORiskLevel.HIGH

    def test_critical_risk(self, detector):
        assert detector._classify_risk(0.85) == ATORiskLevel.CRITICAL
        assert detector._classify_risk(1.0) == ATORiskLevel.CRITICAL


class TestATOResponseRecommendation:
    def test_response_mapping(self, detector):
        assert detector._recommend_response(ATORiskLevel.LOW) == ATOResponseAction.NONE
        assert detector._recommend_response(ATORiskLevel.MODERATE) == ATOResponseAction.RE_AUTH
        assert detector._recommend_response(ATORiskLevel.HIGH) == ATOResponseAction.STEP_UP
        assert detector._recommend_response(ATORiskLevel.CRITICAL) == ATOResponseAction.LOCK


class TestATOAlertCreation:
    async def test_high_risk_creates_alert(self, detector, mock_db_session):
        from src.domains.behavior.models import ATOAssessment

        assessment = ATOAssessment(
            session_id="session-ato",
            user_id="user-boston",
            ato_risk_score=0.85,
            risk_level=ATORiskLevel.CRITICAL,
            contributing_signals=[
                ATOSignal(signal_name="session_anomaly", score=0.9, details=""),
            ],
            recommended_response=ATOResponseAction.LOCK,
            timestamp=datetime.now(UTC),
        )

        alert = await detector._create_alert(assessment, mock_db_session)
        assert alert is not None
        assert alert.risk_level == ATORiskLevel.CRITICAL
        assert alert.status == ATOAlertStatus.NEW
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()

    async def test_dedup_prevents_duplicate(self, detector, mock_db_session):
        from src.domains.behavior.models import ATOAssessment

        # Mock dedup check: existing alert found
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 1  # existing alert
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        assessment = ATOAssessment(
            session_id="session-ato-2",
            user_id="user-boston",
            ato_risk_score=0.85,
            risk_level=ATORiskLevel.CRITICAL,
            contributing_signals=[],
            recommended_response=ATOResponseAction.LOCK,
            timestamp=datetime.now(UTC),
        )

        alert = await detector._create_alert(assessment, mock_db_session)
        assert alert is None  # Deduplicated
        mock_db_session.add.assert_not_called()


class TestFullATOAssessment:
    async def test_normal_session_low_ato(self, detector, mock_db_session, established_profile):
        session_event = {
            "session_id": "session-normal",
            "user_id": "user-boston",
            "device_id": "device-iphone-14",
            "geo_location": {"city": "Boston", "country": "US"},
            "session_start": datetime.now(UTC).isoformat(),
            "session_duration_seconds": 300,
            "action_count": 5,
            "actions": ["check_circles", "view_balance"],
            "failed_login_count_10m": 0,
            "failed_login_count_1h": 0,
        }

        assessment = await detector.assess(
            session_event, established_profile, mock_db_session, feast_features={}
        )

        assert assessment.ato_risk_score < 0.5
        assert assessment.risk_level in (ATORiskLevel.LOW, ATORiskLevel.MODERATE)

    async def test_ato_session_critical(self, detector, mock_db_session, established_profile):
        session_event = {
            "session_id": "session-ato",
            "user_id": "user-boston",
            "device_id": "device-unknown-android",
            "device_type": "android",
            "geo_location": {"city": "Lagos", "country": "NG"},
            "session_start": datetime(2026, 1, 15, 3, 0, tzinfo=UTC).isoformat(),
            "session_duration_seconds": 30,
            "action_count": 10,
            "actions": [
                "change_email", "change_phone", "add_payment_method",
                "initiate_large_transaction",
            ],
            "failed_login_count_10m": 5,
            "failed_login_count_1h": 8,
            "pending_transactions": ["txn-001", "txn-002"],
        }

        assessment = await detector.assess(
            session_event, established_profile, mock_db_session, feast_features={}
        )

        assert assessment.ato_risk_score > 0.5
        assert len(assessment.contributing_signals) >= 2
