"""Silver layer: validated, deduplicated, PII-tokenized data."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.pipeline.bronze import list_partitions_db, record_partition
from src.pipeline.models import SilverQualityLog
from src.pipeline.pii import PIITokenizer
from src.pipeline.quality import QualityCheckResult, run_quality_checks
from src.pipeline.storage import DataLakeStorage

logger = structlog.get_logger()

# Default processing schedule: 15 minutes
DEFAULT_PROCESSING_INTERVAL_SECONDS = 900

# Rejection rate alert threshold
DEFAULT_REJECTION_RATE_THRESHOLD = 0.10  # 10%


class SilverProcessor:
    """Process bronze partitions → silver layer with quality, dedup, PII tokenization."""

    def __init__(
        self,
        storage: DataLakeStorage | None = None,
        tokenizer: PIITokenizer | None = None,
    ):
        self.storage = storage or DataLakeStorage()
        self.tokenizer = tokenizer or PIITokenizer()
        self._stats: dict[str, dict[str, int]] = {}

    async def process_bronze_partition(
        self,
        partition_key: str,
        session: AsyncSession | None = None,
        schema: dict | None = None,
    ) -> dict:
        """Process a single bronze partition into silver.

        Returns processing stats dict.
        """
        # Read bronze data
        try:
            table = self.storage.read_partition(partition_key)
        except Exception:
            logger.exception("silver_read_error", partition_key=partition_key)
            return {"error": "read_failed", "partition_key": partition_key}

        # Convert Parquet rows back to event dicts
        events = self._table_to_events(table)
        if not events:
            return {"total": 0, "passed": 0, "rejected": 0, "deduplicated": 0}

        event_type = events[0].get("event_type", "unknown")

        # 1. Run quality checks
        passed, rejected, quality = run_quality_checks(events, schema=schema)

        # 2. Deduplicate
        deduped, dedup_count = self._deduplicate(passed)

        # 3. PII tokenization
        tokenized = [self.tokenizer.tokenize_event(e, event_type) for e in deduped]

        # 4. Write to silver layer
        silver_key = None
        if tokenized:
            silver_key = self._write_silver(tokenized, event_type)

        # 5. Write rejected events to dead-letter partition
        if rejected:
            self._write_rejected(rejected, event_type)

        # 6. Track stats
        stats_key = event_type
        if stats_key not in self._stats:
            self._stats[stats_key] = {
                "processed": 0, "passed": 0, "rejected": 0, "deduplicated": 0,
            }
        self._stats[stats_key]["processed"] += quality.total
        self._stats[stats_key]["passed"] += len(deduped)
        self._stats[stats_key]["rejected"] += quality.rejected
        self._stats[stats_key]["deduplicated"] += dedup_count

        # 7. Log quality to DB
        if session:
            await self._log_quality(session, partition_key, event_type, quality, dedup_count)

        # Check rejection rate
        if quality.total > 0:
            rejection_rate = quality.rejected / quality.total
            if rejection_rate > DEFAULT_REJECTION_RATE_THRESHOLD:
                logger.warning(
                    "high_rejection_rate",
                    event_type=event_type,
                    rejection_rate=rejection_rate,
                    rejected=quality.rejected,
                    total=quality.total,
                )

        result = {
            "total": quality.total,
            "passed": len(deduped),
            "rejected": quality.rejected,
            "deduplicated": dedup_count,
            "warnings": quality.warnings,
            "silver_key": silver_key,
            "event_type": event_type,
        }
        logger.info("silver_partition_processed", **result)
        return result

    async def process_new_bronze_data(
        self,
        session: AsyncSession,
        event_type: str | None = None,
    ) -> list[dict]:
        """Process all unprocessed bronze partitions.

        Returns list of processing results per partition.
        """
        # List bronze partitions
        bronze_partitions = await list_partitions_db(session, layer="bronze", event_type=event_type)

        # List already-processed silver partitions to avoid reprocessing
        silver_partitions = await list_partitions_db(
            session, layer="silver", event_type=event_type
        )
        processed_sources = {p["path"] for p in silver_partitions}

        results = []
        for partition in bronze_partitions:
            if partition["path"] in processed_sources:
                continue
            result = await self.process_bronze_partition(partition["path"], session=session)
            results.append(result)

        return results

    def _table_to_events(self, table: pa.Table) -> list[dict]:
        """Convert a PyArrow table back to event dicts."""
        events = []
        if "_raw_json" in table.column_names:
            for raw in table.column("_raw_json").to_pylist():
                try:
                    events.append(json.loads(raw))
                except (json.JSONDecodeError, TypeError):
                    continue
        else:
            # Reconstruct from columns
            for i in range(table.num_rows):
                event: dict[str, Any] = {}
                for col_name in table.column_names:
                    event[col_name] = table.column(col_name)[i].as_py()
                if "payload_json" in event:
                    try:
                        event["payload"] = json.loads(event.pop("payload_json"))
                    except (json.JSONDecodeError, TypeError):
                        pass
                events.append(event)
        return events

    def _deduplicate(self, events: list[dict]) -> tuple[list[dict], int]:
        """Deduplicate events by (event_id, timestamp). Returns (deduped, dup_count)."""
        seen: set[str] = set()
        deduped = []
        dup_count = 0

        for event in events:
            event_id = event.get("event_id", "")
            timestamp = event.get("timestamp", "")
            dedup_key = f"{event_id}:{timestamp}"

            if dedup_key in seen:
                dup_count += 1
                continue
            seen.add(dedup_key)
            deduped.append(event)

        if dup_count > 0:
            logger.info("dedup_removed", count=dup_count)
        return deduped, dup_count

    def _write_silver(self, events: list[dict], event_type: str) -> str | None:
        """Write tokenized events to the silver layer."""
        now = datetime.now(UTC)
        batch_id = f"batch{uuid.uuid4().hex[:8]}"

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
            "_processed_at": [now.isoformat()] * len(events),
        }

        table = pa.table(records)
        try:
            key, _size = self.storage.write_batch(
                table=table,
                layer="silver",
                event_type=event_type,
                dt=now,
                batch_id=batch_id,
            )
            return key
        except Exception:
            logger.exception("silver_write_error", event_type=event_type)
            return None

    def _write_rejected(self, rejected: list[dict], event_type: str) -> None:
        """Write rejected events to dead-letter partition."""
        now = datetime.now(UTC)
        batch_id = f"rejected{uuid.uuid4().hex[:8]}"

        records = {
            "event_id": [
                r["event"].get("event_id", "") for r in rejected
            ],
            "event_type": [event_type] * len(rejected),
            "rejection_reasons": [
                json.dumps(r["rejection_reasons"]) for r in rejected
            ],
            "raw_event": [json.dumps(r["event"]) for r in rejected],
            "_rejected_at": [now.isoformat()] * len(rejected),
        }

        table = pa.table(records)
        key = (
            f"silver/_rejected/{event_type}/{now.year}/{now.month:02d}/{now.day:02d}"
            f"/rejected_{int(now.timestamp())}_{batch_id}.parquet"
        )
        import io

        import pyarrow.parquet as pq

        buf = io.BytesIO()
        pq.write_table(table, buf, compression="snappy")
        data = buf.getvalue()
        try:
            self.storage.write_key(key, data)
            logger.info(
                "rejected_events_written",
                event_type=event_type,
                count=len(rejected),
                key=key,
            )
        except Exception:
            logger.exception("rejected_write_error", event_type=event_type)

    async def _log_quality(
        self,
        session: AsyncSession,
        partition_path: str,
        event_type: str,
        quality: QualityCheckResult,
        dedup_count: int,
    ) -> None:
        """Log quality check results to PostgreSQL."""
        log_entry = SilverQualityLog(
            partition_path=partition_path,
            event_type=event_type,
            total_events=quality.total,
            passed=quality.passed,
            rejected=quality.rejected,
            duplicates_removed=dedup_count,
            warnings=quality.warnings,
            details=quality.to_dict(),
        )
        session.add(log_entry)
        await session.commit()

    def get_stats(self) -> dict:
        """Return processing statistics."""
        total_processed = sum(s["processed"] for s in self._stats.values())
        total_passed = sum(s["passed"] for s in self._stats.values())
        total_rejected = sum(s["rejected"] for s in self._stats.values())
        total_dedup = sum(s["deduplicated"] for s in self._stats.values())
        return {
            "total_processed": total_processed,
            "total_passed": total_passed,
            "total_rejected": total_rejected,
            "total_deduplicated": total_dedup,
            "by_event_type": dict(self._stats),
        }
