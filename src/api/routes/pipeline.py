"""API routes for the data pipeline: bronze, silver, gold layers."""

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_session
from src.pipeline.bronze import BronzeIngestionBuffer, get_checkpoints, list_partitions_db
from src.pipeline.gold import GoldProcessor
from src.pipeline.models import SilverQualityLog
from src.pipeline.silver import SilverProcessor
from src.pipeline.storage import DataLakeStorage

from sqlalchemy import select

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])

# Shared instances
_storage = DataLakeStorage()
_bronze_buffer = BronzeIngestionBuffer(storage=_storage)
_silver_processor = SilverProcessor(storage=_storage)
_gold_processor = GoldProcessor(storage=_storage)


# ---------------------------------------------------------------------------
# Bronze endpoints
# ---------------------------------------------------------------------------


@router.get("/bronze/stats")
async def bronze_stats(session: AsyncSession = Depends(get_session)) -> dict:
    """Bronze ingestion statistics."""
    stats = _bronze_buffer.get_stats()
    checkpoints = await get_checkpoints(session)
    stats["latest_checkpoints"] = checkpoints
    return stats


@router.get("/bronze/partitions")
async def bronze_partitions(
    event_type: str | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List bronze partitions with metadata."""
    sd = datetime.fromisoformat(start_date) if start_date else None
    ed = datetime.fromisoformat(end_date) if end_date else None
    partitions = await list_partitions_db(
        session, layer="bronze", event_type=event_type, start_date=sd, end_date=ed
    )
    return {"partitions": partitions, "count": len(partitions)}


# ---------------------------------------------------------------------------
# Silver endpoints
# ---------------------------------------------------------------------------


@router.get("/silver/stats")
async def silver_stats() -> dict:
    """Silver processing statistics."""
    return _silver_processor.get_stats()


@router.get("/silver/quality")
async def silver_quality(
    event_type: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Latest quality check results per event type."""
    stmt = select(SilverQualityLog).order_by(SilverQualityLog.processed_at.desc()).limit(50)
    if event_type:
        stmt = stmt.where(SilverQualityLog.event_type == event_type)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return {
        "quality_results": [
            {
                "event_type": r.event_type,
                "total_events": r.total_events,
                "passed": r.passed,
                "rejected": r.rejected,
                "duplicates_removed": r.duplicates_removed,
                "warnings": r.warnings,
                "processed_at": r.processed_at.isoformat() if r.processed_at else None,
            }
            for r in rows
        ]
    }


@router.get("/silver/rejected")
async def silver_rejected(
    event_type: str | None = Query(None),
    limit: int = Query(10, ge=1, le=100),
) -> dict:
    """Sample of rejected events with rejection reasons."""
    partitions = _storage.list_partitions(
        "silver",
        prefix=f"silver/_rejected/{event_type}/" if event_type else "silver/_rejected/",
    )

    rejected_samples: list[dict] = []
    for p in partitions[:5]:  # Read up to 5 partitions
        try:
            table = _storage.read_partition(p["key"])
            import json

            for i in range(min(table.num_rows, limit - len(rejected_samples))):
                rejected_samples.append({
                    "event_id": table.column("event_id")[i].as_py(),
                    "event_type": table.column("event_type")[i].as_py(),
                    "rejection_reasons": json.loads(
                        table.column("rejection_reasons")[i].as_py()
                    ),
                })
                if len(rejected_samples) >= limit:
                    break
        except Exception:
            continue
        if len(rejected_samples) >= limit:
            break

    return {"rejected_events": rejected_samples, "count": len(rejected_samples)}


# ---------------------------------------------------------------------------
# Gold endpoints
# ---------------------------------------------------------------------------


@router.get("/gold/datasets")
async def gold_datasets(session: AsyncSession = Depends(get_session)) -> dict:
    """List available gold datasets with freshness timestamps."""
    datasets = await _gold_processor.get_datasets(session)
    return {"datasets": datasets}


@router.get("/gold/{dataset_name}")
async def query_gold_dataset(
    dataset_name: str,
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> dict:
    """Query a gold dataset with optional filters and date range."""
    date_range = (start_date, end_date) if start_date and end_date else None
    records = _gold_processor.query_gold(dataset_name, date_range=date_range)
    return {
        "dataset": dataset_name,
        "records": records[:limit],
        "total_count": len(records),
        "returned_count": min(len(records), limit),
    }


@router.post("/gold/{dataset_name}/refresh")
async def refresh_gold_dataset(
    dataset_name: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Trigger an on-demand refresh of a gold dataset."""
    result = await _gold_processor.refresh_dataset(dataset_name, session)
    return result
