"""Rule-based fraud detection engine."""

from datetime import UTC, datetime

import structlog

from .models import FraudScoreRequest, FraudScoreResponse, RuleResult, TransactionFeatures
from .rules import ALL_RULES, UnusualHourEvaluator

logger = structlog.get_logger()


class RulesEngine:
    """Evaluates transaction events against fraud detection rules."""

    def __init__(self) -> None:
        self._rules = list(ALL_RULES)
        logger.info("rules_engine_initialized", rule_count=len(self._rules))

    def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
    ) -> tuple[FraudScoreResponse, list[RuleResult]]:
        """Evaluate a transaction against all rules. Returns response and detailed results."""
        amount = request.amount_float
        results: list[RuleResult] = []

        # Run all feature-based rules
        for rule in self._rules:
            result = rule.evaluate(amount, features)
            results.append(result)

        # Run the unusual hour rule separately (needs initiated_at)
        if request.initiated_at:
            hour_result = UnusualHourEvaluator.evaluate(request.initiated_at.hour)
            # Replace the placeholder UnusualHourRule result
            results = [r for r in results if r.rule_name != "unusual_hour"]
            results.append(hour_result)

        # Aggregate: sum of triggered scores, capped at 100
        triggered = [r for r in results if r.triggered]
        total_score = min(sum(r.score for r in triggered), 100)
        risk_factors = [r.risk_factor.value for r in triggered if r.risk_factor]

        # Confidence based on number of rules triggered
        confidence = min(len(triggered) / 5, 1.0) if triggered else 0.0

        response = FraudScoreResponse(
            transaction_id=request.transaction_id,
            score=total_score,
            confidence=confidence,
            risk_factors=risk_factors,
            model_version="rules-v1",
            computed_at=datetime.now(UTC),
        )

        logger.info(
            "rules_evaluated",
            transaction_id=request.transaction_id,
            score=total_score,
            triggered_count=len(triggered),
            risk_factors=risk_factors,
        )

        return response, results
