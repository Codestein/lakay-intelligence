"""Unit tests for engagement scoring and lifecycle classification."""

from datetime import UTC, datetime

import pytest

from src.domains.behavior.engagement import EngagementScorer
from src.domains.behavior.models import (
    EngagementBaseline,
    LifecycleStage,
    ProfileStatus,
    UserBehaviorProfile,
    UserEngagement,
)


@pytest.fixture
def scorer() -> EngagementScorer:
    return EngagementScorer()


@pytest.fixture
def active_profile() -> UserBehaviorProfile:
    return UserBehaviorProfile(
        user_id="user-active",
        profile_status=ProfileStatus.ACTIVE,
        profile_maturity=30,
        engagement_baseline=EngagementBaseline(
            typical_features_used=["circles", "remittance", "balance"],
            feature_usage_breadth=0.5,
            avg_sessions_per_week=5.0,
        ),
        last_updated=datetime.now(UTC),
    )


@pytest.fixture
def new_profile() -> UserBehaviorProfile:
    return UserBehaviorProfile(
        user_id="user-new",
        profile_status=ProfileStatus.BUILDING,
        profile_maturity=3,
        last_updated=datetime.now(UTC),
    )


class TestEngagementScoring:
    async def test_highly_engaged_user(self, scorer, active_profile):
        features = {
            "session_count_7d": 7,
            "login_streak_days": 14,
            "feature_usage_breadth": 0.8,
            "days_since_last_login": 0,
        }
        result = await scorer.score_engagement(
            "user-active", active_profile, feast_features=features
        )
        assert result.engagement_score >= 70
        assert result.lifecycle_stage in (LifecycleStage.ACTIVE, LifecycleStage.POWER_USER)

    async def test_dormant_user(self, scorer, active_profile):
        features = {
            "session_count_7d": 0,
            "login_streak_days": 0,
            "feature_usage_breadth": 0.0,
            "days_since_last_login": 20,
        }
        result = await scorer.score_engagement(
            "user-dormant", active_profile, feast_features=features
        )
        assert result.lifecycle_stage == LifecycleStage.DORMANT

    async def test_churned_user(self, scorer, active_profile):
        features = {
            "session_count_7d": 0,
            "login_streak_days": 0,
            "feature_usage_breadth": 0.0,
            "days_since_last_login": 45,
        }
        result = await scorer.score_engagement(
            "user-churned", active_profile, feast_features=features
        )
        assert result.lifecycle_stage == LifecycleStage.CHURNED
        assert result.churn_risk >= 0.9

    async def test_new_user_classification(self, scorer, new_profile):
        features = {
            "session_count_7d": 2,
            "login_streak_days": 2,
            "feature_usage_breadth": 0.2,
            "days_since_last_login": 1,
        }
        result = await scorer.score_engagement(
            "user-new", new_profile, feast_features=features
        )
        assert result.lifecycle_stage == LifecycleStage.NEW

    async def test_power_user(self, scorer, active_profile):
        features = {
            "session_count_7d": 10,
            "login_streak_days": 21,
            "feature_usage_breadth": 0.9,
            "days_since_last_login": 0,
        }
        result = await scorer.score_engagement(
            "user-power", active_profile, feast_features=features
        )
        assert result.engagement_score >= 80
        assert result.lifecycle_stage == LifecycleStage.POWER_USER

    async def test_engagement_score_range(self, scorer, active_profile):
        features = {
            "session_count_7d": 3,
            "login_streak_days": 5,
            "feature_usage_breadth": 0.4,
            "days_since_last_login": 2,
        }
        result = await scorer.score_engagement(
            "user-active", active_profile, feast_features=features
        )
        assert 0 <= result.engagement_score <= 100


