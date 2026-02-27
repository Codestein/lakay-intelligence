"""Unit tests for circle health scoring engine."""

import pytest

from src.domains.circles.config import CircleHealthConfig
from src.domains.circles.models import HealthTier, TrendDirection
from src.domains.circles.scoring import CircleHealthScorer


@pytest.fixture
def scorer() -> CircleHealthScorer:
    return CircleHealthScorer()


@pytest.fixture
def perfect_features() -> dict:
    """Features representing a perfectly healthy circle."""
    return {
        "on_time_payment_rate": 1.0,
        "avg_days_late": 0.0,
        "consecutive_on_time_streak": 10,
        "missed_contribution_count": 0,
        "member_drop_rate": 0.0,
        "member_count_current": 10,
        "member_count_original": 10,
        "avg_member_tenure_days": 120,
        "collection_ratio": 1.0,
        "payout_completion_rate": 1.0,
        "late_payment_trend": 0.0,
        "coordinated_behavior_score": 0.0,
        "largest_single_missed_amount": 0.0,
        "contribution_amount": 100.0,
        "post_payout_disengagement_rate": 0.0,
        "cycles_completed": 8,
    }


@pytest.fixture
def struggling_features() -> dict:
    """Features representing a struggling circle."""
    return {
        "on_time_payment_rate": 0.60,
        "avg_days_late": 5.0,
        "consecutive_on_time_streak": 0,
        "missed_contribution_count": 4,
        "member_drop_rate": 0.35,
        "member_count_current": 5,
        "member_count_original": 10,
        "avg_member_tenure_days": 30,
        "collection_ratio": 0.55,
        "payout_completion_rate": 0.40,
        "late_payment_trend": 0.6,
        "coordinated_behavior_score": 0.8,
        "largest_single_missed_amount": 300.0,
        "contribution_amount": 100.0,
        "post_payout_disengagement_rate": 0.5,
        "cycles_completed": 6,
    }


class TestCircleHealthScorer:
    def test_perfect_circle_scores_high(self, scorer, perfect_features):
        result = scorer.score("circle-1", perfect_features)
        assert result.health_score >= 90
        assert result.health_tier == HealthTier.HEALTHY

    def test_struggling_circle_scores_low(self, scorer, struggling_features):
        result = scorer.score("circle-2", struggling_features)
        assert result.health_score < 40
        assert result.health_tier == HealthTier.CRITICAL

    def test_score_range_0_to_100(self, scorer, perfect_features):
        result = scorer.score("circle-1", perfect_features)
        assert 0 <= result.health_score <= 100

    def test_dimension_scores_present(self, scorer, perfect_features):
        result = scorer.score("circle-1", perfect_features)
        assert "contribution_reliability" in result.dimension_scores
        assert "membership_stability" in result.dimension_scores
        assert "financial_progress" in result.dimension_scores
        assert "trust_integrity" in result.dimension_scores

    def test_dimension_scores_0_to_100(self, scorer, perfect_features):
        result = scorer.score("circle-1", perfect_features)
        for dim in result.dimension_scores.values():
            assert 0 <= dim.score <= 100

    def test_dimension_weights_match_config(self, scorer, perfect_features):
        result = scorer.score("circle-1", perfect_features)
        cfg = CircleHealthConfig()
        dims = result.dimension_scores
        assert dims["contribution_reliability"].weight == cfg.contribution.weight
        assert dims["membership_stability"].weight == cfg.membership.weight
        assert dims["financial_progress"].weight == cfg.financial.weight
        assert dims["trust_integrity"].weight == cfg.trust.weight

    def test_contributing_factors_populated(self, scorer, struggling_features):
        result = scorer.score("circle-2", struggling_features)
        # At least some dimensions should have contributing factors
        all_factors = []
        for dim in result.dimension_scores.values():
            all_factors.extend(dim.contributing_factors)
        assert len(all_factors) > 0

    def test_scoring_version_set(self, scorer, perfect_features):
        result = scorer.score("circle-1", perfect_features)
        assert result.scoring_version == "circle-health-v1"

    def test_circle_id_preserved(self, scorer, perfect_features):
        result = scorer.score("my-circle-123", perfect_features)
        assert result.circle_id == "my-circle-123"


