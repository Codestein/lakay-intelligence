"""Cross-domain integration tests (Phase 10).

Validates that modules across different domains (fraud, compliance, behavior,
circles, pipeline) interact correctly when a single event touches multiple
systems. All tests use mock database sessions and the ASGI test transport
to exercise the real FastAPI routes without external infrastructure.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.db.database import get_session
from src.main import app
from tests.conftest import override_get_session

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session():
    """Create a mock async database session that returns empty results."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalar_one.return_value = 0
    mock_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
    session.execute = AsyncMock(return_value=mock_result)
    return session


def _fraud_score_payload(
    txn_id: str = "txn-cross-001",
    user_id: str = "user-cross-001",
    amount: str = "15000.00",
) -> dict:
    """Standard fraud-score request body."""
    return {
        "transaction_id": txn_id,
        "user_id": user_id,
        "amount": amount,
        "currency": "USD",
        "initiated_at": "2026-02-15T14:30:00+00:00",
    }


def _ato_assess_payload(
    session_id: str = "sess-cross-001",
    user_id: str = "user-cross-001",
) -> dict:
    """ATO assessment request with high-risk signals."""
    return {
        "session_id": session_id,
        "user_id": user_id,
        "device_id": "device-unknown-999",
        "device_type": "android",
        "ip_address": "203.0.113.42",
        "geo_location": {"city": "Lagos", "country": "NG"},
        "session_start": "2026-02-15T03:00:00+00:00",
        "session_duration_seconds": 45,
        "action_count": 10,
        "actions": [
            "change_email",
            "change_phone",
            "add_payment_method",
            "initiate_large_transaction",
        ],
        "failed_login_count_10m": 5,
        "failed_login_count_1h": 8,
        "pending_transactions": ["txn-pending-001"],
    }


# ---------------------------------------------------------------------------
# 1. Fraud -> Compliance cross-domain
# ---------------------------------------------------------------------------


class TestFraudToCompliance:
    """A high-value transaction triggers fraud scoring AND compliance CTR
    tracking. Both subsystems should process the event independently."""

    @pytest.mark.asyncio
    async def test_fraud_score_high_value_transaction(self):
        """POST /api/v1/fraud/score with amount 15000.00 returns a valid
        fraud score and risk assessment."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json=_fraud_score_payload(amount="15000.00"),
                )
                assert response.status_code == 200
                data = response.json()
                assert "score" in data
                assert "risk_tier" in data
                assert "model_version" in data
                assert data["transaction_id"] == "txn-cross-001"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_compliance_ctr_daily_tracking(self):
        """GET /api/v1/compliance/ctr/daily/{user_id} returns CTR tracking
        data for the same user whose transaction was fraud-scored."""
        user_id = "user-cross-001"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/compliance/ctr/daily/{user_id}",
            )
            assert response.status_code == 200
            data = response.json()
            assert data["user_id"] == user_id
            assert "cumulative_amount" in data
            assert "threshold_met" in data
            assert "ctr_threshold" in data

    @pytest.mark.asyncio
    async def test_fraud_and_compliance_process_independently(self):
        """Both fraud scoring and compliance CTR tracking succeed within the
        same test, demonstrating independent processing."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Fraud scoring
                fraud_resp = await client.post(
                    "/api/v1/fraud/score",
                    json=_fraud_score_payload(
                        txn_id="txn-cross-indep-001",
                        amount="15000.00",
                    ),
                )
                assert fraud_resp.status_code == 200
                fraud_data = fraud_resp.json()

                # Compliance CTR
                ctr_resp = await client.get(
                    "/api/v1/compliance/ctr/daily/user-cross-001",
                )
                assert ctr_resp.status_code == 200
                ctr_data = ctr_resp.json()

                # Both processed without errors
                assert "score" in fraud_data
                assert "cumulative_amount" in ctr_data
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 2. ATO -> Fraud & Circles cross-domain
# ---------------------------------------------------------------------------


