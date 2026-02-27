"""Validation tests for circle health scoring against simulated failure modes.

These tests verify that the scoring pipeline produces expected results for
each failure scenario described in Phase 6, Task 6.4.
"""

import time

import pytest

from src.domains.circles.anomaly import CircleAnomalyDetector
from src.domains.circles.classification import CircleClassifier
from src.domains.circles.models import (
    AnomalySeverity,
    AnomalyType,
    HealthTier,
    TrendDirection,
)
from src.domains.circles.scoring import CircleHealthScorer


@pytest.fixture
def scorer() -> CircleHealthScorer:
    return CircleHealthScorer()


@pytest.fixture
def anomaly_detector() -> CircleAnomalyDetector:
    return CircleAnomalyDetector()


@pytest.fixture
def classifier() -> CircleClassifier:
    return CircleClassifier()


class TestScenarioAHealthyCircle:
    """Scenario A — Healthy circle: 10 members, 0% late, 0% drops, full rotation.

    Expected: health score >70, classified Healthy, no anomalies.
    """

    @pytest.fixture
    def features(self) -> dict:
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
            "cycles_completed": 10,
            "late_members_current_cycle": 0,
            "members_paid_out": 10,
        }

    def test_health_score_above_70(self, scorer, features):
        result = scorer.score("healthy-circle", features)
        assert result.health_score > 70, f"Expected >70, got {result.health_score}"

    def test_classified_healthy(self, scorer, classifier, features):
        health = scorer.score("healthy-circle", features)
        classification = classifier.classify(health, [])
        assert classification.health_tier == HealthTier.HEALTHY

    def test_no_anomalies(self, anomaly_detector, features):
        anomalies = anomaly_detector.detect_all("healthy-circle", features)
        assert len(anomalies) == 0


class TestScenarioBGradualDegradation:
    """Scenario B — Gradual degradation: late rate 5% -> 25%.

    Expected: score starts >70, deteriorates to <55, trend = deteriorating.
    """

    @pytest.fixture
    def early_features(self) -> dict:
        """Early in the rotation — mostly healthy."""
        return {
            "on_time_payment_rate": 0.95,
            "avg_days_late": 0.5,
            "consecutive_on_time_streak": 5,
            "missed_contribution_count": 0,
            "member_drop_rate": 0.0,
            "member_count_current": 10,
            "member_count_original": 10,
            "avg_member_tenure_days": 60,
            "collection_ratio": 0.95,
            "payout_completion_rate": 1.0,
            "late_payment_trend": 0.0,
            "coordinated_behavior_score": 0.0,
            "largest_single_missed_amount": 0.0,
            "contribution_amount": 100.0,
            "post_payout_disengagement_rate": 0.0,
            "cycles_completed": 4,
        }

    @pytest.fixture
    def late_features(self) -> dict:
        """Late in the rotation — degraded."""
        return {
            "on_time_payment_rate": 0.65,
            "avg_days_late": 4.5,
            "consecutive_on_time_streak": 0,
            "missed_contribution_count": 3,
            "member_drop_rate": 0.10,
            "member_count_current": 9,
            "member_count_original": 10,
            "avg_member_tenure_days": 90,
            "collection_ratio": 0.75,
            "payout_completion_rate": 0.80,
            "late_payment_trend": 0.5,
            "coordinated_behavior_score": 0.2,
            "largest_single_missed_amount": 100.0,
            "contribution_amount": 100.0,
            "post_payout_disengagement_rate": 0.1,
            "cycles_completed": 8,
            "current_health_score": 45,
            "health_score_1_cycle_ago": 55,
            "health_score_3_cycles_ago": 72,
        }

    def test_early_score_above_70(self, scorer, early_features):
        result = scorer.score("degrading-circle", early_features)
        assert result.health_score > 70

    def test_late_score_below_55(self, scorer, late_features):
        result = scorer.score("degrading-circle", late_features)
        assert result.health_score < 55

    def test_trend_deteriorating(self, scorer, late_features):
        result = scorer.score("degrading-circle", late_features)
        assert result.trend == TrendDirection.DETERIORATING

    def test_classified_at_risk_or_critical(self, scorer, classifier, late_features):
        health = scorer.score("degrading-circle", late_features)
        anomalies = []
        classification = classifier.classify(health, anomalies)
        assert classification.health_tier in (HealthTier.AT_RISK, HealthTier.CRITICAL)


