"""Tests for compliance reporting pipeline."""

import pytest

from src.pipeline.compliance_reports import (
    AuditReport,
    ComplianceSummary,
    CTRReport,
    SARReport,
    _generate_sar_narrative,
)
from datetime import UTC, datetime


@pytest.fixture
def date_range():
    return (
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 31, tzinfo=UTC),
    )


class TestCTRReport:
    def test_init(self, date_range):
        report = CTRReport("ctr-001", date_range)
        assert report.report_id == "ctr-001"
        assert report.total_amount == 0.0
        assert report.filing_count == 0

    def test_to_dict(self, date_range):
        report = CTRReport("ctr-001", date_range)
        report.transactions = [
            {"user_id": "u1", "date": "2026-01-15", "total_amount": 15000.00}
        ]
        report.total_amount = 15000.00
        report.filing_count = 1

        d = report.to_dict()
        assert d["report_type"] == "ctr"
        assert d["summary"]["total_transactions"] == 1
        assert d["summary"]["total_amount"] == 15000.00

    def test_to_csv(self, date_range):
        report = CTRReport("ctr-001", date_range)
        report.transactions = [
            {"user_id": "u1", "amount": "15000.00", "filing_status": "pending"}
        ]
        csv_str = report.to_csv()
        assert "user_id" in csv_str
        assert "15000.00" in csv_str

    def test_empty_csv(self, date_range):
        report = CTRReport("ctr-001", date_range)
        assert report.to_csv() == ""


class TestSARReport:
    def test_init(self, date_range):
        report = SARReport("sar-001", date_range)
        assert report.report_id == "sar-001"
        assert report.cases == []
        assert report.narratives == []

    def test_to_dict(self, date_range):
        report = SARReport("sar-001", date_range)
        report.cases = [{"alert_id": "a1", "severity": "high"}]
        report.narratives = ["Suspicious activity for customer..."]

        d = report.to_dict()
        assert d["report_type"] == "sar"
        assert d["summary"]["total_cases"] == 1
        assert d["summary"]["narratives_generated"] == 1


class TestComplianceSummary:
    def test_init(self):
        summary = ComplianceSummary("sum-001", "monthly")
        assert summary.period == "monthly"
        assert summary.filing_counts == {"ctr": 0, "sar": 0}

    def test_to_dict(self):
        summary = ComplianceSummary("sum-001", "monthly")
        summary.alert_volume = {"fraud": 10, "compliance": 5}
        summary.filing_counts = {"ctr": 3, "sar": 1}

        d = summary.to_dict()
        assert d["report_type"] == "compliance_summary"
        assert d["alert_volume"]["fraud"] == 10
        assert d["filing_counts"]["ctr"] == 3


class TestAuditReport:
    def test_init(self, date_range):
        report = AuditReport("audit-001", date_range)
        assert report.monitoring_rules == []

    def test_to_dict(self, date_range):
        report = AuditReport("audit-001", date_range)
        report.monitoring_rules = [
            {"rule_name": "CTR Threshold", "status": "active"}
        ]
        report.alert_statistics = {"total_alerts": 100, "resolved": 80}

        d = report.to_dict()
        assert d["report_type"] == "audit"
        assert len(d["monitoring_rules"]) == 1
        assert d["alert_statistics"]["total_alerts"] == 100


class TestSARNarrative:
    def test_narrative_generation(self):
        class MockAlert:
            user_id = "user-123"
            severity = "high"
            created_at = datetime(2026, 1, 15, tzinfo=UTC)
            details = {
                "rules_triggered": ["structuring_near_3k", "velocity_count_1h"],
                "risk_score": 0.85,
            }

        narrative = _generate_sar_narrative(MockAlert())
        assert "user-123" in narrative
        assert "high" in narrative
        assert "structuring_near_3k" in narrative
        assert "0.85" in narrative
        assert "FinCEN" in narrative

    def test_narrative_without_details(self):
        class MockAlert:
            user_id = "user-456"
            severity = "critical"
            created_at = datetime(2026, 2, 1, tzinfo=UTC)
            details = {}

        narrative = _generate_sar_narrative(MockAlert())
        assert "user-456" in narrative
        assert "critical" in narrative
