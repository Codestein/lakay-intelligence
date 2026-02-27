"""Consumer for transaction events."""

from typing import Any

import structlog

from src.db.database import async_session_factory
from src.domains.fraud.config import FraudConfig
from src.domains.fraud.models import FraudScoreRequest
from src.domains.fraud.scorer import FraudScorer

from .base import BaseConsumer

logger = structlog.get_logger()

TRANSACTION_EVENT_TYPES = [
    "transaction-initiated",
    "transaction-completed",
    "transaction-failed",
    "transaction-flagged",
]


class TransactionConsumer(BaseConsumer):
    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str = "lakay-intelligence",
        config: FraudConfig | None = None,
        kafka_producer=None,
    ) -> None:
        super().__init__(
            topics=["trebanx.transaction.events"],
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
        )
        self._scorer = FraudScorer(config=config, kafka_producer=kafka_producer)
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

        if event_type == "transaction-initiated" and txn_id:
            await self._score_transaction(payload)

    async def _score_transaction(self, payload: dict[str, Any]) -> None:
        try:
            request = FraudScoreRequest(
                transaction_id=payload["transaction_id"],
                user_id=payload["user_id"],
                amount=payload.get("amount", "0"),
                currency=payload.get("currency", "USD"),
                ip_address=payload.get("ip_address"),
                device_id=payload.get("device_id"),
                geo_location=payload.get("geo_location"),
                transaction_type=payload.get("type"),
                initiated_at=payload.get("initiated_at"),
                recipient_id=payload.get("recipient_id"),
            )
            async with async_session_factory() as session:
                result = await self._scorer.score_transaction(request, session)
                ctx = result.scoring_context
                logger.info(
                    "transaction_scored_via_consumer",
                    transaction_id=request.transaction_id,
                    score=result.final_score,
                    composite_score=ctx.composite_score if ctx else None,
                    risk_tier=ctx.risk_tier.value if ctx else None,
                    recommendation=ctx.recommendation if ctx else None,
                )
        except Exception:
            logger.exception(
                "fraud_scoring_error",
                transaction_id=payload.get("transaction_id"),
            )
