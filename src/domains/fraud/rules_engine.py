"""Rule-based fraud detection engine. Phase 3 implementation."""

from datetime import UTC, datetime

import structlog

from .models import FraudScoreRequest, FraudScoreResponse

logger = structlog.get_logger()


class RulesEngine:
    """Evaluates transaction events against fraud detection rules."""

    def __init__(self) -> None:
        self._rules: list = []
        logger.info("rules_engine_initialized", rule_count=0)

    async def evaluate(self, request: FraudScoreRequest) -> FraudScoreResponse:
        """Evaluate a transaction against all rules. Stub implementation."""
        logger.info("evaluating_transaction", transaction_id=request.transaction_id)
        return FraudScoreResponse(
            transaction_id=request.transaction_id,
            score=0.0,
            confidence=0.0,
            risk_factors=[],
            model_version="stub",
            computed_at=datetime.now(UTC),
        )
