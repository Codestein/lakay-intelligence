"""Consumer for user and session events."""

from typing import Any

import structlog

from .base import BaseConsumer

logger = structlog.get_logger()

USER_EVENT_TYPES = [
    "user-registered",
    "user-verified",
    "user-profile-updated",
    "login-attempt",
    "login-success",
    "login-failed",
    "session-started",
    "session-ended",
    "device-registered",
    "user-action-performed",
]


class SessionConsumer(BaseConsumer):
    def __init__(self, bootstrap_servers: str, group_id: str = "lakay-intelligence") -> None:
        super().__init__(
            topics=["trebanx.user.events"],
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
        )
        for event_type in USER_EVENT_TYPES:
            self.register_handler(event_type, self._handle_user_event)

    async def _handle_user_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("event_type", "unknown")
        payload = event.get("payload", {})
        user_id = payload.get("user_id")
        logger.info(
            "user_event_received",
            event_type=event_type,
            user_id=user_id,
            event_id=event.get("event_id"),
        )
