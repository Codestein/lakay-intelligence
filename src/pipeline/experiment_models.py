"""Pydantic models for the experimentation / A/B testing framework."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AssignmentStrategy(StrEnum):
    USER_HASH = "user_hash"
    RANDOM = "random"
    SEGMENT = "segment"


class ExperimentVariant(BaseModel):
    variant_id: str
    name: str  # e.g., "control", "treatment_a"
    config: dict[str, Any] = Field(default_factory=dict)


class CreateExperimentRequest(BaseModel):
    name: str
    description: str = ""
    hypothesis: str = ""
    variants: list[ExperimentVariant]
    assignment_strategy: AssignmentStrategy = AssignmentStrategy.USER_HASH
    traffic_allocation: dict[str, float] = Field(default_factory=dict)
    primary_metric: str = ""
    guardrail_metrics: list[str] = Field(default_factory=list)
    layer: str = "default"
    created_by: str = "system"


class ExperimentResponse(BaseModel):
    experiment_id: str
    name: str
    description: str = ""
    status: ExperimentStatus
    hypothesis: str = ""
    variants: list[ExperimentVariant] = Field(default_factory=list)
    assignment_strategy: str = "user_hash"
    traffic_allocation: dict[str, float] = Field(default_factory=dict)
    primary_metric: str = ""
    guardrail_metrics: list[str] = Field(default_factory=list)
    layer: str = "default"
    start_date: datetime | None = None
    end_date: datetime | None = None
    created_by: str = "system"
    created_at: datetime | None = None
    report: dict | None = None


class ExperimentAssignment(BaseModel):
    user_id: str
    experiment_id: str
    variant_id: str
    assigned_at: datetime


class MetricSummary(BaseModel):
    variant_id: str
    metric_name: str
    mean: float
    std: float
    count: int
    confidence_interval: tuple[float, float] = (0.0, 0.0)


class SignificanceResult(BaseModel):
    metric_name: str
    control_variant: str
    treatment_variant: str
    control_mean: float
    treatment_mean: float
    p_value: float
    effect_size: float
    confidence_interval: tuple[float, float]
    control_sample_size: int
    treatment_sample_size: int
    is_significant: bool
    alpha: float = 0.05
    minimum_sample_met: bool = True


class GuardrailStatus(BaseModel):
    metric_name: str
    variant_id: str
    current_value: float
    threshold: float
    breached: bool
    description: str = ""


class ExperimentReport(BaseModel):
    experiment_id: str
    name: str
    hypothesis: str
    variants: list[ExperimentVariant]
    metric_summaries: dict[str, list[MetricSummary]] = Field(default_factory=dict)
    significance_results: list[SignificanceResult] = Field(default_factory=list)
    guardrail_statuses: list[GuardrailStatus] = Field(default_factory=list)
    recommendation: str = "inconclusive"  # ship / don't_ship / inconclusive
    generated_at: datetime | None = None
