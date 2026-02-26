"""Transaction pattern generator with fraud injection."""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from .base import BaseGenerator
from .utils.distributions import generate_device_id, generate_ip_address, log_normal_sample
from .utils.geography import location_to_geo, random_us_location
from .utils.names import random_name


class TransactionGenerator(BaseGenerator):
    def generate(self, num_transactions: int = 10000) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        config = self.config

        num_users = config.get("num_users", 500)
        time_span = config.get("time_span_days", 90)
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        end_time = base_time + timedelta(days=time_span)

        # Create user pool
        users = []
        for _ in range(num_users):
            first, last = random_name()
            location = random_us_location()
            users.append(
                {
                    "user_id": self._uuid(),
                    "first_name": first,
                    "last_name": last,
                    "location": location,
                    "device_id": generate_device_id(),
                    "ip_address": generate_ip_address(),
                }
            )

        type_weights = config.get(
            "type_weights",
            {
                "circle_contribution": 0.35,
                "circle_payout": 0.15,
                "remittance": 0.30,
                "fee": 0.15,
                "refund": 0.05,
            },
        )
        amount_dist = config.get(
            "amount_distribution", {"log_normal_mean": 4.5, "log_normal_std": 1.2}
        )

        for _ in range(num_transactions):
            user = random.choice(users)
            txn_type = self._weighted_choice(type_weights)
            txn_time = self._random_datetime(base_time, end_time)
            amount = log_normal_sample(
                amount_dist["log_normal_mean"],
                amount_dist["log_normal_std"],
                min_val=1.0,
                max_val=50000.0,
            )
            correlation_id = self._uuid()
            txn_id = self._uuid()
            geo = location_to_geo(user["location"])

            # Fraud injection: structuring
            if random.random() < config.get("structuring_injection_rate", 0.0):
                amount = (
                    random.uniform(2800, 2999)
                    if random.random() < 0.5
                    else random.uniform(9500, 9999)
                )

            # Fraud injection: velocity spike
            is_velocity = random.random() < config.get("velocity_anomaly_rate", 0.0)
            if is_velocity:
                for _burst in range(random.randint(8, 15)):
                    burst_time = txn_time + timedelta(minutes=random.randint(1, 55))
                    burst_txn_id = self._uuid()
                    burst_amount = log_normal_sample(
                        amount_dist["log_normal_mean"],
                        amount_dist["log_normal_std"],
                        min_val=1.0,
                        max_val=5000.0,
                    )
                    events.extend(
                        self._make_transaction_events(
                            burst_txn_id,
                            user,
                            txn_type,
                            burst_amount,
                            burst_time,
                            correlation_id,
                            geo,
                        )
                    )
                continue

            events.extend(
                self._make_transaction_events(
                    txn_id,
                    user,
                    txn_type,
                    amount,
                    txn_time,
                    correlation_id,
                    geo,
                )
            )

            # Flag suspicious transactions
            if amount > 9000 or random.random() < config.get("fraud_injection_rate", 0.0):
                flag_time = txn_time + timedelta(seconds=random.randint(1, 60))
                events.append(
                    self._envelope(
                        "transaction-flagged",
                        "transaction-service",
                        {
                            "transaction_id": txn_id,
                            "flagged_at": flag_time.isoformat(),
                            "flag_type": random.choice(
                                ["fraud_suspicion", "aml_threshold", "velocity_limit"]
                            ),
                            "risk_score": random.randint(50, 95),
                            "flag_details": {
                                "rule_triggered": "amount_threshold"
                                if amount > 9000
                                else "pattern_match",
                                "description": f"Transaction amount ${amount:.2f} flagged",
                            },
                            "action_taken": random.choice(
                                ["blocked", "held_for_review", "allowed_with_flag"]
                            ),
                        },
                        timestamp=flag_time,
                        correlation_id=correlation_id,
                    )
                )

        events.sort(key=lambda e: e["timestamp"])
        return events

    def _make_transaction_events(
        self,
        txn_id: str,
        user: dict,
        txn_type: str,
        amount: float,
        txn_time: datetime,
        correlation_id: str,
        geo: dict,
    ) -> list[dict[str, Any]]:
        events = []
        source_type = random.choice(["stripe", "bank", "balance"])
        dest_type = random.choice(["stripe", "bank", "balance"])

        events.append(
            self._envelope(
                "transaction-initiated",
                "transaction-service",
                {
                    "transaction_id": txn_id,
                    "user_id": user["user_id"],
                    "type": txn_type,
                    "amount": self._decimal_str(amount),
                    "currency": "USD",
                    "source": {"type": source_type, "identifier": f"src_{user['user_id'][:8]}"},
                    "destination": {"type": dest_type, "identifier": f"dst_{self._uuid()[:8]}"},
                    "initiated_at": txn_time.isoformat(),
                    "ip_address": user["ip_address"],
                    "device_id": user["device_id"],
                    "geo_location": geo,
                },
                timestamp=txn_time,
                correlation_id=correlation_id,
            )
        )

        complete_time = txn_time + timedelta(seconds=random.randint(1, 120))
        if random.random() < 0.95:  # 95% success rate
            events.append(
                self._envelope(
                    "transaction-completed",
                    "transaction-service",
                    {
                        "transaction_id": txn_id,
                        "completed_at": complete_time.isoformat(),
                        "processor_reference": f"ch_{self._uuid()[:12]}",
                        "fees": {
                            "platform_fee": self._decimal_str(amount * 0.02),
                            "processor_fee": self._decimal_str(amount * 0.029 + 0.30),
                            "currency": "USD",
                        },
                        "net_amount": self._decimal_str(amount * 0.951),
                    },
                    timestamp=complete_time,
                    correlation_id=correlation_id,
                )
            )
        else:
            events.append(
                self._envelope(
                    "transaction-failed",
                    "transaction-service",
                    {
                        "transaction_id": txn_id,
                        "failed_at": complete_time.isoformat(),
                        "error_code": random.choice(
                            ["insufficient_funds", "card_declined", "network_error"]
                        ),
                        "error_message": "Transaction could not be processed",
                        "retry_eligible": random.choice([True, False]),
                    },
                    timestamp=complete_time,
                    correlation_id=correlation_id,
                )
            )

        return events
