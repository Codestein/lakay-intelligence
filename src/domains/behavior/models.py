"""Pydantic models for the behavioral analytics domain (Phase 7)."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


# --- Enums ---


class ProfileStatus(StrEnum):
    BUILDING = "building"
    ACTIVE = "active"
    STALE = "stale"


class AnomalyClassification(StrEnum):
    NORMAL = "normal"
    SUSPICIOUS = "suspicious"
    HIGH_RISK = "high_risk"
    CRITICAL = "critical"


class RecommendedAction(StrEnum):
    NONE = "none"
    MONITOR = "monitor"
    CHALLENGE = "challenge"
    TERMINATE = "terminate"


class LifecycleStage(StrEnum):
    NEW = "new"
    ONBOARDING = "onboarding"
    ACTIVE = "active"
    POWER_USER = "power_user"
    DECLINING = "declining"
    DORMANT = "dormant"
    CHURNED = "churned"
    REACTIVATED = "reactivated"


class ATORiskLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class ATOResponseAction(StrEnum):
    NONE = "none"
    RE_AUTH = "re_authenticate"
    STEP_UP = "step_up_auth"
    LOCK = "lock_account"


class ATOAlertStatus(StrEnum):
    NEW = "new"
    INVESTIGATING = "investigating"
    CONFIRMED_ATO = "confirmed_ato"
    FALSE_POSITIVE = "false_positive"
    RESOLVED = "resolved"


# --- Baseline Models ---


class SessionBaseline(BaseModel):
    avg_duration: float = 0.0
    std_duration: float = 0.0
    avg_actions: float = 0.0
    std_actions: float = 0.0
    typical_action_sequences: list[list[str]] = Field(default_factory=list)


class TemporalBaseline(BaseModel):
    typical_hours: dict[int, float] = Field(default_factory=dict)  # hour -> frequency
    typical_days: dict[int, float] = Field(default_factory=dict)  # weekday (0=Mon) -> frequency
    typical_frequency_mean: float = 0.0  # sessions per week
    typical_frequency_std: float = 0.0


class DeviceBaseline(BaseModel):
    known_devices: list[str] = Field(default_factory=list)  # device fingerprints
    primary_device: str | None = None
    device_switch_rate: float = 0.0  # fraction of sessions on a different device
    device_platforms: list[str] = Field(default_factory=list)  # e.g., ["ios", "android"]


class GeographicBaseline(BaseModel):
    known_locations: list[dict[str, str]] = Field(default_factory=list)  # [{"city": ..., "country": ...}]
    primary_location: dict[str, str] | None = None
    typical_travel_patterns: list[dict[str, str]] = Field(default_factory=list)  # common transitions


class EngagementBaseline(BaseModel):
    typical_features_used: list[str] = Field(default_factory=list)
    feature_usage_breadth: float = 0.0  # 0.0–1.0
    avg_sessions_per_week: float = 0.0


# --- Profile Model ---


class UserBehaviorProfile(BaseModel):
    user_id: str
    profile_status: ProfileStatus = ProfileStatus.BUILDING
    profile_maturity: int = 0  # number of sessions used to build the profile
    session_baseline: SessionBaseline = Field(default_factory=SessionBaseline)
    temporal_baseline: TemporalBaseline = Field(default_factory=TemporalBaseline)
    device_baseline: DeviceBaseline = Field(default_factory=DeviceBaseline)
    geographic_baseline: GeographicBaseline = Field(default_factory=GeographicBaseline)
    engagement_baseline: EngagementBaseline = Field(default_factory=EngagementBaseline)
    last_updated: datetime
    profile_version: str = "behavior-profile-v1"


# --- Anomaly Scoring Models ---


class DimensionAnomalyScore(BaseModel):
    dimension: str
    score: float = Field(ge=0.0, le=1.0)
    details: str = ""


class SessionAnomalyResult(BaseModel):
    session_id: str
    user_id: str
    composite_score: float = Field(ge=0.0, le=1.0)
    classification: AnomalyClassification
    dimension_scores: list[DimensionAnomalyScore] = Field(default_factory=list)
    profile_maturity: int = 0
    recommended_action: RecommendedAction = RecommendedAction.NONE
    timestamp: datetime


class SessionScoreRequest(BaseModel):
    session_id: str
    user_id: str
    device_id: str | None = None
    device_type: str | None = None  # e.g., "ios", "android", "web"
    ip_address: str | None = None
    geo_location: dict | None = None  # {"city": ..., "country": ..., "lat": ..., "lon": ...}
    session_start: datetime | None = None
    session_duration_seconds: float | None = None
    action_count: int | None = None
    actions: list[str] | None = None  # sequence of action types
    features: dict | None = None  # override Feast features for testing


# --- Engagement Models ---


class UserEngagement(BaseModel):
    user_id: str
    engagement_score: float = Field(ge=0, le=100)
    lifecycle_stage: LifecycleStage
    churn_risk: float = Field(ge=0.0, le=1.0, default=0.0)
    churn_risk_level: str = "low"  # low / medium / high
    engagement_trend: str = "stable"  # improving / stable / declining
    computed_at: datetime


class EngagementSummary(BaseModel):
    total_users: int = 0
    stage_distribution: dict[str, int] = Field(default_factory=dict)
    avg_engagement_by_stage: dict[str, float] = Field(default_factory=dict)
    computed_at: datetime


class AtRiskUser(BaseModel):
    user_id: str
    engagement_score: float
    lifecycle_stage: LifecycleStage
    churn_risk: float
    days_since_last_login: int = 0


# --- ATO Models ---


class ATOSignal(BaseModel):
    signal_name: str
    score: float = Field(ge=0.0, le=1.0)
    details: str = ""


class ATOAssessment(BaseModel):
    session_id: str
    user_id: str
    ato_risk_score: float = Field(ge=0.0, le=1.0)
    risk_level: ATORiskLevel
    contributing_signals: list[ATOSignal] = Field(default_factory=list)
    recommended_response: ATOResponseAction = ATOResponseAction.NONE
    affected_transactions: list[str] = Field(default_factory=list)
    timestamp: datetime


class ATOAssessRequest(BaseModel):
    session_id: str
    user_id: str
    device_id: str | None = None
    device_type: str | None = None
    ip_address: str | None = None
    geo_location: dict | None = None
    session_start: datetime | None = None
    session_duration_seconds: float | None = None
    action_count: int | None = None
    actions: list[str] | None = None
    failed_login_count_10m: int = 0
    failed_login_count_1h: int = 0
    pending_transactions: list[str] | None = None
    features: dict | None = None  # override Feast features for testing


class ATOAlert(BaseModel):
    alert_id: str
    user_id: str
    session_id: str
    ato_risk_score: float = Field(ge=0.0, le=1.0)
    risk_level: ATORiskLevel
    contributing_signals: list[ATOSignal] = Field(default_factory=list)
    recommended_response: ATOResponseAction
    affected_transactions: list[str] = Field(default_factory=list)
    created_at: datetime
    status: ATOAlertStatus = ATOAlertStatus.NEW


class ATOAlertUpdate(BaseModel):
    status: ATOAlertStatus


# --- API Response Models ---


class ProfileSummary(BaseModel):
    user_id: str
    profile_status: ProfileStatus
    profile_maturity: int
    primary_device: str | None = None
    primary_location: dict[str, str] | None = None
    typical_hours: str = ""  # human-readable
    risk_level: str = "low"
    last_updated: datetime
