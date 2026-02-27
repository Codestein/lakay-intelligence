"""Tests for CTR threshold tracking and auto-flagging (Task 8.2).

Covers all CTR regulatory scenarios:
  C-1: Single transaction CTR
  C-2: Aggregated CTR (multiple transactions, same business day)
  C-3: Just-below threshold
  C-4: Cross-day boundary
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from src.domains.compliance.config import ComplianceConfig
from src.domains.compliance.ctr import CTRTracker, _get_business_date
from src.domains.compliance.models import (
    ComplianceTransaction,
    RecommendedAction,
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


class TestBusinessDateBoundary:
    """Verify correct business day boundary handling."""

    def test_same_day_transactions(self):
        # Two transactions at 10 AM and 3 PM same day
        base = datetime(2024, 6, 15, 15, 0, tzinfo=UTC)  # 10 AM EST
        d1 = _get_business_date(base, tz_offset_hours=-5.0)
        d2 = _get_business_date(base + timedelta(hours=5), tz_offset_hours=-5.0)
        assert d1 == d2

    def test_cross_midnight_different_days(self):
        """Scenario C-4: Transactions at 11 PM and 1 AM are different days."""
        # 11 PM EST = 4 AM UTC next day
        day1_11pm = datetime(2024, 6, 16, 4, 0, tzinfo=UTC)  # 11 PM EST June 15
        day2_1am = datetime(2024, 6, 16, 6, 0, tzinfo=UTC)   # 1 AM EST June 16

        d1 = _get_business_date(day1_11pm, tz_offset_hours=-5.0)
        d2 = _get_business_date(day2_1am, tz_offset_hours=-5.0)
        assert d1 != d2  # Different business days


class TestScenarioC1SingleTransactionCTR:
    """Scenario C-1: User sends a $12,000 remittance.

    Expected: CTR alert generated immediately, filing package assembled,
    priority = urgent.
    """

    @pytest.fixture()
    def tracker(self):
        return CTRTracker()

    def test_single_12000_transaction_triggers_ctr(self, tracker):
        tx = _make_tx(
            transaction_id="tx-single-12k",
            user_id="user-c1",
            amount=12_000.0,
        )
        alerts = tracker.process_transaction(tx)

        # CTR alert generated
        assert len(alerts) == 1
        assert alerts[0].recommended_action == RecommendedAction.FILE_CTR

        # Filing package assembled
        pending = tracker.get_pending_obligations()
        assert len(pending) == 1
        assert pending[0].user_id == "user-c1"
        assert pending[0].total_amount == 12_000.0
        assert pending[0].transaction_count == 1
        assert pending[0].status == "pending"

    def test_filing_package_has_required_fields(self, tracker):
        tx = _make_tx(
            transaction_id="tx-12k",
            user_id="user-c1",
            amount=12_000.0,
        )
        tracker.process_transaction(tx)
        packages = tracker.get_pending_obligations()
        pkg = packages[0]

        assert pkg.customer_info is not None
        assert pkg.institution_info["name"] == "Trebanx"
        assert "filing_deadline" in pkg.filing_metadata
        assert "regulatory_basis" in pkg.filing_metadata


class TestScenarioC2AggregatedCTR:
    """Scenario C-2: User makes 4 transactions in one day: $3,000, $2,500,
    $2,800, $2,200 (total: $10,500).

    Expected: CTR alert generated when cumulative total crosses $10,000,
    all 4 transactions included in the filing package.
    """

    @pytest.fixture()
    def tracker(self):
        return CTRTracker()

    def test_aggregated_transactions_trigger_ctr(self, tracker):
        # Use a fixed midday timestamp so all txns fall on the same business day
        base = datetime(2024, 7, 10, 18, 0, tzinfo=UTC)  # 1 PM EST
        amounts = [3_000.0, 2_500.0, 2_800.0, 2_200.0]
        all_alerts = []

        for i, amount in enumerate(amounts):
            tx = _make_tx(
                transaction_id=f"tx-c2-{i}",
                user_id="user-c2",
                amount=amount,
                initiated_at=base + timedelta(minutes=i * 30),
            )
            alerts = tracker.process_transaction(tx)
            all_alerts.extend(alerts)

        # CTR alert should fire on the 4th transaction (cumulative = 10,500)
        ctr_alerts = [
            a for a in all_alerts
            if a.recommended_action == RecommendedAction.FILE_CTR
        ]
        assert len(ctr_alerts) == 1

        # All 4 transactions in filing package
        pending = tracker.get_pending_obligations()
        assert len(pending) == 1
        assert pending[0].transaction_count == 4
        assert pending[0].total_amount == 10_500.0

    def test_pre_threshold_warnings_fire_before_ctr(self, tracker):
        # Use a fixed midday timestamp so all txns fall on the same business day
        base = datetime(2024, 7, 10, 18, 0, tzinfo=UTC)  # 1 PM EST
        # First 3 txns: $3,000 + $2,500 + $2,800 = $8,300 → should trigger $8,000 warning
        tx1 = _make_tx(
            transaction_id="tx-c2-0", user_id="user-c2",
            amount=3_000.0, initiated_at=base,
        )
        alerts1 = tracker.process_transaction(tx1)
        assert len(alerts1) == 0  # $3,000 — no warning yet

        tx2 = _make_tx(
            transaction_id="tx-c2-1", user_id="user-c2",
            amount=2_500.0, initiated_at=base + timedelta(minutes=30),
        )
        alerts2 = tracker.process_transaction(tx2)
        assert len(alerts2) == 0  # $5,500 — no warning yet

        tx3 = _make_tx(
            transaction_id="tx-c2-2", user_id="user-c2",
            amount=2_800.0, initiated_at=base + timedelta(minutes=60),
        )
        alerts3 = tracker.process_transaction(tx3)
        # $8,300 — should trigger $8,000 pre-threshold warning
        assert len(alerts3) >= 1
        assert alerts3[0].recommended_action == RecommendedAction.ENHANCED_MONITORING


class TestScenarioC3JustBelowThreshold:
    """Scenario C-3: User makes a single $9,999 transaction.

    Expected: No CTR alert, but pre-threshold warning generated.
    """

    @pytest.fixture()
    def tracker(self):
        return CTRTracker()

    def test_9999_no_ctr_but_warning(self, tracker):
        tx = _make_tx(
            transaction_id="tx-c3",
            user_id="user-c3",
            amount=9_999.0,
        )
        alerts = tracker.process_transaction(tx)

        # No CTR filing alert
        ctr_alerts = [
            a for a in alerts
            if a.recommended_action == RecommendedAction.FILE_CTR
        ]
        assert len(ctr_alerts) == 0

        # Pre-threshold warning should exist
        warnings = [
            a for a in alerts
            if a.recommended_action == RecommendedAction.ENHANCED_MONITORING
        ]
        assert len(warnings) == 1

        # No filing package
        assert len(tracker.get_pending_obligations()) == 0


class TestScenarioC4CrossDayBoundary:
    """Scenario C-4: User transacts $6,000 at 11 PM and $5,000 at 1 AM.

    Expected: Two different business days, no CTR threshold met on either.
    """

    @pytest.fixture()
    def tracker(self):
        return CTRTracker()

    def test_cross_day_no_ctr(self, tracker):
        # 11 PM EST = 4 AM UTC next day
        est = timezone(timedelta(hours=-5))
        day1_11pm = datetime(2024, 6, 15, 23, 0, tzinfo=est).astimezone(UTC)
        day2_1am = datetime(2024, 6, 16, 1, 0, tzinfo=est).astimezone(UTC)

        tx1 = _make_tx(
            transaction_id="tx-c4-1",
            user_id="user-c4",
            amount=6_000.0,
            initiated_at=day1_11pm,
        )
        tx2 = _make_tx(
            transaction_id="tx-c4-2",
            user_id="user-c4",
            amount=5_000.0,
            initiated_at=day2_1am,
        )

        alerts1 = tracker.process_transaction(tx1, tz_offset_hours=-5.0)
        alerts2 = tracker.process_transaction(tx2, tz_offset_hours=-5.0)

        # No CTR threshold met on either day
        all_ctr = [
            a for a in alerts1 + alerts2
            if a.recommended_action == RecommendedAction.FILE_CTR
        ]
        assert len(all_ctr) == 0

        # Verify separate daily totals
        d1 = _get_business_date(day1_11pm, -5.0)
        d2 = _get_business_date(day2_1am, -5.0)
        assert d1 != d2

        total1 = tracker.get_daily_total("user-c4", d1)
        total2 = tracker.get_daily_total("user-c4", d2)
        assert total1.cumulative_amount == 6_000.0
        assert total2.cumulative_amount == 5_000.0


class TestCTRFilingWorkflow:
    """Test the filing package assembly and status tracking."""

    @pytest.fixture()
    def tracker(self):
        return CTRTracker()

    def test_filing_package_assembled_on_threshold(self, tracker):
        tx = _make_tx(user_id="user-filing", amount=11_000.0)
        tracker.process_transaction(tx)

        packages = tracker.get_pending_obligations()
        assert len(packages) == 1
        assert packages[0].status == "pending"

    def test_mark_filed(self, tracker):
        tx = _make_tx(user_id="user-filing", amount=11_000.0)
        tracker.process_transaction(tx)

        packages = tracker.get_pending_obligations()
        pkg_id = packages[0].package_id

        result = tracker.mark_filed(pkg_id, "CTR-2024-001234")
        assert result is not None
        assert result.status == "filed"
        assert result.filing_reference == "CTR-2024-001234"
        assert result.filed_at is not None

        # No longer in pending
        assert len(tracker.get_pending_obligations()) == 0

        # Still in history
        assert len(tracker.get_filing_history()) == 1

    def test_no_duplicate_alert_on_additional_transactions(self, tracker):
        """Once CTR threshold is met, additional transactions don't generate
        duplicate CTR alerts."""
        now = datetime.now(UTC)
        tx1 = _make_tx(
            transaction_id="tx-dup-1", user_id="user-dup",
            amount=10_000.0, initiated_at=now,
        )
        tx2 = _make_tx(
            transaction_id="tx-dup-2", user_id="user-dup",
            amount=2_000.0, initiated_at=now + timedelta(hours=1),
        )

        alerts1 = tracker.process_transaction(tx1)
        alerts2 = tracker.process_transaction(tx2)

        ctr_alerts1 = [a for a in alerts1 if a.recommended_action == RecommendedAction.FILE_CTR]
        ctr_alerts2 = [a for a in alerts2 if a.recommended_action == RecommendedAction.FILE_CTR]

        assert len(ctr_alerts1) == 1  # First CTR alert
        assert len(ctr_alerts2) == 0  # No duplicate

    def test_non_cash_equivalent_not_tracked(self, tracker):
        tx = _make_tx(
            user_id="user-non-cash",
            amount=15_000.0,
            transaction_type="account_verification",
        )
        alerts = tracker.process_transaction(tx)
        assert len(alerts) == 0
        daily = tracker.get_daily_total("user-non-cash")
        assert daily.cumulative_amount == 0.0
