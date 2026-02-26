"""Pydantic models for the fraud domain."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class RiskFactor(StrEnum):
    HIGH_AMOUNT = "high_amount"
    STRUCTURING_NEAR_3K = "structuring_near_3k"
    STRUCTURING_NEAR_10K = "structuring_near_10k"
    VELOCITY_COUNT_1H = "velocity_count_1h"
    VELOCITY_COUNT_24H = "velocity_count_24h"
    VELOCITY_AMOUNT_24H = "velocity_amount_24h"
    NEW_DEVICE = "new_device"
    NEW_GEOLOCATION = "new_geolocation"
    IMPOSSIBLE_TRAVEL = "impossible_travel"
    UNUSUAL_HOUR = "unusual_hour"


class RuleResult(BaseModel):
    rule_name: str
    triggered: bool
    score: float = 0.0
    risk_factor: RiskFactor | None = None
    details: str = ""


class TransactionFeatures(BaseModel):
    velocity_count_1h: int = 0
    velocity_count_24h: int = 0
    velocity_amount_1h: float = 0.0
    velocity_amount_24h: float = 0.0
    unique_devices_7d: int = 0
    unique_countries_7d: int = 0
    is_new_device: bool = False
    is_new_country: bool = False
    last_geo_location: dict | None = None
    time_since_last_txn_seconds: float | None = None
    avg_amount_30d: float = 0.0
    stddev_amount_30d: float = 0.0


class ScoringResult(BaseModel):
    final_score: float = Field(ge=0, le=100)
    rule_results: list[RuleResult] = []
    features_used: TransactionFeatures | None = None


class FraudScoreRequest(BaseModel):
    transaction_id: str
    user_id: str
    amount: str
    currency: str = "USD"
    ip_address: str | None = None
    device_id: str | None = None
    geo_location: dict | None = None
    transaction_type: str | None = None
    initiated_at: datetime | None = None

    @property
    def amount_float(self) -> float:
        return float(Decimal(self.amount))


class FraudScoreResponse(BaseModel):
    transaction_id: str
    score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_factors: list[str] = []
    model_version: str = "rules-v1"
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
