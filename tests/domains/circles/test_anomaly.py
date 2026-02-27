"""Unit tests for circle anomaly detection."""

import pytest

from src.domains.circles.anomaly import CircleAnomalyDetector
from src.domains.circles.models import AnomalySeverity, AnomalyType


@pytest.fixture
def detector() -> CircleAnomalyDetector:
    return CircleAnomalyDetector()


class TestCoordinatedLateDetection:
    def test_no_late_members_no_anomaly(self, detector):
        features = {
            "late_members_current_cycle": 0,
            "member_count_current": 10,
            "historical_late_rate": 0.10,
        }
        anomalies = detector._detect_coordinated_late("c1", features, None)
        assert len(anomalies) == 0

    def test_few_late_members_no_anomaly(self, detector):
        features = {
            "late_members_current_cycle": 1,
            "member_count_current": 10,
            "historical_late_rate": 0.10,
        }
        anomalies = detector._detect_coordinated_late("c1", features, None)
        assert len(anomalies) == 0

    def test_many_late_members_flags_anomaly(self, detector):
        features = {
            "late_members_current_cycle": 6,
            "member_count_current": 10,
            "historical_late_rate": 0.10,
        }
        anomalies = detector._detect_coordinated_late("c1", features, None)
        assert len(anomalies) == 1
        assert anomalies[0].anomaly_type == AnomalyType.COORDINATED_LATE

    def test_high_severity_when_most_members_late(self, detector):
        features = {
            "late_members_current_cycle": 8,
            "member_count_current": 10,
            "historical_late_rate": 0.10,
        }
        anomalies = detector._detect_coordinated_late("c1", features, None)
        assert len(anomalies) == 1
        assert anomalies[0].severity == AnomalySeverity.HIGH

    def test_with_member_level_data(self, detector):
        member_features = [
            {"user_id": f"user-{i}", "is_late_current_cycle": i < 5}
            for i in range(10)
        ]
        features = {"historical_late_rate": 0.10}
        anomalies = detector._detect_coordinated_late("c1", features, member_features)
        assert len(anomalies) == 1
        assert len(anomalies[0].affected_members) == 5


class TestPostPayoutDisengagement:
    def test_no_disengagement_no_anomaly(self, detector):
        features = {
            "post_payout_disengagement_rate": 0.0,
            "members_paid_out": 5,
        }
        anomalies = detector._detect_post_payout_disengagement("c1", features, None)
        assert len(anomalies) == 0

    def test_high_disengagement_flags_anomaly(self, detector):
        features = {
            "post_payout_disengagement_rate": 0.6,
            "members_paid_out": 5,
        }
        anomalies = detector._detect_post_payout_disengagement("c1", features, None)
        assert len(anomalies) == 1
        assert anomalies[0].anomaly_type == AnomalyType.POST_PAYOUT_DISENGAGEMENT

    def test_with_member_level_data(self, detector):
        member_features = [
            {
                "user_id": "user-1",
                "has_received_payout": True,
                "pre_payout_reliability": 1.0,
                "post_payout_reliability": 0.2,
            },
            {
                "user_id": "user-2",
                "has_received_payout": True,
                "pre_payout_reliability": 0.95,
                "post_payout_reliability": 0.3,
            },
            {
                "user_id": "user-3",
                "has_received_payout": False,
                "pre_payout_reliability": 0.9,
                "post_payout_reliability": 0.9,
            },
        ]
        features = {"members_paid_out": 2}
        anomalies = detector._detect_post_payout_disengagement("c1", features, member_features)
        assert len(anomalies) == 1
        assert "user-1" in anomalies[0].affected_members
        assert "user-2" in anomalies[0].affected_members


class TestFreeRiderDetection:
    def test_no_member_features_no_detection(self, detector):
        anomalies = detector._detect_free_riders("c1", {}, None)
        assert len(anomalies) == 0

    def test_balanced_members_no_anomaly(self, detector):
        member_features = [
            {
                "user_id": "user-1",
                "has_received_payout": True,
                "total_contributed": 500.0,
                "expected_contributed": 500.0,
            },
        ]
        anomalies = detector._detect_free_riders("c1", {}, member_features)
        assert len(anomalies) == 0

    def test_free_rider_detected(self, detector):
        member_features = [
            {
                "user_id": "user-1",
                "has_received_payout": True,
                "total_contributed": 100.0,
                "expected_contributed": 500.0,
            },
        ]
        anomalies = detector._detect_free_riders("c1", {}, member_features)
        assert len(anomalies) == 1
        assert anomalies[0].anomaly_type == AnomalyType.FREE_RIDER
        assert "user-1" in anomalies[0].affected_members

    def test_no_payout_not_flagged(self, detector):
        """Members who haven't received payout shouldn't be flagged as free-riders."""
        member_features = [
            {
                "user_id": "user-1",
                "has_received_payout": False,
                "total_contributed": 100.0,
                "expected_contributed": 500.0,
            },
        ]
        anomalies = detector._detect_free_riders("c1", {}, member_features)
        assert len(anomalies) == 0


class TestBehavioralShiftDetection:
    def test_no_shift_no_anomaly(self, detector):
        features = {
            "cycles_completed": 5,
            "avg_payment_timing_zscore": 0.5,
            "amount_consistency_zscore": 0.3,
            "activity_level_zscore": 0.2,
            "member_count_current": 10,
        }
        anomalies = detector._detect_behavioral_shift("c1", features, None)
        assert len(anomalies) == 0

    def test_significant_shift_detected(self, detector):
        features = {
            "cycles_completed": 5,
            "avg_payment_timing_zscore": 3.5,
            "amount_consistency_zscore": 0.3,
            "activity_level_zscore": 0.2,
            "member_count_current": 10,
        }
        anomalies = detector._detect_behavioral_shift("c1", features, None)
        assert len(anomalies) == 1
        assert anomalies[0].anomaly_type == AnomalyType.BEHAVIORAL_SHIFT

    def test_too_few_cycles_no_detection(self, detector):
        """Need at least 3 cycles to establish baseline."""
        features = {
            "cycles_completed": 1,
            "avg_payment_timing_zscore": 5.0,
        }
        anomalies = detector._detect_behavioral_shift("c1", features, None)
        assert len(anomalies) == 0


class TestDetectAll:
    def test_detect_all_returns_multiple_anomalies(self, detector):
        features = {
            "late_members_current_cycle": 7,
            "member_count_current": 10,
            "historical_late_rate": 0.10,
            "post_payout_disengagement_rate": 0.6,
            "members_paid_out": 5,
            "cycles_completed": 5,
            "avg_payment_timing_zscore": 4.0,
        }
        anomalies = detector.detect_all("c1", features)
        types = {a.anomaly_type for a in anomalies}
        assert AnomalyType.COORDINATED_LATE in types
        assert AnomalyType.POST_PAYOUT_DISENGAGEMENT in types
        assert AnomalyType.BEHAVIORAL_SHIFT in types

    def test_clean_circle_no_anomalies(self, detector):
        features = {
            "late_members_current_cycle": 0,
            "member_count_current": 10,
            "post_payout_disengagement_rate": 0.0,
            "members_paid_out": 5,
            "cycles_completed": 5,
        }
        anomalies = detector.detect_all("c1", features)
        assert len(anomalies) == 0
