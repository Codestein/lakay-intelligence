"""Unit tests for circle risk classification."""

from datetime import UTC, datetime

import pytest

from src.domains.circles.classification import CircleClassifier
from src.domains.circles.models import (
    AnomalyEvidence,
    AnomalySeverity,
    AnomalyType,
    CircleAnomaly,
    CircleHealthScore,
    DimensionScore,
    HealthTier,
    TrendDirection,
)


@pytest.fixture
def classifier() -> CircleClassifier:
    return CircleClassifier()


def _make_health_score(
    score: float,
    tier: HealthTier | None = None,
    trend: TrendDirection = TrendDirection.STABLE,
    circle_id: str = "circle-1",
) -> CircleHealthScore:
    """Helper to create a CircleHealthScore for testing."""
    if tier is None:
        if score >= 70:
            tier = HealthTier.HEALTHY
        elif score >= 40:
            tier = HealthTier.AT_RISK
        else:
            tier = HealthTier.CRITICAL

    return CircleHealthScore(
        circle_id=circle_id,
        health_score=score,
        health_tier=tier,
        dimension_scores={
            "contribution_reliability": DimensionScore(
                dimension_name="contribution_reliability",
                score=score,
                weight=0.35,
                contributing_factors=[],
            ),
            "membership_stability": DimensionScore(
                dimension_name="membership_stability",
                score=score,
                weight=0.25,
                contributing_factors=[],
            ),
            "financial_progress": DimensionScore(
                dimension_name="financial_progress",
                score=score,
                weight=0.25,
                contributing_factors=[],
            ),
            "trust_integrity": DimensionScore(
                dimension_name="trust_integrity",
                score=score,
                weight=0.15,
                contributing_factors=[],
            ),
        },
        trend=trend,
        last_updated=datetime.now(UTC),
    )


def _make_anomaly(
    anomaly_type: AnomalyType = AnomalyType.COORDINATED_LATE,
    severity: AnomalySeverity = AnomalySeverity.LOW,
) -> CircleAnomaly:
    return CircleAnomaly(
        anomaly_id="anomaly-1",
        circle_id="circle-1",
        anomaly_type=anomaly_type,
        severity=severity,
        affected_members=["user-1"],
        evidence=[
            AnomalyEvidence(
                metric_name="test",
                observed_value=1.0,
                threshold=0.5,
                description="test evidence",
            )
        ],
        detected_at=datetime.now(UTC),
    )


class TestClassification:
    def test_healthy_circle(self, classifier):
        hs = _make_health_score(85)
        result = classifier.classify(hs, [])
        assert result.health_tier == HealthTier.HEALTHY

    def test_at_risk_circle(self, classifier):
        hs = _make_health_score(55)
        result = classifier.classify(hs, [])
        assert result.health_tier == HealthTier.AT_RISK

    def test_critical_circle(self, classifier):
        hs = _make_health_score(30)
        result = classifier.classify(hs, [])
        assert result.health_tier == HealthTier.CRITICAL


class TestAnomalyEscalation:
    def test_high_anomaly_escalates_healthy_to_at_risk(self, classifier):
        hs = _make_health_score(80)
        anomaly = _make_anomaly(severity=AnomalySeverity.HIGH)
        result = classifier.classify(hs, [anomaly])
        assert result.health_tier == HealthTier.AT_RISK

    def test_high_anomaly_escalates_at_risk_to_critical(self, classifier):
        hs = _make_health_score(55)
        anomaly = _make_anomaly(severity=AnomalySeverity.HIGH)
        result = classifier.classify(hs, [anomaly])
        assert result.health_tier == HealthTier.CRITICAL

    def test_medium_anomaly_escalates_healthy_to_at_risk(self, classifier):
        hs = _make_health_score(80)
        anomaly = _make_anomaly(severity=AnomalySeverity.MEDIUM)
        result = classifier.classify(hs, [anomaly])
        assert result.health_tier == HealthTier.AT_RISK

    def test_low_anomaly_no_escalation(self, classifier):
        hs = _make_health_score(80)
        anomaly = _make_anomaly(severity=AnomalySeverity.LOW)
        result = classifier.classify(hs, [anomaly])
        assert result.health_tier == HealthTier.HEALTHY


