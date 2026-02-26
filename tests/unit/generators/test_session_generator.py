"""Tests for the session behavior generator."""

from generators.session_generator import SessionGenerator

DEFAULT_CONFIG = {
    "num_users": 50,
    "sessions_per_user_range": [5, 20],
    "session_duration_distribution": {"log_normal_mean": 6.0, "log_normal_std": 1.0},
    "actions_per_session_distribution": {"log_normal_mean": 2.0, "log_normal_std": 0.8},
    "anomaly_injection_rate": 0.0,
    "account_takeover_injection_rate": 0.0,
    "device_diversity": 2,
    "location_diversity": 2,
    "time_span_days": 30,
}


class TestSessionGenerator:
    def test_deterministic_output(self):
        gen1 = SessionGenerator(config=DEFAULT_CONFIG, seed=42)
        events1 = gen1.generate(num_sessions=50)
        gen2 = SessionGenerator(config=DEFAULT_CONFIG, seed=42)
        events2 = gen2.generate(num_sessions=50)
        assert len(events1) == len(events2)

    def test_generates_login_attempts(self):
        gen = SessionGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_sessions=20)
        logins = [e for e in events if e["event_type"] == "login-attempt"]
        assert len(logins) > 0

    def test_generates_sessions(self):
        gen = SessionGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_sessions=20)
        started = [e for e in events if e["event_type"] == "session-started"]
        ended = [e for e in events if e["event_type"] == "session-ended"]
        assert len(started) > 0
        assert len(ended) > 0

    def test_generates_user_actions(self):
        gen = SessionGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_sessions=20)
        actions = [e for e in events if e["event_type"] == "user-action-performed"]
        assert len(actions) > 0

    def test_event_envelope_structure(self):
        gen = SessionGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_sessions=10)
        for event in events:
            assert "event_id" in event
            assert "event_type" in event
            assert "payload" in event
