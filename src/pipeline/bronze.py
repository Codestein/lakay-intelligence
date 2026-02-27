"""Bronze layer: raw, immutable event ingestion into the data lake."""

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa
import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.pipeline.models import DataPartition, IngestionCheckpoint, SchemaRegistry
from src.pipeline.storage import DataLakeStorage

logger = structlog.get_logger()

# All Kafka topics that flow into the bronze layer
BRONZE_TOPICS = [
    "trebanx.transaction.events",
    "trebanx.session.events",
    "trebanx.circle.events",
    "trebanx.remittance.events",
    "trebanx.security.events",
    "lakay.fraud.alerts",
    "lakay.circles.tier-changes",
    "lakay.behavior.ato-alerts",
    "lakay.compliance.alerts",
    "lakay.compliance.edd-triggers",
]

# Default flush settings
DEFAULT_FLUSH_INTERVAL_SECONDS = 60
DEFAULT_FLUSH_BATCH_SIZE = 1000


class BronzeIngestionBuffer:
    """Buffers events and flushes to Parquet on the bronze layer."""

    def __init__(
        self,
        storage: DataLakeStorage | None = None,
        flush_interval: int = DEFAULT_FLUSH_INTERVAL_SECONDS,
        flush_batch_size: int = DEFAULT_FLUSH_BATCH_SIZE,
    ):
        self.storage = storage or DataLakeStorage()
        self.flush_interval = flush_interval
        self.flush_batch_size = flush_batch_size
        # Buffers keyed by event_type
        self._buffers: dict[str, list[dict]] = {}
        self._last_flush: dict[str, float] = {}
        self._stats: dict[str, int] = {}  # total events ingested per type
        self._partitions_created = 0
        self._total_size_bytes = 0

    def add_event(
        self,
        event: dict[str, Any],
        source_topic: str,
        kafka_partition: int = 0,
        kafka_offset: int = 0,
    ) -> str | None:
        """Add an event to the buffer. Returns the partition key if a flush occurred."""
        event_type = event.get("event_type", "unknown")
        now = datetime.now(UTC)

        # Add metadata columns
        enriched = {
            **event,
            "_ingested_at": now.isoformat(),
            "_source_topic": source_topic,
            "_partition": kafka_partition,
            "_offset": kafka_offset,
        }

        if event_type not in self._buffers:
            self._buffers[event_type] = []
            self._last_flush[event_type] = time.time()

        self._buffers[event_type].append(enriched)
        self._stats[event_type] = self._stats.get(event_type, 0) + 1

        # Check flush conditions
        buffer = self._buffers[event_type]
        elapsed = time.time() - self._last_flush.get(event_type, time.time())
        if len(buffer) >= self.flush_batch_size or elapsed >= self.flush_interval:
            return self._flush(event_type)
        return None

    def flush_all(self) -> list[str]:
        """Flush all buffered event types. Returns list of written keys."""
        keys = []
        for event_type in list(self._buffers.keys()):
            if self._buffers[event_type]:
                key = self._flush(event_type)
                if key:
                    keys.append(key)
        return keys

    def _flush(self, event_type: str) -> str | None:
        """Write buffered events for an event_type to Parquet. Returns key."""
        buffer = self._buffers.get(event_type, [])
        if not buffer:
            return None

        now = datetime.now(UTC)
        batch_id = f"batch{uuid.uuid4().hex[:8]}"

        # Flatten events into a column-oriented structure for Parquet
        # Store the entire event as a JSON string column for immutability
        import json

        records = {
            "event_id": [e.get("event_id", "") for e in buffer],
            "event_type": [e.get("event_type", "") for e in buffer],
            "event_version": [e.get("event_version", "1.0") for e in buffer],
            "timestamp": [e.get("timestamp", "") for e in buffer],
            "source_service": [e.get("source_service", "") for e in buffer],
            "correlation_id": [e.get("correlation_id", "") for e in buffer],
            "payload_json": [json.dumps(e.get("payload", {})) for e in buffer],
            "_ingested_at": [e.get("_ingested_at", "") for e in buffer],
            "_source_topic": [e.get("_source_topic", "") for e in buffer],
            "_partition": [e.get("_partition", 0) for e in buffer],
            "_offset": [e.get("_offset", 0) for e in buffer],
            "_raw_json": [json.dumps(e) for e in buffer],
        }

        table = pa.table(records)

        try:
            key, size_bytes = self.storage.write_batch(
                table=table,
                layer="bronze",
                event_type=event_type,
                dt=now,
                batch_id=batch_id,
            )
            self._partitions_created += 1
            self._total_size_bytes += size_bytes
            self._buffers[event_type] = []
            self._last_flush[event_type] = time.time()

            logger.info(
                "bronze_flush",
                event_type=event_type,
                record_count=len(buffer),
                key=key,
            )
            return key
        except Exception:
            logger.exception("bronze_flush_error", event_type=event_type)
            return None

    def get_stats(self) -> dict:
        """Return ingestion statistics."""
        return {
            "total_events_ingested": sum(self._stats.values()),
            "events_by_type": dict(self._stats),
            "partitions_created": self._partitions_created,
            "total_size_bytes": self._total_size_bytes,
            "buffered_events": {k: len(v) for k, v in self._buffers.items() if v},
        }


