"""Shared test fixtures for Lakay Intelligence tests."""

import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://lakay:lakay_dev@localhost:5432/lakay_test"
)
os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")


@pytest.fixture
def contracts_path() -> str:
    return str(Path(__file__).parent.parent.parent / "trebanx-contracts" / "schemas")


@pytest.fixture
def sample_circle_created_event() -> dict:
    return {
        "event_id": "550e8400-e29b-41d4-a716-446655440000",
        "event_type": "circle-created",
        "event_version": "1.0",
        "timestamp": "2026-01-15T10:30:00+00:00",
        "source_service": "circle-service",
        "correlation_id": "660e8400-e29b-41d4-a716-446655440001",
        "payload": {
            "circle_id": "770e8400-e29b-41d4-a716-446655440002",
            "organizer_id": "880e8400-e29b-41d4-a716-446655440003",
            "name": "Lakay Savings Group",
            "contribution_amount": "100.00",
            "currency": "USD",
            "frequency": "monthly",
            "max_members": 10,
            "rotation_order": "sequential",
            "start_date": "2026-02-01",
            "status": "pending",
        },
    }


@pytest.fixture
def sample_transaction_initiated_event() -> dict:
    return {
        "event_id": "550e8400-e29b-41d4-a716-446655440010",
        "event_type": "transaction-initiated",
        "event_version": "1.0",
        "timestamp": "2026-01-15T14:00:00+00:00",
        "source_service": "transaction-service",
        "correlation_id": "660e8400-e29b-41d4-a716-446655440011",
        "payload": {
            "transaction_id": "770e8400-e29b-41d4-a716-446655440012",
            "user_id": "880e8400-e29b-41d4-a716-446655440003",
            "type": "circle_contribution",
            "amount": "100.00",
            "currency": "USD",
            "source": {"type": "stripe", "identifier": "pm_test_123"},
            "destination": {"type": "balance", "identifier": "circle_pool_001"},
            "initiated_at": "2026-01-15T14:00:00+00:00",
            "ip_address": "10.0.1.50",
            "device_id": "device_abc123",
            "geo_location": {
                "latitude": 42.3601,
                "longitude": -71.0589,
                "country": "US",
                "city": "Boston",
            },
        },
    }


@pytest.fixture
def sample_remittance_initiated_event() -> dict:
    return {
        "event_id": "550e8400-e29b-41d4-a716-446655440020",
        "event_type": "remittance-initiated",
        "event_version": "1.0",
        "timestamp": "2026-01-15T16:00:00+00:00",
        "source_service": "remittance-service",
        "correlation_id": "660e8400-e29b-41d4-a716-446655440021",
        "payload": {
            "remittance_id": "770e8400-e29b-41d4-a716-446655440022",
            "sender_id": "880e8400-e29b-41d4-a716-446655440003",
            "recipient_name": "Marie Jean-Baptiste",
            "recipient_phone": "+50934567890",
            "recipient_country": "HT",
            "send_amount": "200.00",
            "send_currency": "USD",
            "receive_amount": "26500.00",
            "receive_currency": "HTG",
            "exchange_rate": "132.50",
            "delivery_method": "mobile_wallet",
            "initiated_at": "2026-01-15T16:00:00+00:00",
            "fee_amount": "4.99",
        },
    }


@pytest.fixture
def mock_kafka_consumer():
    consumer = AsyncMock()
    consumer.start = AsyncMock()
    consumer.stop = AsyncMock()
    return consumer


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session
