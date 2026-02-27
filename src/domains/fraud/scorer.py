"""Fraud scoring pipeline: features -> rules -> persist -> alert."""

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import FraudScore as FraudScoreDB

from .alerts import create_alert, publish_alert
from .config import FraudConfig, default_config
from .feature_computer import FeatureComputer
from .models import FraudScoreRequest, ScoringResult
from .rules_engine import RulesEngine

logger = structlog.get_logger()


class FraudScorer:
    """Orchestrates the full fraud scoring pipeline."""

    def __init__(
        self,
        config: FraudConfig | None = None,
        kafka_producer=None,
    ) -> None:
        self._config = config or default_config
        self._feature_computer = FeatureComputer()
        self._rules_engine = RulesEngine(config=self._config)
        self._kafka_producer = kafka_producer

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

        # 2. Evaluate rules (async, weighted 0-1)
        scoring_context, rule_results = await self._rules_engine.evaluate(
            request, features, session, self._config
        )

        # 3. Persist FraudScore
        # Convert 0-1 composite to 0-100 for backward compat in DB
        legacy_score = min(scoring_context.composite_score * 100, 100)
        risk_factors = [
            r.risk_factor.value for r in scoring_context.triggered_rules if r.risk_factor
        ]

        score_row = FraudScoreDB(
            transaction_id=request.transaction_id,
            user_id=request.user_id,
            risk_score=legacy_score,
            confidence=scoring_context.scoring_metadata.get("confidence", 0.0),
            risk_tier=scoring_context.risk_tier.value,
            rules_triggered={
                "rules": [r.model_dump() for r in rule_results if r.triggered],
                "risk_factors": risk_factors,
                "scoring_context": {
                    "composite_score": scoring_context.composite_score,
                    "risk_tier": scoring_context.risk_tier.value,
                    "recommendation": scoring_context.recommendation,
                    "category_scores": scoring_context.scoring_metadata.get("category_scores", {}),
                },
            },
            model_version="rules-v2",
            scored_at=datetime.now(UTC),
        )
        session.add(score_row)

        # 4. Create alert if risk tier >= HIGH (with dedup)
        alert = await create_alert(scoring_context, request, session, self._config)

        await session.commit()

        # 5. Publish alert to Kafka (after commit so alert is persisted)
        if alert and self._kafka_producer:
            await publish_alert(alert, self._kafka_producer)

        logger.info(
            "transaction_scored",
            transaction_id=request.transaction_id,
            composite_score=scoring_context.composite_score,
            risk_tier=scoring_context.risk_tier.value,
            recommendation=scoring_context.recommendation,
            triggered_count=len(scoring_context.triggered_rules),
            alert_created=alert is not None,
        )

        return ScoringResult(
            final_score=legacy_score,
            rule_results=rule_results,
            features_used=features,
            scoring_context=scoring_context,
        )
