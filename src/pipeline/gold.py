"""Gold layer: business-ready aggregated datasets (materialized views)."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.pipeline.aggregations import (
    GOLD_DATASETS,
    aggregate_circle_lifecycle,
    aggregate_compliance_reporting,
    aggregate_daily_transactions,
    aggregate_haiti_corridor,
    aggregate_platform_health,
    aggregate_user_risk,
)
from src.pipeline.models import GoldDatasetMeta
from src.pipeline.storage import DataLakeStorage

logger = structlog.get_logger()

# Map dataset name → aggregation function
AGGREGATION_FUNCTIONS = {
    "daily-transaction-summary": aggregate_daily_transactions,
    "circle-lifecycle-summary": aggregate_circle_lifecycle,
    "user-risk-dashboard": aggregate_user_risk,
    "compliance-reporting": aggregate_compliance_reporting,
    "platform-health": aggregate_platform_health,
    "haiti-corridor-analytics": aggregate_haiti_corridor,
}


class GoldProcessor:
    """Process silver data into gold materialized datasets."""

    def __init__(self, storage: DataLakeStorage | None = None):
        self.storage = storage or DataLakeStorage()

    async def refresh_dataset(
        self,
        dataset_name: str,
        session: AsyncSession,
        date_range: tuple[datetime, datetime] | None = None,
    ) -> dict:
        """Refresh a gold dataset by reading silver and applying aggregation.

        Returns refresh stats.
        """
        if dataset_name not in GOLD_DATASETS:
            return {"error": f"unknown dataset: {dataset_name}"}

        dataset_def = GOLD_DATASETS[dataset_name]
        source_types = dataset_def["source_event_types"]
        agg_fn = AGGREGATION_FUNCTIONS.get(dataset_name)
        if not agg_fn:
            return {"error": f"no aggregation function for {dataset_name}"}

        # Collect events from silver layer
        all_events: list[dict] = []
        for event_type in source_types:
            events = self._read_silver_events(event_type)
            all_events.extend(events)

        if not all_events:
            logger.info("gold_no_data", dataset=dataset_name)
            return {"dataset": dataset_name, "records": 0, "status": "no_data"}

        # Apply date range filter if provided
        if date_range:
            start, end = date_range
            filtered = []
            for e in all_events:
                ts = e.get("timestamp", "")
                if isinstance(ts, str):
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if start <= dt <= end:
                            filtered.append(e)
                    except (ValueError, TypeError):
                        filtered.append(e)
                else:
                    filtered.append(e)
            all_events = filtered

        # Run aggregation
        if dataset_name == "user-risk-dashboard":
            # user-risk-dashboard accepts extra keyword arguments
            aggregated = agg_fn(all_events)
        else:
            aggregated = agg_fn(all_events)

        if not aggregated:
            return {"dataset": dataset_name, "records": 0, "status": "no_results"}

        # Write to gold layer
        now = datetime.now(UTC)
        batch_id = f"gold{uuid.uuid4().hex[:8]}"
        key = self._write_gold(aggregated, dataset_name, now, batch_id)

        # Update metadata
        await self._update_metadata(
            session, dataset_name, dataset_def, len(aggregated), now
        )

        result = {
            "dataset": dataset_name,
            "records": len(aggregated),
            "key": key,
            "refreshed_at": now.isoformat(),
            "status": "refreshed",
        }
        logger.info("gold_dataset_refreshed", **result)
        return result

    async def refresh_all(self, session: AsyncSession) -> list[dict]:
        """Refresh all gold datasets."""
        results = []
        for name in GOLD_DATASETS:
            result = await self.refresh_dataset(name, session)
            results.append(result)
        return results

    def query_gold(
        self,
        dataset_name: str,
        filters: dict[str, Any] | None = None,
        date_range: tuple[str, str] | None = None,
    ) -> list[dict]:
        """Query a gold dataset from storage.

        Returns list of records (dicts).
        """
        partitions = self.storage.list_partitions("gold", event_type=dataset_name)
        if not partitions:
            return []

        all_records: list[dict] = []
        for p in partitions:
            try:
                table = self.storage.read_partition(p["key"])
                records = table.to_pydict()
                # Convert column-oriented dict to list of row dicts
                if records:
                    num_rows = len(next(iter(records.values())))
                    for i in range(num_rows):
                        row = {col: records[col][i] for col in records}
                        all_records.append(row)
            except Exception:
                logger.warning("gold_read_error", key=p["key"])
                continue

        # Apply filters
        if filters:
            all_records = [
                r for r in all_records
                if all(r.get(k) == v for k, v in filters.items())
            ]

        # Apply date range filter
        if date_range:
            start_str, end_str = date_range
            all_records = [
                r for r in all_records
                if "date" in r and start_str <= str(r["date"]) <= end_str
            ]

        return all_records

    def _read_silver_events(self, event_type: str) -> list[dict]:
        """Read all silver events for a given event type."""
        partitions = self.storage.list_partitions("silver", event_type=event_type)
        events: list[dict] = []

        for p in partitions:
            try:
                table = self.storage.read_partition(p["key"])
                # Reconstruct events from silver columns
                for i in range(table.num_rows):
                    event: dict[str, Any] = {}
                    for col_name in table.column_names:
                        event[col_name] = table.column(col_name)[i].as_py()
                    # Parse payload_json back to dict
                    if "payload_json" in event:
                        try:
                            event["payload"] = json.loads(event["payload_json"])
                        except (json.JSONDecodeError, TypeError):
                            event["payload"] = {}
                    events.append(event)
            except Exception:
                logger.warning("silver_read_error", key=p["key"], event_type=event_type)
                continue

        return events

    def _write_gold(
        self, records: list[dict], dataset_name: str, dt: datetime, batch_id: str
    ) -> str | None:
        """Write aggregated records to the gold layer as Parquet."""
        if not records:
            return None

        # Build column-oriented dict from list of row dicts
        columns: dict[str, list] = {}
        for key in records[0]:
            columns[key] = []
        for record in records:
            for key in columns:
                val = record.get(key)
                # Convert non-primitive types to strings for Parquet
                if isinstance(val, (dict, list, set)):
                    val = json.dumps(val, default=str)
                columns[key].append(val)

        table = pa.table(columns)
        try:
            key, _size = self.storage.write_batch(
                table=table,
                layer="gold",
                event_type=dataset_name,
                dt=dt,
                batch_id=batch_id,
            )
            return key
        except Exception:
            logger.exception("gold_write_error", dataset=dataset_name)
            return None

    async def _update_metadata(
        self,
        session: AsyncSession,
        dataset_name: str,
        dataset_def: dict,
        record_count: int,
        refreshed_at: datetime,
    ) -> None:
        """Update gold dataset metadata in PostgreSQL."""
        result = await session.execute(
            select(GoldDatasetMeta).where(GoldDatasetMeta.dataset_name == dataset_name)
        )
        meta = result.scalar_one_or_none()

        if meta:
            meta.last_refreshed_at = refreshed_at
            meta.record_count = record_count
            if meta.last_refreshed_at:
                meta.freshness_seconds = int(
                    (refreshed_at - meta.last_refreshed_at).total_seconds()
                )
        else:
            meta = GoldDatasetMeta(
                dataset_name=dataset_name,
                description=dataset_def.get("description", ""),
                grain=dataset_def.get("grain", ""),
                refresh_schedule=dataset_def.get("refresh_schedule", "daily"),
                last_refreshed_at=refreshed_at,
                record_count=record_count,
                freshness_seconds=0,
            )
            session.add(meta)

        await session.commit()

    async def get_datasets(self, session: AsyncSession) -> list[dict]:
        """List all gold datasets with metadata."""
        result = await session.execute(select(GoldDatasetMeta))
        rows = result.scalars().all()
        db_meta = {r.dataset_name: r for r in rows}

        datasets = []
        for name, defn in GOLD_DATASETS.items():
            meta = db_meta.get(name)
            datasets.append({
                "dataset_name": name,
                "description": defn["description"],
                "grain": defn["grain"],
                "refresh_schedule": defn["refresh_schedule"],
                "last_refreshed_at": (
                    meta.last_refreshed_at.isoformat() if meta and meta.last_refreshed_at else None
                ),
                "record_count": meta.record_count if meta else 0,
            })
        return datasets