class TestLifecycleClassification:
    def test_churned(self, scorer):
        stage = scorer._classify_lifecycle(
            session_count=50, days_since_login=35, engagement_score=0,
            personal_frequency=5.0, session_count_7d=0,
        )
        assert stage == LifecycleStage.CHURNED

    def test_dormant(self, scorer):
        stage = scorer._classify_lifecycle(
            session_count=50, days_since_login=18, engagement_score=10,
            personal_frequency=5.0, session_count_7d=0,
        )
        assert stage == LifecycleStage.DORMANT

    def test_new(self, scorer):
        stage = scorer._classify_lifecycle(
            session_count=3, days_since_login=1, engagement_score=50,
            personal_frequency=1.0, session_count_7d=2,
        )
        assert stage == LifecycleStage.NEW

    def test_onboarding(self, scorer):
        stage = scorer._classify_lifecycle(
            session_count=10, days_since_login=1, engagement_score=60,
            personal_frequency=3.0, session_count_7d=5,
        )
        assert stage == LifecycleStage.ONBOARDING

    def test_declining(self, scorer):
        stage = scorer._classify_lifecycle(
            session_count=50, days_since_login=3, engagement_score=40,
            personal_frequency=5.0, session_count_7d=2,
            engagement_history=[80, 70, 55],
        )
        assert stage == LifecycleStage.DECLINING

    def test_reactivated(self, scorer):
        stage = scorer._classify_lifecycle(
            session_count=50, days_since_login=1, engagement_score=50,
            personal_frequency=5.0, session_count_7d=3,
            engagement_history=[5, 50],
        )
        assert stage == LifecycleStage.REACTIVATED


class TestChurnRisk:
    def test_churned_high_risk(self, scorer):
        risk, level = scorer._compute_churn_risk(
            LifecycleStage.CHURNED, 0, []
        )
        assert risk == 1.0
        assert level == "high"

    def test_dormant_high_risk(self, scorer):
        risk, level = scorer._compute_churn_risk(
            LifecycleStage.DORMANT, 15, []
        )
        assert risk == 0.7
        assert level == "high"

    def test_active_low_risk(self, scorer):
        risk, level = scorer._compute_churn_risk(
            LifecycleStage.ACTIVE, 80, [80, 78, 82]
        )
        assert risk < 0.3
        assert level == "low"

    def test_dropping_engagement_medium_risk(self, scorer):
        risk, level = scorer._compute_churn_risk(
            LifecycleStage.ACTIVE, 55, [80, 70, 55]
        )
        assert risk > 0.3

    def test_new_user_moderate_risk(self, scorer):
        risk, level = scorer._compute_churn_risk(
            LifecycleStage.NEW, 50, []
        )
        assert risk == 0.3
        assert level == "medium"


class TestEngagementTrend:
    def test_improving(self, scorer):
        assert scorer._compute_trend([50, 60, 70]) == "improving"

    def test_declining(self, scorer):
        assert scorer._compute_trend([70, 60, 50]) == "declining"

    def test_stable(self, scorer):
        assert scorer._compute_trend([50, 51, 52]) == "stable"

    def test_no_history(self, scorer):
        assert scorer._compute_trend([]) == "stable"
        assert scorer._compute_trend(None) == "stable"


class TestEngagementSummary:
    async def test_summary_computation(self, scorer):
        engagements = [
            UserEngagement(
                user_id="u1", engagement_score=80, lifecycle_stage=LifecycleStage.ACTIVE,
                churn_risk=0.1, computed_at=datetime.now(UTC),
            ),
            UserEngagement(
                user_id="u2", engagement_score=90, lifecycle_stage=LifecycleStage.POWER_USER,
                churn_risk=0.05, computed_at=datetime.now(UTC),
            ),
            UserEngagement(
                user_id="u3", engagement_score=30, lifecycle_stage=LifecycleStage.DECLINING,
                churn_risk=0.7, computed_at=datetime.now(UTC),
            ),
        ]
        summary = await scorer.get_engagement_summary(engagements)
        assert summary.total_users == 3
        assert summary.stage_distribution["active"] == 1
        assert summary.stage_distribution["power_user"] == 1
        assert summary.stage_distribution["declining"] == 1

    def test_at_risk_users(self, scorer):
        engagements = [
            UserEngagement(
                user_id="u1", engagement_score=80, lifecycle_stage=LifecycleStage.ACTIVE,
                churn_risk=0.1, computed_at=datetime.now(UTC),
            ),
            UserEngagement(
                user_id="u2", engagement_score=30, lifecycle_stage=LifecycleStage.DECLINING,
                churn_risk=0.7, computed_at=datetime.now(UTC),
            ),
            UserEngagement(
                user_id="u3", engagement_score=20, lifecycle_stage=LifecycleStage.DORMANT,
                churn_risk=0.8, computed_at=datetime.now(UTC),
            ),
        ]
        at_risk = scorer.get_at_risk_users(engagements)
        assert len(at_risk) == 2
        # Sorted by churn risk descending
        assert at_risk[0].user_id == "u3"
        assert at_risk[1].user_id == "u2"
