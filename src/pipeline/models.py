"""Data pipeline ORM and Pydantic models for bronze/silver/gold layers."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class LayerName(StrEnum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


# ---------------------------------------------------------------------------
# ORM models (PostgreSQL metadata)
# ---------------------------------------------------------------------------


class DataPartition(Base):
    """Metadata about a stored partition in the data lake."""

    __tablename__ = "data_partitions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    layer: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    path: Mapped[str] = mapped_column(String, unique=True)
    date_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    date_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    schema_version: Mapped[str] = mapped_column(String, default="1.0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IngestionCheckpoint(Base):
    """Tracks the last ingested Kafka offset per topic/partition for exactly-once."""

    __tablename__ = "ingestion_checkpoints"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(String, index=True)
    partition: Mapped[int] = mapped_column(Integer)
    offset: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint("topic", "partition", name="uq_topic_partition"),
    )


class SchemaRegistry(Base):
    """Maps event_type → schema version → schema definition."""

    __tablename__ = "schema_registry"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    schema_version: Mapped[str] = mapped_column(String)
    schema_definition: Mapped[dict] = mapped_column(JSONB, default=dict)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint(
            "event_type", "schema_version", name="uq_event_schema"
        ),
    )


class PIITokenMapping(Base):
    """Encrypted mapping of PII tokens to original values."""

    __tablename__ = "pii_token_mappings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    field_name: Mapped[str] = mapped_column(String, index=True)
    token: Mapped[str] = mapped_column(String, unique=True, index=True)
    encrypted_value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SilverQualityLog(Base):
    """Quality check results per silver partition."""

    __tablename__ = "silver_quality_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    partition_path: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    total_events: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_removed: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class GoldDatasetMeta(Base):
    """Metadata for gold materialized datasets."""

    __tablename__ = "gold_dataset_meta"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_name: Mapped[str] = mapped_column(String, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    grain: Mapped[str] = mapped_column(String, default="")
    refresh_schedule: Mapped[str] = mapped_column(String, default="daily")
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    freshness_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class PartitionInfo(BaseModel):
    layer: str
    event_type: str
    path: str
    date_start: datetime
    date_end: datetime
    record_count: int
    size_bytes: int
    schema_version: str
    created_at: datetime


class BronzeStats(BaseModel):
    total_events_ingested: int = 0
    events_by_type: dict[str, int] = Field(default_factory=dict)
    partitions_created: int = 0
    total_size_bytes: int = 0
    latest_checkpoints: dict[str, dict[str, int]] = Field(default_factory=dict)


class SilverStats(BaseModel):
    total_processed: int = 0
    total_passed: int = 0
    total_rejected: int = 0
    total_deduplicated: int = 0
    by_event_type: dict[str, dict[str, int]] = Field(default_factory=dict)


class QualityResult(BaseModel):
    event_type: str
    total_events: int
    passed: int
    rejected: int
    duplicates_removed: int
    warnings: int
    processed_at: datetime


class GoldDatasetInfo(BaseModel):
    dataset_name: str
    description: str
    grain: str
    refresh_schedule: str
    last_refreshed_at: datetime | None = None
    record_count: int = 0


class RejectedEvent(BaseModel):
    event_id: str | None = None
    event_type: str | None = None
    rejection_reason: str
    raw_data: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Experiment models (Task 9.4) - separate file but referenced here for DB
# ---------------------------------------------------------------------------


class ExperimentDB(Base):
    """Experiment state stored in PostgreSQL."""

    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="draft")
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    variants: Mapped[dict] = mapped_column(JSONB, default=list)
    assignment_strategy: Mapped[str] = mapped_column(String, default="user_hash")
    traffic_allocation: Mapped[dict] = mapped_column(JSONB, default=dict)
    primary_metric: Mapped[str] = mapped_column(String, default="")
    guardrail_metrics: Mapped[dict] = mapped_column(JSONB, default=list)
    layer: Mapped[str] = mapped_column(String, default="default")
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String, default="system")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ExperimentAssignmentDB(Base):
    """Persistent user→variant assignment."""

    __tablename__ = "experiment_assignments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    experiment_id: Mapped[str] = mapped_column(String, index=True)
    variant_id: Mapped[str] = mapped_column(String)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint(
            "user_id", "experiment_id", name="uq_user_experiment"
        ),
    )


class ExperimentMetricDB(Base):
    """Metric observations for experiments."""

    __tablename__ = "experiment_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(String, index=True)
    variant_id: Mapped[str] = mapped_column(String, index=True)
    metric_name: Mapped[str] = mapped_column(String, index=True)
    metric_value: Mapped[float] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer, default=1)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ComplianceReportDB(Base):
    """Generated compliance reports metadata."""

    __tablename__ = "compliance_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    report_type: Mapped[str] = mapped_column(String, index=True)
    date_range_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    date_range_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="generated")
    storage_path: Mapped[str] = mapped_column(String, default="")
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    report_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
