"""Tests for the transaction pattern generator."""

from generators.transaction_generator import TransactionGenerator

DEFAULT_CONFIG = {
    "num_users": 50,
    "transactions_per_user_range": [5, 20],
    "amount_distribution": {"log_normal_mean": 4.5, "log_normal_std": 1.2},
    "fraud_injection_rate": 0.0,
    "structuring_injection_rate": 0.0,
    "velocity_anomaly_rate": 0.0,
    "type_weights": {
        "circle_contribution": 0.35,
        "circle_payout": 0.15,
        "remittance": 0.30,
        "fee": 0.15,
        "refund": 0.05,
    },
    "time_span_days": 30,
}


class TestTransactionGenerator:
    def test_deterministic_output(self):
        gen1 = TransactionGenerator(config=DEFAULT_CONFIG, seed=42)
        gen2 = TransactionGenerator(config=DEFAULT_CONFIG, seed=42)
        events1 = gen1.generate(num_transactions=100)
        events2 = gen2.generate(num_transactions=100)
        assert len(events1) == len(events2)

    def test_generates_initiated_events(self):
        gen = TransactionGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_transactions=50)
        initiated = [e for e in events if e["event_type"] == "transaction-initiated"]
        assert len(initiated) > 0

    def test_generates_completed_or_failed(self):
        gen = TransactionGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_transactions=50)
        completed = [e for e in events if e["event_type"] == "transaction-completed"]
        failed = [e for e in events if e["event_type"] == "transaction-failed"]
        assert len(completed) + len(failed) > 0

    def test_event_envelope_structure(self):
        gen = TransactionGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_transactions=10)
        for event in events:
            assert "event_id" in event
            assert "event_type" in event
            assert "payload" in event
