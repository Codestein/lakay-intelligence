"""Tests for the bronze layer: raw event ingestion."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from src.pipeline.bronze import BronzeIngestionBuffer


@pytest.fixture
def mock_storage():
    storage = MagicMock()
    storage.write_batch = MagicMock(return_value=("bronze/test/key.parquet", 1024))
    return storage


@pytest.fixture
def sample_event():
    return {
        "event_id": "evt-001",
        "event_type": "transaction-initiated",
        "event_version": "1.0",
        "timestamp": "2026-01-15T14:00:00+00:00",
        "source_service": "transaction-service",
        "correlation_id": "corr-001",
        "payload": {
            "transaction_id": "txn-001",
            "user_id": "user-001",
            "amount": "100.00",
            "currency": "USD",
        },
    }


class TestBronzeIngestionBuffer:
    def test_add_event_buffers(self, mock_storage, sample_event):
        buffer = BronzeIngestionBuffer(
            storage=mock_storage, flush_batch_size=100, flush_interval=3600
        )
        result = buffer.add_event(sample_event, "trebanx.transaction.events")
        # Should not flush yet (batch size = 100)
        assert result is None
        assert "transaction-initiated" in buffer._buffers
        assert len(buffer._buffers["transaction-initiated"]) == 1

    def test_add_event_adds_metadata(self, mock_storage, sample_event):
        buffer = BronzeIngestionBuffer(
            storage=mock_storage, flush_batch_size=100, flush_interval=3600
        )
        buffer.add_event(sample_event, "trebanx.transaction.events", kafka_partition=2, kafka_offset=42)
        enriched = buffer._buffers["transaction-initiated"][0]
        assert "_ingested_at" in enriched
        assert enriched["_source_topic"] == "trebanx.transaction.events"
        assert enriched["_partition"] == 2
        assert enriched["_offset"] == 42

    def test_flush_on_batch_size(self, mock_storage, sample_event):
        buffer = BronzeIngestionBuffer(
            storage=mock_storage, flush_batch_size=3, flush_interval=3600
        )
        buffer.add_event(sample_event, "test-topic")
        buffer.add_event(sample_event, "test-topic")
        result = buffer.add_event(sample_event, "test-topic")
        # Third event triggers flush
        assert result is not None
        assert mock_storage.write_batch.called
        # Buffer should be cleared
        assert len(buffer._buffers.get("transaction-initiated", [])) == 0

    def test_flush_all(self, mock_storage, sample_event):
        buffer = BronzeIngestionBuffer(
            storage=mock_storage, flush_batch_size=1000, flush_interval=3600
        )
        buffer.add_event(sample_event, "test-topic")
        event2 = {**sample_event, "event_type": "session-started"}
        buffer.add_event(event2, "test-topic-2")

        keys = buffer.flush_all()
        assert len(keys) == 2
        assert mock_storage.write_batch.call_count == 2

    def test_get_stats(self, mock_storage, sample_event):
        buffer = BronzeIngestionBuffer(
            storage=mock_storage, flush_batch_size=1000, flush_interval=3600
        )
        buffer.add_event(sample_event, "test-topic")
        buffer.add_event(sample_event, "test-topic")

        stats = buffer.get_stats()
        assert stats["total_events_ingested"] == 2
        assert stats["events_by_type"]["transaction-initiated"] == 2
        assert stats["buffered_events"]["transaction-initiated"] == 2

    def test_flush_writes_parquet(self, mock_storage, sample_event):
        buffer = BronzeIngestionBuffer(
            storage=mock_storage, flush_batch_size=2, flush_interval=3600
        )
        buffer.add_event(sample_event, "test-topic")
        buffer.add_event(sample_event, "test-topic")

        # Verify the write_batch was called with a PyArrow table
        call_args = mock_storage.write_batch.call_args
        table = call_args.kwargs.get("table") or call_args[1].get("table") or call_args[0][0]
        assert isinstance(table, pa.Table)
        assert table.num_rows == 2
        assert "event_id" in table.column_names
        assert "_ingested_at" in table.column_names
        assert "_raw_json" in table.column_names

    def test_stats_after_flush(self, mock_storage, sample_event):
        buffer = BronzeIngestionBuffer(
            storage=mock_storage, flush_batch_size=1, flush_interval=3600
        )
        buffer.add_event(sample_event, "test-topic")

        stats = buffer.get_stats()
        assert stats["partitions_created"] == 1
        assert stats["total_size_bytes"] == 1024

    def test_handles_multiple_event_types(self, mock_storage, sample_event):
        buffer = BronzeIngestionBuffer(
            storage=mock_storage, flush_batch_size=1000, flush_interval=3600
        )
        buffer.add_event(sample_event, "topic-1")
        event2 = {**sample_event, "event_type": "circle-created"}
        buffer.add_event(event2, "topic-2")
        event3 = {**sample_event, "event_type": "remittance-initiated"}
        buffer.add_event(event3, "topic-3")

        stats = buffer.get_stats()
        assert len(stats["events_by_type"]) == 3
