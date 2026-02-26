"""Consumer for remittance events."""

from typing import Any

import structlog

from .base import BaseConsumer

logger = structlog.get_logger()

REMITTANCE_EVENT_TYPES = [
    "remittance-initiated",
    "remittance-processing",
    "remittance-completed",
    "remittance-failed",
    "exchange-rate-updated",
]


class RemittanceConsumer(BaseConsumer):
    def __init__(self, bootstrap_servers: str, group_id: str = "lakay-intelligence") -> None:
        super().__init__(
            topics=["trebanx.remittance.events"],
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
        )
        for event_type in REMITTANCE_EVENT_TYPES:
            self.register_handler(event_type, self._handle_remittance_event)

    async def _handle_remittance_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("event_type", "unknown")
        payload = event.get("payload", {})
        remittance_id = payload.get("remittance_id")
        logger.info(
            "remittance_event_received",
            event_type=event_type,
            remittance_id=remittance_id,
            event_id=event.get("event_id"),
        )