class TestContributionReliability:
    def test_perfect_on_time_rate(self, scorer):
        features = {"on_time_payment_rate": 1.0, "avg_days_late": 0.0}
        result = scorer._score_contribution_reliability(features)
        assert result.score >= 90

    def test_low_on_time_rate(self, scorer):
        features = {
            "on_time_payment_rate": 0.50,
            "avg_days_late": 3.0,
            "missed_contribution_count": 3,
        }
        result = scorer._score_contribution_reliability(features)
        assert result.score < 30

    def test_late_days_penalty(self, scorer):
        features_no_late = {"on_time_payment_rate": 0.85, "avg_days_late": 0.0}
        features_late = {"on_time_payment_rate": 0.85, "avg_days_late": 5.0}
        score_no_late = scorer._score_contribution_reliability(features_no_late)
        score_late = scorer._score_contribution_reliability(features_late)
        assert score_no_late.score > score_late.score

    def test_small_lateness_gentle_penalty(self, scorer):
        """A member who's 2 days late but always pays should still score well."""
        features = {
            "on_time_payment_rate": 0.90,
            "avg_days_late": 2.0,
            "consecutive_on_time_streak": 5,
        }
        result = scorer._score_contribution_reliability(features)
        # Should still be decent — culturally acceptable lateness
        assert result.score >= 50

    def test_streak_bonus(self, scorer):
        features_no_streak = {"on_time_payment_rate": 0.85, "consecutive_on_time_streak": 0}
        features_streak = {"on_time_payment_rate": 0.85, "consecutive_on_time_streak": 8}
        score_no = scorer._score_contribution_reliability(features_no_streak)
        score_yes = scorer._score_contribution_reliability(features_streak)
        assert score_yes.score > score_no.score

    def test_missed_contributions_escalating_penalty(self, scorer):
        scores = []
        for missed in [0, 1, 2, 3, 4]:
            features = {"on_time_payment_rate": 0.85, "missed_contribution_count": missed}
            result = scorer._score_contribution_reliability(features)
            scores.append(result.score)
        # Each additional miss should reduce the score
        for i in range(1, len(scores)):
            assert scores[i] <= scores[i - 1]


class TestMembershipStability:
    def test_no_drops_high_score(self, scorer):
        features = {
            "member_drop_rate": 0.0,
            "member_count_current": 10,
            "member_count_original": 10,
            "avg_member_tenure_days": 100,
        }
        result = scorer._score_membership_stability(features)
        assert result.score >= 90

    def test_critical_drop_rate(self, scorer):
        features = {
            "member_drop_rate": 0.40,
            "member_count_current": 5,
            "member_count_original": 10,
        }
        result = scorer._score_membership_stability(features)
        assert result.score < 30

    def test_size_shrinkage_penalty(self, scorer):
        features_full = {
            "member_drop_rate": 0.10,
            "member_count_current": 9,
            "member_count_original": 10,
        }
        features_half = {
            "member_drop_rate": 0.10,
            "member_count_current": 4,
            "member_count_original": 10,
        }
        score_full = scorer._score_membership_stability(features_full)
        score_half = scorer._score_membership_stability(features_half)
        assert score_full.score > score_half.score


class TestFinancialProgress:
    def test_on_track_high_score(self, scorer):
        features = {
            "collection_ratio": 1.0,
            "payout_completion_rate": 1.0,
            "late_payment_trend": 0.0,
        }
        result = scorer._score_financial_progress(features)
        assert result.score >= 90

    def test_behind_schedule(self, scorer):
        features = {
            "collection_ratio": 0.50,
            "payout_completion_rate": 0.40,
            "late_payment_trend": 0.6,
        }
        result = scorer._score_financial_progress(features)
        assert result.score < 30


class TestTrustIntegrity:
    def test_clean_circle(self, scorer):
        features = {
            "coordinated_behavior_score": 0.0,
            "largest_single_missed_amount": 0.0,
            "contribution_amount": 100.0,
            "post_payout_disengagement_rate": 0.0,
        }
        result = scorer._score_trust_integrity(features)
        assert result.score >= 90

    def test_high_coordination_penalty(self, scorer):
        features = {
            "coordinated_behavior_score": 0.9,
            "contribution_amount": 100.0,
        }
        result = scorer._score_trust_integrity(features)
        assert result.score < 70

    def test_post_payout_disengagement_penalty(self, scorer):
        features = {
            "coordinated_behavior_score": 0.0,
            "contribution_amount": 100.0,
            "post_payout_disengagement_rate": 0.6,
        }
        result = scorer._score_trust_integrity(features)
        # 0.6 disengagement rate produces a noticeable penalty
        assert result.score < 90
        # Score with disengagement should be lower than without
        clean_features = {
            "coordinated_behavior_score": 0.0,
            "contribution_amount": 100.0,
            "post_payout_disengagement_rate": 0.0,
        }
        clean_result = scorer._score_trust_integrity(clean_features)
        assert result.score < clean_result.score