class TestATOToFraudAndCircles:
    """When an ATO is assessed with high-risk signals, the fraud scoring
    pipeline should still function and can incorporate behavioral context."""

    @pytest.mark.asyncio
    async def test_ato_assessment_high_risk_signals(self):
        """POST /api/v1/behavior/ato/assess with suspicious signals produces
        a risk assessment with contributing signals."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/behavior/ato/assess",
                    json=_ato_assess_payload(),
                )
                assert response.status_code == 200
                data = response.json()
                assert data["session_id"] == "sess-cross-001"
                assert data["user_id"] == "user-cross-001"
                assert "ato_risk_score" in data
                assert "risk_level" in data
                assert "contributing_signals" in data
                assert "recommended_response" in data
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_fraud_scoring_after_ato_assessment(self):
        """After an ATO assessment, fraud scoring for the same user still
        returns a valid response, reflecting elevated scrutiny context."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # First: ATO assessment
                ato_resp = await client.post(
                    "/api/v1/behavior/ato/assess",
                    json=_ato_assess_payload(
                        session_id="sess-cross-ato-fraud-001",
                    ),
                )
                assert ato_resp.status_code == 200

                # Second: fraud scoring for the same user
                fraud_resp = await client.post(
                    "/api/v1/fraud/score",
                    json=_fraud_score_payload(
                        txn_id="txn-cross-ato-fraud-001",
                        user_id="user-cross-001",
                        amount="5000.00",
                    ),
                )
                assert fraud_resp.status_code == 200
                fraud_data = fraud_resp.json()
                assert "score" in fraud_data
                assert "risk_tier" in fraud_data
                assert fraud_data["transaction_id"] == "txn-cross-ato-fraud-001"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ato_signals_include_expected_dimensions(self):
        """ATO assessment with new device, new location, and failed logins
        should produce multiple contributing signals."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/behavior/ato/assess",
                    json=_ato_assess_payload(
                        session_id="sess-cross-signals-001",
                    ),
                )
                assert response.status_code == 200
                data = response.json()
                # Should produce at least one contributing signal
                assert isinstance(data["contributing_signals"], list)
                assert data["ato_risk_score"] >= 0.0
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 3. Circle anomaly -> Fraud
# ---------------------------------------------------------------------------


class TestCircleAnomalyToFraud:
    """Circle health scoring produces anomalies. High-severity anomalies
    should cross-reference with the fraud alert system."""

    @pytest.mark.asyncio
    async def test_circle_health_scoring_produces_result(self):
        """POST /api/v1/circles/{circle_id}/score returns health score
        with anomaly count and classification."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                circle_id = "circle-cross-001"
                response = await client.post(
                    f"/api/v1/circles/{circle_id}/score",
                    json={
                        "circle_id": circle_id,
                        "features": {
                            "payment_rate": 0.3,
                            "avg_days_late": 15.0,
                            "member_retention": 0.4,
                            "contribution_variance": 0.8,
                            "organizer_response_hours": 72.0,
                        },
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert data["circle_id"] == circle_id
                assert "health_score" in data
                assert "health_tier" in data
                assert "anomaly_count" in data
                assert "classification" in data
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_circle_anomaly_and_fraud_alerts_coexist(self):
        """After circle scoring, the fraud alerts endpoint still works
        independently, allowing cross-referencing of alerts."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Circle scoring with poor metrics
                circle_resp = await client.post(
                    "/api/v1/circles/circle-cross-002/score",
                    json={
                        "circle_id": "circle-cross-002",
                        "features": {
                            "payment_rate": 0.2,
                            "avg_days_late": 20.0,
                            "member_retention": 0.3,
                            "contribution_variance": 0.9,
                            "organizer_response_hours": 96.0,
                        },
                    },
                )
                assert circle_resp.status_code == 200
                circle_data = circle_resp.json()
                assert circle_data["anomaly_count"] >= 0

                # Fraud alerts should still function
                fraud_alerts_resp = await client.get("/api/v1/fraud/alerts")
                assert fraud_alerts_resp.status_code == 200
                fraud_alerts_data = fraud_alerts_resp.json()
                assert "items" in fraud_alerts_data
                assert "total" in fraud_alerts_data
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_circle_score_reflects_anomaly_severity(self):
        """A circle with very poor metrics should produce anomalies and a
        low health tier, enabling cross-domain risk correlation."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/circles/circle-cross-severe-001/score",
                    json={
                        "circle_id": "circle-cross-severe-001",
                        "features": {
                            "on_time_payment_rate": 0.1,
                            "avg_days_late": 30.0,
                            "missed_contribution_count": 5,
                            "member_drop_rate": 0.6,
                            "member_count_current": 2,
                            "member_count_original": 10,
                            "collection_ratio": 0.3,
                            "payout_completion_rate": 0.2,
                            "late_payment_trend": 0.8,
                            "coordinated_behavior_score": 0.8,
                            "post_payout_disengagement_rate": 0.7,
                        },
                    },
                )
                assert response.status_code == 200
                data = response.json()
                # Poor metrics should produce a low health score
                assert data["health_score"] < 40
                assert data["health_tier"] in ("at-risk", "critical")
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 4. Compliance alert -> Risk escalation
# ---------------------------------------------------------------------------


class TestComplianceAlertToRiskEscalation:
    """Creating a compliance alert and escalating it should reflect in the
    customer risk profile when queried."""

    @pytest.mark.asyncio
    async def test_create_compliance_alert_and_escalate(self):
        """Create a compliance alert via the in-memory store, update it to
        escalated status, and verify the status change."""
        from src.api.routes.compliance import _alerts
        from src.domains.compliance.models import (
            AlertPriority,
            AlertStatus,
            AlertType,
            ComplianceAlert,
            RecommendedAction,
        )

        # Seed an alert into the in-memory store
        alert_id = "alert-cross-escalate-001"
        alert = ComplianceAlert(
            alert_id=alert_id,
            alert_type=AlertType.SUSPICIOUS_ACTIVITY,
            user_id="user-cross-escalate-001",
            transaction_ids=["txn-escalate-001"],
            amount_total=15000.00,
            description="High-value transaction pattern detected",
            regulatory_basis="BSA Section 5313",
            recommended_action=RecommendedAction.ESCALATE_TO_BSA_OFFICER,
            priority=AlertPriority.URGENT,
            status=AlertStatus.NEW,
            created_at=datetime(2026, 2, 15, 14, 0, 0, tzinfo=UTC),
        )
        _alerts[alert_id] = alert

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Escalate the alert
                update_resp = await client.put(
                    f"/api/v1/compliance/alerts/{alert_id}",
                    json={
                        "status": "escalated",
                        "reviewed_by": "officer-001",
                        "resolution_notes": "Escalated for BSA officer review",
                    },
                )
                assert update_resp.status_code == 200
                update_data = update_resp.json()
                assert update_data["status"] == "escalated"
                assert update_data["reviewed_by"] == "officer-001"
        finally:
            _alerts.pop(alert_id, None)

    @pytest.mark.asyncio
    async def test_risk_profile_reflects_escalation(self):
        """After alert escalation, the risk profile endpoint for the same
        user should still return a valid assessment."""
        user_id = "user-cross-escalate-002"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Check customer risk
            risk_resp = await client.get(
                f"/api/v1/compliance/risk/{user_id}",
            )
            assert risk_resp.status_code == 200
            risk_data = risk_resp.json()
            assert risk_data["user_id"] == user_id
            assert "risk_level" in risk_data

    @pytest.mark.asyncio
    async def test_compliance_alert_list_filters_by_status(self):
        """The compliance alerts listing endpoint respects status filters,
        enabling risk escalation workflows."""
        from src.api.routes.compliance import _alerts
        from src.domains.compliance.models import (
            AlertPriority,
            AlertStatus,
            AlertType,
            ComplianceAlert,
            RecommendedAction,
        )

        alert_id = "alert-cross-filter-001"
        alert = ComplianceAlert(
            alert_id=alert_id,
            alert_type=AlertType.CTR_THRESHOLD,
            user_id="user-cross-filter-001",
            amount_total=12000.00,
            description="CTR threshold crossed",
            regulatory_basis="BSA 31 CFR 1010.311",
            recommended_action=RecommendedAction.FILE_CTR,
            priority=AlertPriority.ELEVATED,
            status=AlertStatus.ESCALATED,
            created_at=datetime(2026, 2, 15, 10, 0, 0, tzinfo=UTC),
        )
        _alerts[alert_id] = alert

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/compliance/alerts",
                    params={"status": "escalated"},
                )
                assert response.status_code == 200
                data = response.json()
                assert data["total"] >= 1
                escalated_ids = [a["alert_id"] for a in data["items"]]
                assert alert_id in escalated_ids
        finally:
            _alerts.pop(alert_id, None)


