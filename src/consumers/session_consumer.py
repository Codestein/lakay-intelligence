"""Consumer for user and session events."""

from typing import Any

import structlog

from src.db.database import async_session_factory
from src.domains.fraud.config import FraudConfig, default_config
from src.domains.fraud.models import FraudScoreRequest, TransactionFeatures
from src.domains.fraud.rules.velocity import LoginVelocityRule

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
    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str = "lakay-intelligence",
        config: FraudConfig | None = None,
    ) -> None:
        super().__init__(
            topics=["trebanx.user.events"],
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
        )
        self._config = config or default_config
        self._login_velocity_rule = LoginVelocityRule()
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

        # Lightweight login velocity check on session-started events
        if event_type == "session-started" and user_id:
            await self._check_login_velocity(user_id, payload)

    async def _check_login_velocity(self, user_id: str, payload: dict[str, Any]) -> None:
        """Run just the LoginVelocityRule as a lightweight check."""
        try:
            # Build a minimal request for the rule
            request = FraudScoreRequest(
                transaction_id=f"session-{payload.get('session_id', 'unknown')}",
                user_id=user_id,
                amount="0",
                initiated_at=payload.get("timestamp"),
            )
            features = TransactionFeatures()

            async with async_session_factory() as session:
                result = await self._login_velocity_rule.evaluate(
                    request, features, session, self._config
                )
                if result.triggered:
                    logger.warning(
                        "login_velocity_alert",
                        user_id=user_id,
                        score=result.score,
                        details=result.details,
                        evidence=result.evidence,
                    )
        except Exception:
            logger.exception("login_velocity_check_error", user_id=user_id)
