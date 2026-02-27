"""Rule-based fraud detection engine with weighted category aggregation."""

from collections import defaultdict
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .config import FraudConfig, default_config
from .models import (
    FraudScoreRequest,
    FraudScoreResponse,
    RiskTier,
    RuleResult,
    ScoringContext,
    TransactionFeatures,
)
from .rules import ALL_RULES

logger = structlog.get_logger()


def _classify_risk_tier(score: float, config: FraudConfig) -> RiskTier:
    if score >= config.alerts.critical_threshold:
        return RiskTier.CRITICAL
    if score >= config.alerts.high_threshold:
        return RiskTier.HIGH
    if score >= 0.3:
        return RiskTier.MEDIUM
    return RiskTier.LOW


_TIER_RECOMMENDATIONS = {
    RiskTier.LOW: "allow",
    RiskTier.MEDIUM: "monitor",
    RiskTier.HIGH: "hold",
    RiskTier.CRITICAL: "block",
}


class RulesEngine:
    """Evaluates transaction events against fraud detection rules.

    Scoring uses weighted category aggregation (0.0-1.0):
    1. Run all rules -> list[RuleResult]
    2. Group triggered rules by category
    3. Per category: weighted sum, capped at category max
    4. Composite = sum of category scores, capped at 1.0
    5. Confidence = f(num_triggered, categories_triggered)
    """

    def __init__(self, config: FraudConfig | None = None) -> None:
        self._rules = list(ALL_RULES)
        self._config = config or default_config
        logger.info("rules_engine_initialized", rule_count=len(self._rules), version="rules-v2")

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig | None = None,
    ) -> tuple[ScoringContext, list[RuleResult]]:
        """Evaluate a transaction against all rules. Returns scoring context and results."""
        cfg = config or self._config
        results: list[RuleResult] = []

        # Run all rules (now async)
        for rule in self._rules:
            try:
                result = await rule.evaluate(request, features, session, cfg)
                results.append(result)
            except Exception:
                logger.exception("rule_evaluation_error", rule_id=rule.rule_id)
                results.append(
                    RuleResult(
                        rule_name=rule.rule_id,
                        triggered=False,
                        details="Rule evaluation failed",
                        category=rule.category,
                    )
                )

        # Aggregate triggered rules
        triggered = [r for r in results if r.triggered]

        # Group by category
        by_category: dict[str, list[RuleResult]] = defaultdict(list)
        for r in triggered:
            by_category[r.category].append(r)

        # Category caps from config
        category_caps = {
            "velocity": cfg.scoring.velocity_cap,
            "amount": cfg.scoring.amount_cap,
            "geo": cfg.scoring.geo_cap,
            "patterns": cfg.scoring.patterns_cap,
        }

        # Per-category weighted aggregation
        category_scores: dict[str, float] = {}
        for cat, cat_results in by_category.items():
            cap = category_caps.get(cat, 0.25)
            # Find the matching rule weights
            rule_weights = {rule.rule_id: rule.default_weight for rule in self._rules}
            weighted_sum = sum(r.score * rule_weights.get(r.rule_name, 0.10) for r in cat_results)
            category_scores[cat] = min(weighted_sum, cap)

        # Composite score: sum of category scores, capped at 1.0
        composite = min(sum(category_scores.values()), 1.0)

        # Confidence: based on triggered count and category spread
        num_triggered = len(triggered)
        num_categories = len(by_category)
        if num_triggered == 0:
            confidence = 0.0
        else:
            count_factor = min(num_triggered / 5, 1.0)
            category_factor = min(num_categories / 3, 1.0)
            # Average of triggered rule confidences
            avg_rule_confidence = sum(r.confidence for r in triggered) / num_triggered
            confidence = min(
                0.4 * count_factor + 0.3 * category_factor + 0.3 * avg_rule_confidence,
                1.0,
            )

        # Risk tier and recommendation
        risk_tier = _classify_risk_tier(composite, cfg)
        recommendation = _TIER_RECOMMENDATIONS[risk_tier]

        scoring_context = ScoringContext(
            composite_score=round(composite, 4),
            risk_tier=risk_tier,
            triggered_rules=triggered,
            recommendation=recommendation,
            scoring_metadata={
                "category_scores": category_scores,
                "model_version": "rules-v2",
                "rule_count": len(self._rules),
                "triggered_count": num_triggered,
                "categories_triggered": list(by_category.keys()),
                "confidence": round(confidence, 4),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        logger.info(
            "rules_evaluated",
            transaction_id=request.transaction_id,
            composite_score=composite,
            risk_tier=risk_tier.value,
            triggered_count=num_triggered,
            categories=list(by_category.keys()),
            recommendation=recommendation,
        )

        return scoring_context, results

    def evaluate_sync(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
    ) -> tuple[FraudScoreResponse, list[RuleResult]]:
        """Legacy synchronous evaluation for backward compatibility.

        Uses simple additive scoring (0-100 scale). Deprecated — use evaluate() instead.
        """
        # This is kept for any code that still uses the sync interface
        # It cannot run the new async rules, so it returns a basic response
        legacy_score = 0.0
        results: list[RuleResult] = []

        risk_factors = [r.risk_factor.value for r in results if r.triggered and r.risk_factor]
        triggered = [r for r in results if r.triggered]
        confidence = min(len(triggered) / 5, 1.0) if triggered else 0.0

        return FraudScoreResponse(
            transaction_id=request.transaction_id,
            score=min(legacy_score, 100),
            confidence=confidence,
            risk_factors=risk_factors,
            model_version="rules-v1",
            computed_at=datetime.now(UTC),
        ), results
