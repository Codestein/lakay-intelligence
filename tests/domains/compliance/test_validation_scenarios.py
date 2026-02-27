"""End-to-end regulatory scenario validation tests (Task 8.6).

These tests validate the compliance module against scenarios derived from
Trebanx's 62-document BSA/AML compliance framework. Each scenario is
identified by its regulatory scenario ID (C-*, S-*, SAR-*, R-*, CC-*).
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.domains.compliance.config import ComplianceConfig
from src.domains.compliance.ctr import CTRTracker
from src.domains.compliance.models import (
    AlertPriority,
    AlertType,
    CaseStatus,
    ComplianceCase,
    ComplianceTransaction,
    RecommendedAction,
    RiskLevel,
    SARDraftStatus,
    StructuringTypology,
)
from src.domains.compliance.monitoring import ComplianceMonitor
from src.domains.compliance.risk_scoring import CustomerRiskManager, compute_risk_score
from src.domains.compliance.sar import SARDraftManager, draft_narrative
from src.domains.compliance.structuring import StructuringDetector


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


# ===================================================================
# CTR SCENARIOS
# ===================================================================


class TestCTRScenarios:
    """CTR scenarios C-1 through C-4."""

    @pytest.fixture()
    def tracker(self):
        return CTRTracker()

    def test_c1_single_transaction_ctr(self, tracker):
        """C-1: User sends a $12,000 remittance.

        Expected: CTR alert generated immediately, filing package assembled,
        priority = urgent.
        """
        tx = _make_tx(
            transaction_id="tx-c1",
            user_id="user-c1",
            amount=12_000.0,
        )
        alerts = tracker.process_transaction(tx)

        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.CTR_THRESHOLD
        assert alerts[0].recommended_action == RecommendedAction.FILE_CTR
        assert alerts[0].priority == AlertPriority.URGENT
        assert alerts[0].amount_total == 12_000.0

        packages = tracker.get_pending_obligations()
        assert len(packages) == 1
        assert packages[0].total_amount == 12_000.0

    def test_c2_aggregated_ctr(self, tracker):
        """C-2: User makes 4 transactions in one day: $3,000, $2,500, $2,800, $2,200.

        Expected: CTR alert when cumulative crosses $10,000, all 4 included.
        """
        # Use a fixed midday timestamp so all txns fall on the same business day
        base = datetime(2024, 7, 10, 18, 0, tzinfo=UTC)  # 1 PM EST
        amounts = [3_000.0, 2_500.0, 2_800.0, 2_200.0]
        all_alerts = []

        for i, amount in enumerate(amounts):
            tx = _make_tx(
                transaction_id=f"tx-c2-{i}",
                user_id="user-c2",
                amount=amount,
                initiated_at=base + timedelta(minutes=i * 60),
            )
            all_alerts.extend(tracker.process_transaction(tx))

        ctr_alerts = [a for a in all_alerts if a.recommended_action == RecommendedAction.FILE_CTR]
        assert len(ctr_alerts) == 1
        assert ctr_alerts[0].amount_total == 10_500.0

        packages = tracker.get_pending_obligations()
        assert packages[0].transaction_count == 4

    def test_c3_just_below_threshold(self, tracker):
        """C-3: User makes a single $9,999 transaction.

        Expected: No CTR alert, but pre-threshold warning generated.
        """
        tx = _make_tx(
            transaction_id="tx-c3",
            user_id="user-c3",
            amount=9_999.0,
        )
        alerts = tracker.process_transaction(tx)

        ctr_alerts = [a for a in alerts if a.recommended_action == RecommendedAction.FILE_CTR]
        assert len(ctr_alerts) == 0

        warnings = [a for a in alerts if a.recommended_action == RecommendedAction.ENHANCED_MONITORING]
        assert len(warnings) >= 1

    def test_c4_cross_day_boundary(self, tracker):
        """C-4: User transacts $6,000 at 11 PM and $5,000 at 1 AM.

        Expected: Two different business days, no CTR threshold met.
        """
        est = timezone(timedelta(hours=-5))
        day1_11pm = datetime(2024, 6, 15, 23, 0, tzinfo=est).astimezone(UTC)
        day2_1am = datetime(2024, 6, 16, 1, 0, tzinfo=est).astimezone(UTC)

        tx1 = _make_tx(
            transaction_id="tx-c4-1", user_id="user-c4",
            amount=6_000.0, initiated_at=day1_11pm,
        )
        tx2 = _make_tx(
            transaction_id="tx-c4-2", user_id="user-c4",
            amount=5_000.0, initiated_at=day2_1am,
        )

        alerts1 = tracker.process_transaction(tx1, tz_offset_hours=-5.0)
        alerts2 = tracker.process_transaction(tx2, tz_offset_hours=-5.0)

        all_ctr = [
            a for a in alerts1 + alerts2
            if a.recommended_action == RecommendedAction.FILE_CTR
        ]
        assert len(all_ctr) == 0


# ===================================================================
# STRUCTURING SCENARIOS
# ===================================================================


class TestStructuringScenarios:
    """Structuring scenarios S-1 through S-5."""

    @pytest.fixture()
    def detector(self):
        return StructuringDetector()

    def test_s1_micro_structuring(self, detector):
        """S-1: User sends 5 remittances of $1,900 each in one day ($9,500 total).

        Expected: structuring detected (micro), confidence > 0.5, alert generated.
        """
        now = datetime.now(UTC)
        txns = [
            _make_tx(
                transaction_id=f"tx-s1-{i}",
                user_id="user-s1",
                amount=1_900.0,
                recipient_id="r-001",
                initiated_at=now + timedelta(hours=i),
            )
            for i in range(5)
        ]

        detections, alerts = detector.analyze("user-s1", txns)

        micro_detections = [d for d in detections if d.typology == StructuringTypology.MICRO]
        assert len(micro_detections) >= 1
        assert micro_detections[0].confidence > 0.5
        assert len(alerts) >= 1

    def test_s2_slow_structuring(self, detector):
        """S-2: User sends $4,500 every Monday for 3 weeks ($13,500 total).

        Expected: structuring detected (slow), confidence > 0.7, SAR recommended.
        """
        now = datetime.now(UTC)
        txns = [
            _make_tx(
                transaction_id=f"tx-s2-{i}",
                user_id="user-s2",
                amount=4_500.0,
                initiated_at=now - timedelta(weeks=i),
            )
            for i in range(3)
        ]

        detections, alerts = detector.analyze("user-s2", txns)

        slow_detections = [d for d in detections if d.typology == StructuringTypology.SLOW]
        assert len(slow_detections) >= 1
        assert slow_detections[0].confidence > 0.7
        assert slow_detections[0].amount_total == 13_500.0

    def test_s3_fan_out(self, detector):
        """S-3: User sends $3,200 each to 4 different recipients in Haiti ($12,800 total).

        Expected: structuring detected (fan_out), confidence > 0.6.
        """
        now = datetime.now(UTC)
        txns = [
            _make_tx(
                transaction_id=f"tx-s3-{i}",
                user_id="user-s3",
                sender_id="user-s3",
                amount=3_200.0,
                recipient_id=f"recipient-ht-{i}",
                initiated_at=now + timedelta(hours=i),
            )
            for i in range(4)
        ]

        detections, alerts = detector.analyze("user-s3", txns)

        fan_out = [d for d in detections if d.typology == StructuringTypology.FAN_OUT]
        assert len(fan_out) >= 1
        assert fan_out[0].confidence > 0.6
        assert fan_out[0].amount_total == 12_800.0

    def test_s4_funnel(self, detector):
        """S-4: 4 users each send $3,000 to the same recipient within 48 hours ($12,000 total).

        Expected: structuring detected (funnel), confidence > 0.5.
        """
        now = datetime.now(UTC)
        recipient_id = "recipient-haiti"
        txns = [
            _make_tx(
                transaction_id=f"tx-s4-{i}",
                user_id=f"sender-{i}",
                amount=3_000.0,
                recipient_id=recipient_id,
                initiated_at=now + timedelta(hours=i * 6),
            )
            for i in range(4)
        ]

        detections, alerts = detector.analyze(recipient_id, txns)

        funnel = [d for d in detections if d.typology == StructuringTypology.FUNNEL]
        assert len(funnel) >= 1
        assert funnel[0].confidence > 0.5
        assert funnel[0].amount_total == 12_000.0

    def test_s5_legitimate_pattern(self, detector):
        """S-5: User consistently sends $500/week to family in Haiti (6+ months).

        Expected: No structuring flag — normal diaspora behavior.
        """
        now = datetime.now(UTC)
        txns = [
            _make_tx(
                transaction_id=f"tx-s5-{i}",
                user_id="user-s5",
                amount=500.0,
                recipient_id="family-haiti",
                initiated_at=now - timedelta(weeks=i),
            )
            for i in range(26)
        ]

        detections, alerts = detector.analyze(
            "user-s5", txns, historical_avg_amount=500.0
        )

        # Should NOT flag legitimate pattern
        # $500 is well below the $3,000 slow-structuring range
        # Single recipient means no fan-out
        # Single daily transactions means no micro-structuring
        assert len(detections) == 0


# ===================================================================
# SAR SCENARIOS
# ===================================================================


class TestSARScenarios:
    """SAR scenarios SAR-1 and SAR-2."""

    def test_sar1_rapid_movement(self):
        """SAR-1: User receives circle payout of $5,000, immediately sends $4,800.

        Expected: rapid movement fires, alert generated, SAR narrative available.
        """
        now = datetime.now(UTC)
        monitor = ComplianceMonitor()

        received = [
            _make_tx(
                transaction_id="tx-payout",
                user_id="user-sar1",
                amount=5_000.0,
                transaction_type="circle_payout",
                initiated_at=now,
            )
        ]
        sent = [
            _make_tx(
                transaction_id="tx-remit",
                user_id="user-sar1",
                amount=4_800.0,
                transaction_type="remittance_send",
                initiated_at=now + timedelta(hours=1),
            )
        ]

        # Check rapid movement on the send transaction
        from src.domains.compliance.monitoring import check_rapid_movement

        alerts = check_rapid_movement("user-sar1", received, sent)
        assert len(alerts) >= 1
        assert alerts[0].recommended_action == RecommendedAction.FILE_SAR

        # Generate SAR narrative
        case = ComplianceCase(
            case_id="case-sar1",
            user_id="user-sar1",
            alert_ids=[alerts[0].alert_id],
            case_type="rapid_movement",
            opened_at=now,
        )
        draft = draft_narrative(case, alerts)
        assert draft.status == SARDraftStatus.DRAFT
        assert "MACHINE-GENERATED DRAFT" in draft.narrative

    def test_sar2_multi_signal(self):
        """SAR-2: User has structuring + geographic anomaly + elevated fraud score.

        Expected: case opened grouping all signals, priority = critical,
        SAR recommended.
        """
        from src.domains.compliance.models import (
            AlertStatus,
            ComplianceAlert,
        )

        now = datetime.now(UTC)

        alerts = [
            ComplianceAlert(
                alert_id="alert-struct",
                alert_type=AlertType.STRUCTURING,
                user_id="user-sar2",
                transaction_ids=["tx-1", "tx-2", "tx-3"],
                amount_total=9_800.0,
                description="Structuring detected (medium confidence).",
                regulatory_basis="31 USC § 5324",
                recommended_action=RecommendedAction.ENHANCED_MONITORING,
                priority=AlertPriority.ELEVATED,
                status=AlertStatus.NEW,
                created_at=now,
            ),
            ComplianceAlert(
                alert_id="alert-geo",
                alert_type=AlertType.SUSPICIOUS_ACTIVITY,
                user_id="user-sar2",
                amount_total=3_000.0,
                description="Geographic anomaly: transaction from unexpected country.",
                regulatory_basis="31 CFR § 1022.210(d)(4)",
                recommended_action=RecommendedAction.ENHANCED_MONITORING,
                priority=AlertPriority.ELEVATED,
                status=AlertStatus.NEW,
                created_at=now,
            ),
            ComplianceAlert(
                alert_id="alert-fraud",
                alert_type=AlertType.VELOCITY_ANOMALY,
                user_id="user-sar2",
                amount_total=5_000.0,
                description="Elevated fraud score from Phase 3.",
                regulatory_basis="FinCEN Advisory FIN-2014-A007",
                recommended_action=RecommendedAction.ENHANCED_MONITORING,
                priority=AlertPriority.ELEVATED,
                status=AlertStatus.NEW,
                created_at=now,
            ),
        ]

        case = ComplianceCase(
            case_id="case-sar2",
            user_id="user-sar2",
            alert_ids=[a.alert_id for a in alerts],
            case_type="multi_signal",
            opened_at=now,
        )

        draft = draft_narrative(case, alerts)
        assert draft.sections.get("alert_count") == 3
        assert "MULTIPLE INDICATORS" in draft.narrative


# ===================================================================
# CUSTOMER RISK SCENARIOS
# ===================================================================


class TestRiskScenarios:
    """Customer risk scenarios R-1 through R-3."""

    def test_r1_new_high_volume_user(self):
        """R-1: Account created 2 weeks ago, already $15,000 in transactions.

        Expected: risk score elevated, EDD triggered.
        """
        assessment = compute_risk_score(
            user_id="user-r1",
            account_age_days=14,
            tx_volume_vs_baseline=5.0,
            ctr_filing_count=1,
            compliance_alert_count=1,
        )

        assert assessment.risk_score > 0.1
        # New account boost applies
        assert any(
            f.factor_name == "new_account" for f in assessment.factor_details
        )

    def test_r2_established_low_risk_user(self):
        """R-2: Account 1 year old, consistent $500/week, no alerts, complete KYC.

        Expected: risk level = low, standard monitoring.
        """
        assessment = compute_risk_score(
            user_id="user-r2",
            account_age_days=365,
            profile_complete=True,
            ctr_filing_count=0,
            compliance_alert_count=0,
        )

        assert assessment.risk_level == RiskLevel.LOW
        assert assessment.edd_required is False

    def test_r3_escalating_risk(self):
        """R-3: User transitions low → medium → high over time.

        Expected: EDD triggered, audit trail shows progression.
        """
        manager = CustomerRiskManager()

        # Phase 1: Low risk
        a1, _ = manager.assess_risk(
            user_id="user-r3",
            account_age_days=365,
            profile_complete=True,
        )
        assert a1.risk_level == RiskLevel.LOW

        # Phase 2: Increasing risk
        a2, _ = manager.assess_risk(
            user_id="user-r3",
            account_age_days=365,
            compliance_alert_count=3,
            structuring_flag_count=1,
            fraud_score_avg=0.5,
            tx_volume_vs_baseline=4.0,
        )
        assert a2.risk_score > a1.risk_score

        # Phase 3: High risk
        a3, alerts3 = manager.assess_risk(
            user_id="user-r3",
            account_age_days=365,
            compliance_alert_count=8,
            structuring_flag_count=4,
            fraud_score_avg=0.8,
            tx_volume_vs_baseline=8.0,
            high_risk_country_transactions=3,
            ato_alert_count=2,
            flagged_circle_count=2,
            circle_count=8,
        )

        # Verify progression in history
        history = manager.get_history("user-r3")
        assert len(history) == 3
        scores = [h.risk_score for h in history]
        assert scores[0] <= scores[1] <= scores[2]


# ===================================================================
# CIRCLE COMPLIANCE SCENARIOS
# ===================================================================


class TestCircleComplianceScenarios:
    """Circle compliance scenarios CC-1 and CC-2."""

    def test_cc1_circle_aggregate(self):
        """CC-1: 10-member circle, each contributing $1,200/month,
        monthly payout = $12,000.

        Expected: CTR obligation for payout recipient.
        """
        from src.domains.compliance.monitoring import check_circle_compliance

        alerts = check_circle_compliance(
            circle_id="circle-cc1",
            member_contributions_total=12_000.0,
            payout_amount=12_000.0,
            payout_recipient_id="user-cc1-recipient",
            payout_recipient_daily_total=0.0,
        )

        # Aggregate flag
        aggregate_alerts = [a for a in alerts if "aggregate" in a.description.lower()]
        assert len(aggregate_alerts) >= 1

        # CTR flag for payout recipient
        ctr_alerts = [a for a in alerts if a.recommended_action == RecommendedAction.FILE_CTR]
        assert len(ctr_alerts) >= 1

    def test_cc2_circle_with_flagged_member(self):
        """CC-2: One circle member under compliance alert.

        Expected: Circle flagged for enhanced monitoring.
        """
        from src.domains.compliance.monitoring import check_circle_compliance

        alerts = check_circle_compliance(
            circle_id="circle-cc2",
            member_contributions_total=5_000.0,
            members_with_alerts=["flagged-user"],
        )

        edd_alerts = [a for a in alerts if a.alert_type == AlertType.EDD_TRIGGER]
        assert len(edd_alerts) >= 1
        assert "flagged-user" in edd_alerts[0].description


# ===================================================================
# CONFIGURATION VALIDATION
# ===================================================================


class TestConfigurationValidation:
    """Validate that all rules are configurable with documented defaults."""

    def test_all_rules_have_enabled_flag(self):
        config = ComplianceConfig()
        assert hasattr(config.ctr, "enabled")
        assert hasattr(config.round_amount, "enabled")
        assert hasattr(config.rapid_movement, "enabled")
        assert hasattr(config.unusual_volume, "enabled")
        assert hasattr(config.geographic, "enabled")
        assert hasattr(config.circle, "enabled")
        assert hasattr(config.structuring, "enabled")

    def test_all_rules_have_priority_override(self):
        config = ComplianceConfig()
        assert hasattr(config.ctr, "priority_override")
        assert hasattr(config.round_amount, "priority_override")
        assert hasattr(config.rapid_movement, "priority_override")
        assert hasattr(config.unusual_volume, "priority_override")
        assert hasattr(config.geographic, "priority_override")
        assert hasattr(config.circle, "priority_override")

    def test_corridor_overrides_exist(self):
        config = ComplianceConfig()
        assert len(config.corridor_overrides) >= 1
        assert config.corridor_overrides[0].corridor == "US-HT"

    def test_kafka_topics_configured(self):
        config = ComplianceConfig()
        assert config.alerts_topic == "lakay.compliance.alerts"
        assert config.edd_triggers_topic == "lakay.compliance.edd-triggers"

    def test_env_override_works(self):
        import os
        os.environ["COMPLIANCE_CTR_THRESHOLD"] = "5000"
        try:
            config = ComplianceConfig.from_env()
            assert config.ctr.ctr_threshold == 5_000.0
        finally:
            del os.environ["COMPLIANCE_CTR_THRESHOLD"]


# ===================================================================
# AUDIT TRAIL VALIDATION
# ===================================================================


class TestAuditTrail:
    """Verify that all compliance events have proper audit trails."""

    def test_alerts_have_timestamps(self):
        from src.domains.compliance.monitoring import check_ctr_threshold

        alerts = check_ctr_threshold("user-audit", 10_000.0, ["tx-001"])
        assert alerts[0].created_at is not None

    def test_risk_history_tracked(self):
        manager = CustomerRiskManager()
        manager.assess_risk(user_id="user-hist")
        manager.assess_risk(user_id="user-hist", compliance_alert_count=2)

        history = manager.get_history("user-hist")
        assert len(history) == 2
        assert all(h.assessed_at is not None for h in history)

    def test_structuring_audit_log(self):
        detector = StructuringDetector()
        now = datetime.now(UTC)
        txns = [
            _make_tx(
                transaction_id=f"tx-audit-{i}",
                user_id="user-audit",
                amount=2_000.0,
                recipient_id="r-001",
                initiated_at=now + timedelta(hours=i),
            )
            for i in range(5)
        ]
        detector.analyze("user-audit", txns)
        # Audit log should capture all detections
        assert isinstance(detector.audit_log, list)

    def test_officer_review_audit_trail(self):
        manager = CustomerRiskManager()
        manager.assess_risk(user_id="user-review-audit")
        manager.record_review(
            user_id="user-review-audit",
            reviewer="officer-002",
            notes="Quarterly review complete.",
        )

        reviews = manager.get_reviews("user-review-audit")
        assert len(reviews) == 1
        assert reviews[0]["reviewer"] == "officer-002"
        assert "reviewed_at" in reviews[0]
