"""Tests for the circle lifecycle generator."""

from generators.circle_generator import CircleGenerator

DEFAULT_CONFIG = {
    "member_range": [5, 10],
    "contribution_range": [50.0, 200.0],
    "frequency_weights": {"weekly": 0.2, "biweekly": 0.3, "monthly": 0.5},
    "late_payment_rate": 0.10,
    "late_payment_days_mean": 3,
    "late_payment_days_std": 2,
    "miss_payment_rate": 0.05,
    "member_drop_rate": 0.03,
    "circle_failure_rate": 0.05,
    "collusion_rate": 0.0,
    "fraud_injection_rate": 0.0,
}


class TestCircleGenerator:
    def test_deterministic_output(self):
        gen1 = CircleGenerator(config=DEFAULT_CONFIG, seed=42)
        events1 = gen1.generate(num_circles=3)
        gen2 = CircleGenerator(config=DEFAULT_CONFIG, seed=42)
        events2 = gen2.generate(num_circles=3)
        assert len(events1) == len(events2)
        for e1, e2 in zip(events1, events2, strict=True):
            assert e1["event_type"] == e2["event_type"]
            assert e1["event_id"] == e2["event_id"]

    def test_generates_circle_created(self):
        gen = CircleGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_circles=1)
        created = [e for e in events if e["event_type"] == "circle-created"]
        assert len(created) == 1

    def test_generates_member_joined(self):
        gen = CircleGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_circles=1)
        joined = [e for e in events if e["event_type"] == "circle-member-joined"]
        assert len(joined) >= DEFAULT_CONFIG["member_range"][0]

    def test_generates_contributions(self):
        gen = CircleGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_circles=1)
        contributions = [e for e in events if e["event_type"] == "circle-contribution-received"]
        assert len(contributions) > 0

    def test_generates_payout(self):
        gen = CircleGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_circles=1)
        payouts = [e for e in events if e["event_type"] == "circle-payout-executed"]
        assert len(payouts) > 0

    def test_event_envelope_structure(self):
        gen = CircleGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_circles=1)
        for event in events:
            assert "event_id" in event
            assert "event_type" in event
            assert "event_version" in event
            assert "timestamp" in event
            assert "source_service" in event
            assert "correlation_id" in event
            assert "payload" in event

    def test_zero_fraud_rate(self):
        config = {**DEFAULT_CONFIG, "fraud_injection_rate": 0.0, "collusion_rate": 0.0}
        gen = CircleGenerator(config=config, seed=42)
        events = gen.generate(num_circles=5)
        assert len(events) > 0

    def test_contribution_amounts_in_range(self):
        gen = CircleGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_circles=3)
        for event in events:
            if event["event_type"] == "circle-created":
                amount = float(event["payload"]["contribution_amount"])
                assert (
                    DEFAULT_CONFIG["contribution_range"][0]
                    <= amount
                    <= DEFAULT_CONFIG["contribution_range"][1]
                )
