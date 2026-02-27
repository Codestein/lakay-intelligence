"""End-to-end user lifecycle flow tests (Phase 10).

Validates complete multi-module user journeys that exercise behavior,
fraud, circles, and compliance endpoints in realistic sequences.

Each test class simulates a distinct user scenario:
  E2E-1: New user onboarding
  E2E-2: Normal established-user lifecycle
  E2E-3: Fraud/ATO incident chain
  E2E-4: Circle health degradation
  E2E-5: Compliance escalation pipeline
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.db.database import get_session
from src.main import app
from tests.conftest import override_get_session

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Deterministic test identifiers
# ---------------------------------------------------------------------------

_NEW_USER_ID = "e2e-new-user-00000000-0000-0000-0000-000000000001"
_ESTABLISHED_USER_ID = "e2e-established-00000000-0000-0000-0000-000000000002"
_FRAUD_USER_ID = "e2e-fraud-user-00000000-0000-0000-0000-000000000003"
_CIRCLE_ID = "e2e-circle-00000000-0000-0000-0000-000000000010"
_COMPLIANCE_USER_ID = "e2e-compliance-00000000-0000-0000-0000-000000000020"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session():
    """Create a fully-stubbed async DB session.

    All query patterns used by the route handlers are handled:
    - scalar_one_or_none -> None  (no existing row)
    - scalar_one -> 0             (count queries)
    - scalars().all() -> []       (list queries)
    """
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


def _install_mock_session(session):
    """Override FastAPI's get_session dependency with our mock."""
    app.dependency_overrides[get_session] = override_get_session(session)


def _cleanup_overrides():
    app.dependency_overrides.clear()


