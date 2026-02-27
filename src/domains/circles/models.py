"""Pydantic models for the circle health scoring domain."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# --- Enums ---


class HealthTier(StrEnum):
    HEALTHY = "healthy"
    AT_RISK = "at-risk"
    CRITICAL = "critical"


class TrendDirection(StrEnum):
    IMPROVING = "improving"
    STABLE = "stable"
    DETERIORATING = "deteriorating"


class AnomalyType(StrEnum):
    COORDINATED_LATE = "coordinated_late"
    POST_PAYOUT_DISENGAGEMENT = "post_payout_disengagement"
    FREE_RIDER = "free_rider"
    BEHAVIORAL_SHIFT = "behavioral_shift"


class AnomalySeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# --- Request Models ---


class CircleHealthRequest(BaseModel):
    circle_id: str


class CircleScoreRequest(BaseModel):
    circle_id: str
    # Optional: pass features directly for testing instead of fetching from store
    features: dict[str, float] | None = None


# --- Scoring Output Models ---


class DimensionScore(BaseModel):
    dimension_name: str
    score: float = Field(ge=0, le=100)
    weight: float = Field(ge=0, le=1)
    contributing_factors: list[str] = Field(default_factory=list)


class CircleHealthScore(BaseModel):
    circle_id: str
    health_score: float = Field(ge=0, le=100)
    health_tier: HealthTier
    dimension_scores: dict[str, DimensionScore] = Field(default_factory=dict)
    trend: TrendDirection = TrendDirection.STABLE
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    last_updated: datetime
    scoring_version: str = "circle-health-v1"


# --- Anomaly Models ---


class AnomalyEvidence(BaseModel):
    metric_name: str
    observed_value: float
    threshold: float
    description: str


class CircleAnomaly(BaseModel):
    anomaly_id: str
    circle_id: str
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    affected_members: list[str] = Field(default_factory=list)
    evidence: list[AnomalyEvidence] = Field(default_factory=list)
    detected_at: datetime


# --- Classification Models ---


class RecommendedAction(BaseModel):
    action: str
    reason: str
    priority: str = "medium"  # low / medium / high


class CircleClassification(BaseModel):
    circle_id: str
    health_tier: HealthTier
    health_score: float = Field(ge=0, le=100)
    trend: TrendDirection
    anomaly_count: int = 0
    highest_anomaly_severity: AnomalySeverity | None = None
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)
    classified_at: datetime
    classification_reason: str = ""


class TierChange(BaseModel):
    circle_id: str
    previous_tier: HealthTier
    new_tier: HealthTier
    health_score: float
    reason: str
    changed_at: datetime


# --- API Response Models ---


class CircleHealthSummaryItem(BaseModel):
    circle_id: str
    health_score: float
    health_tier: HealthTier
    trend: TrendDirection
    last_updated: datetime


class CircleHealthSummaryResponse(BaseModel):
    items: list[CircleHealthSummaryItem]
    total: int


class AtRiskCircleItem(BaseModel):
    circle_id: str
    health_score: float
    health_tier: HealthTier
    trend: TrendDirection
    recommended_actions: list[RecommendedAction]
    classified_at: datetime
