"""Tests for gold layer aggregation functions."""

import pytest

from src.pipeline.aggregations import (
    aggregate_circle_lifecycle,
    aggregate_compliance_reporting,
    aggregate_daily_transactions,
    aggregate_haiti_corridor,
    aggregate_platform_health,
    aggregate_user_risk,
)


@pytest.fixture
def transaction_events():
    return [
        {
            "event_id": "e1",
            "event_type": "transaction-initiated",
            "timestamp": "2026-01-15T14:00:00+00:00",
            "payload": {
                "transaction_id": "t1",
                "user_id": "user-1",
                "amount": "100.00",
                "currency": "USD",
                "recipient_id": "rec-1",
            },
        },
        {
            "event_id": "e2",
            "event_type": "transaction-initiated",
            "timestamp": "2026-01-15T15:00:00+00:00",
            "payload": {
                "transaction_id": "t2",
                "user_id": "user-1",
                "amount": "200.00",
                "currency": "USD",
                "recipient_id": "rec-2",
            },
        },
        {
            "event_id": "e3",
            "event_type": "transaction-initiated",
            "timestamp": "2026-01-16T10:00:00+00:00",
            "payload": {
                "transaction_id": "t3",
                "user_id": "user-2",
                "amount": "500.00",
                "currency": "USD",
            },
        },
    ]


@pytest.fixture
def circle_events():
    return [
        {
            "event_id": "c1",
            "event_type": "circle-created",
            "timestamp": "2026-01-10T10:00:00+00:00",
            "payload": {
                "circle_id": "circle-1",
                "organizer_id": "user-1",
                "contribution_amount": "100.00",
                "max_members": 5,
            },
        },
        {
            "event_id": "c2",
            "event_type": "circle-member-joined",
            "timestamp": "2026-01-11T10:00:00+00:00",
            "payload": {"circle_id": "circle-1", "user_id": "user-2"},
        },
        {
            "event_id": "c3",
            "event_type": "circle-member-joined",
            "timestamp": "2026-01-12T10:00:00+00:00",
            "payload": {"circle_id": "circle-1", "user_id": "user-3"},
        },
        {
            "event_id": "c4",
            "event_type": "circle-member-dropped",
            "timestamp": "2026-01-13T10:00:00+00:00",
            "payload": {"circle_id": "circle-1", "user_id": "user-3"},
        },
    ]


@pytest.fixture
def remittance_events():
    return [
        {
            "event_id": "r1",
            "event_type": "remittance-initiated",
            "timestamp": "2026-01-15T16:00:00+00:00",
            "payload": {
                "remittance_id": "rem-1",
                "sender_id": "user-1",
                "recipient_country": "HT",
                "send_amount": "200.00",
                "send_currency": "USD",
                "exchange_rate": "132.50",
            },
        },
        {
            "event_id": "r2",
            "event_type": "remittance-completed",
            "timestamp": "2026-01-15T17:00:00+00:00",
            "payload": {"remittance_id": "rem-1"},
        },
        {
            "event_id": "r3",
            "event_type": "remittance-initiated",
            "timestamp": "2026-01-15T18:00:00+00:00",
            "payload": {
                "remittance_id": "rem-2",
                "sender_id": "user-2",
                "recipient_country": "HT",
                "send_amount": "300.00",
                "send_currency": "USD",
                "exchange_rate": "133.00",
            },
        },
    ]


class TestDailyTransactionSummary:
    def test_basic_aggregation(self, transaction_events):
        results = aggregate_daily_transactions(transaction_events)
        assert len(results) == 2  # 2 user-day combinations

        # Find user-1 on 2026-01-15
        u1_day1 = next(
            r for r in results if r["user_id"] == "user-1" and r["date"] == "2026-01-15"
        )
        assert u1_day1["transaction_count"] == 2
        assert u1_day1["total_amount"] == 300.00
        assert u1_day1["average_amount"] == 150.00
        assert u1_day1["min_amount"] == 100.00
        assert u1_day1["max_amount"] == 200.00
        assert u1_day1["distinct_recipients"] == 2

    def test_empty_events(self):
        results = aggregate_daily_transactions([])
        assert results == []


class TestCircleLifecycleSummary:
    def test_circle_lifecycle(self, circle_events):
        results = aggregate_circle_lifecycle(circle_events)
        assert len(results) == 1

        circle = results[0]
        assert circle["circle_id"] == "circle-1"
        assert circle["member_count_original"] == 5
        # 1 (organizer) + 2 joined - 1 dropped = 2
        assert circle["member_count_current"] == 2
        assert circle["member_count_dropped"] == 1
        assert circle["expected_collected"] == 500.00  # 100 * 5

    def test_empty_events(self):
        results = aggregate_circle_lifecycle([])
        assert results == []


class TestUserRisk:
    def test_basic_aggregation(self, transaction_events):
        results = aggregate_user_risk(transaction_events)
        assert len(results) >= 1

    def test_with_fraud_scores(self, transaction_events):
        results = aggregate_user_risk(
            transaction_events,
            fraud_scores={"user-1": 0.85, "user-2": 0.3},
        )
        u1 = next(r for r in results if r["user_id"] == "user-1")
        assert u1["fraud_score"] == 0.85


class TestComplianceReporting:
    def test_ctr_eligible_transactions(self):
        events = [
            {
                "event_id": "e1",
                "event_type": "transaction-initiated",
                "timestamp": "2026-01-15T14:00:00+00:00",
                "payload": {"amount": "15000.00"},
            },
            {
                "event_id": "e2",
                "event_type": "transaction-initiated",
                "timestamp": "2026-01-15T15:00:00+00:00",
                "payload": {"amount": "5000.00"},
            },
        ]
        results = aggregate_compliance_reporting(events)
        assert len(results) == 1
        day = results[0]
        assert day["ctr_filing_count"] == 1  # Only the $15K transaction
        assert day["ctr_total_amount"] == 15000.00


class TestPlatformHealth:
    def test_aggregation(self, transaction_events):
        session_events = [
            {
                "event_id": "s1",
                "event_type": "session-started",
                "timestamp": "2026-01-15T13:00:00+00:00",
                "payload": {"session_id": "sess-1", "user_id": "user-1"},
            },
        ]
        all_events = transaction_events + session_events
        results = aggregate_platform_health(all_events)
        assert len(results) >= 1

        day1 = next(r for r in results if r["date"] == "2026-01-15")
        assert day1["sessions"] == 1
        assert day1["transaction_count"] == 2
        assert day1["active_users"] >= 1


class TestHaitiCorridor:
    def test_corridor_aggregation(self, remittance_events):
        results = aggregate_haiti_corridor(remittance_events)
        assert len(results) >= 1

        # Check a corridor has data
        corridors = [r for r in results if r["corridor"].endswith("->HT")]
        assert len(corridors) >= 1
        corridor = corridors[0]
        assert corridor["remittance_count"] >= 1
        assert corridor["total_volume_usd"] > 0

    def test_delivery_success_rate(self, remittance_events):
        results = aggregate_haiti_corridor(remittance_events)
        # At least one corridor should have delivery data
        corridors_with_delivery = [
            r for r in results if r["delivery_success_rate"] > 0
        ]
        assert len(corridors_with_delivery) >= 1
