"""Tests for schema loading and validation."""

from pathlib import Path

import jsonschema
import pytest

from src.shared.schemas import load_schema, validate_event

CONTRACTS_PATH = str(Path(__file__).parent.parent.parent.parent / "trebanx-contracts" / "schemas")


class TestSchemaLoading:
    def test_load_circle_created_schema(self):
        schema = load_schema("circle-created", CONTRACTS_PATH)
        assert schema["properties"]["event_type"]["const"] == "circle-created"

    def test_load_transaction_initiated_schema(self):
        schema = load_schema("transaction-initiated", CONTRACTS_PATH)
        assert "payload" in schema["properties"]

    def test_load_unknown_event_type_raises(self):
        with pytest.raises(ValueError):
            load_schema("unknown-event", CONTRACTS_PATH)

    def test_load_missing_schema_raises(self):
        with pytest.raises(FileNotFoundError):
            load_schema("circle-nonexistent", CONTRACTS_PATH)


class TestEventValidation:
    def test_validate_valid_circle_created(self, sample_circle_created_event):
        assert validate_event(sample_circle_created_event, CONTRACTS_PATH) is True

    def test_validate_valid_transaction_initiated(self, sample_transaction_initiated_event):
        assert validate_event(sample_transaction_initiated_event, CONTRACTS_PATH) is True

    def test_validate_missing_event_type_raises(self):
        with pytest.raises(ValueError):
            validate_event({"payload": {}}, CONTRACTS_PATH)

    def test_validate_invalid_event_raises(self):
        invalid_event = {
            "event_id": "550e8400-e29b-41d4-a716-446655440000",
            "event_type": "circle-created",
            "event_version": "1.0",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "source_service": "test",
            "correlation_id": "550e8400-e29b-41d4-a716-446655440001",
            "payload": {},
        }
        with pytest.raises(jsonschema.ValidationError):
            validate_event(invalid_event, CONTRACTS_PATH)