# ---------------------------------------------------------------------------
# Schema registry helpers
# ---------------------------------------------------------------------------


async def register_schema(
    session: AsyncSession,
    event_type: str,
    schema_version: str,
    schema_definition: dict,
) -> None:
    """Register or update a schema in the registry."""
    stmt = (
        pg_insert(SchemaRegistry)
        .values(
            event_type=event_type,
            schema_version=schema_version,
            schema_definition=schema_definition,
        )
        .on_conflict_do_nothing(constraint="uq_event_schema")
    )
    await session.execute(stmt)
    await session.commit()
    logger.info("schema_registered", event_type=event_type, version=schema_version)


async def get_schemas(session: AsyncSession, event_type: str | None = None) -> list[dict]:
    """Retrieve schemas from the registry."""
    stmt = select(SchemaRegistry)
    if event_type:
        stmt = stmt.where(SchemaRegistry.event_type == event_type)
    stmt = stmt.order_by(SchemaRegistry.registered_at.desc())
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "event_type": r.event_type,
            "schema_version": r.schema_version,
            "schema_definition": r.schema_definition,
            "registered_at": r.registered_at.isoformat() if r.registered_at else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------


async def save_checkpoint(
    session: AsyncSession, topic: str, partition: int, offset: int
) -> None:
    """Upsert an ingestion checkpoint."""
    stmt = (
        pg_insert(IngestionCheckpoint)
        .values(topic=topic, partition=partition, offset=offset)
        .on_conflict_do_update(
            constraint="uq_topic_partition",
            set_={"offset": offset, "updated_at": datetime.now(UTC)},
        )
    )
    await session.execute(stmt)
    await session.commit()


async def get_checkpoints(session: AsyncSession) -> dict[str, dict[str, int]]:
    """Return latest checkpoint per topic/partition."""
    result = await session.execute(select(IngestionCheckpoint))
    rows = result.scalars().all()
    checkpoints: dict[str, dict[str, int]] = {}
    for r in rows:
        if r.topic not in checkpoints:
            checkpoints[r.topic] = {}
        checkpoints[r.topic][str(r.partition)] = r.offset
    return checkpoints


# ---------------------------------------------------------------------------
# Partition metadata persistence
# ---------------------------------------------------------------------------


async def record_partition(
    session: AsyncSession,
    layer: str,
    event_type: str,
    path: str,
    date_start: datetime,
    date_end: datetime,
    record_count: int,
    size_bytes: int,
    schema_version: str = "1.0",
) -> None:
    """Record metadata about a written partition."""
    partition = DataPartition(
        layer=layer,
        event_type=event_type,
        path=path,
        date_start=date_start,
        date_end=date_end,
        record_count=record_count,
        size_bytes=size_bytes,
        schema_version=schema_version,
    )
    session.add(partition)
    await session.commit()


async def list_partitions_db(
    session: AsyncSession,
    layer: str,
    event_type: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> list[dict]:
    """List partitions from the metadata table."""
    stmt = select(DataPartition).where(DataPartition.layer == layer)
    if event_type:
        stmt = stmt.where(DataPartition.event_type == event_type)
    if start_date:
        stmt = stmt.where(DataPartition.date_end >= start_date)
    if end_date:
        stmt = stmt.where(DataPartition.date_start <= end_date)
    stmt = stmt.order_by(DataPartition.date_start.desc())

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "layer": r.layer,
            "event_type": r.event_type,
            "path": r.path,
            "date_start": r.date_start.isoformat() if r.date_start else None,
            "date_end": r.date_end.isoformat() if r.date_end else None,
            "record_count": r.record_count,
            "size_bytes": r.size_bytes,
            "schema_version": r.schema_version,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