class TestScenarioCSuddenMemberDrop:
    """Scenario C — Sudden member drop: 8 members, 2 drop at cycle 4 of 8.

    Expected: membership stability drops sharply, overall score drops, At-Risk.
    """

    @pytest.fixture
    def features(self) -> dict:
        return {
            "on_time_payment_rate": 0.85,
            "avg_days_late": 1.5,
            "consecutive_on_time_streak": 3,
            "missed_contribution_count": 1,
            "member_drop_rate": 0.25,  # 2 of 8 dropped
            "member_count_current": 6,
            "member_count_original": 8,
            "avg_member_tenure_days": 60,
            "collection_ratio": 0.80,
            "payout_completion_rate": 0.75,
            "late_payment_trend": 0.15,
            "coordinated_behavior_score": 0.1,
            "largest_single_missed_amount": 100.0,
            "contribution_amount": 100.0,
            "post_payout_disengagement_rate": 0.0,
            "cycles_completed": 4,
        }

    def test_membership_stability_drops(self, scorer, features):
        result = scorer.score("drop-circle", features)
        membership_score = result.dimension_scores["membership_stability"].score
        assert membership_score < 70, f"Expected <70, got {membership_score}"

    def test_overall_score_drops(self, scorer, features):
        result = scorer.score("drop-circle", features)
        # With 25% drop rate and 6/8 members, score should be reduced
        assert result.health_score < 75

    def test_classified_at_risk(self, scorer, classifier, features):
        health = scorer.score("drop-circle", features)
        classification = classifier.classify(health, [])
        assert classification.health_tier in (HealthTier.AT_RISK, HealthTier.CRITICAL)


class TestScenarioDPostPayoutScam:
    """Scenario D — Post-payout scam: member receives payout in cycle 1,
    stops contributing from cycle 2 onward.

    Expected: free-rider anomaly, post-payout disengagement, Critical.
    """

    @pytest.fixture
    def features(self) -> dict:
        return {
            "on_time_payment_rate": 0.70,
            "avg_days_late": 3.0,
            "consecutive_on_time_streak": 0,
            "missed_contribution_count": 5,
            "member_drop_rate": 0.17,
            "member_count_current": 5,
            "member_count_original": 6,
            "avg_member_tenure_days": 40,
            "collection_ratio": 0.65,
            "payout_completion_rate": 0.50,
            "late_payment_trend": 0.4,
            "coordinated_behavior_score": 0.3,
            "largest_single_missed_amount": 500.0,
            "contribution_amount": 100.0,
            "post_payout_disengagement_rate": 0.5,
            "cycles_completed": 5,
            "members_paid_out": 2,
            "late_members_current_cycle": 2,
        }

    @pytest.fixture
    def member_features(self) -> list[dict]:
        return [
            {
                "user_id": "scammer-1",
                "has_received_payout": True,
                "total_contributed": 100.0,
                "expected_contributed": 500.0,
                "pre_payout_reliability": 1.0,
                "post_payout_reliability": 0.0,
            },
            {
                "user_id": "scammer-2",
                "has_received_payout": True,
                "total_contributed": 150.0,
                "expected_contributed": 500.0,
                "pre_payout_reliability": 0.95,
                "post_payout_reliability": 0.20,
            },
            {
                "user_id": "honest-1",
                "has_received_payout": False,
                "total_contributed": 400.0,
                "expected_contributed": 500.0,
                "pre_payout_reliability": 0.90,
                "post_payout_reliability": 0.90,
            },
        ]

    def test_free_rider_detected(self, anomaly_detector, features, member_features):
        anomalies = anomaly_detector.detect_all("scam-circle", features, member_features)
        types = {a.anomaly_type for a in anomalies}
        assert AnomalyType.FREE_RIDER in types

    def test_post_payout_disengagement_detected(self, anomaly_detector, features, member_features):
        anomalies = anomaly_detector.detect_all("scam-circle", features, member_features)
        types = {a.anomaly_type for a in anomalies}
        assert AnomalyType.POST_PAYOUT_DISENGAGEMENT in types

    def test_classified_critical(
        self, scorer, classifier, anomaly_detector, features, member_features
    ):
        health = scorer.score("scam-circle", features)
        anomalies = anomaly_detector.detect_all("scam-circle", features, member_features)
        classification = classifier.classify(health, anomalies)
        assert classification.health_tier == HealthTier.CRITICAL