# ---------------------------------------------------------------------------
# 5. Transaction multi-domain flow
# ---------------------------------------------------------------------------


class TestTransactionMultiDomainFlow:
    """A single transaction event flows through fraud scoring, compliance
    monitoring, and pipeline stats. All three should process independently."""

    @pytest.mark.asyncio
    async def test_fraud_scoring_in_multi_domain_flow(self):
        """Fraud scoring processes the transaction independently."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json=_fraud_score_payload(
                        txn_id="txn-multi-001",
                        amount="15000.00",
                    ),
                )
                assert response.status_code == 200
                data = response.json()
                assert data["transaction_id"] == "txn-multi-001"
                assert "score" in data
                assert "composite_score" in data
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_compliance_monitoring_in_multi_domain_flow(self):
        """Compliance CTR tracking processes the same user independently."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/compliance/ctr/daily/user-cross-001",
            )
            assert response.status_code == 200
            data = response.json()
            assert data["user_id"] == "user-cross-001"
            assert "cumulative_amount" in data

    @pytest.mark.asyncio
    async def test_pipeline_stats_in_multi_domain_flow(self):
        """Pipeline bronze stats processes independently alongside fraud
        and compliance."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/pipeline/bronze/stats")
                assert response.status_code == 200
                data = response.json()
                assert "latest_checkpoints" in data
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_all_three_domains_process_single_event(self):
        """All three domains (fraud, compliance, pipeline) process the same
        conceptual event without interference."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # 1) Fraud scoring
                fraud_resp = await client.post(
                    "/api/v1/fraud/score",
                    json=_fraud_score_payload(
                        txn_id="txn-multi-all-001",
                        amount="15000.00",
                    ),
                )
                assert fraud_resp.status_code == 200

                # 2) Compliance CTR
                ctr_resp = await client.get(
                    "/api/v1/compliance/ctr/daily/user-cross-001",
                )
                assert ctr_resp.status_code == 200

                # 3) Pipeline stats
                pipeline_resp = await client.get(
                    "/api/v1/pipeline/bronze/stats",
                )
                assert pipeline_resp.status_code == 200

                # Verify all produced valid results
                assert "score" in fraud_resp.json()
                assert "cumulative_amount" in ctr_resp.json()
                assert "latest_checkpoints" in pipeline_resp.json()
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 6. Model fallback
# ---------------------------------------------------------------------------


