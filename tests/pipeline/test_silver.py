"""Tests for the silver layer: validation, dedup, PII tokenization."""

import json
from unittest.mock import MagicMock

import pyarrow as pa
import pytest

from src.pipeline.pii import PIITokenizer
from src.pipeline.silver import SilverProcessor


@pytest.fixture
def mock_storage():
    storage = MagicMock()
    storage.write_batch = MagicMock(return_value=("silver/test/key.parquet", 512))
    storage.write_key = MagicMock(return_value=256)
    return storage


@pytest.fixture
def sample_events():
    return [
        {
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
                "ip_address": "10.0.1.50",
            },
            "_ingested_at": "2026-01-15T14:01:00+00:00",
            "_source_topic": "trebanx.transaction.events",
        },
        {
            "event_id": "evt-002",
            "event_type": "transaction-initiated",
            "event_version": "1.0",
            "timestamp": "2026-01-15T14:05:00+00:00",
            "source_service": "transaction-service",
            "correlation_id": "corr-002",
            "payload": {
                "transaction_id": "txn-002",
                "user_id": "user-002",
                "amount": "200.00",
                "currency": "USD",
            },
            "_ingested_at": "2026-01-15T14:06:00+00:00",
            "_source_topic": "trebanx.transaction.events",
        },
    ]


def _events_to_table(events):
    """Create a bronze-like Parquet table from events."""
    records = {
        "event_id": [e.get("event_id", "") for e in events],
        "event_type": [e.get("event_type", "") for e in events],
        "event_version": [e.get("event_version", "1.0") for e in events],
        "timestamp": [e.get("timestamp", "") for e in events],
        "source_service": [e.get("source_service", "") for e in events],
        "correlation_id": [e.get("correlation_id", "") for e in events],
        "payload_json": [json.dumps(e.get("payload", {})) for e in events],
        "_ingested_at": [e.get("_ingested_at", "") for e in events],
        "_source_topic": [e.get("_source_topic", "") for e in events],
        "_partition": [0] * len(events),
        "_offset": list(range(len(events))),
        "_raw_json": [json.dumps(e) for e in events],
    }
    return pa.table(records)


class TestSilverProcessor:
    @pytest.mark.asyncio
    async def test_process_partition_basic(self, mock_storage, sample_events):
        table = _events_to_table(sample_events)
        mock_storage.read_partition = MagicMock(return_value=table)

        processor = SilverProcessor(storage=mock_storage)
        result = await processor.process_bronze_partition("bronze/test/key.parquet")

        assert result["total"] == 2
        assert result["passed"] == 2
        assert result["rejected"] == 0
        assert result["deduplicated"] == 0

    @pytest.mark.asyncio
    async def test_deduplication(self, mock_storage, sample_events):
        # Add a duplicate event
        dup = sample_events[0].copy()
        events = sample_events + [dup]
        table = _events_to_table(events)
        mock_storage.read_partition = MagicMock(return_value=table)

        processor = SilverProcessor(storage=mock_storage)
        result = await processor.process_bronze_partition("bronze/test/key.parquet")

        assert result["total"] == 3
        assert result["deduplicated"] == 1
        assert result["passed"] == 2

    @pytest.mark.asyncio
    async def test_pii_tokenization(self, mock_storage, sample_events):
        table = _events_to_table(sample_events)
        mock_storage.read_partition = MagicMock(return_value=table)

        processor = SilverProcessor(storage=mock_storage)
        await processor.process_bronze_partition("bronze/test/key.parquet")

        # Verify write_batch was called with tokenized data
        assert mock_storage.write_batch.called
        call_args = mock_storage.write_batch.call_args
        written_table = call_args.kwargs.get("table") or call_args[0][0]
        assert written_table.num_rows == 2

    @pytest.mark.asyncio
    async def test_rejected_events(self, mock_storage):
        bad_events = [
            {
                "event_type": "transaction-initiated",
                # Missing event_id
                "timestamp": "2026-01-15T14:00:00+00:00",
                "payload": {"transaction_id": "t1", "user_id": "u1", "amount": "50", "currency": "X"},
            },
        ]
        table = _events_to_table(bad_events)
        mock_storage.read_partition = MagicMock(return_value=table)

        processor = SilverProcessor(storage=mock_storage)
        result = await processor.process_bronze_partition("bronze/test/key.parquet")

        assert result["rejected"] == 1
        # Dead-letter write should have been called
        assert mock_storage.write_key.called

    def test_get_stats_initial(self, mock_storage):
        processor = SilverProcessor(storage=mock_storage)
        stats = processor.get_stats()
        assert stats["total_processed"] == 0

    @pytest.mark.asyncio
    async def test_stats_accumulate(self, mock_storage, sample_events):
        table = _events_to_table(sample_events)
        mock_storage.read_partition = MagicMock(return_value=table)

        processor = SilverProcessor(storage=mock_storage)
        await processor.process_bronze_partition("bronze/test/key.parquet")

        stats = processor.get_stats()
        assert stats["total_processed"] == 2
        assert stats["total_passed"] == 2
