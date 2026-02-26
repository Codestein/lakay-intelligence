"""Pydantic models for the compliance domain."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ComplianceRiskRequest(BaseModel):
    user_id: str


class ComplianceRiskResponse(BaseModel):
    user_id: str
    risk_level: RiskLevel = RiskLevel.LOW
    risk_score: float = Field(ge=0, le=100)
    factors: dict = {}
    model_version: str = "stub"
    computed_at: datetime