class TestTrendOverride:
    def test_deteriorating_below_55_becomes_critical(self, classifier):
        hs = _make_health_score(50, trend=TrendDirection.DETERIORATING)
        result = classifier.classify(hs, [])
        assert result.health_tier == HealthTier.CRITICAL

    def test_deteriorating_at_72_becomes_at_risk(self, classifier):
        """A circle at 72 but deteriorating rapidly should be At-Risk."""
        hs = _make_health_score(72, trend=TrendDirection.DETERIORATING)
        result = classifier.classify(hs, [])
        # 72 - 10 = 62 effective -> AT_RISK
        assert result.health_tier == HealthTier.AT_RISK

    def test_improving_trend_no_demotion(self, classifier):
        hs = _make_health_score(75, trend=TrendDirection.IMPROVING)
        result = classifier.classify(hs, [])
        assert result.health_tier == HealthTier.HEALTHY


class TestRecommendedActions:
    def test_healthy_has_standard_monitoring(self, classifier):
        hs = _make_health_score(85)
        result = classifier.classify(hs, [])
        assert len(result.recommended_actions) >= 1
        assert "monitoring" in result.recommended_actions[0].action.lower()

    def test_at_risk_has_specific_actions(self, classifier):
        hs = _make_health_score(55)
        # Make contribution the weakest dimension
        hs.dimension_scores["contribution_reliability"].score = 30.0
        result = classifier.classify(hs, [])
        assert len(result.recommended_actions) >= 1
        actions_text = " ".join(a.action for a in result.recommended_actions)
        assert "members" in actions_text.lower() or "payment" in actions_text.lower()

    def test_free_rider_anomaly_generates_action(self, classifier):
        hs = _make_health_score(55)
        anomaly = _make_anomaly(
            anomaly_type=AnomalyType.FREE_RIDER,
            severity=AnomalySeverity.HIGH,
        )
        result = classifier.classify(hs, [anomaly])
        actions_text = " ".join(a.action for a in result.recommended_actions)
        assert "payout" in actions_text.lower() or "contributed" in actions_text.lower()

    def test_deteriorating_trend_generates_action(self, classifier):
        hs = _make_health_score(50, trend=TrendDirection.DETERIORATING)
        result = classifier.classify(hs, [])
        actions_text = " ".join(a.action for a in result.recommended_actions)
        assert "declining" in actions_text.lower() or "worse" in actions_text.lower()

    def test_actions_are_plain_language(self, classifier):
        """Actions should be readable by non-technical circle organizers."""
        hs = _make_health_score(45)
        hs.dimension_scores["membership_stability"].score = 25.0
        result = classifier.classify(hs, [])
        for action in result.recommended_actions:
            # No technical jargon
            assert "z-score" not in action.action.lower()
            assert "p-value" not in action.action.lower()
            assert "algorithm" not in action.action.lower()


class TestTierChange:
    def test_tier_change_detected(self, classifier):
        change = classifier.detect_tier_change(
            circle_id="c1",
            current_tier=HealthTier.AT_RISK,
            previous_tier=HealthTier.HEALTHY,
            health_score=55.0,
            reason="Score dropped below 70",
        )
        assert change is not None
        assert change.previous_tier == HealthTier.HEALTHY
        assert change.new_tier == HealthTier.AT_RISK

    def test_no_change_returns_none(self, classifier):
        change = classifier.detect_tier_change(
            circle_id="c1",
            current_tier=HealthTier.HEALTHY,
            previous_tier=HealthTier.HEALTHY,
            health_score=85.0,
            reason="",
        )
        assert change is None

    def test_no_previous_returns_none(self, classifier):
        change = classifier.detect_tier_change(
            circle_id="c1",
            current_tier=HealthTier.HEALTHY,
            previous_tier=None,
            health_score=85.0,
            reason="",
        )
        assert change is None
