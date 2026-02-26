"""Validate that every generated event conforms to its JSON Schema."""

from pathlib import Path

import pytest

from generators.circle_generator import CircleGenerator
from generators.remittance_generator import RemittanceGenerator
from generators.session_generator import SessionGenerator
from generators.transaction_generator import TransactionGenerator
from src.shared.schemas import validate_event

CONTRACTS_PATH = str(Path(__file__).parent.parent.parent.parent / "trebanx-contracts" / "schemas")


class TestCircleSchemaConformance:
    @pytest.fixture(scope="class")
    def circle_events(self):
        config = {
            "member_range": [5, 8],
            "contribution_range": [50.0, 200.0],
            "frequency_weights": {"weekly": 0.3, "biweekly": 0.3, "monthly": 0.4},
            "late_payment_rate": 0.1,
            "late_payment_days_mean": 3,
            "late_payment_days_std": 2,
            "miss_payment_rate": 0.05,
            "member_drop_rate": 0.03,
            "circle_failure_rate": 0.05,
            "collusion_rate": 0.0,
            "fraud_injection_rate": 0.0,
        }
        gen = CircleGenerator(config=config, seed=42)
        return gen.generate(num_circles=50)

    def test_all_circle_events_valid(self, circle_events):
        failures = []
        for i, event in enumerate(circle_events):
            try:
                validate_event(event, CONTRACTS_PATH)
            except Exception as e:
                failures.append(f"Event {i} ({event.get('event_type')}): {e}")
        assert len(failures) == 0, "Schema validation failures:\n" + "\n".join(failures[:10])


class TestTransactionSchemaConformance:
    @pytest.fixture(scope="class")
    def transaction_events(self):
        config = {
            "num_users": 50,
            "transactions_per_user_range": [5, 20],
            "amount_distribution": {"log_normal_mean": 4.5, "log_normal_std": 1.2},
            "fraud_injection_rate": 0.0,
            "structuring_injection_rate": 0.0,
            "velocity_anomaly_rate": 0.0,
            "type_weights": {
                "circle_contribution": 0.3,
                "circle_payout": 0.2,
                "remittance": 0.3,
                "fee": 0.1,
                "refund": 0.1,
            },
            "time_span_days": 30,
        }
        gen = TransactionGenerator(config=config, seed=42)
        return gen.generate(num_transactions=500)

    def test_all_transaction_events_valid(self, transaction_events):
        failures = []
        for i, event in enumerate(transaction_events):
            try:
                validate_event(event, CONTRACTS_PATH)
            except Exception as e:
                failures.append(f"Event {i} ({event.get('event_type')}): {e}")
        assert len(failures) == 0, "Schema validation failures:\n" + "\n".join(failures[:10])


class TestSessionSchemaConformance:
    @pytest.fixture(scope="class")
    def session_events(self):
        config = {
            "num_users": 50,
            "sessions_per_user_range": [5, 20],
            "session_duration_distribution": {"log_normal_mean": 6.0, "log_normal_std": 1.0},
            "actions_per_session_distribution": {"log_normal_mean": 2.0, "log_normal_std": 0.8},
            "anomaly_injection_rate": 0.0,
            "account_takeover_injection_rate": 0.0,
            "device_diversity": 2,
            "location_diversity": 2,
            "time_span_days": 30,
        }
        gen = SessionGenerator(config=config, seed=42)
        return gen.generate(num_sessions=500)

    def test_all_session_events_valid(self, session_events):
        failures = []
        for i, event in enumerate(session_events):
            try:
                validate_event(event, CONTRACTS_PATH)
            except Exception as e:
                failures.append(f"Event {i} ({event.get('event_type')}): {e}")
        assert len(failures) == 0, "Schema validation failures:\n" + "\n".join(failures[:10])


class TestRemittanceSchemaConformance:
    @pytest.fixture(scope="class")
    def remittance_events(self):
        config = {
            "num_senders": 50,
            "remittances_per_sender_range": [1, 10],
            "send_amount_distribution": {
                "common_amounts": [50, 100, 200],
                "common_amount_probability": 0.6,
                "random_mean": 200,
                "random_std": 100,
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
        gen = RemittanceGenerator(config=config, seed=42)
        return gen.generate(num_remittances=500)

    def test_all_remittance_events_valid(self, remittance_events):
        failures = []
        for i, event in enumerate(remittance_events):
            try:
                validate_event(event, CONTRACTS_PATH)
            except Exception as e:
                failures.append(f"Event {i} ({event.get('event_type')}): {e}")
        assert len(failures) == 0, "Schema validation failures:\n" + "\n".join(failures[:10])
