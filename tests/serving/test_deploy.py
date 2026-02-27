"""Tests for the model deployment pipeline."""

from src.serving.deploy import (
    DeploymentPipeline,
    _generate_validation_events,
)


class TestValidationEvents:
    def test_generates_correct_count(self):
        events = _generate_validation_events(count=50)
        assert len(events) == 50

    def test_events_have_expected_keys(self):
        events = _generate_validation_events(count=5)
        expected_keys = {
            "amount",
            "amount_zscore",
            "hour_of_day",
            "day_of_week",
            "tx_type_encoded",
            "balance_delta_sender",
            "balance_delta_receiver",
            "velocity_count_1h",
            "velocity_count_24h",
            "velocity_amount_1h",
            "velocity_amount_24h",
        }
        for event in events:
            assert set(event.keys()) == expected_keys

    def test_deterministic_with_same_seed(self):
        events1 = _generate_validation_events(count=10)
        events2 = _generate_validation_events(count=10)
        for e1, e2 in zip(events1, events2, strict=True):
            assert e1 == e2


class TestDeploymentPipeline:
    def test_validate_model_catches_load_failure(self):
        pipeline = DeploymentPipeline(tracking_uri="http://nonexistent:5000")
        result = pipeline.validate_model("fake-model", "1")
        assert not result.passed
        assert result.checks.get("model_loads") is False

    def test_history_tracking(self):
        pipeline = DeploymentPipeline()
        assert len(pipeline.history) == 0

        # A failed validation still gets recorded
        pipeline.validate_model("fake-model", "1")
        # validate_model itself doesn't add to history; promote does
        assert len(pipeline.history) == 0

    def test_promote_records_history(self):
        pipeline = DeploymentPipeline(tracking_uri="http://nonexistent:5000")
        record = pipeline.promote_to_production("fake", "1")
        assert not record.success
        assert len(pipeline.history) == 1
        assert pipeline.history[0].action == "promote"

    def test_rollback_records_history(self):
        pipeline = DeploymentPipeline(tracking_uri="http://nonexistent:5000")
        record = pipeline.rollback("fake")
        assert not record.success
        assert record.action == "rollback"
        assert len(pipeline.history) == 1