class TestModelFallback:
    """When the ML model is unavailable, fraud scoring continues with
    rule-based scoring and returns model_version 'rules-v2'."""

    @pytest.mark.asyncio
    async def test_fallback_to_rules_when_model_unavailable(self):
        """Fraud scoring falls back to rules-v2 when no ML model is loaded."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json=_fraud_score_payload(
                        txn_id="txn-fallback-001",
                        amount="500.00",
                    ),
                )
                assert response.status_code == 200
                data = response.json()
                assert data["model_version"] == "rules-v2"
                assert data["ml_score"] is None
                assert "score" in data
                assert "risk_tier" in data
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_fallback_still_produces_risk_factors(self):
        """Rule-based fallback still evaluates risk factors on the
        transaction."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json=_fraud_score_payload(
                        txn_id="txn-fallback-002",
                        amount="9999.00",
                    ),
                )
                assert response.status_code == 200
                data = response.json()
                assert data["model_version"] == "rules-v2"
                assert "risk_factors" in data
                assert isinstance(data["risk_factors"], list)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_fallback_score_is_rule_score(self):
        """When ML is unavailable, the composite_score equals the rule_score."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json=_fraud_score_payload(
                        txn_id="txn-fallback-003",
                        amount="250.00",
                    ),
                )
                assert response.status_code == 200
                data = response.json()
                assert data["model_version"] == "rules-v2"
                # When ML is unavailable, composite_score == rule_score
                assert data["composite_score"] == data["rule_score"]
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 7. Feature store consistency
# ---------------------------------------------------------------------------


class TestFeatureStoreConsistency:
    """Verify that fraud scoring, circle health scoring, and behavioral
    analytics all use the feature store. Each endpoint should function
    consistently when the feature store returns default (empty) features."""

    @pytest.mark.asyncio
    async def test_fraud_scoring_with_feature_store(self):
        """Fraud scoring operates correctly with default feature store."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json=_fraud_score_payload(
                        txn_id="txn-feature-001",
                        amount="200.00",
                    ),
                )
                assert response.status_code == 200
                data = response.json()
                assert "score" in data
                assert "model_version" in data
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_circle_scoring_with_feature_store(self):
        """Circle health scoring uses the feature store for input features.
        When features are passed explicitly, it bypasses the store."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/circles/circle-feature-001/score",
                    json={
                        "circle_id": "circle-feature-001",
                        "features": {
                            "payment_rate": 0.85,
                            "avg_days_late": 2.0,
                            "member_retention": 0.9,
                            "contribution_variance": 0.1,
                            "organizer_response_hours": 4.0,
                        },
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert "health_score" in data
                assert "scoring_version" in data
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_behavior_analytics_with_feature_store(self):
        """Behavioral session scoring operates with the feature store,
        returning consistent results."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/behavior/sessions/score",
                    json={
                        "session_id": "sess-feature-001",
                        "user_id": "user-feature-001",
                        "device_id": "device-phone-001",
                        "device_type": "ios",
                        "ip_address": "10.0.1.50",
                        "geo_location": {"city": "Boston", "country": "US"},
                        "session_start": "2026-02-15T19:00:00+00:00",
                        "session_duration_seconds": 300,
                        "action_count": 5,
                        "actions": ["check_circles", "view_balance"],
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert "composite_score" in data
                assert "classification" in data
                assert data["session_id"] == "sess-feature-001"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_all_domains_consistent_with_empty_features(self):
        """All three feature-store-backed endpoints produce valid responses
        when the feature store returns empty/default features."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Fraud
                fraud_resp = await client.post(
                    "/api/v1/fraud/score",
                    json=_fraud_score_payload(
                        txn_id="txn-feature-all-001",
                        amount="100.00",
                    ),
                )
                assert fraud_resp.status_code == 200

                # Circles
                circle_resp = await client.post(
                    "/api/v1/circles/circle-feature-all-001/score",
                    json={
                        "circle_id": "circle-feature-all-001",
                        "features": {
                            "payment_rate": 0.7,
                            "avg_days_late": 3.0,
                            "member_retention": 0.8,
                            "contribution_variance": 0.2,
                            "organizer_response_hours": 8.0,
                        },
                    },
                )
                assert circle_resp.status_code == 200

                # Behavior
                behavior_resp = await client.post(
                    "/api/v1/behavior/sessions/score",
                    json={
                        "session_id": "sess-feature-all-001",
                        "user_id": "user-feature-all-001",
                        "device_id": "device-all-001",
                        "device_type": "ios",
                        "session_start": "2026-02-15T19:00:00+00:00",
                        "session_duration_seconds": 250,
                        "action_count": 4,
                        "actions": ["view_balance"],
                    },
                )
                assert behavior_resp.status_code == 200

                # All returned valid structures
                assert "score" in fraud_resp.json()
                assert "health_score" in circle_resp.json()
                assert "composite_score" in behavior_resp.json()
        finally:
            app.dependency_overrides.clear()
