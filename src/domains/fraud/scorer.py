"""Fraud scoring pipeline: features → rules → persist → alert."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Alert as AlertDB
from src.db.models import FraudScore as FraudScoreDB

from .feature_computer import FeatureComputer
from .models import FraudScoreRequest, ScoringResult
from .rules_engine import RulesEngine

logger = structlog.get_logger()

ALERT_THRESHOLD = 50
BLOCK_THRESHOLD = 80


class FraudScorer:
    """Orchestrates the full fraud scoring pipeline."""

    def __init__(self) -> None:
        self._feature_computer = FeatureComputer()
        self._rules_engine = RulesEngine()

    async def score_transaction(
        self,
        request: FraudScoreRequest,
        session: AsyncSession,
    ) -> ScoringResult:
        """Run the full scoring pipeline for a transaction."""
        # 1. Compute features from historical data
        features = await self._feature_computer.compute(
            session=session,
            user_id=request.user_id,
            device_id=request.device_id,
            geo_location=request.geo_location,
            now=request.initiated_at or datetime.now(UTC),
        )

        # 2. Evaluate rules
        response, rule_results = self._rules_engine.evaluate(request, features)

        # 3. Persist FraudScore
        score_row = FraudScoreDB(
            transaction_id=request.transaction_id,
            risk_score=response.score,
            rules_triggered={
                "rules": [r.model_dump() for r in rule_results if r.triggered],
                "risk_factors": response.risk_factors,
            },
            model_version="rules-v1",
            scored_at=response.computed_at,
        )
        session.add(score_row)

        # 4. Create alert if score exceeds threshold
        if response.score >= ALERT_THRESHOLD:
            severity = "critical" if response.score >= BLOCK_THRESHOLD else "high"
            alert_row = AlertDB(
                alert_id=str(uuid.uuid4()),
                user_id=request.user_id,
                alert_type="fraud_score",
                severity=severity,
                details={
                    "transaction_id": request.transaction_id,
                    "score": response.score,
                    "risk_factors": response.risk_factors,
                    "model_version": "rules-v1",
                },
                status="open",
                created_at=datetime.now(UTC),
            )
            session.add(alert_row)
            logger.warning(
                "fraud_alert_created",
                transaction_id=request.transaction_id,
                score=response.score,
                severity=severity,
            )

        await session.commit()

        logger.info(
            "transaction_scored",
            transaction_id=request.transaction_id,
            score=response.score,
            risk_factors=response.risk_factors,
        )

        return ScoringResult(
            final_score=response.score,
            rule_results=rule_results,
            features_used=features,
        )