class TestScenarioECoordinatedManipulation:
    """Scenario E — Coordinated manipulation: 10 members, 4 collude.

    Expected: coordinated behavior score elevated, anomaly detected,
    trust/integrity dimension low.
    """

    @pytest.fixture
    def features(self) -> dict:
        return {
            "on_time_payment_rate": 0.80,
            "avg_days_late": 2.0,
            "consecutive_on_time_streak": 2,
            "missed_contribution_count": 2,
            "member_drop_rate": 0.10,
            "member_count_current": 9,
            "member_count_original": 10,
            "avg_member_tenure_days": 60,
            "collection_ratio": 0.80,
            "payout_completion_rate": 0.70,
            "late_payment_trend": 0.2,
            "coordinated_behavior_score": 0.85,
            "largest_single_missed_amount": 300.0,
            "contribution_amount": 100.0,
            "post_payout_disengagement_rate": 0.3,
            "cycles_completed": 6,
            "late_members_current_cycle": 4,
            "historical_late_rate": 0.10,
            "members_paid_out": 4,
        }

    def test_trust_integrity_low(self, scorer, features):
        result = scorer.score("collude-circle", features)
        trust_score = result.dimension_scores["trust_integrity"].score
        assert trust_score < 60, f"Expected <60, got {trust_score}"

    def test_coordinated_late_anomaly(self, anomaly_detector, features):
        anomalies = anomaly_detector.detect_all("collude-circle", features)
        types = {a.anomaly_type for a in anomalies}
        assert AnomalyType.COORDINATED_LATE in types

    def test_manipulation_flagged(self, anomaly_detector, features):
        anomalies = anomaly_detector.detect_all("collude-circle", features)
        assert len(anomalies) > 0
        # At least one should be medium or high severity
        severities = {a.severity for a in anomalies}
        assert AnomalySeverity.MEDIUM in severities or AnomalySeverity.HIGH in severities


class TestScenarioFRecovery:
    """Scenario F — Recovery: late rate spikes to 20% then returns to 5%.

    Expected: score dips then recovers, trend = improving, final = Healthy.
    """

    @pytest.fixture
    def recovered_features(self) -> dict:
        return {
            "on_time_payment_rate": 0.92,
            "avg_days_late": 0.5,
            "consecutive_on_time_streak": 4,
            "missed_contribution_count": 1,
            "member_drop_rate": 0.0,
            "member_count_current": 8,
            "member_count_original": 8,
            "avg_member_tenure_days": 100,
            "collection_ratio": 0.95,
            "payout_completion_rate": 0.90,
            "late_payment_trend": -0.15,  # improving
            "coordinated_behavior_score": 0.0,
            "largest_single_missed_amount": 0.0,
            "contribution_amount": 100.0,
            "post_payout_disengagement_rate": 0.0,
            "cycles_completed": 8,
            "current_health_score": 78,
            "health_score_1_cycle_ago": 60,
            "health_score_3_cycles_ago": 55,
        }

    def test_recovered_score_above_70(self, scorer, recovered_features):
        result = scorer.score("recovery-circle", recovered_features)
        assert result.health_score > 70

    def test_trend_improving(self, scorer, recovered_features):
        result = scorer.score("recovery-circle", recovered_features)
        assert result.trend == TrendDirection.IMPROVING

    def test_classified_healthy(self, scorer, classifier, recovered_features):
        health = scorer.score("recovery-circle", recovered_features)
        classification = classifier.classify(health, [])
        assert classification.health_tier == HealthTier.HEALTHY