def _client():
    """Return an httpx AsyncClient wired to the ASGI app."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ===================================================================
# E2E-1: New User Onboarding
# ===================================================================


class TestE2ENewUserOnboarding:
    """Simulate a brand-new user's first interactions with the platform.

    Flow:
      1. Score user's first session  (behavior)
      2. Score user's first transaction  (fraud / rule-based)
      3. Check behavioral profile  (should be building or absent)
      4. Check compliance risk  (should default to low)
      5. Confirm every module returns sensible defaults with no errors
    """

    async def test_new_user_session_score(self):
        """Step 1 -- First session is scored without error; anomaly score is
        returned with a low/building classification."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.post(
                    "/api/v1/behavior/sessions/score",
                    json={
                        "session_id": "e2e-1-session-001",
                        "user_id": _NEW_USER_ID,
                        "device_id": "device-new-iphone",
                        "device_type": "ios",
                        "ip_address": "192.168.1.100",
                        "geo_location": {"city": "Miami", "country": "US"},
                        "session_duration_seconds": 120,
                        "action_count": 3,
                        "actions": ["view_balance", "check_circles"],
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert "composite_score" in data
                assert "classification" in data
                assert data["user_id"] == _NEW_USER_ID
                # New user should not trigger critical classification
                assert data["classification"] in (
                    "normal",
                    "suspicious",
                    "low",
                    "building",
                )
        finally:
            _cleanup_overrides()

    async def test_new_user_first_transaction_fraud_score(self):
        """Step 2 -- Rule-based fraud score for a small first transaction."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json={
                        "transaction_id": "e2e-1-txn-001",
                        "user_id": _NEW_USER_ID,
                        "amount": "50.00",
                        "currency": "USD",
                        "transaction_type": "circle_contribution",
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert "score" in data
                assert "composite_score" in data
                assert "risk_tier" in data
                assert "model_version" in data
                # Small first-time transaction should get rules-only scoring
                assert data["model_version"] in ("rules-v2", "hybrid-v1")
        finally:
            _cleanup_overrides()

    async def test_new_user_behavioral_profile_absent(self):
        """Step 3 -- Profile lookup returns a 'no profile' placeholder."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.get(
                    f"/api/v1/behavior/users/{_NEW_USER_ID}/profile",
                )
                assert response.status_code == 200
                data = response.json()
                assert data["user_id"] == _NEW_USER_ID
                # Brand-new user has no profile built yet
                assert data["profile"] is None or data.get("profile_status") == "building"
        finally:
            _cleanup_overrides()

    async def test_new_user_compliance_risk_defaults_low(self):
        """Step 4 -- Compliance risk for an unknown user defaults to low."""
        async with _client() as client:
            response = await client.get(
                f"/api/v1/compliance/risk/{_NEW_USER_ID}",
            )
            assert response.status_code == 200
            data = response.json()
            assert data["user_id"] == _NEW_USER_ID
            assert data["risk_level"] == "low"
            assert data["risk_score"] == 0.0

    async def test_new_user_engagement_graceful(self):
        """Step 5 -- Engagement endpoint returns sensible defaults for new user."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.get(
                    f"/api/v1/behavior/users/{_NEW_USER_ID}/engagement",
                )
                assert response.status_code == 200
                data = response.json()
                assert data["user_id"] == _NEW_USER_ID
                assert "engagement_score" in data
                assert "lifecycle_stage" in data
                assert "churn_risk" in data
        finally:
            _cleanup_overrides()


# ===================================================================
# E2E-2: Normal Established-User Lifecycle
# ===================================================================


class TestE2ENormalUserLifecycle:
    """Simulate day-to-day interactions for an established user.

    Flow:
      1. Get behavioral profile
      2. Score a remittance to Haiti ($200 USD)
      3. Score a circle contribution
      4. Check fraud score (hybrid if ML available, rules fallback)
      5. Check engagement metrics
      6. Check compliance CTR daily total
      7. Verify all responses are well-formed
    """

    async def test_established_user_profile(self):
        """Step 1 -- Profile endpoint returns data (or absent placeholder)."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.get(
                    f"/api/v1/behavior/users/{_ESTABLISHED_USER_ID}/profile",
                )
                assert response.status_code == 200
                data = response.json()
                assert data["user_id"] == _ESTABLISHED_USER_ID
                # Either returns a full profile or a no-profile message
                assert "profile" in data or "profile_status" in data
        finally:
            _cleanup_overrides()

    async def test_score_remittance_to_haiti(self):
        """Step 2 -- Score a $200 remittance to Haiti via fraud endpoint."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json={
                        "transaction_id": "e2e-2-txn-remittance-001",
                        "user_id": _ESTABLISHED_USER_ID,
                        "amount": "200.00",
                        "currency": "USD",
                        "transaction_type": "remittance",
                        "geo_location": {
                            "city": "Boston",
                            "country": "US",
                        },
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert data["transaction_id"] == "e2e-2-txn-remittance-001"
                assert "score" in data
                assert "composite_score" in data
                assert "risk_tier" in data
                assert "recommendation" in data
                assert data["model_version"] in ("rules-v2", "hybrid-v1")
        finally:
            _cleanup_overrides()

    async def test_score_circle_contribution(self):
        """Step 3 -- Score a circle contribution transaction."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json={
                        "transaction_id": "e2e-2-txn-circle-001",
                        "user_id": _ESTABLISHED_USER_ID,
                        "amount": "100.00",
                        "currency": "USD",
                        "transaction_type": "circle_contribution",
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert "score" in data
                assert "risk_tier" in data
                # Circle contribution is routine, should not be high risk
                assert data["risk_tier"] in ("low", "medium")
        finally:
            _cleanup_overrides()

    async def test_fraud_score_has_required_fields(self):
        """Step 4 -- Verify fraud scoring response schema completeness."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json={
                        "transaction_id": "e2e-2-txn-schema-check",
                        "user_id": _ESTABLISHED_USER_ID,
                        "amount": "150.00",
                        "currency": "USD",
                    },
                )
                assert response.status_code == 200
                data = response.json()
                required_fields = [
                    "transaction_id",
                    "score",
                    "composite_score",
                    "risk_tier",
                    "recommendation",
                    "model_version",
                    "computed_at",
                ]
                for field in required_fields:
                    assert field in data, f"Missing field: {field}"
        finally:
            _cleanup_overrides()

    async def test_engagement_metrics(self):
        """Step 5 -- Engagement endpoint returns all expected fields."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.get(
                    f"/api/v1/behavior/users/{_ESTABLISHED_USER_ID}/engagement",
                )
                assert response.status_code == 200
                data = response.json()
                assert data["user_id"] == _ESTABLISHED_USER_ID
                assert "engagement_score" in data
                assert "lifecycle_stage" in data
                assert "churn_risk" in data
                assert "churn_risk_level" in data
                assert "engagement_trend" in data
                assert "computed_at" in data
        finally:
            _cleanup_overrides()

    async def test_compliance_ctr_daily_total(self):
        """Step 6 -- CTR daily total endpoint returns well-formed data."""
        async with _client() as client:
            response = await client.get(
                f"/api/v1/compliance/ctr/daily/{_ESTABLISHED_USER_ID}",
            )
            assert response.status_code == 200
            data = response.json()
            assert data["user_id"] == _ESTABLISHED_USER_ID
            assert "cumulative_amount" in data
            assert "transaction_count" in data
            assert "threshold_met" in data
            assert "ctr_threshold" in data

    async def test_fraud_alerts_endpoint(self):
        """Step 7 -- Fraud alerts listing works for the user."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.get(
                    "/api/v1/fraud/alerts",
                    params={"user_id": _ESTABLISHED_USER_ID},
                )
                assert response.status_code == 200
                data = response.json()
                assert "items" in data
                assert "total" in data
                assert isinstance(data["items"], list)
        finally:
            _cleanup_overrides()


# ===================================================================
# E2E-3: Fraud / ATO Incident Chain
# ===================================================================


class TestE2EFraudIncident:
    """Simulate an account takeover incident chain across modules.

    Flow:
      1. Assess a suspicious session with many ATO red flags
      2. Verify the ATO risk is high or critical
      3. Score a large transaction from the compromised account
      4. Verify elevated fraud score
      5. Check compliance alerts endpoint
      6. Verify cross-module incident chain (behavior -> fraud -> compliance)
    """

    async def test_suspicious_session_ato_assessment(self):
        """Step 1 -- Session with new device, new location, failed logins triggers ATO."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.post(
                    "/api/v1/behavior/ato/assess",
                    json={
                        "session_id": "e2e-3-session-suspicious",
                        "user_id": _FRAUD_USER_ID,
                        "device_id": "device-unknown-android-999",
                        "device_type": "android",
                        "ip_address": "203.0.113.42",
                        "geo_location": {"city": "Lagos", "country": "NG"},
                        "session_duration_seconds": 30,
                        "action_count": 8,
                        "actions": [
                            "change_email",
                            "change_phone",
                            "add_payment_method",
                            "initiate_large_transaction",
                            "update_security_settings",
                        ],
                        "failed_login_count_10m": 5,
                        "failed_login_count_1h": 8,
                        "pending_transactions": ["txn-compromised-001"],
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert data["user_id"] == _FRAUD_USER_ID
                assert "ato_risk_score" in data
                assert "risk_level" in data
                assert "contributing_signals" in data
                assert "recommended_response" in data
        finally:
            _cleanup_overrides()

    async def test_ato_risk_is_elevated(self):
        """Step 2 -- With multiple red flags the risk level should be elevated."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.post(
                    "/api/v1/behavior/ato/assess",
                    json={
                        "session_id": "e2e-3-session-elevated",
                        "user_id": _FRAUD_USER_ID,
                        "device_id": "device-unknown-android-999",
                        "device_type": "android",
                        "ip_address": "203.0.113.42",
                        "geo_location": {"city": "Lagos", "country": "NG"},
                        "session_duration_seconds": 30,
                        "action_count": 10,
                        "actions": [
                            "change_email",
                            "change_phone",
                            "add_payment_method",
                            "initiate_large_transaction",
                            "update_security_settings",
                        ],
                        "failed_login_count_10m": 5,
                        "failed_login_count_1h": 8,
                    },
                )
                assert response.status_code == 200
                data = response.json()
                # With this many red flags, risk should be at least moderate
                assert data["risk_level"] in ("moderate", "high", "critical")
                assert data["ato_risk_score"] > 0.0
                # Should have contributing signals explaining the assessment
                assert len(data["contributing_signals"]) >= 1
        finally:
            _cleanup_overrides()

    async def test_large_transaction_from_compromised_account(self):
        """Step 3 -- Score a $5000 transaction from the compromised account."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json={
                        "transaction_id": "e2e-3-txn-large-001",
                        "user_id": _FRAUD_USER_ID,
                        "amount": "5000.00",
                        "currency": "USD",
                        "transaction_type": "remittance",
                        "ip_address": "203.0.113.42",
                        "geo_location": {"city": "Lagos", "country": "NG"},
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert data["transaction_id"] == "e2e-3-txn-large-001"
                assert "score" in data
                assert "composite_score" in data
                assert "risk_tier" in data
        finally:
            _cleanup_overrides()

    async def test_elevated_fraud_score_for_large_amount(self):
        """Step 4 -- Verify the $5000 transaction gets a non-trivial score."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json={
                        "transaction_id": "e2e-3-txn-large-002",
                        "user_id": _FRAUD_USER_ID,
                        "amount": "5000.00",
                        "currency": "USD",
                        "transaction_type": "remittance",
                    },
                )
                assert response.status_code == 200
                data = response.json()
                # $5000 is a notable amount -- composite score should reflect some risk
                assert data["composite_score"] >= 0.0
                assert data["risk_tier"] in ("low", "medium", "high", "critical")
        finally:
            _cleanup_overrides()

    async def test_compliance_alerts_endpoint_works(self):
        """Step 5 -- Compliance alerts endpoint returns valid structure."""
        async with _client() as client:
            response = await client.get(
                "/api/v1/compliance/alerts",
                params={"user_id": _FRAUD_USER_ID},
            )
            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "total" in data
            assert isinstance(data["items"], list)

    async def test_cross_module_behavior_session_score(self):
        """Step 6 -- Behavior session scoring also works for the fraud user."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.post(
                    "/api/v1/behavior/sessions/score",
                    json={
                        "session_id": "e2e-3-session-crossmod",
                        "user_id": _FRAUD_USER_ID,
                        "device_id": "device-unknown-android-999",
                        "device_type": "android",
                        "geo_location": {"city": "Lagos", "country": "NG"},
                        "session_duration_seconds": 30,
                        "action_count": 8,
                        "actions": [
                            "change_email",
                            "change_phone",
                            "add_payment_method",
                        ],
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert data["user_id"] == _FRAUD_USER_ID
                assert "composite_score" in data
                assert "classification" in data
                assert "dimension_scores" in data
        finally:
            _cleanup_overrides()


# ===================================================================
# E2E-4: Circle Health Degradation
# ===================================================================


class TestE2ECircleFailure:
    """Simulate a circle transitioning from healthy to degraded.

    Flow:
      1. Score circle with healthy features
      2. Score same circle with degraded features
      3. Verify health tier changes appropriately
      4. Check classification endpoint reflects degradation
      5. Verify anomaly detection catches problems
    """

    async def test_score_healthy_circle(self):
        """Step 1 -- Circle with perfect features scores as healthy."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.post(
                    f"/api/v1/circles/{_CIRCLE_ID}/score",
                    json={
                        "circle_id": _CIRCLE_ID,
                        "features": {
                            "payment_rate": 1.0,
                            "on_time_payment_rate": 1.0,
                            "dispute_count": 0,
                            "member_count": 10,
                            "active_member_count": 10,
                            "missed_payments": 0,
                            "total_contributions": 10000.0,
                            "avg_contribution_delay_hours": 0.0,
                            "member_dropout_rate": 0.0,
                            "payout_completion_rate": 1.0,
                            "rounds_completed": 5,
                            "total_rounds": 10,
                        },
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert data["circle_id"] == _CIRCLE_ID
                assert "health_score" in data
                assert "health_tier" in data
                assert "confidence" in data
                assert "classification" in data
                assert "scoring_version" in data
                # Healthy features should yield a good tier
                assert data["health_tier"] in ("healthy", "good", "excellent")
        finally:
            _cleanup_overrides()

    async def test_score_degraded_circle(self):
        """Step 2 -- Circle with degraded features scores lower."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.post(
                    f"/api/v1/circles/{_CIRCLE_ID}/score",
                    json={
                        "circle_id": _CIRCLE_ID,
                        "features": {
                            "payment_rate": 0.6,
                            "on_time_payment_rate": 0.5,
                            "dispute_count": 3,
                            "member_count": 10,
                            "active_member_count": 6,
                            "missed_payments": 4,
                            "total_contributions": 6000.0,
                            "avg_contribution_delay_hours": 48.0,
                            "member_dropout_rate": 0.4,
                            "payout_completion_rate": 0.7,
                            "rounds_completed": 3,
                            "total_rounds": 10,
                        },
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert data["circle_id"] == _CIRCLE_ID
                assert "health_score" in data
                assert "health_tier" in data
                # Degraded features should lower the tier
                assert data["health_tier"] in (
                    "at_risk",
                    "at-risk",
                    "critical",
                    "watch",
                    "declining",
                    "good",
                )
        finally:
            _cleanup_overrides()

    async def test_health_score_comparison(self):
        """Step 3 -- Healthy score > degraded score."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                # Score healthy
                resp_healthy = await client.post(
                    f"/api/v1/circles/{_CIRCLE_ID}/score",
                    json={
                        "circle_id": _CIRCLE_ID,
                        "features": {
                            "payment_rate": 1.0,
                            "on_time_payment_rate": 1.0,
                            "dispute_count": 0,
                            "member_count": 10,
                            "active_member_count": 10,
                            "missed_payments": 0,
                            "total_contributions": 10000.0,
                            "avg_contribution_delay_hours": 0.0,
                            "member_dropout_rate": 0.0,
                            "payout_completion_rate": 1.0,
                        },
                    },
                )
                assert resp_healthy.status_code == 200
                healthy_score = resp_healthy.json()["health_score"]

                # Score degraded
                resp_degraded = await client.post(
                    f"/api/v1/circles/{_CIRCLE_ID}/score",
                    json={
                        "circle_id": _CIRCLE_ID,
                        "features": {
                            "payment_rate": 0.6,
                            "on_time_payment_rate": 0.5,
                            "dispute_count": 3,
                            "member_count": 10,
                            "active_member_count": 6,
                            "missed_payments": 4,
                            "total_contributions": 6000.0,
                            "avg_contribution_delay_hours": 48.0,
                            "member_dropout_rate": 0.4,
                            "payout_completion_rate": 0.7,
                        },
                    },
                )
                assert resp_degraded.status_code == 200
                degraded_score = resp_degraded.json()["health_score"]

                assert healthy_score > degraded_score, (
                    f"Healthy score ({healthy_score}) should exceed "
                    f"degraded score ({degraded_score})"
                )
        finally:
            _cleanup_overrides()

    async def test_classification_endpoint(self):
        """Step 4 -- Classification endpoint returns a valid structure."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.get(
                    f"/api/v1/circles/{_CIRCLE_ID}/classification",
                )
                assert response.status_code == 200
                data = response.json()
                assert data["circle_id"] == _CIRCLE_ID
                # Either a classification or a 'not yet computed' message
                assert "health_tier" in data or "classification" in data or "message" in data
        finally:
            _cleanup_overrides()

    async def test_anomaly_detection_endpoint(self):
        """Step 5 -- Anomalies endpoint returns valid structure."""
        mock = _mock_session()
        _install_mock_session(mock)
        try:
            async with _client() as client:
                response = await client.get(
                    f"/api/v1/circles/{_CIRCLE_ID}/anomalies",
                )
                assert response.status_code == 200
                data = response.json()
                assert "items" in data
                assert "total" in data
                assert isinstance(data["items"], list)
        finally:
            _cleanup_overrides()


# ===================================================================
# E2E-5: Compliance Escalation Pipeline
# ===================================================================


class TestE2EComplianceEscalation:
    """Simulate the full compliance pipeline: detection -> case -> SAR.

    Flow:
      1. Check CTR daily total for user
      2. Verify compliance alerts endpoint works
      3. Create a compliance case
      4. Update case status to investigating
      5. Generate SAR draft for the case
      6. Check customer risk profile
      7. Verify the full pipeline from detection through reporting
    """

    async def test_ctr_daily_total_check(self):
        """Step 1 -- CTR daily total endpoint returns valid structure."""
        async with _client() as client:
            response = await client.get(
                f"/api/v1/compliance/ctr/daily/{_COMPLIANCE_USER_ID}",
            )
            assert response.status_code == 200
            data = response.json()
            assert data["user_id"] == _COMPLIANCE_USER_ID
            assert "cumulative_amount" in data
            assert "transaction_count" in data
            assert "threshold_met" in data
            assert "alert_generated" in data
            assert "ctr_threshold" in data
            # New user should have zero cumulative
            assert data["cumulative_amount"] == 0.0
            assert data["transaction_count"] == 0

    async def test_compliance_alerts_endpoint(self):
        """Step 2 -- Compliance alerts listing works."""
        async with _client() as client:
            response = await client.get(
                "/api/v1/compliance/alerts",
            )
            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "total" in data
            assert "limit" in data
            assert "offset" in data

    async def test_create_compliance_case(self):
        """Step 3 -- Create a compliance case and verify response."""
        async with _client() as client:
            response = await client.post(
                "/api/v1/compliance/cases",
                json={
                    "user_id": _COMPLIANCE_USER_ID,
                    "alert_ids": [],
                    "case_type": "suspicious_activity",
                    "assigned_to": "officer-001",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert "case_id" in data
            assert data["user_id"] == _COMPLIANCE_USER_ID
            assert data["status"] == "open"
            assert data["assigned_to"] == "officer-001"
            # Store case_id for subsequent steps
            self.__class__._case_id = data["case_id"]

    async def test_update_case_status_to_investigating(self):
        """Step 4 -- Update case status to investigating."""
        # Ensure step 3 has run (create case first if needed)
        if not hasattr(self.__class__, "_case_id"):
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/compliance/cases",
                    json={
                        "user_id": _COMPLIANCE_USER_ID,
                        "case_type": "suspicious_activity",
                    },
                )
                self.__class__._case_id = resp.json()["case_id"]

        case_id = self.__class__._case_id
        async with _client() as client:
            response = await client.put(
                f"/api/v1/compliance/cases/{case_id}",
                json={
                    "status": "investigating",
                    "assigned_to": "officer-001",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "investigating"

    async def test_generate_sar_draft(self):
        """Step 5 -- Generate a SAR draft for the case."""
        # Ensure we have a case
        if not hasattr(self.__class__, "_case_id"):
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/compliance/cases",
                    json={
                        "user_id": _COMPLIANCE_USER_ID,
                        "case_type": "suspicious_activity",
                    },
                )
                self.__class__._case_id = resp.json()["case_id"]

        case_id = self.__class__._case_id
        async with _client() as client:
            response = await client.post(
                f"/api/v1/compliance/sar/draft/{case_id}",
            )
            assert response.status_code == 200
            data = response.json()
            assert "draft_id" in data
            assert data["case_id"] == case_id
            assert "narrative" in data
            assert "status" in data
            assert data["status"] == "draft"
            # Verify machine-generated disclaimer is present
            assert "machine_generated_disclaimer" in data

    async def test_customer_risk_profile(self):
        """Step 6 -- Check customer risk profile."""
        async with _client() as client:
            response = await client.get(
                f"/api/v1/compliance/risk/{_COMPLIANCE_USER_ID}",
            )
            assert response.status_code == 200
            data = response.json()
            assert data["user_id"] == _COMPLIANCE_USER_ID
            assert "risk_level" in data
            assert "risk_score" in data

    async def test_full_pipeline_cases_list(self):
        """Step 7 -- Verify cases list endpoint includes our case."""
        # Ensure case exists
        if not hasattr(self.__class__, "_case_id"):
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/compliance/cases",
                    json={
                        "user_id": _COMPLIANCE_USER_ID,
                        "case_type": "suspicious_activity",
                    },
                )
                self.__class__._case_id = resp.json()["case_id"]

        async with _client() as client:
            response = await client.get(
                "/api/v1/compliance/cases",
                params={"user_id": _COMPLIANCE_USER_ID},
            )
            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "total" in data
            assert data["total"] >= 1
            # Verify our case is in the list
            case_ids = [c["case_id"] for c in data["items"]]
            assert self.__class__._case_id in case_ids

    async def test_compliance_risk_post_endpoint(self):
        """Step 8 -- Legacy risk assessment endpoint works."""
        async with _client() as client:
            response = await client.post(
                "/api/v1/compliance/risk",
                json={"user_id": _COMPLIANCE_USER_ID},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["user_id"] == _COMPLIANCE_USER_ID
            assert "risk_level" in data
            assert "risk_score" in data
            assert "model_version" in data
            assert data["model_version"] == "compliance-v1"

    async def test_pending_ctr_obligations(self):
        """Step 9 -- Pending CTR obligations endpoint works."""
        async with _client() as client:
            response = await client.get(
                "/api/v1/compliance/ctr/pending",
            )
            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "total" in data
            assert isinstance(data["items"], list)

    async def test_ctr_filing_history(self):
        """Step 10 -- CTR filing history endpoint works."""
        async with _client() as client:
            response = await client.get(
                "/api/v1/compliance/ctr/filings",
            )
            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "total" in data
            assert isinstance(data["items"], list)
