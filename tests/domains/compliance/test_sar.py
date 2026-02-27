"""Tests for SAR narrative draft generator (Task 8.4)."""

from datetime import UTC, datetime

import pytest

from src.domains.compliance.models import (
    AlertPriority,
    AlertStatus,
    AlertType,
    CaseStatus,
    ComplianceAlert,
    ComplianceCase,
    RecommendedAction,
    SARDraftStatus,
)
from src.domains.compliance.sar import (
    DISCLAIMER,
    SARDraftManager,
    assemble_sar_data,
    draft_narrative,
)


def _make_alert(**kwargs) -> ComplianceAlert:
    defaults = {
        "alert_id": "alert-001",
        "alert_type": AlertType.STRUCTURING,
        "user_id": "user-001",
        "transaction_ids": ["tx-001", "tx-002"],
        "amount_total": 9_500.0,
        "description": "Micro-structuring detected: 5 transactions.",
        "regulatory_basis": "31 USC § 5324",
        "recommended_action": RecommendedAction.FILE_SAR,
        "priority": AlertPriority.URGENT,
        "status": AlertStatus.NEW,
        "created_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return ComplianceAlert(**defaults)


def _make_case(**kwargs) -> ComplianceCase:
    defaults = {
        "case_id": "case-001",
        "user_id": "user-001",
        "alert_ids": ["alert-001"],
        "case_type": "structuring",
        "status": CaseStatus.INVESTIGATING,
        "opened_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return ComplianceCase(**defaults)


class TestSARDataAssembly:
    """Test data assembly from case and alerts."""

    def test_assemble_basic_data(self):
        case = _make_case()
        alerts = [_make_alert()]
        data = assemble_sar_data(case, alerts)

        assert data["customer_id"] == "user-001"
        assert data["alert_count"] == 1
        assert "structuring" in data["alert_types"]
        assert len(data["transaction_ids"]) == 2
        assert data["total_amount"] == 9_500.0

    def test_assemble_multiple_alerts(self):
        case = _make_case(alert_ids=["alert-001", "alert-002"])
        alerts = [
            _make_alert(
                alert_id="alert-001",
                amount_total=9_500.0,
                transaction_ids=["tx-001", "tx-002"],
            ),
            _make_alert(
                alert_id="alert-002",
                alert_type=AlertType.SUSPICIOUS_ACTIVITY,
                amount_total=5_000.0,
                transaction_ids=["tx-003"],
                description="Rapid movement detected.",
            ),
        ]
        data = assemble_sar_data(case, alerts)

        assert data["alert_count"] == 2
        assert len(data["alert_types"]) == 2
        assert data["total_amount"] == 14_500.0
        assert len(data["transaction_ids"]) == 3


class TestSARNarrativeDrafting:
    """Test SAR narrative generation."""

    def test_structuring_narrative(self):
        case = _make_case()
        alerts = [_make_alert()]
        draft = draft_narrative(case, alerts)

        assert draft.case_id == "case-001"
        assert draft.user_id == "user-001"
        assert draft.status == SARDraftStatus.DRAFT
        assert "MACHINE-GENERATED DRAFT" in draft.narrative
        assert "user-001" in draft.narrative
        assert draft.confidence_note != ""

    def test_rapid_movement_narrative(self):
        case = _make_case(case_type="rapid_movement")
        alerts = [
            _make_alert(
                alert_type=AlertType.SUSPICIOUS_ACTIVITY,
                description="Rapid movement: received $5,000 and sent $4,800 within 2 hours. Layering suspected.",
            )
        ]
        draft = draft_narrative(case, alerts)
        assert "MACHINE-GENERATED DRAFT" in draft.narrative

    def test_multi_signal_narrative(self):
        case = _make_case(
            alert_ids=["alert-001", "alert-002"],
            case_type="multi_signal",
        )
        alerts = [
            _make_alert(
                alert_id="alert-001",
                alert_type=AlertType.STRUCTURING,
                description="Structuring detected.",
            ),
            _make_alert(
                alert_id="alert-002",
                alert_type=AlertType.SUSPICIOUS_ACTIVITY,
                description="Geographic anomaly detected.",
            ),
        ]
        draft = draft_narrative(case, alerts)

        assert "MULTIPLE INDICATORS" in draft.narrative or "MACHINE-GENERATED" in draft.narrative
        assert draft.sections.get("template_used") == "multi_signal"

    def test_disclaimer_always_present(self):
        case = _make_case()
        alerts = [_make_alert()]
        draft = draft_narrative(case, alerts)
        assert "MACHINE-GENERATED DRAFT" in draft.machine_generated_disclaimer
        assert "MUST be reviewed" in draft.machine_generated_disclaimer
        assert "MACHINE-GENERATED DRAFT" in draft.narrative

    def test_empty_alerts_handled(self):
        case = _make_case(alert_ids=[])
        draft = draft_narrative(case, [])
        assert draft.narrative != ""  # Should still produce something


class TestScenarioSAR1RapidMovement:
    """Scenario SAR-1: User receives a circle payout of $5,000, immediately
    sends $4,800 as a remittance to Haiti.

    Expected: Rapid movement rule fires, compliance alert generated,
    SAR narrative draft available.
    """

    def test_sar_draft_available_for_rapid_movement(self):
        case = _make_case(
            case_id="case-sar1",
            user_id="user-sar1",
            case_type="rapid_movement",
        )
        alerts = [
            _make_alert(
                alert_id="alert-sar1",
                alert_type=AlertType.SUSPICIOUS_ACTIVITY,
                user_id="user-sar1",
                transaction_ids=["tx-payout", "tx-remit"],
                amount_total=9_800.0,
                description=(
                    "User user-sar1 received $5,000.00 and sent $4,800.00 "
                    "within 2.0 hours (96% of received amount). "
                    "This rapid movement of funds may indicate layering."
                ),
            )
        ]
        draft = draft_narrative(case, alerts)
        assert draft.status == SARDraftStatus.DRAFT
        assert "user-sar1" in draft.narrative


class TestScenarioSAR2MultiSignal:
    """Scenario SAR-2: User has structuring (medium confidence) + geographic
    anomaly + elevated fraud score.

    Expected: compliance case grouping all signals, priority = critical,
    SAR recommended.
    """

    def test_multi_signal_case_sar(self):
        case = _make_case(
            case_id="case-sar2",
            user_id="user-sar2",
            alert_ids=["alert-struct", "alert-geo", "alert-fraud"],
            case_type="multi_signal",
        )
        alerts = [
            _make_alert(
                alert_id="alert-struct",
                alert_type=AlertType.STRUCTURING,
                description="Structuring detection (medium confidence).",
                priority=AlertPriority.ELEVATED,
            ),
            _make_alert(
                alert_id="alert-geo",
                alert_type=AlertType.SUSPICIOUS_ACTIVITY,
                description="Geographic anomaly: transaction from unexpected country.",
                priority=AlertPriority.ELEVATED,
            ),
            _make_alert(
                alert_id="alert-fraud",
                alert_type=AlertType.VELOCITY_ANOMALY,
                description="Elevated fraud score from Phase 3.",
                priority=AlertPriority.ELEVATED,
            ),
        ]

        draft = draft_narrative(case, alerts)
        assert "MULTIPLE INDICATORS" in draft.narrative
        assert draft.sections.get("alert_count") == 3


class TestSARDraftManager:
    """Test SAR draft management workflow."""

    @pytest.fixture()
    def manager(self):
        return SARDraftManager()

    def test_generate_and_retrieve(self, manager):
        case = _make_case()
        alerts = [_make_alert()]
        draft = manager.generate_draft(case, alerts)

        retrieved = manager.get_draft(draft.draft_id)
        assert retrieved is not None
        assert retrieved.draft_id == draft.draft_id

    def test_pending_drafts(self, manager):
        case = _make_case()
        alerts = [_make_alert()]
        manager.generate_draft(case, alerts)

        pending = manager.get_pending_drafts()
        assert len(pending) == 1

    def test_update_status_workflow(self, manager):
        case = _make_case()
        alerts = [_make_alert()]
        draft = manager.generate_draft(case, alerts)

        # Review
        manager.update_status(draft.draft_id, SARDraftStatus.REVIEWED, "officer-001")
        draft = manager.get_draft(draft.draft_id)
        assert draft.status == SARDraftStatus.REVIEWED
        assert draft.reviewed_by == "officer-001"

        # Approve
        manager.update_status(draft.draft_id, SARDraftStatus.APPROVED)
        draft = manager.get_draft(draft.draft_id)
        assert draft.status == SARDraftStatus.APPROVED

        # File
        manager.update_status(draft.draft_id, SARDraftStatus.FILED)
        draft = manager.get_draft(draft.draft_id)
        assert draft.status == SARDraftStatus.FILED

        # No longer pending
        pending = manager.get_pending_drafts()
        assert len(pending) == 0