class TestScoringBoundaries:
    """Edge cases: new circles, small circles, boundary scores."""

    def test_brand_new_circle_1_cycle(self, scorer):
        """Scoring should work with limited history, noting low confidence."""
        features = {
            "on_time_payment_rate": 1.0,
            "avg_days_late": 0.0,
            "missed_contribution_count": 0,
            "member_drop_rate": 0.0,
            "member_count_current": 10,
            "member_count_original": 10,
            "collection_ratio": 1.0,
            "payout_completion_rate": 1.0,
            "late_payment_trend": 0.0,
            "coordinated_behavior_score": 0.0,
            "contribution_amount": 100.0,
            "cycles_completed": 1,
        }
        result = scorer.score("new-circle", features)
        assert 0 <= result.health_score <= 100
        assert result.confidence < 0.6  # low confidence for new circle

    def test_two_member_circle(self, scorer):
        """All calculations should handle small N."""
        features = {
            "on_time_payment_rate": 1.0,
            "avg_days_late": 0.0,
            "missed_contribution_count": 0,
            "member_drop_rate": 0.0,
            "member_count_current": 2,
            "member_count_original": 2,
            "collection_ratio": 1.0,
            "payout_completion_rate": 1.0,
            "late_payment_trend": 0.0,
            "coordinated_behavior_score": 0.0,
            "contribution_amount": 100.0,
            "cycles_completed": 2,
        }
        result = scorer.score("small-circle", features)
        assert 0 <= result.health_score <= 100
        assert result.confidence < 0.5  # reduced confidence for 2-member

    def test_boundary_score_70(self, scorer, classifier):
        """Score at exactly 70 should be classified Healthy."""
        # Craft features to land near 70
        features = {
            "on_time_payment_rate": 0.85,
            "avg_days_late": 1.0,
            "missed_contribution_count": 0,
            "member_drop_rate": 0.05,
            "member_count_current": 9,
            "member_count_original": 10,
            "avg_member_tenure_days": 60,
            "collection_ratio": 0.85,
            "payout_completion_rate": 0.80,
            "late_payment_trend": 0.05,
            "coordinated_behavior_score": 0.1,
            "contribution_amount": 100.0,
            "cycles_completed": 5,
        }
        result = scorer.score("boundary-circle", features)
        # We can't guarantee exactly 70, but verify tier assignment is correct
        if result.health_score >= 70:
            assert result.health_tier == HealthTier.HEALTHY
        elif result.health_score >= 40:
            assert result.health_tier == HealthTier.AT_RISK
        else:
            assert result.health_tier == HealthTier.CRITICAL

    def test_perfect_score_near_100(self, scorer):
        """Perfect features should yield a score near 100."""
        features = {
            "on_time_payment_rate": 1.0,
            "avg_days_late": 0.0,
            "consecutive_on_time_streak": 20,
            "missed_contribution_count": 0,
            "member_drop_rate": 0.0,
            "member_count_current": 10,
            "member_count_original": 10,
            "avg_member_tenure_days": 200,
            "collection_ratio": 1.0,
            "payout_completion_rate": 1.0,
            "late_payment_trend": 0.0,
            "coordinated_behavior_score": 0.0,
            "largest_single_missed_amount": 0.0,
            "contribution_amount": 100.0,
            "post_payout_disengagement_rate": 0.0,
            "cycles_completed": 10,
        }
        result = scorer.score("perfect-circle", features)
        assert result.health_score >= 95, f"Perfect circle got {result.health_score}"

    def test_empty_features_no_crash(self, scorer):
        """Scoring with empty features should not crash."""
        result = scorer.score("empty-circle", {})
        assert 0 <= result.health_score <= 100

    def test_worst_case_features(self, scorer):
        """Worst possible features should score below 30."""
        features = {
            "on_time_payment_rate": 0.0,
            "avg_days_late": 14.0,
            "consecutive_on_time_streak": 0,
            "missed_contribution_count": 10,
            "member_drop_rate": 0.50,
            "member_count_current": 3,
            "member_count_original": 10,
            "avg_member_tenure_days": 10,
            "collection_ratio": 0.30,
            "payout_completion_rate": 0.20,
            "late_payment_trend": 0.8,
            "coordinated_behavior_score": 0.95,
            "largest_single_missed_amount": 500.0,
            "contribution_amount": 100.0,
            "post_payout_disengagement_rate": 0.8,
            "cycles_completed": 5,
        }
        result = scorer.score("failing-circle", features)
        assert result.health_score < 30, f"Worst case got {result.health_score}"


