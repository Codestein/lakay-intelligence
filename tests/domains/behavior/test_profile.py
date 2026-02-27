"""Unit tests for behavioral profile engine."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domains.behavior.config import BehaviorConfig
from src.domains.behavior.models import (
    DeviceBaseline,
    GeographicBaseline,
    ProfileStatus,
    SessionBaseline,
    TemporalBaseline,
    UserBehaviorProfile,
)
from src.domains.behavior.profile import BehaviorProfileEngine


@pytest.fixture
def engine() -> BehaviorProfileEngine:
    return BehaviorProfileEngine()


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    # Return None for get_profile (no existing profile)
    # Use MagicMock for result since scalar_one_or_none() is sync
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)
    return session


@pytest.fixture
def sample_sessions() -> list[dict]:
    """20 historical sessions for an established user."""
    base_time = datetime(2026, 1, 1, 18, 0, tzinfo=UTC)
    sessions = []
    for i in range(20):
        sessions.append({
            "session_id": f"session-{i}",
            "user_id": "user-123",
            "device_id": "device-primary",
            "device_type": "ios",
            "ip_address": "10.0.1.50",
            "geo_location": {"city": "Boston", "country": "US", "lat": 42.36, "lon": -71.06},
            "session_start": (base_time + timedelta(days=i, hours=i % 3)).isoformat(),
            "session_duration_seconds": 300 + (i * 10),
            "action_count": 5 + (i % 3),
            "actions": ["check_circles", "view_balance", "send_remittance"],
            "features_used": ["circles", "remittance"],
        })
    return sessions


@pytest.fixture
def minimal_sessions() -> list[dict]:
    """3 sessions for a new user (building profile)."""
    base_time = datetime(2026, 1, 1, 18, 0, tzinfo=UTC)
    sessions = []
    for i in range(3):
        sessions.append({
            "session_id": f"session-{i}",
            "user_id": "user-new",
            "device_id": "device-phone",
            "device_type": "android",
            "geo_location": {"city": "Miami", "country": "US"},
            "session_start": (base_time + timedelta(days=i)).isoformat(),
            "session_duration_seconds": 180,
            "action_count": 3,
            "actions": ["view_balance"],
        })
    return sessions


class TestBuildProfile:
    async def test_build_active_profile(self, engine, mock_db_session, sample_sessions):
        profile = await engine.build_profile("user-123", mock_db_session, sample_sessions)

        assert profile.user_id == "user-123"
        assert profile.profile_status == ProfileStatus.ACTIVE
        assert profile.profile_maturity == 20
        assert profile.session_baseline.avg_duration > 0
        assert profile.device_baseline.primary_device == "device-primary"
        assert profile.geographic_baseline.primary_location == {"city": "Boston", "country": "US"}

    async def test_build_building_profile(self, engine, mock_db_session, minimal_sessions):
        profile = await engine.build_profile("user-new", mock_db_session, minimal_sessions)

        assert profile.profile_status == ProfileStatus.BUILDING
        assert profile.profile_maturity == 3

    async def test_session_baseline_computed(self, engine, mock_db_session, sample_sessions):
        profile = await engine.build_profile("user-123", mock_db_session, sample_sessions)

        sb = profile.session_baseline
        assert sb.avg_duration > 0
        assert sb.avg_actions > 0
        assert sb.std_duration >= 0
        assert sb.std_actions >= 0

    async def test_temporal_baseline_computed(self, engine, mock_db_session, sample_sessions):
        profile = await engine.build_profile("user-123", mock_db_session, sample_sessions)

        tb = profile.temporal_baseline
        assert len(tb.typical_hours) > 0
        assert tb.typical_frequency_mean > 0

    async def test_device_baseline_computed(self, engine, mock_db_session, sample_sessions):
        profile = await engine.build_profile("user-123", mock_db_session, sample_sessions)

        db = profile.device_baseline
        assert "device-primary" in db.known_devices
        assert db.primary_device == "device-primary"
        assert "ios" in db.device_platforms

    async def test_geographic_baseline_computed(self, engine, mock_db_session, sample_sessions):
        profile = await engine.build_profile("user-123", mock_db_session, sample_sessions)

        gb = profile.geographic_baseline
        assert len(gb.known_locations) > 0
        assert gb.primary_location is not None
        assert gb.primary_location["city"] == "Boston"

    async def test_engagement_baseline_computed(self, engine, mock_db_session, sample_sessions):
        profile = await engine.build_profile("user-123", mock_db_session, sample_sessions)

        eb = profile.engagement_baseline
        assert len(eb.typical_features_used) > 0
        assert eb.feature_usage_breadth > 0

    async def test_empty_sessions_builds_empty_profile(self, engine, mock_db_session):
        profile = await engine.build_profile("user-empty", mock_db_session, [])

        assert profile.profile_status == ProfileStatus.BUILDING
        assert profile.profile_maturity == 0
        assert profile.session_baseline.avg_duration == 0


class TestUpdateProfile:
    async def test_update_increments_maturity(self, engine, mock_db_session, sample_sessions):
        # Build initial profile
        profile = await engine.build_profile("user-123", mock_db_session, sample_sessions)
        initial_maturity = profile.profile_maturity

        # Mock get_profile to return existing profile
        with patch.object(engine, "get_profile", return_value=profile):
            new_session = {
                "session_id": "session-new",
                "user_id": "user-123",
                "device_id": "device-primary",
                "device_type": "ios",
                "geo_location": {"city": "Boston", "country": "US"},
                "session_start": datetime.now(UTC).isoformat(),
                "session_duration_seconds": 400,
                "action_count": 8,
                "actions": ["check_circles"],
            }
            updated = await engine.update_profile("user-123", new_session, mock_db_session)

        assert updated.profile_maturity == initial_maturity + 1

    async def test_new_device_added_on_update(self, engine, mock_db_session, sample_sessions):
        profile = await engine.build_profile("user-123", mock_db_session, sample_sessions)

        with patch.object(engine, "get_profile", return_value=profile):
            new_session = {
                "session_id": "session-new",
                "user_id": "user-123",
                "device_id": "device-new-tablet",
                "device_type": "android",
                "session_start": datetime.now(UTC).isoformat(),
                "session_duration_seconds": 200,
                "action_count": 3,
            }
            updated = await engine.update_profile("user-123", new_session, mock_db_session)

        assert "device-new-tablet" in updated.device_baseline.known_devices
        assert "android" in updated.device_baseline.device_platforms


class TestEMAMath:
    def test_ema_basic(self, engine):
        # Start at 100, new value 200, alpha=0.5 -> should be 150
        result = engine._ema(100.0, 200.0, 0.5)
        assert abs(result - 150.0) < 1e-6

    def test_ema_low_alpha(self, engine):
        # Low alpha = slow adaptation
        result = engine._ema(100.0, 200.0, 0.1)
        assert abs(result - 110.0) < 1e-6  # mostly keeps old value

    def test_ema_high_alpha(self, engine):
        # High alpha = fast adaptation
        result = engine._ema(100.0, 200.0, 0.9)
        assert abs(result - 190.0) < 1e-6  # mostly takes new value

    def test_compute_std(self, engine):
        values = [10.0, 12.0, 8.0, 11.0, 9.0]
        std = engine._compute_std(values)
        assert std > 0

    def test_compute_std_single_value(self, engine):
        assert engine._compute_std([5.0]) == 0.0

    def test_count_distinct_days(self, engine):
        sessions = [
            {"session_start": "2026-01-01T10:00:00+00:00"},
            {"session_start": "2026-01-01T14:00:00+00:00"},
            {"session_start": "2026-01-02T10:00:00+00:00"},
            {"session_start": "2026-01-03T10:00:00+00:00"},
        ]
        assert engine._count_distinct_days(sessions) == 3


class TestProfileStaleness:
    async def test_stale_profile_detection(self, engine, mock_db_session, sample_sessions):
        profile = await engine.build_profile("user-123", mock_db_session, sample_sessions)

        # Manually set last_updated to 60 days ago
        profile.last_updated = datetime.now(UTC) - timedelta(days=60)
        profile.profile_status = ProfileStatus.ACTIVE

        # Simulate get_profile returning stale profile
        from unittest.mock import MagicMock
        from src.db.models import UserProfileDB

        mock_row = MagicMock(spec=UserProfileDB)
        mock_row.user_id = "user-123"
        mock_row.behavioral_features = {
            "profile_status": "active",
            "profile_maturity": 20,
            "session_baseline": profile.session_baseline.model_dump(),
            "temporal_baseline": profile.temporal_baseline.model_dump(),
            "device_baseline": profile.device_baseline.model_dump(),
            "geographic_baseline": profile.geographic_baseline.model_dump(),
            "engagement_baseline": profile.engagement_baseline.model_dump(),
        }
        mock_row.last_updated = datetime.now(UTC) - timedelta(days=60)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        retrieved = await engine.get_profile("user-123", mock_db_session)
        assert retrieved is not None
        assert retrieved.profile_status == ProfileStatus.STALE
