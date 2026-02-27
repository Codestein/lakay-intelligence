"""Tests for PII tokenization."""

import pytest

from src.pipeline.pii import PIITokenizer, _decrypt_value, _encrypt_value


@pytest.fixture
def tokenizer():
    return PIITokenizer()


class TestPIITokenizer:
    def test_tokenize_deterministic(self, tokenizer):
        """Same value → same token every time."""
        token1 = tokenizer.tokenize("user_id", "user-123")
        token2 = tokenizer.tokenize("user_id", "user-123")
        assert token1 == token2

    def test_tokenize_different_values(self, tokenizer):
        """Different values → different tokens."""
        token1 = tokenizer.tokenize("user_id", "user-123")
        token2 = tokenizer.tokenize("user_id", "user-456")
        assert token1 != token2

    def test_tokenize_different_fields(self, tokenizer):
        """Same value in different fields → different tokens."""
        token1 = tokenizer.tokenize("user_id", "abc123")
        token2 = tokenizer.tokenize("email", "abc123")
        assert token1 != token2

    def test_token_format(self, tokenizer):
        token = tokenizer.tokenize("user_id", "test-value")
        assert token.startswith("tok_user_id_")
        assert len(token) > len("tok_user_id_")

    def test_tokenize_event_top_level(self, tokenizer):
        event = {
            "event_id": "evt-001",
            "event_type": "transaction-initiated",
            "user_id": "user-123",
            "payload": {
                "user_id": "user-123",
                "amount": "100.00",
                "ip_address": "192.168.1.1",
            },
        }
        result = tokenizer.tokenize_event(event, "transaction-initiated")
        # Top-level user_id should be tokenized
        assert result["user_id"].startswith("tok_")
        # Payload user_id should be tokenized
        assert result["payload"]["user_id"].startswith("tok_")
        # Payload ip_address should be tokenized
        assert result["payload"]["ip_address"].startswith("tok_")
        # Non-PII fields should be unchanged
        assert result["event_id"] == "evt-001"
        assert result["payload"]["amount"] == "100.00"

    def test_tokenize_event_preserves_structure(self, tokenizer):
        event = {
            "event_id": "evt-001",
            "event_type": "remittance-initiated",
            "payload": {
                "sender_id": "user-abc",
                "recipient_name": "Marie Jean-Baptiste",
                "send_amount": "200.00",
            },
        }
        result = tokenizer.tokenize_event(event, "remittance-initiated")
        assert "payload" in result
        assert result["payload"]["send_amount"] == "200.00"
        assert result["payload"]["sender_id"].startswith("tok_")
        assert result["payload"]["recipient_name"].startswith("tok_")

    def test_tokenize_nested_geo(self, tokenizer):
        event = {
            "event_id": "evt-001",
            "event_type": "transaction-initiated",
            "payload": {
                "user_id": "u1",
                "geo_location": {
                    "latitude": 42.3601,
                    "longitude": -71.0589,
                    "country": "US",
                },
            },
        }
        result = tokenizer.tokenize_event(event, "transaction-initiated")
        geo = result["payload"]["geo_location"]
        # Latitude and longitude should be tokenized
        assert isinstance(geo["latitude"], str) and geo["latitude"].startswith("tok_")
        assert isinstance(geo["longitude"], str) and geo["longitude"].startswith("tok_")
        # Country should not be tokenized
        assert geo["country"] == "US"

    def test_tokenize_handles_none(self, tokenizer):
        event = {
            "event_id": "evt-001",
            "event_type": "transaction-initiated",
            "payload": {
                "user_id": None,
                "ip_address": "1.2.3.4",
            },
        }
        result = tokenizer.tokenize_event(event)
        # None should not be tokenized
        assert result["payload"]["user_id"] is None

    def test_consistency_across_events(self, tokenizer):
        """Same user_id in two events → same token (enables joins)."""
        event1 = {
            "event_id": "e1",
            "event_type": "transaction-initiated",
            "payload": {"user_id": "shared-user"},
        }
        event2 = {
            "event_id": "e2",
            "event_type": "session-started",
            "payload": {"user_id": "shared-user"},
        }
        r1 = tokenizer.tokenize_event(event1)
        r2 = tokenizer.tokenize_event(event2)
        assert r1["payload"]["user_id"] == r2["payload"]["user_id"]


class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        original = "user-123@example.com"
        encrypted = _encrypt_value(original)
        decrypted = _decrypt_value(encrypted)
        assert decrypted == original

    def test_encrypt_produces_different_output(self):
        encrypted = _encrypt_value("test")
        assert encrypted != "test"

    def test_encrypt_deterministic(self):
        e1 = _encrypt_value("same-value")
        e2 = _encrypt_value("same-value")
        assert e1 == e2
