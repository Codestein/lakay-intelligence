"""Circle lifecycle simulator — generates complete sou-sou circle event streams."""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from .base import BaseGenerator
from .utils.distributions import generate_device_id, generate_ip_address
from .utils.geography import location_to_geo, random_us_location
from .utils.names import random_name


class CircleGenerator(BaseGenerator):
    def generate(self, num_circles: int = 100) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        base_time = datetime(2026, 1, 1, tzinfo=UTC)

        for i in range(num_circles):
            circle_start = base_time + timedelta(
                days=random.randint(0, 60), hours=random.randint(8, 20)
            )
            circle_events = self._generate_circle(circle_start, i)
            events.extend(circle_events)

        events.sort(key=lambda e: e["timestamp"])
        return events

    def _generate_circle(self, start_time: datetime, circle_index: int) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        config = self.config

        circle_id = self._uuid()
        organizer_id = self._uuid()
        correlation_id = self._uuid()
        member_range = config.get("member_range", [5, 12])
        num_members = random.randint(member_range[0], member_range[1])
        contrib_range = config.get("contribution_range", [50.0, 300.0])
        contribution_amount = round(random.uniform(contrib_range[0], contrib_range[1]), 2)
        frequency = self._weighted_choice(config.get("frequency_weights", {"monthly": 1.0}))
        frequency_days = {"weekly": 7, "biweekly": 14, "monthly": 30}[frequency]

        is_collusion = random.random() < config.get("collusion_rate", 0.0)
        # Consume random state for fraud flag to keep deterministic sequence
        random.random()

        # Circle created
        events.append(
            self._envelope(
                "circle-created",
                "circle-service",
                {
                    "circle_id": circle_id,
                    "organizer_id": organizer_id,
                    "name": f"Lakay Circle #{circle_index + 1}",
                    "contribution_amount": self._decimal_str(contribution_amount),
                    "currency": "USD",
                    "frequency": frequency,
                    "max_members": min(20, max(num_members, 5)),
                    "rotation_order": random.choice(["sequential", "random"]),
                    "start_date": (start_time + timedelta(days=7)).strftime("%Y-%m-%d"),
                    "status": "pending",
                },
                timestamp=start_time,
                correlation_id=correlation_id,
            )
        )

        # Members join
        members: list[dict[str, Any]] = []
        join_time = start_time + timedelta(hours=random.randint(1, 48))
        for pos in range(num_members):
            user_id = self._uuid()
            location = random_us_location()
            first, last = random_name()
            members.append(
                {
                    "user_id": user_id,
                    "position": pos + 1,
                    "active": True,
                    "first_name": first,
                    "last_name": last,
                    "location": location,
                    "device_id": generate_device_id(),
                    "ip_address": generate_ip_address(),
                }
            )
            events.append(
                self._envelope(
                    "circle-member-joined",
                    "circle-service",
                    {
                        "circle_id": circle_id,
                        "user_id": user_id,
                        "position": pos + 1,
                        "joined_at": join_time.isoformat(),
                        "verification_status": "verified" if random.random() > 0.1 else "pending",
                    },
                    timestamp=join_time,
                    correlation_id=correlation_id,
                )
            )
            join_time += timedelta(hours=random.randint(1, 24))

        # Run cycles
        cycle_start = start_time + timedelta(days=7)
        active_members = [m for m in members if m["active"]]
        total_cycles = len(active_members)
        rotation = list(range(len(active_members)))
        random.shuffle(rotation)

        force_fail = random.random() < config.get("circle_failure_rate", 0.05)
        fail_at_cycle = random.randint(2, max(2, total_cycles - 1)) if force_fail else None

        for cycle in range(total_cycles):
            cycle_num = cycle + 1
            cycle_time = cycle_start + timedelta(days=cycle * frequency_days)
            active_members = [m for m in members if m["active"]]

            if len(active_members) < 3:
                events.append(
                    self._envelope(
                        "circle-failed",
                        "circle-service",
                        {
                            "circle_id": circle_id,
                            "failed_at": cycle_time.isoformat(),
                            "reason": "insufficient_members",
                            "cycles_completed": cycle,
                            "cycles_planned": total_cycles,
                            "members_at_failure": len(active_members),
                        },
                        timestamp=cycle_time,
                        correlation_id=correlation_id,
                    )
                )
                return events

            if fail_at_cycle and cycle_num >= fail_at_cycle:
                events.append(
                    self._envelope(
                        "circle-failed",
                        "circle-service",
                        {
                            "circle_id": circle_id,
                            "failed_at": cycle_time.isoformat(),
                            "reason": "excessive_defaults",
                            "cycles_completed": cycle,
                            "cycles_planned": total_cycles,
                            "members_at_failure": len(active_members),
                        },
                        timestamp=cycle_time,
                        correlation_id=correlation_id,
                    )
                )
                return events

            # Contributions
            for member in active_members:
                pay_time = cycle_time + timedelta(hours=random.randint(0, 48))
                days_late = 0

                if random.random() < config.get("miss_payment_rate", 0.05):
                    events.append(
                        self._envelope(
                            "circle-contribution-missed",
                            "circle-service",
                            {
                                "circle_id": circle_id,
                                "user_id": member["user_id"],
                                "cycle_number": cycle_num,
                                "due_date": cycle_time.strftime("%Y-%m-%d"),
                                "amount_due": self._decimal_str(contribution_amount),
                                "currency": "USD",
                                "consecutive_misses": 1,
                            },
                            timestamp=pay_time,
                            correlation_id=correlation_id,
                        )
                    )
                    if random.random() < config.get("member_drop_rate", 0.03) * 3:
                        member["active"] = False
                        events.append(
                            self._envelope(
                                "circle-member-dropped",
                                "circle-service",
                                {
                                    "circle_id": circle_id,
                                    "user_id": member["user_id"],
                                    "reason": "missed_payments",
                                    "dropped_at": pay_time.isoformat(),
                                    "payments_made": cycle,
                                    "payments_owed": total_cycles - cycle,
                                },
                                timestamp=pay_time,
                                correlation_id=correlation_id,
                            )
                        )
                    continue

                if random.random() < config.get("late_payment_rate", 0.10):
                    mean = config.get("late_payment_days_mean", 3)
                    std = config.get("late_payment_days_std", 2)
                    days_late = max(1, int(random.gauss(mean, std)))
                    pay_time += timedelta(days=days_late)

                contribution_id = self._uuid()
                payment_method = random.choice(["stripe", "bank_transfer", "balance"])
                source_type_map = {
                    "stripe": "stripe",
                    "bank_transfer": "bank",
                    "balance": "balance",
                }
                geo = location_to_geo(member["location"])

                events.append(
                    self._envelope(
                        "circle-contribution-received",
                        "circle-service",
                        {
                            "circle_id": circle_id,
                            "user_id": member["user_id"],
                            "contribution_id": contribution_id,
                            "amount": self._decimal_str(contribution_amount),
                            "currency": "USD",
                            "cycle_number": cycle_num,
                            "payment_method": payment_method,
                            "paid_at": pay_time.isoformat(),
                            "days_late": days_late,
                        },
                        timestamp=pay_time,
                        correlation_id=correlation_id,
                    )
                )

                # Transaction events for the contribution
                txn_id = self._uuid()
                events.append(
                    self._envelope(
                        "transaction-initiated",
                        "transaction-service",
                        {
                            "transaction_id": txn_id,
                            "user_id": member["user_id"],
                            "type": "circle_contribution",
                            "amount": self._decimal_str(contribution_amount),
                            "currency": "USD",
                            "source": {
                                "type": source_type_map[payment_method],
                                "identifier": f"src_{member['user_id'][:8]}",
                            },
                            "destination": {
                                "type": "balance",
                                "identifier": f"circle_{circle_id[:8]}",
                            },
                            "metadata": {"circle_id": circle_id, "cycle_number": cycle_num},
                            "initiated_at": pay_time.isoformat(),
                            "ip_address": member["ip_address"],
                            "device_id": member["device_id"],
                            "geo_location": geo,
                        },
                        timestamp=pay_time,
                        correlation_id=correlation_id,
                    )
                )

                complete_time = pay_time + timedelta(seconds=random.randint(1, 30))
                events.append(
                    self._envelope(
                        "transaction-completed",
                        "transaction-service",
                        {
                            "transaction_id": txn_id,
                            "completed_at": complete_time.isoformat(),
                            "processor_reference": f"ch_{self._uuid()[:12]}",
                            "fees": {
                                "platform_fee": self._decimal_str(contribution_amount * 0.02),
                                "processor_fee": self._decimal_str(
                                    contribution_amount * 0.029 + 0.30
                                ),
                                "currency": "USD",
                            },
                            "net_amount": self._decimal_str(contribution_amount * 0.951),
                        },
                        timestamp=complete_time,
                        correlation_id=correlation_id,
                    )
                )

            # Payout
            active_members = [m for m in members if m["active"]]
            if active_members and cycle < len(active_members):
                recipient = active_members[cycle % len(active_members)]
                payout_amount = contribution_amount * len(active_members)
                payout_time = cycle_time + timedelta(
                    days=frequency_days - 1, hours=random.randint(10, 18)
                )
                payout_id = self._uuid()

                events.append(
                    self._envelope(
                        "circle-payout-executed",
                        "circle-service",
                        {
                            "circle_id": circle_id,
                            "recipient_id": recipient["user_id"],
                            "payout_id": payout_id,
                            "amount": self._decimal_str(payout_amount),
                            "currency": "USD",
                            "cycle_number": cycle_num,
                            "payout_method": random.choice(["stripe", "bank_transfer", "balance"]),
                            "executed_at": payout_time.isoformat(),
                        },
                        timestamp=payout_time,
                        correlation_id=correlation_id,
                    )
                )

                # Collusion: first recipient drops after payout
                if is_collusion and cycle == 0:
                    drop_time = payout_time + timedelta(days=random.randint(1, 3))
                    recipient["active"] = False
                    events.append(
                        self._envelope(
                            "circle-member-dropped",
                            "circle-service",
                            {
                                "circle_id": circle_id,
                                "user_id": recipient["user_id"],
                                "reason": "voluntary",
                                "dropped_at": drop_time.isoformat(),
                                "payments_made": 1,
                                "payments_owed": total_cycles - 1,
                            },
                            timestamp=drop_time,
                            correlation_id=correlation_id,
                        )
                    )

            # Random member drop
            for member in active_members:
                if random.random() < config.get("member_drop_rate", 0.03):
                    member["active"] = False
                    drop_time = cycle_time + timedelta(days=random.randint(1, frequency_days))
                    events.append(
                        self._envelope(
                            "circle-member-dropped",
                            "circle-service",
                            {
                                "circle_id": circle_id,
                                "user_id": member["user_id"],
                                "reason": random.choice(["voluntary", "removed_by_organizer"]),
                                "dropped_at": drop_time.isoformat(),
                                "payments_made": cycle_num,
                                "payments_owed": total_cycles - cycle_num,
                            },
                            timestamp=drop_time,
                            correlation_id=correlation_id,
                        )
                    )

        # Circle completed
        active_members = [m for m in members if m["active"]]
        dropped_count = sum(1 for m in members if not m["active"])
        completion_time = cycle_start + timedelta(days=total_cycles * frequency_days)

        events.append(
            self._envelope(
                "circle-completed",
                "circle-service",
                {
                    "circle_id": circle_id,
                    "completed_at": completion_time.isoformat(),
                    "total_cycles": total_cycles,
                    "total_volume": self._decimal_str(
                        contribution_amount * num_members * total_cycles
                    ),
                    "currency": "USD",
                    "members_completed": len(active_members),
                    "members_dropped": dropped_count,
                },
                timestamp=completion_time,
                correlation_id=correlation_id,
            )
        )

        return events
