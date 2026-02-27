"""Tests for data quality checks."""

import pytest

from src.pipeline.quality import (
    check_completeness,
    check_ranges,
    check_referential_integrity,
    check_timestamp,
    run_quality_checks,
    validate_schema,
)


@pytest.fixture
def valid_transaction_event():
    return {
        "event_id": "evt-001",
        "event_type": "transaction-initiated",
        "timestamp": "2026-01-15T14:00:00+00:00",
        "source_service": "transaction-service",
        "payload": {
            "transaction_id": "txn-001",
            "user_id": "user-001",
            "amount": "100.00",
            "currency": "USD",
        },
    }


class TestCompleteness:
    def test_valid_event_passes(self, valid_transaction_event):
        is_complete, missing = check_completeness(valid_transaction_event)
        assert is_complete
        assert missing == []

    def test_missing_event_id(self, valid_transaction_event):
        del valid_transaction_event["event_id"]
        is_complete, missing = check_completeness(valid_transaction_event)
        assert not is_complete
        assert "event_id" in missing

    def test_missing_payload_field(self, valid_transaction_event):
        del valid_transaction_event["payload"]["user_id"]
        is_complete, missing = check_completeness(valid_transaction_event)
        assert not is_complete
        assert "payload.user_id" in missing

    def test_empty_string_field(self, valid_transaction_event):
        valid_transaction_event["event_id"] = ""
        is_complete, missing = check_completeness(valid_transaction_event)
        assert not is_complete

    def test_unknown_event_type_minimal_check(self):
        event = {"event_id": "e1", "event_type": "unknown-type", "timestamp": "2026-01-01T00:00:00Z"}
        is_complete, missing = check_completeness(event)
        assert is_complete


class TestRanges:
    def test_valid_amount(self, valid_transaction_event):
        in_range, violations = check_ranges(valid_transaction_event)
        assert in_range
        assert violations == []

    def test_zero_amount_rejected(self, valid_transaction_event):
        valid_transaction_event["payload"]["amount"] = "0"
        in_range, violations = check_ranges(valid_transaction_event)
        assert not in_range
        assert len(violations) == 1

    def test_negative_amount_rejected(self, valid_transaction_event):
        valid_transaction_event["payload"]["amount"] = "-50"
        in_range, violations = check_ranges(valid_transaction_event)
        assert not in_range

    def test_non_numeric_amount(self, valid_transaction_event):
        valid_transaction_event["payload"]["amount"] = "not-a-number"
        in_range, violations = check_ranges(valid_transaction_event)
        assert not in_range
        assert "not numeric" in violations[0]


class TestTimestamp:
    def test_valid_timestamp(self):
        valid, reason = check_timestamp({"timestamp": "2026-01-15T14:00:00+00:00"})
        assert valid

    def test_missing_timestamp(self):
        valid, reason = check_timestamp({})
        assert not valid
        assert "missing" in reason

    def test_unparseable_timestamp(self):
        valid, reason = check_timestamp({"timestamp": "not-a-date"})
        assert not valid


class TestReferentialIntegrity:
    def test_known_user(self):
        event = {"event_type": "test", "payload": {"user_id": "user-1"}}
        warnings = check_referential_integrity(
            event, known_users={"user-1"}
        )
        assert warnings == []

    def test_unknown_user_warning(self):
        event = {"event_type": "test", "payload": {"user_id": "user-unknown"}}
        warnings = check_referential_integrity(
            event, known_users={"user-1", "user-2"}
        )
        assert len(warnings) == 1
        assert "unknown_user_id" in warnings[0]

    def test_no_known_set_no_warnings(self):
        event = {"event_type": "test", "payload": {"user_id": "any"}}
        warnings = check_referential_integrity(event)
        assert warnings == []


class TestSchemaValidation:
    def test_no_schema_passes(self):
        valid, reason = validate_schema({"any": "data"}, schema=None)
        assert valid

    def test_valid_against_schema(self):
        schema = {
            "type": "object",
            "required": ["event_id"],
            "properties": {"event_id": {"type": "string"}},
        }
        valid, reason = validate_schema({"event_id": "e1"}, schema)
        assert valid

    def test_invalid_against_schema(self):
        schema = {
            "type": "object",
            "required": ["event_id"],
            "properties": {"event_id": {"type": "string"}},
        }
        valid, reason = validate_schema({}, schema)
        assert not valid
        assert "schema_validation_failed" in reason


class TestRunQualityChecks:
    def test_all_pass(self, valid_transaction_event):
        passed, rejected, result = run_quality_checks([valid_transaction_event])
        assert len(passed) == 1
        assert len(rejected) == 0
        assert result.total == 1
        assert result.passed == 1

    def test_mixed_batch(self, valid_transaction_event):
        bad_event = {
            "event_type": "transaction-initiated",
            "timestamp": "2026-01-15T14:00:00+00:00",
            # missing event_id
            "payload": {"transaction_id": "t1", "user_id": "u1", "amount": "50", "currency": "USD"},
        }
        passed, rejected, result = run_quality_checks(
            [valid_transaction_event, bad_event]
        )
        assert result.total == 2
        assert result.passed == 1
        assert result.rejected == 1

    def test_empty_batch(self):
        passed, rejected, result = run_quality_checks([])
        assert result.total == 0
        assert passed == []
