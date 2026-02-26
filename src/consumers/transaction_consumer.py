"""Consumer for transaction events."""

from typing import Any

import structlog

from .base import BaseConsumer

logger = structlog.get_logger()

TRANSACTION_EVENT_TYPES = [
    "transaction-initiated",
    "transaction-completed",
    "transaction-failed",
    "transaction-flagged",
]


class TransactionConsumer(BaseConsumer):
    def __init__(self, bootstrap_servers: str, group_id: str = "lakay-intelligence") -> None:
        super().__init__(
            topics=["trebanx.transaction.events"],
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
        )
        for event_type in TRANSACTION_EVENT_TYPES:
            self.register_handler(event_type, self._handle_transaction_event)

    async def _handle_transaction_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("event_type", "unknown")
        payload = event.get("payload", {})
        txn_id = payload.get("transaction_id")
        logger.info(
            "transaction_event_received",
            event_type=event_type,
            transaction_id=txn_id,
            event_id=event.get("event_id"),
        )
