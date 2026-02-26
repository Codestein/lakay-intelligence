"""Risk score aggregation."""

from datetime import UTC, datetime

import structlog

logger = structlog.get_logger()


class FraudScorer:
    """Aggregates rule-based and model-based fraud scores."""

    async def aggregate(
        self,
        transaction_id: str,
        rule_score: float = 0.0,
        model_score: float = 0.0,
    ) -> dict:
        """Combine scores into a final risk assessment. Stub implementation."""
        return {
            "transaction_id": transaction_id,
            "final_score": max(rule_score, model_score),
            "rule_score": rule_score,
            "model_score": model_score,
            "model_version": "stub",
            "computed_at": datetime.now(UTC).isoformat(),
        }
