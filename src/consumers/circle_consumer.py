"""Consumer for circle lifecycle events."""

from typing import Any

import structlog

from .base import BaseConsumer

logger = structlog.get_logger()

CIRCLE_EVENT_TYPES = [
    "circle-created",
    "circle-member-joined",
    "circle-member-dropped",
    "circle-contribution-received",
    "circle-contribution-missed",
    "circle-payout-executed",
    "circle-completed",
    "circle-failed",
]


class CircleConsumer(BaseConsumer):
    def __init__(self, bootstrap_servers: str, group_id: str = "lakay-intelligence") -> None:
        super().__init__(
            topics=["trebanx.circle.events"],
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
        )
        for event_type in CIRCLE_EVENT_TYPES:
            self.register_handler(event_type, self._handle_circle_event)

    async def _handle_circle_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("event_type", "unknown")
        payload = event.get("payload", {})
        circle_id = payload.get("circle_id")
        logger.info(
            "circle_event_received",
            event_type=event_type,
            circle_id=circle_id,
            event_id=event.get("event_id"),
        )