class TestBatchPerformance:
    """Performance test: score 1,000 circles and measure throughput."""

    def test_batch_scoring_1000_circles(self, scorer):
        """Score 1,000 circles and verify acceptable latency."""
        features = {
            "on_time_payment_rate": 0.90,
            "avg_days_late": 1.5,
            "consecutive_on_time_streak": 3,
            "missed_contribution_count": 1,
            "member_drop_rate": 0.05,
            "member_count_current": 8,
            "member_count_original": 10,
            "avg_member_tenure_days": 60,
            "collection_ratio": 0.90,
            "payout_completion_rate": 0.85,
            "late_payment_trend": 0.1,
            "coordinated_behavior_score": 0.1,
            "largest_single_missed_amount": 50.0,
            "contribution_amount": 100.0,
            "post_payout_disengagement_rate": 0.05,
            "cycles_completed": 5,
        }

        start = time.time()
        for i in range(1000):
            scorer.score(f"circle-{i}", features)
        elapsed = time.time() - start

        # Should complete 1000 scores in under 5 seconds
        assert elapsed < 5.0, f"1000 scores took {elapsed:.2f}s (expected <5s)"

        # Log performance metrics
        avg_ms = (elapsed / 1000) * 1000
        print(
            f"\nBatch scoring: 1000 circles in {elapsed:.3f}s"
            f" ({avg_ms:.2f}ms/circle)"
        )


class TestThresholdSensitivity:
    """Verify how results change when dimension weights shift by +-10%."""

    def test_weight_sensitivity(self, scorer):
        """Shifting contribution weight by ±10% should change scores predictably."""
        from src.domains.circles.config import (
            CircleHealthConfig,
            ContributionReliabilityConfig,
            FinancialProgressConfig,
            MembershipStabilityConfig,
            TrustIntegrityConfig,
        )

        features = {
            "on_time_payment_rate": 0.75,
            "avg_days_late": 3.0,
            "missed_contribution_count": 2,
            "member_drop_rate": 0.0,
            "member_count_current": 10,
            "member_count_original": 10,
            "collection_ratio": 0.95,
            "payout_completion_rate": 0.90,
            "late_payment_trend": 0.0,
            "coordinated_behavior_score": 0.0,
            "contribution_amount": 100.0,
            "cycles_completed": 5,
        }

        # Default weights
        default_scorer = CircleHealthScorer()
        default_result = default_scorer.score("test", features)

        # Increase contribution weight by 10% (0.35 -> 0.385)
        # Decrease others proportionally to keep sum = 1.0
        high_contrib_config = CircleHealthConfig(
            contribution=ContributionReliabilityConfig(weight=0.385),
            membership=MembershipStabilityConfig(weight=0.225),
            financial=FinancialProgressConfig(weight=0.225),
            trust=TrustIntegrityConfig(weight=0.165),
        )
        high_scorer = CircleHealthScorer(config=high_contrib_config)
        high_result = high_scorer.score("test", features)

        # With low contribution score and higher contribution weight,
        # the overall score should decrease
        # (because contribution is the weak dimension here)
        assert high_result.health_score != default_result.health_score

        # All scores should still be in valid range
        assert 0 <= high_result.health_score <= 100
        assert 0 <= default_result.health_score <= 100
