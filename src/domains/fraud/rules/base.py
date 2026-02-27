"""Enhanced abstract base class for fraud detection rules."""

from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import FraudConfig
from ..models import FraudScoreRequest, RuleResult, TransactionFeatures


class FraudRule(ABC):
    """Base class for all fraud rules.

    Rules are async (some need DB queries) and receive the full request,
    features, DB session, and config for maximum flexibility.
    """

    rule_id: str
    category: str  # "velocity" | "amount" | "geo" | "patterns"
    default_weight: float

    @abstractmethod
    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        """Evaluate this rule and return a RuleResult."""
        ...

    def _not_triggered(self) -> RuleResult:
        """Convenience: return a non-triggered result for this rule."""
        return RuleResult(
            rule_name=self.rule_id,
            triggered=False,
            category=self.category,
        )

    def _triggered(
        self,
        score: float,
        risk_factor,
        details: str,
        severity: str = "medium",
        confidence: float = 0.8,
        evidence: dict | None = None,
    ) -> RuleResult:
        """Convenience: return a triggered result for this rule."""
        return RuleResult(
            rule_name=self.rule_id,
            triggered=True,
            score=score,
            risk_factor=risk_factor,
            details=details,
            severity=severity,
            confidence=confidence,
            evidence=evidence or {},
            category=self.category,
        )
