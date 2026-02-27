"""SQLAlchemy ORM models for Lakay Intelligence internal state."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RawEvent(Base):
    __tablename__ = "raw_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed: Mapped[bool] = mapped_column(Boolean, default=False)


class FraudScore(Base):
    __tablename__ = "fraud_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    risk_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_tier: Mapped[str | None] = mapped_column(String, nullable=True)
    rules_triggered: Mapped[dict] = mapped_column(JSONB, default=dict)
    model_version: Mapped[str] = mapped_column(String)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CircleHealth(Base):
    __tablename__ = "circle_health"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    circle_id: Mapped[str] = mapped_column(String, index=True)
    health_score: Mapped[float] = mapped_column(Float)
    health_tier: Mapped[str] = mapped_column(String, default="healthy")
    trend: Mapped[str] = mapped_column(String, default="stable")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    dimension_scores: Mapped[dict] = mapped_column(JSONB, default=dict)
    factors: Mapped[dict] = mapped_column(JSONB, default=dict)
    scoring_version: Mapped[str] = mapped_column(String, default="circle-health-v1")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CircleAnomalyDB(Base):
    __tablename__ = "circle_anomalies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    anomaly_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    circle_id: Mapped[str] = mapped_column(String, index=True)
    anomaly_type: Mapped[str] = mapped_column(String, index=True)
    severity: Mapped[str] = mapped_column(String)
    affected_members: Mapped[dict] = mapped_column(JSONB, default=list)
    evidence: Mapped[dict] = mapped_column(JSONB, default=list)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CircleClassificationDB(Base):
    __tablename__ = "circle_classifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    circle_id: Mapped[str] = mapped_column(String, index=True)
    health_tier: Mapped[str] = mapped_column(String, index=True)
    health_score: Mapped[float] = mapped_column(Float)
    trend: Mapped[str] = mapped_column(String)
    anomaly_count: Mapped[int] = mapped_column(BigInteger, default=0)
    recommended_actions: Mapped[dict] = mapped_column(JSONB, default=list)
    classification_reason: Mapped[str] = mapped_column(String, default="")
    classified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CircleTierChangeDB(Base):
    __tablename__ = "circle_tier_changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    circle_id: Mapped[str] = mapped_column(String, index=True)
    previous_tier: Mapped[str] = mapped_column(String)
    new_tier: Mapped[str] = mapped_column(String)
    health_score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserProfileDB(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    behavioral_features: Mapped[dict] = mapped_column(JSONB, default=dict)
    risk_level: Mapped[str] = mapped_column(String, default="low")
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    alert_type: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
