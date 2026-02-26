"""Pydantic models for the behavior domain."""

from datetime import datetime

from pydantic import BaseModel, Field


class AnomalyDetectionRequest(BaseModel):
    session_id: str
    user_id: str
    events: list[dict] = []


class AnomalyDetectionResponse(BaseModel):
    anomaly_score: float = Field(ge=0.0, le=1.0)
    is_anomalous: bool = False
    anomaly_types: list[str] = []
    model_version: str = "stub"
    computed_at: datetime


class UserProfile(BaseModel):
    user_id: str
    behavioral_features: dict = {}
    risk_level: str = "low"
    last_updated: datetime
