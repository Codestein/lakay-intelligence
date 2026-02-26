"""Tests for the remittance flow generator."""

from generators.remittance_generator import RemittanceGenerator

DEFAULT_CONFIG = {
    "num_senders": 50,
    "remittances_per_sender_range": [1, 10],
    "send_amount_distribution": {
        "common_amounts": [50, 100, 200, 300, 500],
        "common_amount_probability": 0.6,
        "random_mean": 200,
        "random_std": 150,
    },
    "exchange_rate_base": 132.50,
    "exchange_rate_volatility": 0.02,
    "delivery_method_weights": {
        "mobile_wallet": 0.5,
        "bank_deposit": 0.3,
        "cash_pickup_agent": 0.2,
    },
    "success_rate": 0.95,
    "processing_time_hours_mean": 24,
    "seasonal_patterns": False,
    "fraud_injection_rate": 0.0,
    "time_span_days": 30,
}


class TestRemittanceGenerator:
    def test_deterministic_output(self):
        gen1 = RemittanceGenerator(config=DEFAULT_CONFIG, seed=42)
        events1 = gen1.generate(num_remittances=50)
        gen2 = RemittanceGenerator(config=DEFAULT_CONFIG, seed=42)
        events2 = gen2.generate(num_remittances=50)
        assert len(events1) == len(events2)

    def test_generates_initiated_events(self):
        gen = RemittanceGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_remittances=20)
        initiated = [e for e in events if e["event_type"] == "remittance-initiated"]
        assert len(initiated) > 0

    def test_generates_processing_events(self):
        gen = RemittanceGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_remittances=20)
        processing = [e for e in events if e["event_type"] == "remittance-processing"]
        assert len(processing) > 0

    def test_generates_exchange_rate_events(self):
        gen = RemittanceGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_remittances=10)
        rates = [e for e in events if e["event_type"] == "exchange-rate-updated"]
        assert len(rates) > 0

    def test_event_envelope_structure(self):
        gen = RemittanceGenerator(config=DEFAULT_CONFIG, seed=42)
        events = gen.generate(num_remittances=10)
        for event in events:
            assert "event_id" in event
            assert "event_type" in event
            assert "payload" in event
