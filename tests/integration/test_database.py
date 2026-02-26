"""Integration tests for database models."""

import pytest

pytestmark = pytest.mark.integration


class TestDatabase:
    def test_models_importable(self):
        from src.db.models import Alert, CircleHealth, FraudScore, RawEvent, UserProfileDB

        assert RawEvent.__tablename__ == "raw_events"
        assert FraudScore.__tablename__ == "fraud_scores"
        assert CircleHealth.__tablename__ == "circle_health"
        assert UserProfileDB.__tablename__ == "user_profiles"
        assert Alert.__tablename__ == "alerts"

    def test_raw_event_model_fields(self):
        from src.db.models import RawEvent

        columns = {c.name for c in RawEvent.__table__.columns}
        assert "event_id" in columns
        assert "event_type" in columns
        assert "payload" in columns
        assert "received_at" in columns
        assert "processed" in columns

    def test_fraud_score_model_fields(self):
        from src.db.models import FraudScore

        columns = {c.name for c in FraudScore.__table__.columns}
        assert "transaction_id" in columns
        assert "risk_score" in columns
        assert "rules_triggered" in columns

    def test_alert_model_fields(self):
        from src.db.models import Alert

        columns = {c.name for c in Alert.__table__.columns}
        assert "alert_id" in columns
        assert "user_id" in columns
        assert "severity" in columns
        assert "status" in columns