class TestTierClassification:
    def test_healthy_tier(self, scorer):
        assert scorer._score_to_tier(85) == HealthTier.HEALTHY
        assert scorer._score_to_tier(70) == HealthTier.HEALTHY

    def test_at_risk_tier(self, scorer):
        assert scorer._score_to_tier(55) == HealthTier.AT_RISK
        assert scorer._score_to_tier(40) == HealthTier.AT_RISK

    def test_critical_tier(self, scorer):
        assert scorer._score_to_tier(30) == HealthTier.CRITICAL
        assert scorer._score_to_tier(0) == HealthTier.CRITICAL

    def test_boundary_70(self, scorer):
        assert scorer._score_to_tier(70.0) == HealthTier.HEALTHY
        assert scorer._score_to_tier(69.99) == HealthTier.AT_RISK

    def test_boundary_40(self, scorer):
        assert scorer._score_to_tier(40.0) == HealthTier.AT_RISK
        assert scorer._score_to_tier(39.99) == HealthTier.CRITICAL


class TestTrendCalculation:
    def test_improving_trend(self, scorer):
        features = {
            "current_health_score": 80,
            "health_score_1_cycle_ago": 70,
            "health_score_3_cycles_ago": 60,
        }
        assert scorer._compute_trend(features) == TrendDirection.IMPROVING

    def test_deteriorating_trend(self, scorer):
        features = {
            "current_health_score": 50,
            "health_score_1_cycle_ago": 65,
            "health_score_3_cycles_ago": 75,
        }
        assert scorer._compute_trend(features) == TrendDirection.DETERIORATING

    def test_stable_trend(self, scorer):
        features = {
            "current_health_score": 72,
            "health_score_1_cycle_ago": 70,
            "health_score_3_cycles_ago": 71,
        }
        assert scorer._compute_trend(features) == TrendDirection.STABLE

    def test_no_history_returns_stable(self, scorer):
        features = {}
        assert scorer._compute_trend(features) == TrendDirection.STABLE


class TestConfidence:
    def test_new_circle_low_confidence(self, scorer):
        features = {"cycles_completed": 1, "member_count_current": 10}
        conf = scorer._compute_confidence(features)
        assert conf < 0.6

    def test_established_circle_high_confidence(self, scorer):
        features = {"cycles_completed": 8, "member_count_current": 10}
        conf = scorer._compute_confidence(features)
        assert conf >= 0.8

    def test_small_circle_reduced_confidence(self, scorer):
        features = {"cycles_completed": 5, "member_count_current": 2}
        conf = scorer._compute_confidence(features)
        # 2-member circle should have lower confidence than a 10-member circle
        features_big = {"cycles_completed": 5, "member_count_current": 10}
        conf_big = scorer._compute_confidence(features_big)
        assert conf < conf_big


class TestConfigValidation:
    def test_default_weights_sum_to_one(self):
        config = CircleHealthConfig()
        total = (
            config.contribution.weight
            + config.membership.weight
            + config.financial.weight
            + config.trust.weight
        )
        assert abs(total - 1.0) < 1e-6

    def test_invalid_weights_raise(self):
        from src.domains.circles.config import (
            ContributionReliabilityConfig,
            FinancialProgressConfig,
            MembershipStabilityConfig,
            TrustIntegrityConfig,
        )

        with pytest.raises(ValueError, match="must sum to 1.0"):
            CircleHealthConfig(
                contribution=ContributionReliabilityConfig(weight=0.5),
                membership=MembershipStabilityConfig(weight=0.5),
                financial=FinancialProgressConfig(weight=0.5),
                trust=TrustIntegrityConfig(weight=0.5),
            )

    def test_custom_weights(self):
        from src.domains.circles.config import (
            ContributionReliabilityConfig,
            FinancialProgressConfig,
            MembershipStabilityConfig,
            TrustIntegrityConfig,
        )

        config = CircleHealthConfig(
            contribution=ContributionReliabilityConfig(weight=0.40),
            membership=MembershipStabilityConfig(weight=0.20),
            financial=FinancialProgressConfig(weight=0.20),
            trust=TrustIntegrityConfig(weight=0.20),
        )
        scorer = CircleHealthScorer(config=config)
        assert scorer._config.contribution.weight == 0.40
