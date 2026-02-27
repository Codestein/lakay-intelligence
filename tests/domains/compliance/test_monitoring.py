"""Tests for BSA/AML transaction monitoring rules (Task 8.1).

Tests cover all six monitoring rules (M-1 through M-6) with boundary
conditions and configuration overrides.
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.domains.compliance.config import ComplianceConfig
from src.domains.compliance.models import (
    AlertPriority,
    AlertType,
    ComplianceTransaction,
    RecommendedAction,
)
from src.domains.compliance.monitoring import (
    ComplianceMonitor,
    check_circle_compliance,
    check_ctr_threshold,
    check_geographic_risk,
    check_rapid_movement,
    check_round_amount,
    check_unusual_volume,
)


def _make_tx(**kwargs) -> ComplianceTransaction:
    defaults = {
        "transaction_id": "tx-001",
        "user_id": "user-001",
        "amount": 1000.0,
        "currency": "USD",
        "transaction_type": "remittance_send",
        "initiated_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return ComplianceTransaction(**defaults)


class TestRuleM1CTRThreshold:
    """Rule M-1: CTR threshold monitoring (31 CFR § 1010.311)."""

    def test_below_threshold_no_alert(self):
        alerts = check_ctr_threshold("user-001", 5_000.0, ["tx-001"])
        assert len(alerts) == 0

    def test_at_threshold_ctr_alert(self):
        alerts = check_ctr_threshold("user-001", 10_000.0, ["tx-001", "tx-002"])
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.CTR_THRESHOLD
        assert alerts[0].recommended_action == RecommendedAction.FILE_CTR
        assert alerts[0].priority == AlertPriority.URGENT

    def test_above_threshold_ctr_alert(self):
        alerts = check_ctr_threshold("user-001", 15_000.0, ["tx-001"])
        assert len(alerts) == 1
        assert alerts[0].recommended_action == RecommendedAction.FILE_CTR

    def test_pre_threshold_warning_at_8000(self):
        alerts = check_ctr_threshold("user-001", 8_000.0, ["tx-001"])
        assert len(alerts) == 1
        assert alerts[0].recommended_action == RecommendedAction.ENHANCED_MONITORING
        assert alerts[0].priority == AlertPriority.ELEVATED

    def test_pre_threshold_warning_at_9000(self):
        alerts = check_ctr_threshold("user-001", 9_500.0, ["tx-001"])
        assert len(alerts) == 1
        assert alerts[0].recommended_action == RecommendedAction.ENHANCED_MONITORING
        # Should get the $9,000 warning (highest applicable)

    def test_below_lowest_warning_no_alert(self):
        alerts = check_ctr_threshold("user-001", 7_999.0, ["tx-001"])
        assert len(alerts) == 0

    def test_ctr_includes_all_transaction_ids(self):
        tx_ids = ["tx-001", "tx-002", "tx-003", "tx-004"]
        alerts = check_ctr_threshold("user-001", 10_500.0, tx_ids)
        assert len(alerts) == 1
        assert set(alerts[0].transaction_ids) == set(tx_ids)

    def test_disabled_rule_no_alerts(self):
        config = ComplianceConfig()
        config.ctr.enabled = False
        alerts = check_ctr_threshold("user-001", 15_000.0, ["tx-001"], config)
        assert len(alerts) == 0

    def test_regulatory_basis_documented(self):
        alerts = check_ctr_threshold("user-001", 10_000.0, ["tx-001"])
        assert "31 CFR" in alerts[0].regulatory_basis


class TestRuleM2RoundAmounts:
    """Rule M-2: Suspicious round-amount patterns (FinCEN Advisory FIN-2014-A007)."""

    def test_exact_9999_triggers_alert(self):
        tx = _make_tx(amount=9_999.0)
        alerts = check_round_amount(tx)
        assert len(alerts) == 1
        assert "9,999" in alerts[0].description or "threshold" in alerts[0].description

    def test_exact_4999_triggers_alert(self):
        tx = _make_tx(amount=4_999.0)
        alerts = check_round_amount(tx)
        assert len(alerts) == 1

    def test_exact_2999_triggers_alert(self):
        tx = _make_tx(amount=2_999.0)
        alerts = check_round_amount(tx)
        assert len(alerts) == 1

    def test_9990_within_tolerance_triggers(self):
        tx = _make_tx(amount=9_990.0)
        alerts = check_round_amount(tx)
        assert len(alerts) == 1

    def test_5000_above_threshold_no_alert(self):
        tx = _make_tx(amount=5_000.0)
        alerts = check_round_amount(tx)
        assert len(alerts) == 0

    def test_normal_amount_no_alert(self):
        tx = _make_tx(amount=3_456.78)
        alerts = check_round_amount(tx)
        assert len(alerts) == 0

    def test_high_round_ratio_triggers(self):
        tx = _make_tx(amount=1_000.0)
        alerts = check_round_amount(tx, round_amount_ratio_30d=0.70)
        assert len(alerts) == 1
        assert "round-amount" in alerts[0].description.lower()

    def test_low_round_ratio_no_alert(self):
        tx = _make_tx(amount=1_000.0)
        alerts = check_round_amount(tx, round_amount_ratio_30d=0.20)
        assert len(alerts) == 0


class TestRuleM3RapidMovement:
    """Rule M-3: Rapid movement / layering (31 CFR § 1022.320)."""

    def test_rapid_movement_detected(self):
        now = datetime.now(UTC)
        received = [_make_tx(transaction_id="rx-001", amount=5_000.0, initiated_at=now)]
        sent = [
            _make_tx(
                transaction_id="tx-001",
                amount=4_500.0,
                initiated_at=now + timedelta(hours=2),
            )
        ]
        alerts = check_rapid_movement("user-001", received, sent)
        assert len(alerts) == 1
        assert alerts[0].recommended_action == RecommendedAction.FILE_SAR
        assert "layering" in alerts[0].description.lower()

    def test_no_rapid_movement_below_ratio(self):
        now = datetime.now(UTC)
        received = [_make_tx(amount=5_000.0, initiated_at=now)]
        sent = [
            _make_tx(amount=1_000.0, initiated_at=now + timedelta(hours=2))
        ]  # Only 20%
        alerts = check_rapid_movement("user-001", received, sent)
        assert len(alerts) == 0

    def test_no_rapid_movement_outside_window(self):
        now = datetime.now(UTC)
        received = [_make_tx(amount=5_000.0, initiated_at=now)]
        sent = [
            _make_tx(amount=4_500.0, initiated_at=now + timedelta(hours=48))
        ]  # Beyond 24h
        alerts = check_rapid_movement("user-001", received, sent)
        assert len(alerts) == 0

    def test_below_min_amount_no_alert(self):
        now = datetime.now(UTC)
        received = [_make_tx(amount=500.0, initiated_at=now)]
        sent = [_make_tx(amount=450.0, initiated_at=now + timedelta(hours=1))]
        alerts = check_rapid_movement("user-001", received, sent)
        assert len(alerts) == 0  # Below $1,000 min_amount


class TestRuleM4UnusualVolume:
    """Rule M-4: Unusual transaction volume (31 CFR § 1022.210(d))."""

    def test_above_multiplier_threshold(self):
        tx = _make_tx(amount=15_000.0)
        alerts = check_unusual_volume(
            tx, tx_count_24h=10, tx_amount_mean_30d=3_000.0, tx_amount_std_30d=500.0
        )
        assert len(alerts) >= 1
        assert any(a.alert_type == AlertType.VELOCITY_ANOMALY for a in alerts)

    def test_normal_volume_no_alert(self):
        tx = _make_tx(amount=3_000.0)
        alerts = check_unusual_volume(
            tx, tx_count_24h=10, tx_amount_mean_30d=3_000.0, tx_amount_std_30d=500.0
        )
        assert len(alerts) == 0

    def test_zscore_triggers_alert(self):
        tx = _make_tx(amount=5_500.0)
        alerts = check_unusual_volume(
            tx, tx_count_24h=10, tx_amount_mean_30d=3_000.0, tx_amount_std_30d=500.0
        )
        # z-score = (5500 - 3000) / 500 = 5.0, exceeds 3.0 threshold
        assert any("z-score" in a.description for a in alerts)

    def test_insufficient_baseline_no_alert(self):
        tx = _make_tx(amount=15_000.0)
        # Only 2 transactions in 24h, below min_baseline_transactions (5)
        alerts = check_unusual_volume(
            tx, tx_count_24h=2, tx_amount_mean_30d=3_000.0
        )
        assert len(alerts) == 0


class TestRuleM5GeographicRisk:
    """Rule M-5: Geographic risk indicators (FATF Rec. 19)."""

    def test_high_risk_country_triggers(self):
        tx = _make_tx(geo_country="IR")  # Iran — FATF blacklist
        alerts = check_geographic_risk(tx)
        assert len(alerts) >= 1
        assert alerts[0].priority == AlertPriority.CRITICAL
        assert alerts[0].recommended_action == RecommendedAction.ESCALATE_TO_BSA_OFFICER

    def test_normal_corridor_no_alert(self):
        tx = _make_tx(geo_country="US")
        alerts = check_geographic_risk(tx, last_known_country="US")
        assert len(alerts) == 0

    def test_unexpected_origin_triggers(self):
        tx = _make_tx(geo_country="NG")  # Nigeria — not in US/HT corridor
        alerts = check_geographic_risk(
            tx, last_known_country="US", distinct_countries_7d=3
        )
        assert len(alerts) >= 1
        assert "outside" in alerts[0].description.lower() or "inconsistent" in alerts[0].description.lower()

    def test_haiti_corridor_no_alert(self):
        tx = _make_tx(geo_country="HT")
        alerts = check_geographic_risk(tx, last_known_country="US")
        assert len(alerts) == 0  # HT is in expected corridor

    def test_no_geo_no_alert(self):
        tx = _make_tx(geo_country=None)
        alerts = check_geographic_risk(tx)
        assert len(alerts) == 0


class TestRuleM6CircleCompliance:
    """Rule M-6: Circle-based compliance concerns."""

    def test_aggregate_approaching_threshold(self):
        alerts = check_circle_compliance(
            circle_id="circle-001",
            member_contributions_total=8_500.0,
        )
        assert len(alerts) >= 1
        assert any("aggregate" in a.description.lower() for a in alerts)

    def test_payout_plus_daily_exceeds_ctr(self):
        alerts = check_circle_compliance(
            circle_id="circle-001",
            member_contributions_total=5_000.0,
            payout_amount=7_000.0,
            payout_recipient_id="user-002",
            payout_recipient_daily_total=4_000.0,
        )
        # 7,000 + 4,000 = 11,000 >= 10,000
        assert any(a.recommended_action == RecommendedAction.FILE_CTR for a in alerts)

    def test_members_with_alerts(self):
        alerts = check_circle_compliance(
            circle_id="circle-001",
            member_contributions_total=5_000.0,
            members_with_alerts=["user-003", "user-004"],
        )
        assert any(a.alert_type == AlertType.EDD_TRIGGER for a in alerts)

    def test_below_aggregate_no_alert_on_contributions(self):
        alerts = check_circle_compliance(
            circle_id="circle-001",
            member_contributions_total=3_000.0,
        )
        # $3,000 is below 80% of $10,000 ($8,000) — no aggregate alert
        assert not any("aggregate" in a.description.lower() for a in alerts)


class TestComplianceMonitorOrchestration:
    """Test the ComplianceMonitor orchestrator that runs all rules."""

    @pytest.fixture()
    def monitor(self):
        return ComplianceMonitor()

    def test_evaluate_transaction_ctr(self, monitor):
        tx = _make_tx(amount=5_000.0)
        alerts = monitor.evaluate_transaction(
            transaction=tx,
            daily_total=6_000.0,  # 6,000 + 5,000 = 11,000 >= 10,000
            daily_transaction_ids=["tx-prev"],
        )
        assert any(a.alert_type == AlertType.CTR_THRESHOLD for a in alerts)

    def test_evaluate_transaction_no_alerts_for_normal(self, monitor):
        tx = _make_tx(amount=500.0)
        alerts = monitor.evaluate_transaction(transaction=tx)
        assert len(alerts) == 0

    def test_evaluate_with_geographic_risk(self, monitor):
        tx = _make_tx(amount=500.0, geo_country="IR")
        alerts = monitor.evaluate_transaction(transaction=tx)
        assert any(a.alert_type == AlertType.SUSPICIOUS_ACTIVITY for a in alerts)
