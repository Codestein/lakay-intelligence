"""Engagement scoring and lifecycle classification (Phase 7, Task 7.3).

Classifies users by lifecycle stage and engagement level, computing a
0-100 engagement health metric and churn risk signals.
"""

from datetime import UTC, datetime
from typing import Any

import structlog

from src.features.store import FeatureStore

from .config import BehaviorConfig, default_config
from .models import (
    AtRiskUser,
    EngagementSummary,
    LifecycleStage,
    UserBehaviorProfile,
    UserEngagement,
)

logger = structlog.get_logger()


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


class EngagementScorer:
    """Computes engagement scores and lifecycle classification."""

    def __init__(
        self,
        config: BehaviorConfig | None = None,
        feature_store: FeatureStore | None = None,
    ) -> None:
        self._config = config or default_config
        self._feature_store = feature_store or FeatureStore()

    async def score_engagement(
        self,
        user_id: str,
        profile: UserBehaviorProfile | None = None,
        feast_features: dict[str, Any] | None = None,
        engagement_history: list[float] | None = None,
    ) -> UserEngagement:
        """Compute engagement score and lifecycle stage for a user.

        Args:
            user_id: The user identifier.
            profile: The user's behavioral profile (optional).
            feast_features: Override Feast features for testing.
            engagement_history: Recent weekly engagement scores for trend analysis.

        Returns:
            UserEngagement with score, lifecycle stage, and churn risk.
        """
        cfg = self._config.engagement
        now = datetime.now(UTC)

        # Fetch features from Feast if not provided
        if feast_features is None:
            feast_features = await self._feature_store.get_features(user_id, "behavior")

        # Extract feature values
        session_count_7d = feast_features.get("session_count_7d", 0)
        login_streak = feast_features.get("login_streak_days", 0)
        feature_breadth = feast_features.get("feature_usage_breadth", 0.0)
        days_since_login = feast_features.get("days_since_last_login", 0)
        avg_sessions_30d = feast_features.get("avg_actions_per_session_30d", 0.0)

        # Use profile data for additional context
        personal_frequency = 0.0
        if profile:
            personal_frequency = profile.engagement_baseline.avg_sessions_per_week

        # Compute engagement score (0-100)
        engagement_score = self._compute_engagement_score(
            session_count_7d=session_count_7d,
            login_streak=login_streak,
            feature_breadth=feature_breadth,
            days_since_login=days_since_login,
            personal_frequency=personal_frequency,
        )

        # Determine lifecycle stage
        maturity = profile.profile_maturity if profile else 0
        lifecycle_stage = self._classify_lifecycle(
            session_count=maturity,
            days_since_login=days_since_login,
            engagement_score=engagement_score,
            personal_frequency=personal_frequency,
            session_count_7d=session_count_7d,
            engagement_history=engagement_history,
        )

        # Compute churn risk
        churn_risk, churn_level = self._compute_churn_risk(
            lifecycle_stage=lifecycle_stage,
            engagement_score=engagement_score,
            engagement_history=engagement_history,
        )

        # Determine engagement trend
        trend = self._compute_trend(engagement_history)

        result = UserEngagement(
            user_id=user_id,
            engagement_score=round(engagement_score, 2),
            lifecycle_stage=lifecycle_stage,
            churn_risk=round(churn_risk, 4),
            churn_risk_level=churn_level,
            engagement_trend=trend,
            computed_at=now,
        )

        logger.info(
            "engagement_scored",
            user_id=user_id,
            engagement_score=result.engagement_score,
            lifecycle_stage=lifecycle_stage.value,
            churn_risk=result.churn_risk,
        )

        return result

    def _compute_engagement_score(
        self,
        session_count_7d: int,
        login_streak: int,
        feature_breadth: float,
        days_since_login: int,
        personal_frequency: float,
    ) -> float:
        """Compute a 0-100 engagement score from multiple signals.

        Each signal is relative to the user's own baseline when possible.
        """
        cfg = self._config.engagement

        # 1. Frequency: session_count_7d relative to personal baseline
        if personal_frequency > 0:
            # Compare to personal baseline (ratio)
            expected_weekly = personal_frequency
            frequency_ratio = session_count_7d / max(expected_weekly, 0.1)
            # 1.0 ratio = 100 score, 0 = 0, >1.5 = still 100
            freq_score = _clamp(frequency_ratio * 100)
        else:
            # No baseline — use absolute scale
            # 7+ sessions/week = 100, 0 = 0
            freq_score = _clamp(session_count_7d / 7.0 * 100)

        # 2. Recency: days since last login
        if days_since_login <= 1:
            recency_score = 100.0
        elif days_since_login <= 3:
            recency_score = 80.0
        elif days_since_login <= 7:
            recency_score = 60.0
        elif days_since_login <= 14:
            recency_score = 30.0
        elif days_since_login <= 30:
            recency_score = 10.0
        else:
            recency_score = 0.0

        # 3. Login streak
        if login_streak >= 14:
            streak_score = 100.0
        elif login_streak >= 7:
            streak_score = 80.0
        elif login_streak >= 3:
            streak_score = 50.0
        elif login_streak >= 1:
            streak_score = 30.0
        else:
            streak_score = 0.0

        # 4. Feature breadth (0.0-1.0 from Feast)
        breadth_score = feature_breadth * 100.0

        # 5. Consistency: stable frequency over time
        # Use streak as a proxy for consistency
        consistency_score = min(login_streak / 7.0, 1.0) * 100.0

        # Weighted combination
        composite = (
            freq_score * cfg.frequency_weight
            + recency_score * cfg.recency_weight
            + streak_score * cfg.streak_weight
            + breadth_score * cfg.breadth_weight
            + consistency_score * cfg.consistency_weight
        )

        return _clamp(composite)

    def _classify_lifecycle(
        self,
        session_count: int,
        days_since_login: int,
        engagement_score: float,
        personal_frequency: float,
        session_count_7d: int,
        engagement_history: list[float] | None = None,
    ) -> LifecycleStage:
        """Classify user into a lifecycle stage."""
        cfg = self._config.engagement

        # Churned: no activity in 30+ days
        if days_since_login >= cfg.churned_days:
            return LifecycleStage.CHURNED

        # Dormant: no activity in 14+ days
        if days_since_login >= cfg.dormant_days:
            return LifecycleStage.DORMANT

        # Reactivated: recently returned after dormancy
        # (detected via high days_since_login in recent history but now active)
        if engagement_history and len(engagement_history) >= 2:
            if engagement_history[-2] < 10 and engagement_history[-1] > 30:
                return LifecycleStage.REACTIVATED

        # New user
        if session_count <= cfg.new_max_sessions:
            return LifecycleStage.NEW

        # Onboarding
        if session_count <= cfg.onboarding_max_sessions:
            return LifecycleStage.ONBOARDING

        # Declining: engagement dropping
        if engagement_history and len(engagement_history) >= 3:
            recent_trend = engagement_history[-1] - engagement_history[-3]
            if recent_trend < -cfg.churn_score_drop_threshold:
                return LifecycleStage.DECLINING

        # Power user: above-average engagement and frequency
        if engagement_score >= 80 and session_count_7d >= 5:
            return LifecycleStage.POWER_USER

        # Active: regular usage
        return LifecycleStage.ACTIVE

    def _compute_churn_risk(
        self,
        lifecycle_stage: LifecycleStage,
        engagement_score: float,
        engagement_history: list[float] | None = None,
    ) -> tuple[float, str]:
        """Compute churn probability based on engagement trends.

        Returns:
            Tuple of (churn_risk: 0.0-1.0, risk_level: "low"/"medium"/"high").
        """
        cfg = self._config.engagement

        # Stages with inherent churn risk
        if lifecycle_stage == LifecycleStage.CHURNED:
            return 1.0, "high"
        if lifecycle_stage == LifecycleStage.DORMANT:
            return 0.7, "high"
        if lifecycle_stage == LifecycleStage.NEW:
            # New users always have moderate churn risk
            return 0.3, "medium"

        # For declining users
        if lifecycle_stage == LifecycleStage.DECLINING:
            return 0.6, "high"

        # For active/power users, look at trend
        if engagement_history and len(engagement_history) >= cfg.churn_window_weeks:
            window = engagement_history[-cfg.churn_window_weeks:]
            score_drop = window[0] - window[-1]
            if score_drop > cfg.churn_score_drop_threshold:
                risk = min(score_drop / 50.0, 1.0)
                level = "high" if risk > 0.5 else "medium"
                return risk, level

        # Low engagement = moderate risk
        if engagement_score < 30:
            return 0.4, "medium"

        return 0.1, "low"

    def _compute_trend(self, engagement_history: list[float] | None) -> str:
        """Compute engagement trend from history."""
        if not engagement_history or len(engagement_history) < 2:
            return "stable"

        recent = engagement_history[-1]
        previous = engagement_history[-2]
        delta = recent - previous

        if delta > 5:
            return "improving"
        elif delta < -5:
            return "declining"
        return "stable"

    async def get_engagement_summary(
        self,
        user_engagements: list[UserEngagement],
    ) -> EngagementSummary:
        """Compute summary statistics across all users.

        Args:
            user_engagements: List of individual user engagement results.

        Returns:
            EngagementSummary with distribution and averages.
        """
        now = datetime.now(UTC)

        stage_counts: dict[str, int] = {}
        stage_scores: dict[str, list[float]] = {}

        for ue in user_engagements:
            stage = ue.lifecycle_stage.value
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
            if stage not in stage_scores:
                stage_scores[stage] = []
            stage_scores[stage].append(ue.engagement_score)

        avg_by_stage = {}
        for stage, scores in stage_scores.items():
            avg_by_stage[stage] = round(sum(scores) / len(scores), 2)

        return EngagementSummary(
            total_users=len(user_engagements),
            stage_distribution=stage_counts,
            avg_engagement_by_stage=avg_by_stage,
            computed_at=now,
        )

    def get_at_risk_users(
        self,
        user_engagements: list[UserEngagement],
    ) -> list[AtRiskUser]:
        """Filter users in declining stage or with high churn risk."""
        at_risk = []
        for ue in user_engagements:
            if ue.lifecycle_stage == LifecycleStage.DECLINING or ue.churn_risk >= 0.5:
                at_risk.append(
                    AtRiskUser(
                        user_id=ue.user_id,
                        engagement_score=ue.engagement_score,
                        lifecycle_stage=ue.lifecycle_stage,
                        churn_risk=ue.churn_risk,
                    )
                )
        # Sort by churn risk descending
        at_risk.sort(key=lambda x: x.churn_risk, reverse=True)
        return at_risk
