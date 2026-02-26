"""Remittance flow generator for US-Haiti corridor."""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from .base import BaseGenerator
from .utils.distributions import (
    generate_device_id,
    generate_ip_address,
    seasonal_multiplier,
    weighted_amount,
)
from .utils.geography import random_haiti_location, random_us_location
from .utils.names import random_full_name, random_name, random_phone


class RemittanceGenerator(BaseGenerator):
    def generate(self, num_remittances: int = 5000) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        config = self.config

        num_senders = config.get("num_senders", 300)
        time_span = config.get("time_span_days", 90)
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        end_time = base_time + timedelta(days=time_span)

        exchange_rate = config.get("exchange_rate_base", 132.50)
        volatility = config.get("exchange_rate_volatility", 0.02)
        previous_rate = exchange_rate

        # Create sender pool
        senders = []
        for _ in range(num_senders):
            first, last = random_name()
            location = random_us_location()
            senders.append(
                {
                    "user_id": self._uuid(),
                    "first_name": first,
                    "last_name": last,
                    "location": location,
                    "device_id": generate_device_id(),
                    "ip_address": generate_ip_address(),
                    "typical_amount": random.choice([50, 100, 200, 300, 500]),
                }
            )

        amount_dist = config.get(
            "send_amount_distribution",
            {
                "common_amounts": [50, 100, 200, 300, 500],
                "common_amount_probability": 0.6,
                "random_mean": 200,
                "random_std": 150,
            },
        )
        delivery_weights = config.get(
            "delivery_method_weights",
            {
                "mobile_wallet": 0.45,
                "bank_deposit": 0.30,
                "cash_pickup_agent": 0.25,
            },
        )
        success_rate = config.get("success_rate", 0.95)
        processing_hours = config.get("processing_time_hours_mean", 24)

        # Generate exchange rate updates (daily)
        for day in range(time_span):
            rate_time = base_time + timedelta(days=day, hours=9)
            new_rate = previous_rate * (1 + random.uniform(-volatility, volatility))
            new_rate = max(100.0, min(200.0, new_rate))

            events.append(
                self._envelope(
                    "exchange-rate-updated",
                    "remittance-service",
                    {
                        "pair": "USD/HTG",
                        "rate": self._decimal_str(new_rate),
                        "source": "central_bank_feed",
                        "effective_at": rate_time.isoformat(),
                        "previous_rate": self._decimal_str(previous_rate),
                    },
                    timestamp=rate_time,
                )
            )
            previous_rate = new_rate
            exchange_rate = new_rate

        # Generate remittances
        for _ in range(num_remittances):
            sender = random.choice(senders)
            remit_time = self._random_datetime(base_time, end_time)
            correlation_id = self._uuid()
            remittance_id = self._uuid()

            # Apply seasonal patterns
            if config.get("seasonal_patterns", True):
                mult = seasonal_multiplier(remit_time)
                if random.random() > (1.0 / mult):
                    continue  # Skip some to reduce volume in off-season

            # Weekend spike
            if remit_time.weekday() >= 5:
                pass  # weekend, higher probability — keep it

            send_amount = weighted_amount(
                amount_dist["common_amounts"],
                amount_dist["common_amount_probability"],
                amount_dist["random_mean"],
                amount_dist["random_std"],
            )
            send_amount = round(send_amount, 2)
            current_rate = exchange_rate * (1 + random.uniform(-0.005, 0.005))
            receive_amount = round(send_amount * current_rate, 2)
            fee = round(max(2.99, send_amount * 0.02 + random.uniform(0, 2)), 2)

            recipient_name = random_full_name()
            recipient_phone = random_phone("HT")
            random_haiti_location()  # consume RNG state for deterministic output
            delivery_method = self._weighted_choice(delivery_weights)

            payload: dict[str, Any] = {
                "remittance_id": remittance_id,
                "sender_id": sender["user_id"],
                "recipient_name": recipient_name,
                "recipient_phone": recipient_phone,
                "recipient_country": "HT",
                "send_amount": self._decimal_str(send_amount),
                "send_currency": "USD",
                "receive_amount": self._decimal_str(receive_amount),
                "receive_currency": "HTG",
                "exchange_rate": self._decimal_str(current_rate),
                "delivery_method": delivery_method,
                "initiated_at": remit_time.isoformat(),
                "fee_amount": self._decimal_str(fee),
            }
            if delivery_method == "cash_pickup_agent":
                payload["agent_id"] = f"agent_{self._uuid()[:8]}"

            events.append(
                self._envelope(
                    "remittance-initiated",
                    "remittance-service",
                    payload,
                    timestamp=remit_time,
                    correlation_id=correlation_id,
                )
            )

            # Processing stages
            stages = ["compliance_check", "funds_captured", "partner_submitted", "in_transit"]
            stage_time = remit_time
            for stage in stages:
                stage_time += timedelta(hours=random.uniform(0.5, processing_hours / len(stages)))
                processing_payload: dict[str, Any] = {
                    "remittance_id": remittance_id,
                    "status": stage,
                    "updated_at": stage_time.isoformat(),
                }
                if stage == "partner_submitted":
                    processing_payload["processor_reference"] = f"ref_{self._uuid()[:10]}"
                events.append(
                    self._envelope(
                        "remittance-processing",
                        "remittance-service",
                        processing_payload,
                        timestamp=stage_time,
                        correlation_id=correlation_id,
                    )
                )

                # Possible failure during processing
                if stage == "compliance_check" and random.random() > success_rate:
                    events.append(
                        self._envelope(
                            "remittance-failed",
                            "remittance-service",
                            {
                                "remittance_id": remittance_id,
                                "failed_at": stage_time.isoformat(),
                                "failure_reason": "compliance_rejected",
                                "refund_status": "pending",
                            },
                            timestamp=stage_time,
                            correlation_id=correlation_id,
                        )
                    )
                    break
            else:
                # Completed
                complete_time = stage_time + timedelta(hours=random.uniform(1, 8))
                actual_rate = current_rate * (1 + random.uniform(-0.002, 0.002))
                actual_receive = round(send_amount * actual_rate, 2)

                events.append(
                    self._envelope(
                        "remittance-completed",
                        "remittance-service",
                        {
                            "remittance_id": remittance_id,
                            "completed_at": complete_time.isoformat(),
                            "actual_receive_amount": self._decimal_str(actual_receive),
                            "actual_exchange_rate": self._decimal_str(actual_rate),
                            "delivery_confirmation": {
                                "confirmed_by": delivery_method,
                                "confirmation_code": f"CONF{self._uuid()[:8].upper()}",
                            },
                        },
                        timestamp=complete_time,
                        correlation_id=correlation_id,
                    )
                )

        events.sort(key=lambda e: e["timestamp"])
        return events
