"""Pydantic models for the fraud domain."""

from datetime import datetime

from pydantic import BaseModel, Field


class FraudScoreRequest(BaseModel):
    transaction_id: str
    user_id: str
    amount: str
    currency: str = "USD"
    ip_address: str | None = None
    device_id: str | None = None


class FraudScoreResponse(BaseModel):
    transaction_id: str
    score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_factors: list[str] = []
    model_version: str = "stub"
    computed_at: datetime


class FraudAlert(BaseModel):
    alert_id: str
    user_id: str
    alert_type: str
    severity: str
    confidence_score: float
    details: dict
    status: str = "open"
    created_at: datetime
    resolved_at: datetime | None = None
