"""Circle risk classification.

Maps health scores and anomalies into actionable risk tiers with
recommended actions in plain language suitable for circle organizers.
"""

import json
from datetime import UTC, datetime
from typing import Any

import structlog

from .models import (
    AnomalySeverity,
    AnomalyType,
    CircleAnomaly,
    CircleClassification,
    CircleHealthScore,
    HealthTier,
    RecommendedAction,
    TierChange,
    TrendDirection,
)

logger = structlog.get_logger()


class CircleClassifier:
    """Classifies circles into risk tiers with actionable recommendations."""

    def classify(
        self,
        health_score: CircleHealthScore,
        anomalies: list[CircleAnomaly],
    ) -> CircleClassification:
        """Classify a circle based on its health score and detected anomalies.

        Classification logic:
        1. Primary signal: health score -> tier
        2. Override: anomaly severity can escalate the tier
        3. Trend: deteriorating trend lowers effective threshold

        Args:
            health_score: The computed health score.
            anomalies: Detected anomalies for this circle.

        Returns:
            CircleClassification with tier and recommended actions.
        """
        # Start with score-based tier
        effective_score = health_score.health_score

        # Collect anomaly info
        highest_severity = self._highest_anomaly_severity(anomalies)
        reasons: list[str] = []

        # Apply trend adjustment: deteriorating trend lowers effective score
        if health_score.trend == TrendDirection.DETERIORATING:
            effective_score -= 10  # effectively shifts tier boundaries
            if effective_score < 0:
                effective_score = 0
            reasons.append("Deteriorating trend detected")

        # Determine tier from adjusted score
        if effective_score >= 70:
            tier = HealthTier.HEALTHY
        elif effective_score >= 40:
            tier = HealthTier.AT_RISK
        else:
            tier = HealthTier.CRITICAL

        # Anomaly severity overrides can escalate tier
        if highest_severity == AnomalySeverity.HIGH:
            if tier == HealthTier.HEALTHY:
                tier = HealthTier.AT_RISK
                reasons.append("High-severity anomaly escalated tier from Healthy to At-Risk")
            elif tier == HealthTier.AT_RISK:
                tier = HealthTier.CRITICAL
                reasons.append("High-severity anomaly escalated tier from At-Risk to Critical")
        elif highest_severity == AnomalySeverity.MEDIUM and tier == HealthTier.HEALTHY:
            tier = HealthTier.AT_RISK
            reasons.append("Medium-severity anomaly escalated tier from Healthy to At-Risk")

        # Specific override: deteriorating + score below 55 = Critical
        if (
            health_score.trend == TrendDirection.DETERIORATING
            and health_score.health_score < 55
            and tier != HealthTier.CRITICAL
        ):
            tier = HealthTier.CRITICAL
            reasons.append(
                f"Score ({health_score.health_score:.0f}) below 55 "
                "with deteriorating trend"
            )

        # Build reason string
        if not reasons:
            reasons.append(f"Health score: {health_score.health_score:.0f}")

        # Generate recommendations
        recommended_actions = self._generate_recommendations(
            tier, health_score, anomalies
        )

        classification = CircleClassification(
            circle_id=health_score.circle_id,
            health_tier=tier,
            health_score=health_score.health_score,
            trend=health_score.trend,
            anomaly_count=len(anomalies),
            highest_anomaly_severity=highest_severity,
            recommended_actions=recommended_actions,
            classified_at=datetime.now(UTC),
            classification_reason="; ".join(reasons),
        )

        logger.info(
            "circle_classified",
            circle_id=health_score.circle_id,
            tier=tier.value,
            score=health_score.health_score,
            anomaly_count=len(anomalies),
            action_count=len(recommended_actions),
        )

        return classification

    def detect_tier_change(
        self,
        circle_id: str,
        current_tier: HealthTier,
        previous_tier: HealthTier | None,
        health_score: float,
        reason: str,
    ) -> TierChange | None:
        """Detect if a tier change occurred and produce a TierChange event.

        Returns None if the tier hasn't changed.
        """
        if previous_tier is None or current_tier == previous_tier:
            return None

        change = TierChange(
            circle_id=circle_id,
            previous_tier=previous_tier,
            new_tier=current_tier,
            health_score=health_score,
            reason=reason,
            changed_at=datetime.now(UTC),
        )

        logger.warning(
            "circle_tier_changed",
            circle_id=circle_id,
            previous_tier=previous_tier.value,
            new_tier=current_tier.value,
            health_score=health_score,
        )

        return change

    def _highest_anomaly_severity(
        self, anomalies: list[CircleAnomaly]
    ) -> AnomalySeverity | None:
        if not anomalies:
            return None

        severity_order = {
            AnomalySeverity.LOW: 0,
            AnomalySeverity.MEDIUM: 1,
            AnomalySeverity.HIGH: 2,
        }
        return max(anomalies, key=lambda a: severity_order[a.severity]).severity

    def _generate_recommendations(
        self,
        tier: HealthTier,
        health_score: CircleHealthScore,
        anomalies: list[CircleAnomaly],
    ) -> list[RecommendedAction]:
        """Generate actionable recommendations based on tier, score dimensions, and anomalies.

        Recommendations are written in plain language for circle organizers.
        """
        actions: list[RecommendedAction] = []

        if tier == HealthTier.HEALTHY:
            actions.append(
                RecommendedAction(
                    action="Continue standard monitoring",
                    reason="Circle is functioning well with no immediate concerns",
                    priority="low",
                )
            )
            return actions

        # Identify the weakest dimension
        dims = health_score.dimension_scores
        weakest = min(dims.values(), key=lambda d: d.score) if dims else None

        # Dimension-specific recommendations
        if weakest:
            if weakest.dimension_name == "contribution_reliability" and weakest.score < 60:
                actions.append(
                    RecommendedAction(
                        action=(
                            "Reach out to members who have missed or been late on payments. "
                            "A friendly reminder from the organizer can make a big difference."
                        ),
                        reason=(
                            f"Contribution reliability score is low ({weakest.score:.0f}/100). "
                            "Late or missed payments are the leading cause of circle failure."
                        ),
                        priority="high",
                    )
                )

            elif weakest.dimension_name == "membership_stability" and weakest.score < 60:
                actions.append(
                    RecommendedAction(
                        action=(
                            "Consider pausing new member additions and focus on retaining "
                            "current members. If members are leaving, reach out to understand why."
                        ),
                        reason=(
                            f"Membership stability score is low ({weakest.score:.0f}/100). "
                            "The circle has lost members, which reduces "
                            "the payout pool for everyone."
                        ),
                        priority="high",
                    )
                )
                if weakest.score < 40:
                    actions.append(
                        RecommendedAction(
                            action=(
                                "Consider restructuring the rotation schedule to account for "
                                "fewer members, so remaining members aren't overburdened."
                            ),
                            reason="Significant membership loss may require rotation adjustment",
                            priority="high",
                        )
                    )

            elif weakest.dimension_name == "financial_progress" and weakest.score < 60:
                actions.append(
                    RecommendedAction(
                        action=(
                            "Review the collection status with your circle. Some contributions "
                            "may be overdue. Consider setting up payment reminders."
                        ),
                        reason=(
                            f"Financial progress score is low ({weakest.score:.0f}/100). "
                            "The circle is falling behind on expected collections."
                        ),
                        priority="high",
                    )
                )

            elif weakest.dimension_name == "trust_integrity" and weakest.score < 60:
                actions.append(
                    RecommendedAction(
                        action=(
                            "Review member activity for unusual patterns. Some members may "
                            "need to be contacted about their commitment to the circle."
                        ),
                        reason=(
                            f"Trust & integrity score is low ({weakest.score:.0f}/100). "
                            "Unusual patterns have been detected that warrant attention."
                        ),
                        priority="high",
                    )
                )

        # Anomaly-specific recommendations
        for anomaly in anomalies:
            if anomaly.anomaly_type == AnomalyType.COORDINATED_LATE:
                actions.append(
                    RecommendedAction(
                        action=(
                            "Multiple members are late this cycle at the same time. "
                            "Check in with the group — there may be a shared circumstance "
                            "(like a holiday or payroll delay) "
                            "or coordination that needs attention."
                        ),
                        reason="Coordinated late payment pattern detected",
                        priority="high" if anomaly.severity == AnomalySeverity.HIGH else "medium",
                    )
                )

            elif anomaly.anomaly_type == AnomalyType.POST_PAYOUT_DISENGAGEMENT:
                actions.append(
                    RecommendedAction(
                        action=(
                            "Some members have reduced their participation after receiving "
                            "their payout. Reach out to remind them that the circle depends "
                            "on everyone continuing to contribute until the end."
                        ),
                        reason="Post-payout disengagement detected — classic sou-sou risk pattern",
                        priority="high",
                    )
                )

            elif anomaly.anomaly_type == AnomalyType.FREE_RIDER:
                actions.append(
                    RecommendedAction(
                        action=(
                            "One or more members have received their payout but contributed "
                            "significantly less than expected. This requires immediate attention "
                            "to protect the other circle members."
                        ),
                        reason="Free-rider detected — member contribution imbalance",
                        priority="high",
                    )
                )
                # Cross-reference with fraud system
                if anomaly.severity == AnomalySeverity.HIGH:
                    actions.append(
                        RecommendedAction(
                            action=(
                                "This pattern may indicate intentional fraud. The system has "
                                "flagged this for review by the Trebanx trust and safety team."
                            ),
                            reason="High-severity free-rider pattern flagged for fraud review",
                            priority="high",
                        )
                    )

            elif anomaly.anomaly_type == AnomalyType.BEHAVIORAL_SHIFT:
                actions.append(
                    RecommendedAction(
                        action=(
                            "The circle's behavior has changed significantly from its "
                            "established pattern. Monitor closely over the next cycle."
                        ),
                        reason="Sudden behavioral change detected",
                        priority="medium",
                    )
                )

        # Trend-based recommendations
        if health_score.trend == TrendDirection.DETERIORATING:
            actions.append(
                RecommendedAction(
                    action=(
                        "The circle's health has been declining over recent cycles. "
                        "Consider having a group discussion to address any issues before "
                        "they get worse."
                    ),
                    reason="Health score trend is deteriorating",
                    priority="high" if tier == HealthTier.CRITICAL else "medium",
                )
            )

        return actions


async def publish_tier_change(
    tier_change: TierChange, kafka_producer: Any, topic: str
) -> None:
    """Publish a tier change event to Kafka.

    Args:
        tier_change: The tier change to publish.
        kafka_producer: An aiokafka AIOKafkaProducer instance.
        topic: The Kafka topic to publish to.
    """
    if kafka_producer is None:
        logger.debug("kafka_producer_not_available", circle_id=tier_change.circle_id)
        return

    payload = {
        "circle_id": tier_change.circle_id,
        "previous_tier": tier_change.previous_tier.value,
        "new_tier": tier_change.new_tier.value,
        "health_score": tier_change.health_score,
        "reason": tier_change.reason,
        "changed_at": tier_change.changed_at.isoformat(),
    }

    try:
        await kafka_producer.send_and_wait(
            topic,
            value=json.dumps(payload, default=str).encode("utf-8"),
            key=tier_change.circle_id.encode("utf-8"),
        )
        logger.info(
            "tier_change_published",
            circle_id=tier_change.circle_id,
            topic=topic,
            new_tier=tier_change.new_tier.value,
        )
    except Exception:
        logger.exception(
            "tier_change_publish_failed",
            circle_id=tier_change.circle_id,
            topic=topic,
        )
