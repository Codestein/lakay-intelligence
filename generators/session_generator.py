"""Session behavior generator with anomaly injection."""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from .base import BaseGenerator
from .utils.distributions import generate_device_id, generate_ip_address, log_normal_sample
from .utils.geography import location_to_geo, random_us_location
from .utils.names import random_email, random_name, random_phone

ACTION_TYPES = [
    "page_view",
    "button_click",
    "form_submit",
    "circle_browse",
    "circle_join_request",
    "contribution_initiate",
    "remittance_initiate",
    "settings_change",
    "support_contact",
]

DEVICE_TYPES = ["ios", "android", "web_desktop", "web_mobile"]

USER_AGENTS = {
    "ios": "Trebanx/1.0 iOS/17.4",
    "android": "Trebanx/1.0 Android/14",
    "web_desktop": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/122.0",
    "web_mobile": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4) Safari/605.1.15",
}


class SessionGenerator(BaseGenerator):
    def generate(self, num_sessions: int = 5000) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        config = self.config

        num_users = config.get("num_users", 500)
        time_span = config.get("time_span_days", 90)
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        end_time = base_time + timedelta(days=time_span)

        # Create user pool with typical behavior profiles
        users = []
        for _ in range(num_users):
            first, last = random_name()
            location = random_us_location()
            device_type = random.choice(DEVICE_TYPES)
            users.append(
                {
                    "user_id": self._uuid(),
                    "first_name": first,
                    "last_name": last,
                    "email": random_email(first, last),
                    "phone": random_phone("US"),
                    "location": location,
                    "device_id": generate_device_id(),
                    "device_type": device_type,
                    "ip_address": generate_ip_address(),
                    "typical_hours": sorted(random.sample(range(8, 23), k=random.randint(4, 8))),
                }
            )

        session_duration_dist = config.get(
            "session_duration_distribution", {"log_normal_mean": 6.0, "log_normal_std": 1.0}
        )
        actions_dist = config.get(
            "actions_per_session_distribution", {"log_normal_mean": 2.0, "log_normal_std": 0.8}
        )

        generated = 0
        while generated < num_sessions:
            user = random.choice(users)
            session_time = self._random_datetime(base_time, end_time)
            correlation_id = self._uuid()

            # Anomaly: account takeover
            is_takeover = random.random() < config.get("account_takeover_injection_rate", 0.0)
            if is_takeover:
                user = dict(user)  # copy
                user["device_id"] = generate_device_id()
                user["device_type"] = random.choice(
                    [d for d in DEVICE_TYPES if d != user["device_type"]]
                )
                user["ip_address"] = generate_ip_address()
                user["location"] = random_us_location()

            # Anomaly: impossible travel
            is_impossible_travel = random.random() < config.get("anomaly_injection_rate", 0.0) * 0.3

            session_events = self._generate_session(
                user,
                session_time,
                correlation_id,
                session_duration_dist,
                actions_dist,
                is_takeover=is_takeover,
            )
            events.extend(session_events)
            generated += 1

            if is_impossible_travel:
                # Second session from distant location within 30 min
                remote_user = dict(user)
                from .utils.geography import HAITI_LOCATIONS

                remote_loc = random.choice(HAITI_LOCATIONS)
                remote_user["location"] = remote_loc
                remote_user["ip_address"] = generate_ip_address()
                travel_time = session_time + timedelta(minutes=random.randint(10, 30))
                travel_events = self._generate_session(
                    remote_user,
                    travel_time,
                    self._uuid(),
                    session_duration_dist,
                    actions_dist,
                )
                events.extend(travel_events)
                generated += 1

        events.sort(key=lambda e: e["timestamp"])
        return events

    def _generate_session(
        self,
        user: dict,
        start_time: datetime,
        correlation_id: str,
        duration_dist: dict,
        actions_dist: dict,
        is_takeover: bool = False,
    ) -> list[dict[str, Any]]:
        events = []
        attempt_id = self._uuid()
        session_id = self._uuid()
        geo = location_to_geo(user["location"])

        # Login attempt
        events.append(
            self._envelope(
                "login-attempt",
                "user-service",
                {
                    "user_id": user["user_id"],
                    "attempt_id": attempt_id,
                    "ip_address": user["ip_address"],
                    "device_id": user["device_id"],
                    "device_type": user["device_type"],
                    "user_agent": USER_AGENTS.get(user["device_type"], "Unknown"),
                    "geo_location": geo,
                    "attempted_at": start_time.isoformat(),
                    "auth_method": random.choice(["password", "biometric", "magic_link"]),
                },
                timestamp=start_time,
                correlation_id=correlation_id,
            )
        )

        # Login result
        login_success = random.random() > 0.05
        if not login_success:
            events.append(
                self._envelope(
                    "login-failed",
                    "user-service",
                    {
                        "user_id": user["user_id"],
                        "attempt_id": attempt_id,
                        "failure_reason": random.choice(
                            ["invalid_password", "mfa_failed", "device_not_trusted"]
                        ),
                        "failed_at": (
                            start_time + timedelta(seconds=random.randint(1, 5))
                        ).isoformat(),
                        "consecutive_failures": random.randint(1, 5),
                    },
                    timestamp=start_time + timedelta(seconds=3),
                    correlation_id=correlation_id,
                )
            )
            return events

        auth_time = start_time + timedelta(seconds=random.randint(1, 5))
        events.append(
            self._envelope(
                "login-success",
                "user-service",
                {
                    "user_id": user["user_id"],
                    "attempt_id": attempt_id,
                    "session_id": session_id,
                    "authenticated_at": auth_time.isoformat(),
                    "mfa_used": random.random() < 0.3,
                },
                timestamp=auth_time,
                correlation_id=correlation_id,
            )
        )

        # Session started
        events.append(
            self._envelope(
                "session-started",
                "user-service",
                {
                    "session_id": session_id,
                    "user_id": user["user_id"],
                    "device_id": user["device_id"],
                    "ip_address": user["ip_address"],
                    "geo_location": geo,
                    "started_at": auth_time.isoformat(),
                },
                timestamp=auth_time,
                correlation_id=correlation_id,
            )
        )

        # User actions
        duration_seconds = int(
            log_normal_sample(
                duration_dist["log_normal_mean"],
                duration_dist["log_normal_std"],
                min_val=10,
                max_val=7200,
            )
        )
        num_actions = max(
            1,
            int(
                log_normal_sample(
                    actions_dist["log_normal_mean"],
                    actions_dist["log_normal_std"],
                    min_val=1,
                    max_val=100,
                )
            ),
        )

        action_time = auth_time
        for _ in range(num_actions):
            action_gap = random.randint(
                2000, max(3000, duration_seconds * 1000 // (num_actions + 1))
            )
            action_time += timedelta(milliseconds=action_gap)

            if is_takeover:
                action_type = random.choice(
                    ["remittance_initiate", "settings_change", "form_submit"]
                )
            else:
                action_type = random.choice(ACTION_TYPES)

            events.append(
                self._envelope(
                    "user-action-performed",
                    "user-service",
                    {
                        "session_id": session_id,
                        "user_id": user["user_id"],
                        "action_id": self._uuid(),
                        "action_type": action_type,
                        "action_target": f"/{action_type.replace('_', '-')}",
                        "performed_at": action_time.isoformat(),
                        "duration_ms": random.randint(500, 30000),
                    },
                    timestamp=action_time,
                    correlation_id=correlation_id,
                )
            )

        # Session ended
        end_time = auth_time + timedelta(seconds=duration_seconds)
        events.append(
            self._envelope(
                "session-ended",
                "user-service",
                {
                    "session_id": session_id,
                    "user_id": user["user_id"],
                    "ended_at": end_time.isoformat(),
                    "reason": random.choice(["user_logout", "timeout"]),
                    "duration_seconds": duration_seconds,
                    "actions_count": num_actions,
                },
                timestamp=end_time,
                correlation_id=correlation_id,
            )
        )

        return events
