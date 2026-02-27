"""Account Takeover (ATO) detection pipeline (Phase 7, Task 7.4).

Aggregates session anomaly scores, fraud signals, and behavioral patterns
into an ATO risk assessment with graduated response recommendations.
Generates alerts for high/critical risk, persists to PostgreSQL, and
publishes to Kafka.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Alert as AlertDB
from src.features.store import FeatureStore

from .anomaly import SessionAnomalyScorer
from .config import BehaviorConfig, default_config
from .models import (
    AnomalyClassification,
    ATOAlert,
    ATOAlertStatus,
    ATOAlertUpdate,
    ATOAssessment,
    ATORiskLevel,
    ATOResponseAction,
    ATOSignal,
    SessionAnomalyResult,
    UserBehaviorProfile,
)

logger = structlog.get_logger()


class ATODetector:
    """End-to-end ATO detection pipeline."""

    def __init__(
        self,
        config: BehaviorConfig | None = None,
        feature_store: FeatureStore | None = None,
        anomaly_scorer: SessionAnomalyScorer | None = None,
        kafka_producer: Any = None,
    ) -> None:
        self._config = config or default_config
        self._feature_store = feature_store or FeatureStore()
        self._anomaly_scorer = anomaly_scorer or SessionAnomalyScorer(
            config=self._config, feature_store=self._feature_store
        )
        self._kafka_producer = kafka_producer

    async def assess(
        self,
        session_event: dict[str, Any],
        profile: UserBehaviorProfile | None,
        db_session: AsyncSession,
        feast_features: dict[str, Any] | None = None,
        anomaly_result: SessionAnomalyResult | None = None,
    ) -> ATOAssessment:
        """Run the full ATO assessment pipeline.

        1. Score session anomaly (if not already provided)
        2. Aggregate ATO signals
        3. Compute ATO risk score with correlation boosting
        4. Generate alert if warranted
        5. Persist and publish

        Args:
            session_event: Session event data.
            profile: User's behavioral profile.
            db_session: Database session for persistence.
            feast_features: Override Feast features for testing.
            anomaly_result: Pre-computed anomaly result (optional).

        Returns:
            ATOAssessment with risk score and response recommendation.
        """
        user_id = session_event.get("user_id", "unknown")
        session_id = session_event.get("session_id", "unknown")
        now = datetime.now(UTC)
        ato_cfg = self._config.ato

        # Step 1: Get anomaly score
        if anomaly_result is None:
            anomaly_result = await self._anomaly_scorer.score_session(
                session_event, profile, feast_features
            )

        # Step 2: Aggregate ATO signals
        signals = self._aggregate_signals(
            session_event, profile, anomaly_result, feast_features or {}
        )

        # Step 3: Compute ATO risk score with correlation
        ato_risk_score = self._compute_ato_risk_score(signals)

        # Step 4: Determine risk level and response
        risk_level = self._classify_risk(ato_risk_score)
        response = self._recommend_response(risk_level)

        # Get affected transactions
        affected_txns = session_event.get("pending_transactions", []) or []

        assessment = ATOAssessment(
            session_id=session_id,
            user_id=user_id,
            ato_risk_score=round(ato_risk_score, 4),
            risk_level=risk_level,
            contributing_signals=signals,
            recommended_response=response,
            affected_transactions=affected_txns,
            timestamp=now,
        )

        # Step 5: Generate alert for high/critical risk
        alert = None
        if risk_level in (ATORiskLevel.HIGH, ATORiskLevel.CRITICAL):
            alert = await self._create_alert(assessment, db_session)

        logger.info(
            "ato_assessed",
            session_id=session_id,
            user_id=user_id,
            ato_risk_score=assessment.ato_risk_score,
            risk_level=risk_level.value,
            signal_count=len([s for s in signals if s.score > 0.0]),
            alert_created=alert is not None,
        )

        return assessment

    def _aggregate_signals(
        self,
        session_event: dict[str, Any],
        profile: UserBehaviorProfile | None,
        anomaly_result: SessionAnomalyResult,
        features: dict[str, Any],
    ) -> list[ATOSignal]:
        """Aggregate multiple signals into the ATO assessment."""
        signals = []

        # Signal 1: Session anomaly score
        if anomaly_result.composite_score > 0.0:
            signals.append(ATOSignal(
                signal_name="session_anomaly",
                score=anomaly_result.composite_score,
                details=f"Classification: {anomaly_result.classification.value}",
            ))

        # Signal 2: Failed login attempts
        failed_10m = session_event.get("failed_login_count_10m", 0)
        failed_1h = session_event.get("failed_login_count_1h", 0)
        feast_login_10m = features.get("login_count_10m", 0)
        feast_login_1h = features.get("login_count_1h", 0)
        # Use max of provided and feast values
        failed_10m = max(failed_10m, feast_login_10m)
        failed_1h = max(failed_1h, feast_login_1h)

        if failed_10m >= self._config.ato.failed_logins_10m_warning:
            login_score = min(failed_10m / 10.0, 1.0)
            signals.append(ATOSignal(
                signal_name="failed_logins",
                score=login_score,
                details=f"{failed_10m} failed logins in 10m, {failed_1h} in 1h",
            ))

        # Signal 3: New device + new location simultaneously
        device_id = session_event.get("device_id")
        geo = session_event.get("geo_location")
        new_device = False
        new_location = False

        if device_id and profile and profile.device_baseline.known_devices:
            new_device = device_id not in profile.device_baseline.known_devices
        elif features.get("new_device_flag"):
            new_device = True

        if geo and profile and profile.geographic_baseline.known_locations:
            city = geo.get("city", "")
            country = geo.get("country", "")
            new_location = not any(
                loc.get("city") == city and loc.get("country") == country
                for loc in profile.geographic_baseline.known_locations
            )

        if new_device and new_location:
            signals.append(ATOSignal(
                signal_name="new_device_and_location",
                score=0.7,
                details="Simultaneous new device and new location",
            ))
        elif new_device:
            signals.append(ATOSignal(
                signal_name="new_device",
                score=0.3,
                details="New device detected",
            ))

        # Signal 4: Sensitive actions in session
        actions = session_event.get("actions", [])
        sensitive_actions = self._config.ato.sensitive_actions
        sensitive_in_session = [a for a in actions if a in sensitive_actions]
        if sensitive_in_session:
            sensitive_score = min(len(sensitive_in_session) / 3.0, 1.0)
            signals.append(ATOSignal(
                signal_name="sensitive_actions",
                score=sensitive_score,
                details=f"Sensitive actions: {', '.join(sensitive_in_session)}",
            ))

        # Signal 5: Impossible travel
        max_travel_speed = features.get("max_travel_speed_24h", 0)
        if max_travel_speed > self._config.anomaly_thresholds.impossible_travel_speed_kmh:
            signals.append(ATOSignal(
                signal_name="impossible_travel",
                score=0.9,
                details=f"Travel speed: {max_travel_speed:.0f} km/h",
            ))

        # Signal 6: Rapid navigation to sensitive areas
        if actions and len(sensitive_in_session) >= 2:
            # Check if sensitive actions happen early in the session
            first_sensitive_idx = next(
                (i for i, a in enumerate(actions) if a in sensitive_actions), len(actions)
            )
            if first_sensitive_idx <= 2:  # within first 3 actions
                signals.append(ATOSignal(
                    signal_name="rapid_sensitive_navigation",
                    score=0.6,
                    details="Rapid navigation to sensitive settings",
                ))

        return signals

    def _compute_ato_risk_score(self, signals: list[ATOSignal]) -> float:
        """Compute ATO risk score with correlation boosting.

        Individual signals are moderate risk. Correlated signals are
        exponentially more suspicious.
        """
        ato_cfg = self._config.ato

        if not signals:
            return 0.0

        # Filter to active signals (score > 0)
        active_signals = [s for s in signals if s.score > 0.0]
        if not active_signals:
            return 0.0

        # Base score: weighted average of signal scores
        signal_weights = {
            "session_anomaly": ato_cfg.anomaly_score_weight,
            "failed_logins": ato_cfg.failed_logins_weight,
            "new_device_and_location": ato_cfg.new_device_location_weight,
            "new_device": ato_cfg.new_device_location_weight * 0.5,
            "sensitive_actions": ato_cfg.sensitive_actions_weight,
            "impossible_travel": ato_cfg.impossible_travel_weight,
            "rapid_sensitive_navigation": ato_cfg.sensitive_actions_weight * 0.5,
        }

        weighted_sum = 0.0
        total_weight = 0.0
        for signal in active_signals:
            weight = signal_weights.get(signal.signal_name, 0.1)
            weighted_sum += signal.score * weight
            total_weight += weight

        base_score = weighted_sum / max(total_weight, 0.01)

        # Correlation boosting
        active_count = len(active_signals)
        if active_count >= 3:
            base_score *= ato_cfg.three_signal_multiplier
        elif active_count >= 2:
            base_score *= ato_cfg.two_signal_multiplier

        return min(base_score, 1.0)

    def _classify_risk(self, score: float) -> ATORiskLevel:
        """Classify ATO risk score into risk levels."""
        ato_cfg = self._config.ato
        if score >= ato_cfg.high_max:
            return ATORiskLevel.CRITICAL
        elif score >= ato_cfg.moderate_max:
            return ATORiskLevel.HIGH
        elif score >= ato_cfg.low_max:
            return ATORiskLevel.MODERATE
        return ATORiskLevel.LOW

    def _recommend_response(self, risk_level: ATORiskLevel) -> ATOResponseAction:
        """Map risk level to recommended response action."""
        mapping = {
            ATORiskLevel.LOW: ATOResponseAction.NONE,
            ATORiskLevel.MODERATE: ATOResponseAction.RE_AUTH,
            ATORiskLevel.HIGH: ATOResponseAction.STEP_UP,
            ATORiskLevel.CRITICAL: ATOResponseAction.LOCK,
        }
        return mapping[risk_level]

    async def _create_alert(
        self,
        assessment: ATOAssessment,
        db_session: AsyncSession,
    ) -> ATOAlert | None:
        """Create an ATO alert if not deduplicated."""
        ato_cfg = self._config.ato

        # Check deduplication
        is_dup = await self._check_dedup(
            assessment.user_id, db_session, ato_cfg.alert_dedup_window_seconds
        )
        if is_dup:
            logger.info(
                "ato_alert_deduplicated",
                user_id=assessment.user_id,
                session_id=assessment.session_id,
            )
            return None

        alert_id = str(uuid.uuid4())

        alert = ATOAlert(
            alert_id=alert_id,
            user_id=assessment.user_id,
            session_id=assessment.session_id,
            ato_risk_score=assessment.ato_risk_score,
            risk_level=assessment.risk_level,
            contributing_signals=assessment.contributing_signals,
            recommended_response=assessment.recommended_response,
            affected_transactions=assessment.affected_transactions,
            created_at=assessment.timestamp,
            status=ATOAlertStatus.NEW,
        )

        # Persist to database using the Alert model
        severity = "critical" if assessment.risk_level == ATORiskLevel.CRITICAL else "high"
        alert_row = AlertDB(
            alert_id=alert_id,
            user_id=assessment.user_id,
            alert_type="ato_detection",
            severity=severity,
            details={
                "session_id": assessment.session_id,
                "ato_risk_score": assessment.ato_risk_score,
                "risk_level": assessment.risk_level.value,
                "recommended_response": assessment.recommended_response.value,
                "contributing_signals": [s.model_dump() for s in assessment.contributing_signals],
                "affected_transactions": assessment.affected_transactions,
            },
            status="new",
            created_at=assessment.timestamp,
        )
        db_session.add(alert_row)
        await db_session.commit()

        # Publish to Kafka
        await self._publish_alert(alert)

        # Cross-domain notifications
        await self._notify_fraud_pipeline(assessment)
        await self._notify_circle_health(assessment)

        logger.warning(
            "ato_alert_created",
            alert_id=alert_id,
            user_id=assessment.user_id,
            session_id=assessment.session_id,
            ato_risk_score=assessment.ato_risk_score,
            risk_level=assessment.risk_level.value,
            severity=severity,
        )

        return alert

    async def _check_dedup(
        self,
        user_id: str,
        db_session: AsyncSession,
        window_seconds: int,
    ) -> bool:
        """Check if a similar ATO alert already exists within the dedup window."""
        cutoff = datetime.now(UTC) - timedelta(seconds=window_seconds)

        stmt = select(func.count()).where(
            AlertDB.user_id == user_id,
            AlertDB.alert_type == "ato_detection",
            AlertDB.status.in_(["new", "investigating"]),
            AlertDB.created_at >= cutoff,
        )
        result = await db_session.execute(stmt)
        count = result.scalar_one()
        return count > 0

    async def _publish_alert(self, alert: ATOAlert) -> None:
        """Publish ATO alert to Kafka topic."""
        if self._kafka_producer is None:
            logger.debug("kafka_producer_not_available", alert_id=alert.alert_id)
            return

        topic = self._config.ato.kafka_topic
        payload = {
            "alert_id": alert.alert_id,
            "user_id": alert.user_id,
            "session_id": alert.session_id,
            "ato_risk_score": alert.ato_risk_score,
            "risk_level": alert.risk_level.value,
            "recommended_response": alert.recommended_response.value,
            "contributing_signals": [s.model_dump() for s in alert.contributing_signals],
            "affected_transactions": alert.affected_transactions,
            "status": alert.status.value,
            "created_at": alert.created_at.isoformat(),
        }

        try:
            await self._kafka_producer.send_and_wait(
                topic,
                value=json.dumps(payload, default=str).encode("utf-8"),
                key=alert.user_id.encode("utf-8"),
            )
            logger.info("ato_alert_published", alert_id=alert.alert_id, topic=topic)
        except Exception:
            logger.exception("ato_alert_publish_failed", alert_id=alert.alert_id, topic=topic)

    async def _notify_fraud_pipeline(self, assessment: ATOAssessment) -> None:
        """Notify fraud pipeline to apply elevated scrutiny for this user.

        Cross-domain integration: when an ATO alert is generated, the fraud
        scoring pipeline should give elevated scrutiny to transactions from
        this user.
        """
        logger.info(
            "ato_fraud_pipeline_notified",
            user_id=assessment.user_id,
            ato_risk_score=assessment.ato_risk_score,
            action="elevated_scrutiny",
        )

    async def _notify_circle_health(self, assessment: ATOAssessment) -> None:
        """Notify circle health module when a circle member is under ATO investigation.

        Cross-domain integration: contributions from a compromised account
        shouldn't be treated as legitimate.
        """
        logger.info(
            "ato_circle_health_notified",
            user_id=assessment.user_id,
            ato_risk_score=assessment.ato_risk_score,
            action="flag_member_contributions",
        )

    async def get_alerts(
        self,
        db_session: AsyncSession,
        user_id: str | None = None,
        status: str | None = None,
        risk_level: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Query ATO alerts with filters.

        Returns:
            Tuple of (alert_list, total_count).
        """
        from sqlalchemy import desc

        # Build query
        stmt = select(AlertDB).where(AlertDB.alert_type == "ato_detection")
        count_stmt = select(func.count()).where(AlertDB.alert_type == "ato_detection")

        if user_id:
            stmt = stmt.where(AlertDB.user_id == user_id)
            count_stmt = count_stmt.where(AlertDB.user_id == user_id)
        if status:
            stmt = stmt.where(AlertDB.status == status)
            count_stmt = count_stmt.where(AlertDB.status == status)
        if risk_level:
            stmt = stmt.where(AlertDB.severity == risk_level)
            count_stmt = count_stmt.where(AlertDB.severity == risk_level)
        if start_date:
            stmt = stmt.where(AlertDB.created_at >= start_date)
            count_stmt = count_stmt.where(AlertDB.created_at >= start_date)
        if end_date:
            stmt = stmt.where(AlertDB.created_at <= end_date)
            count_stmt = count_stmt.where(AlertDB.created_at <= end_date)

        # Get count
        count_result = await db_session.execute(count_stmt)
        total = count_result.scalar_one()

        # Get results
        stmt = stmt.order_by(desc(AlertDB.created_at)).offset(offset).limit(limit)
        result = await db_session.execute(stmt)
        rows = result.scalars().all()

        alerts = [
            {
                "alert_id": r.alert_id,
                "user_id": r.user_id,
                "alert_type": r.alert_type,
                "severity": r.severity,
                "details": r.details,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            }
            for r in rows
        ]

        return alerts, total

    async def update_alert_status(
        self,
        alert_id: str,
        update: ATOAlertUpdate,
        db_session: AsyncSession,
    ) -> dict[str, Any] | None:
        """Update an ATO alert's status."""
        stmt = select(AlertDB).where(
            AlertDB.alert_id == alert_id,
            AlertDB.alert_type == "ato_detection",
        )
        result = await db_session.execute(stmt)
        row = result.scalar_one_or_none()

        if row is None:
            return None

        row.status = update.status.value
        if update.status in (ATOAlertStatus.RESOLVED, ATOAlertStatus.FALSE_POSITIVE, ATOAlertStatus.CONFIRMED_ATO):
            row.resolved_at = datetime.now(UTC)

        await db_session.commit()

        logger.info(
            "ato_alert_status_updated",
            alert_id=alert_id,
            new_status=update.status.value,
        )

        return {
            "alert_id": row.alert_id,
            "user_id": row.user_id,
            "status": row.status,
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        }
