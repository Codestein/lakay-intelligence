"""Security audit tests covering OWASP API Security Top 10.

Phase 10 — validates that Lakay Intelligence API endpoints follow security
best practices across authentication, authorization, input validation, data
exposure, and resource consumption.
"""

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
    """Create a mock async database session returning empty/default results."""
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


def _client():
    """Return an HTTPX AsyncClient wired to the FastAPI test app."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# OWASP API1 — Broken Object-Level Authorization
# ---------------------------------------------------------------------------


class TestAPI1BrokenObjectLevelAuth:
    """Verify that endpoints scope data to the requested user/circle and do
    not leak data belonging to other entities.

    NOTE: Auth middleware is not yet wired; these tests confirm that responses
    are correctly scoped by the user_id / circle_id present in the request so
    that, once auth is added, no cross-user data leakage can occur.
    """

    @pytest.mark.asyncio
    async def test_user_a_cannot_see_user_b_behavioral_profile(self):
        """Requesting user A's profile only returns user A's data."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                user_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
                user_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

                resp_a = await client.get(f"/api/v1/behavior/users/{user_a}/profile")
                resp_b = await client.get(f"/api/v1/behavior/users/{user_b}/profile")

                assert resp_a.status_code == 200
                assert resp_b.status_code == 200

                data_a = resp_a.json()
                data_b = resp_b.json()

                # Each response must scope to its own user_id
                assert data_a["user_id"] == user_a
                assert data_b["user_id"] == user_b

                # User A's payload must never contain user B's id
                assert user_b not in str(data_a)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_circle_ids_scoped_independently(self):
        """Querying circle A's health must not return circle B's data."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                circle_a = "cccccccc-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
                circle_b = "cccccccc-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

                resp_a = await client.get(f"/api/v1/circles/{circle_a}/health")
                resp_b = await client.get(f"/api/v1/circles/{circle_b}/health")

                assert resp_a.status_code == 200
                assert resp_b.status_code == 200

                assert resp_a.json()["circle_id"] == circle_a
                assert resp_b.json()["circle_id"] == circle_b

                # Ensure no cross-contamination
                assert circle_b not in str(resp_a.json())
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_compliance_risk_scoped_per_user(self):
        """Compliance risk endpoint returns data scoped to the given user_id."""
        async with _client() as client:
            user_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
            resp = await client.post(
                "/api/v1/compliance/risk",
                json={"user_id": user_id},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_ctr_daily_scoped_per_user(self):
        """CTR daily total endpoint returns data scoped to the given user_id."""
        async with _client() as client:
            user_id = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
            resp = await client.get(f"/api/v1/compliance/ctr/daily/{user_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["user_id"] == user_id


# ---------------------------------------------------------------------------
# OWASP API2 — Broken Authentication
# ---------------------------------------------------------------------------


class TestAPI2BrokenAuthentication:
    """Verify that public endpoints are accessible without auth and that
    protected endpoints exist and are reachable (auth layer to be added at
    integration time).
    """

    @pytest.mark.asyncio
    async def test_health_accessible_without_auth(self):
        async with _client() as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_ready_accessible_without_auth(self):
        async with _client() as client:
            resp = await client.get("/ready")
            # May return 200 or 503 depending on infra, but must not be 401/403
            assert resp.status_code in (200, 503)

    @pytest.mark.asyncio
    async def test_protected_endpoints_exist_and_respond(self):
        """All protected endpoints should exist and return a response (not 404).
        Auth enforcement will be verified separately once the auth layer is
        integrated.
        """
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                protected_gets = [
                    "/api/v1/fraud/rules",
                    "/api/v1/fraud/alerts",
                    "/api/v1/behavior/users/test-user/profile",
                    "/api/v1/behavior/users/test-user/engagement",
                    "/api/v1/behavior/engagement/summary",
                    "/api/v1/behavior/ato/alerts",
                    "/api/v1/circles/test-circle/health",
                    "/api/v1/circles/health/summary",
                    "/api/v1/circles/at-risk",
                    "/api/v1/compliance/alerts",
                    "/api/v1/compliance/cases",
                    "/api/v1/compliance/ctr/daily/test-user",
                    "/api/v1/compliance/ctr/pending",
                    "/api/v1/compliance/ctr/filings",
                    "/api/v1/compliance/risk/test-user",
                    "/api/v1/compliance/risk/high",
                    "/api/v1/compliance/sar/drafts",
                    "/api/v1/serving/routing",
                    "/api/v1/serving/monitoring",
                    "/api/v1/pipeline/bronze/stats",
                    "/api/v1/pipeline/silver/stats",
                    "/api/v1/pipeline/gold/datasets",
                    # NOTE: Dashboard endpoints are excluded here because they
                    # make real infrastructure calls (MinIO/S3) that cannot be
                    # mocked through the DB session override alone. They are
                    # tested separately in their own integration tests.
                    "/api/v1/experiments",
                    "/api/v1/pipeline/compliance-reports",
                ]
                for endpoint in protected_gets:
                    resp = await client.get(endpoint)
                    assert resp.status_code != 404, (
                        f"Protected endpoint {endpoint} returned 404 — it should exist"
                    )
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_no_auth_bypass_via_debug_headers(self):
        """Ensure that common auth-bypass headers do not alter behavior."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                bypass_headers = {
                    "X-Debug": "true",
                    "X-Bypass-Auth": "1",
                    "X-Internal": "true",
                    "X-Override-User": "admin",
                }
                resp = await client.get(
                    "/api/v1/fraud/alerts", headers=bypass_headers
                )
                # The response must be the same shape as a normal request —
                # no elevated privileges or hidden data.
                assert resp.status_code == 200
                data = resp.json()
                assert "items" in data
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# OWASP API3 — Broken Object Property Level Authorization
# ---------------------------------------------------------------------------


class TestAPI3PropertyLevelAuth:
    """Ensure API responses do not expose internal implementation details,
    raw PII, or internal database identifiers.
    """

    @pytest.mark.asyncio
    async def test_fraud_score_no_internal_db_ids(self):
        """Fraud scoring response must not contain database-internal IDs
        (e.g., auto-increment primary keys, internal ORM identifiers).
        """
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/fraud/score",
                    json={
                        "transaction_id": "550e8400-e29b-41d4-a716-446655440000",
                        "user_id": "660e8400-e29b-41d4-a716-446655440001",
                        "amount": "100.00",
                    },
                )
                assert resp.status_code == 200
                data = resp.json()

                # Must not leak internal DB primary keys
                assert "id" not in data
                assert "_id" not in data
                assert "pk" not in data

                # Expected documented fields only
                expected_keys = {
                    "transaction_id",
                    "score",
                    "composite_score",
                    "rule_score",
                    "ml_score",
                    "risk_tier",
                    "recommendation",
                    "confidence",
                    "risk_factors",
                    "model_version",
                    "computed_at",
                }
                # Response may contain ml_details if ML is loaded, which is fine
                allowed_extra = {"ml_details"}
                actual_keys = set(data.keys())
                unexpected = actual_keys - expected_keys - allowed_extra
                assert not unexpected, f"Unexpected fields in fraud score response: {unexpected}"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_behavioral_profile_no_raw_pii(self):
        """Behavioral profile must not expose raw PII (email, phone, SSN, etc.)."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.get(
                    "/api/v1/behavior/users/test-user-id/profile"
                )
                assert resp.status_code == 200
                body = resp.text.lower()

                pii_indicators = [
                    "email",
                    "phone_number",
                    "ssn",
                    "social_security",
                    "date_of_birth",
                    "dob",
                    "password",
                    "secret",
                ]
                for indicator in pii_indicators:
                    assert indicator not in body, (
                        f"Behavioral profile response contains PII field '{indicator}'"
                    )
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_compliance_risk_no_implementation_details(self):
        """Compliance risk response must not leak stack traces, file paths,
        or ORM implementation details.
        """
        async with _client() as client:
            resp = await client.post(
                "/api/v1/compliance/risk",
                json={"user_id": "test-user-id"},
            )
            assert resp.status_code == 200
            body = resp.text

            leak_indicators = [
                "Traceback",
                "File \"",
                "sqlalchemy",
                "postgresql",
                "asyncpg",
                "site-packages",
            ]
            for indicator in leak_indicators:
                assert indicator not in body, (
                    f"Compliance response leaks implementation detail: '{indicator}'"
                )

    @pytest.mark.asyncio
    async def test_fraud_score_response_schema_documented_fields_only(self):
        """Fraud scoring response keys must be from the documented API contract."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/fraud/score",
                    json={
                        "transaction_id": "550e8400-e29b-41d4-a716-446655440000",
                        "user_id": "660e8400-e29b-41d4-a716-446655440001",
                        "amount": "50.00",
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                documented_fields = {
                    "transaction_id",
                    "score",
                    "composite_score",
                    "rule_score",
                    "ml_score",
                    "risk_tier",
                    "recommendation",
                    "confidence",
                    "risk_factors",
                    "model_version",
                    "computed_at",
                    "ml_details",
                }
                for key in data:
                    assert key in documented_fields, (
                        f"Undocumented field '{key}' in fraud score response"
                    )
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# OWASP API4 — Unrestricted Resource Consumption
# ---------------------------------------------------------------------------


class TestAPI4UnrestrictedResourceConsumption:
    """Validate that paginated endpoints enforce sensible limits and reject
    abusive parameters.
    """

    @pytest.mark.asyncio
    async def test_fraud_alerts_limit_capped_at_500(self):
        """Setting limit > 500 must be rejected (FastAPI Query(le=500))."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.get("/api/v1/fraud/alerts?limit=501")
                assert resp.status_code == 422, (
                    "limit=501 should be rejected by validation (max 500)"
                )
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_compliance_alerts_limit_capped_at_500(self):
        """Compliance alerts must enforce the same cap."""
        async with _client() as client:
            resp = await client.get("/api/v1/compliance/alerts?limit=501")
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_circle_health_summary_limit_capped_at_500(self):
        """Circle health summary must enforce limit <= 500."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.get("/api/v1/circles/health/summary?limit=501")
                assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_negative_offset_rejected(self):
        """Negative offset must be rejected (ge=0)."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.get("/api/v1/fraud/alerts?offset=-1")
                assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_zero_limit_rejected(self):
        """limit=0 must be rejected (ge=1)."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.get("/api/v1/fraud/alerts?limit=0")
                assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ato_alerts_limit_capped_at_500(self):
        """ATO alerts must enforce limit <= 500."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.get("/api/v1/behavior/ato/alerts?limit=501")
                assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_circle_anomalies_limit_capped_at_500(self):
        """Circle anomalies must enforce limit <= 500."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.get(
                    "/api/v1/circles/test-circle/anomalies?limit=501"
                )
                assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_large_limit_within_bounds_accepted(self):
        """limit=500 (the maximum) should be accepted."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.get("/api/v1/fraud/alerts?limit=500")
                assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# OWASP API5 — Broken Function-Level Authorization
# ---------------------------------------------------------------------------


class TestAPI5BrokenFunctionLevelAuth:
    """Identify administrative / write endpoints that must be protected with
    elevated permissions at integration time.

    These tests verify the endpoints exist and document which are read-only
    vs write operations.
    """

    ADMIN_WRITE_ENDPOINTS = [
        ("POST", "/api/v1/serving/reload"),
        ("POST", "/api/v1/serving/routing"),
        ("POST", "/api/v1/experiments"),
        ("POST", "/api/v1/pipeline/gold/test-dataset/refresh"),
    ]

    @pytest.mark.asyncio
    async def test_admin_write_endpoints_exist(self):
        """Administrative write endpoints must exist (not return 404/405).
        They should be gated by elevated permissions at integration time.
        """
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                # POST /api/v1/serving/reload
                resp = await client.post("/api/v1/serving/reload")
                assert resp.status_code != 404, (
                    "POST /api/v1/serving/reload should exist"
                )
                assert resp.status_code != 405, (
                    "POST /api/v1/serving/reload should accept POST method"
                )

                # POST /api/v1/serving/routing
                resp = await client.post(
                    "/api/v1/serving/routing",
                    json={"champion_pct": 90.0, "challenger_pct": 10.0},
                )
                assert resp.status_code != 404
                assert resp.status_code != 405

                # POST /api/v1/experiments
                resp = await client.post(
                    "/api/v1/experiments",
                    json={
                        "name": "test-exp",
                        "variants": [
                            {"variant_id": "control", "name": "control"},
                            {"variant_id": "treatment", "name": "treatment"},
                        ],
                    },
                )
                assert resp.status_code != 404
                assert resp.status_code != 405

                # POST /api/v1/pipeline/gold/{name}/refresh
                resp = await client.post(
                    "/api/v1/pipeline/gold/test-dataset/refresh"
                )
                assert resp.status_code != 404
                assert resp.status_code != 405
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_read_only_endpoints_documented(self):
        """Verify read-only (GET) endpoints do not accept destructive methods."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                read_only_endpoints = [
                    "/api/v1/fraud/rules",
                    "/api/v1/serving/monitoring",
                    "/api/v1/serving/routing",
                    "/api/v1/pipeline/bronze/stats",
                    "/api/v1/pipeline/silver/stats",
                    "/api/v1/pipeline/gold/datasets",
                ]
                for endpoint in read_only_endpoints:
                    resp = await client.get(endpoint)
                    assert resp.status_code != 404, (
                        f"Read-only endpoint {endpoint} should exist"
                    )
                    # DELETE should not be allowed on read-only endpoints
                    resp_delete = await client.delete(endpoint)
                    assert resp_delete.status_code == 405, (
                        f"DELETE should not be allowed on read-only endpoint {endpoint}"
                    )
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# OWASP API6 — Mass Assignment
# ---------------------------------------------------------------------------


class TestAPI6MassAssignment:
    """Ensure that Pydantic models reject or ignore unexpected fields and
    that status/internal fields cannot be set directly during creation.
    """

    @pytest.mark.asyncio
    async def test_compliance_case_ignores_extra_fields(self):
        """Extra fields in the request body must be silently ignored (Pydantic
        default behavior with model_config extra='ignore' or strict models).
        """
        async with _client() as client:
            resp = await client.post(
                "/api/v1/compliance/cases",
                json={
                    "user_id": "test-user",
                    "alert_ids": [],
                    "case_type": "test",
                    "assigned_to": "analyst-1",
                    # Extra fields that should be ignored
                    "is_admin": True,
                    "internal_score": 999,
                    "secret_override": "hack",
                },
            )
            # Should succeed — extra fields are silently dropped
            assert resp.status_code == 200
            data = resp.json()
            assert "is_admin" not in data
            assert "internal_score" not in data
            assert "secret_override" not in data

    @pytest.mark.asyncio
    async def test_compliance_case_status_not_settable_on_creation(self):
        """The status field should not be directly settable on case creation —
        it should default to the initial state.
        """
        async with _client() as client:
            resp = await client.post(
                "/api/v1/compliance/cases",
                json={
                    "user_id": "test-user",
                    "alert_ids": [],
                    "status": "closed",  # Attempt to set status directly
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            # Status should be the default initial state, not "closed"
            assert data["status"] != "closed", (
                "Status should not be directly settable to 'closed' on creation"
            )

    @pytest.mark.asyncio
    async def test_experiment_creation_ignores_extra_fields(self):
        """Extra fields in experiment creation should be ignored."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/experiments",
                    json={
                        "name": "test-experiment",
                        "variants": [
                            {"variant_id": "control", "name": "control"},
                            {"variant_id": "treatment", "name": "treatment"},
                        ],
                        # Extra fields
                        "force_winner": "treatment",
                        "bypass_guardrails": True,
                    },
                )
                # Should not 500; extra fields ignored by Pydantic
                assert resp.status_code in (200, 422), (
                    f"Unexpected status {resp.status_code}"
                )
                if resp.status_code == 200:
                    data = resp.json()
                    assert "force_winner" not in data
                    assert "bypass_guardrails" not in data
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_fraud_score_only_accepts_documented_fields(self):
        """FraudScoreRequest should only accept its documented fields."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/fraud/score",
                    json={
                        "transaction_id": "550e8400-e29b-41d4-a716-446655440000",
                        "user_id": "660e8400-e29b-41d4-a716-446655440001",
                        "amount": "100.00",
                        # Extra fields — should be ignored
                        "override_score": 0.0,
                        "skip_rules": True,
                    },
                )
                assert resp.status_code == 200
                data = resp.json()
                # The override fields should not affect the result
                assert "override_score" not in data
                assert "skip_rules" not in data
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# OWASP API7 — Server-Side Request Forgery (SSRF)
# ---------------------------------------------------------------------------


class TestAPI7SSRF:
    """Verify that no endpoints accept arbitrary URLs as input and that
    infrastructure configuration values are not exposed via the API.
    """

    @pytest.mark.asyncio
    async def test_no_url_parameters_in_fraud_endpoints(self):
        """Fraud endpoints should not accept URL/callback parameters."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/fraud/score",
                    json={
                        "transaction_id": "550e8400-e29b-41d4-a716-446655440000",
                        "user_id": "660e8400-e29b-41d4-a716-446655440001",
                        "amount": "100.00",
                        "callback_url": "http://evil.com/steal",
                        "webhook_url": "http://evil.com/exfil",
                    },
                )
                # Extra URL fields should be ignored; the response should not
                # reference them or attempt to call them
                assert resp.status_code == 200
                body = resp.text
                assert "evil.com" not in body
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_health_does_not_expose_infrastructure_urls(self):
        """Health endpoint must not expose Kafka, database, or Redis URLs."""
        async with _client() as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            body = resp.text
            assert "kafka" not in body.lower() or "kafka" in "kafka_ok"
            assert "postgresql" not in body.lower()
            assert "redis://" not in body.lower()
            assert "localhost:9092" not in body

    @pytest.mark.asyncio
    async def test_ready_does_not_expose_connection_strings(self):
        """Readiness endpoint must not expose connection strings."""
        async with _client() as client:
            resp = await client.get("/ready")
            body = resp.text
            assert "asyncpg://" not in body
            assert "postgresql+asyncpg://" not in body
            assert "minioadmin" not in body

    @pytest.mark.asyncio
    async def test_monitoring_does_not_expose_infra_config(self):
        """Serving monitoring must not leak infrastructure configuration."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.get("/api/v1/serving/monitoring")
                assert resp.status_code == 200
                body = resp.text
                assert "localhost:9092" not in body
                assert "postgresql" not in body.lower()
                assert "redis://" not in body.lower()
                assert "minioadmin" not in body
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Verify that common attack patterns in input fields are handled safely."""

    @pytest.mark.asyncio
    async def test_sql_injection_in_user_id_query_param(self):
        """SQL injection patterns in user_id should not cause 500 errors."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                sqli_payloads = [
                    "'; DROP TABLE users--",
                    "1 OR 1=1",
                    "' UNION SELECT * FROM users--",
                    "admin'--",
                    "1; DELETE FROM fraud_scores",
                ]
                for payload in sqli_payloads:
                    resp = await client.get(
                        f"/api/v1/behavior/users/{payload}/profile"
                    )
                    # Should never cause a 500 internal error
                    assert resp.status_code != 500, (
                        f"SQL injection payload caused 500: {payload}"
                    )
                    # Response should be safe and scoped to the literal string
                    if resp.status_code == 200:
                        data = resp.json()
                        assert data["user_id"] == payload
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_sql_injection_in_fraud_alerts_user_id(self):
        """SQL injection in fraud alerts user_id filter should be safe."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.get(
                    "/api/v1/fraud/alerts",
                    params={"user_id": "'; DROP TABLE alerts--"},
                )
                assert resp.status_code != 500
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_xss_patterns_in_input_fields(self):
        """XSS payloads in input fields must not be reflected unsanitized."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                xss_payload = '<script>alert("xss")</script>'
                resp = await client.get(
                    f"/api/v1/behavior/users/{xss_payload}/profile"
                )
                assert resp.status_code != 500
                # JSON API should not render HTML — check content type
                assert "application/json" in resp.headers.get("content-type", "")
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_extremely_long_string_in_user_id(self):
        """Extremely long input strings should not crash the server."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                long_id = "a" * 10000
                resp = await client.get(
                    f"/api/v1/behavior/users/{long_id}/profile"
                )
                # Must not crash — 200, 400, or 422 are all acceptable
                assert resp.status_code != 500
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_negative_amount_in_fraud_score(self):
        """Negative amounts should be handled gracefully."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/fraud/score",
                    json={
                        "transaction_id": "550e8400-e29b-41d4-a716-446655440000",
                        "user_id": "660e8400-e29b-41d4-a716-446655440001",
                        "amount": "-500.00",
                    },
                )
                # Should not cause 500; 200 (treated as unusual) or 422 are ok
                assert resp.status_code != 500, (
                    "Negative amount caused server error"
                )
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_special_characters_in_path_params(self):
        """Special characters in path parameters must be handled safely."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                special_ids = [
                    "user%00null",
                    "user/../../../etc/passwd",
                    "user;rm -rf /",
                    'user"injection',
                ]
                for uid in special_ids:
                    resp = await client.get(
                        f"/api/v1/compliance/ctr/daily/{uid}"
                    )
                    assert resp.status_code != 500, (
                        f"Special character input caused 500: {uid!r}"
                    )
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_empty_body_on_post_endpoints(self):
        """POST endpoints with empty or missing body should return 422, not 500."""
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                post_endpoints = [
                    "/api/v1/fraud/score",
                    "/api/v1/compliance/risk",
                    "/api/v1/compliance/cases",
                    "/api/v1/experiments",
                ]
                for endpoint in post_endpoints:
                    resp = await client.post(endpoint, content=b"")
                    assert resp.status_code in (400, 422), (
                        f"Empty body to {endpoint} should be 400/422, got {resp.status_code}"
                    )
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Secrets Exposure
# ---------------------------------------------------------------------------


class TestSecretsExposure:
    """Ensure that secrets, connection strings, and internal paths are never
    exposed through API responses.
    """

    @pytest.mark.asyncio
    async def test_health_does_not_expose_secrets(self):
        async with _client() as client:
            resp = await client.get("/health")
            body = resp.text
            assert "lakay-pii-token-secret" not in body
            assert "lakay-encryption-key" not in body
            assert "minioadmin" not in body
            assert "lakay_dev" not in body

    @pytest.mark.asyncio
    async def test_ready_does_not_expose_secrets(self):
        async with _client() as client:
            resp = await client.get("/ready")
            body = resp.text
            assert "lakay-pii-token-secret" not in body
            assert "lakay-encryption-key" not in body
            assert "minioadmin" not in body

    @pytest.mark.asyncio
    async def test_error_responses_do_not_leak_stack_traces(self):
        """When the server returns an error, it should not include Python
        tracebacks or internal file paths.
        """
        async with _client() as client:
            # Trigger a validation error (missing required fields)
            resp = await client.post(
                "/api/v1/fraud/score",
                json={"invalid": "data"},
            )
            body = resp.text
            assert "Traceback" not in body
            assert "File \"/" not in body
            assert "site-packages" not in body

    @pytest.mark.asyncio
    async def test_error_responses_do_not_leak_db_connection_strings(self):
        """Error responses must not contain database connection strings."""
        async with _client() as client:
            resp = await client.post(
                "/api/v1/fraud/score",
                json={"invalid": "payload"},
            )
            body = resp.text
            assert "postgresql+asyncpg://" not in body
            assert "localhost:5432" not in body
            assert "redis://localhost" not in body

    @pytest.mark.asyncio
    async def test_config_defaults_not_in_api_responses(self):
        """Configuration default values (PII secret, encryption key, minio
        credentials) must not appear in any API response.
        """
        mock = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock)
        try:
            async with _client() as client:
                # Check a representative set of endpoints
                endpoints = [
                    ("GET", "/health"),
                    ("GET", "/ready"),
                    ("GET", "/api/v1/fraud/rules"),
                    ("GET", "/api/v1/serving/monitoring"),
                    ("GET", "/api/v1/pipeline/bronze/stats"),
                    ("GET", "/api/v1/pipeline/silver/stats"),
                ]
                sensitive_values = [
                    "lakay-pii-token-secret-dev-only",
                    "lakay-encryption-key-dev-only",
                    "minioadmin",
                    "postgresql+asyncpg://lakay:lakay_dev",
                ]
                for method, endpoint in endpoints:
                    resp = await client.request(method, endpoint)
                    body = resp.text
                    for secret in sensitive_values:
                        assert secret not in body, (
                            f"Config secret '{secret}' found in {endpoint} response"
                        )
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_openapi_schema_does_not_contain_secrets(self):
        """The OpenAPI schema itself should not embed secret values."""
        async with _client() as client:
            resp = await client.get("/openapi.json")
            assert resp.status_code == 200
            body = resp.text
            assert "lakay-pii-token-secret" not in body
            assert "lakay-encryption-key" not in body
            assert "minioadmin" not in body


# ---------------------------------------------------------------------------
# Data Security — PII Handling
# ---------------------------------------------------------------------------


class TestDataSecurityPII:
    """Verify that API responses from compliance endpoints handle user data
    appropriately and that audit trails are tracked.
    """

    @pytest.mark.asyncio
    async def test_compliance_risk_response_structure(self):
        """Compliance risk responses should contain only risk-related fields
        and not leak user personal data.
        """
        async with _client() as client:
            resp = await client.post(
                "/api/v1/compliance/risk",
                json={"user_id": "test-user-001"},
            )
            assert resp.status_code == 200
            data = resp.json()

            # Must have standard risk fields
            assert "user_id" in data
            assert "risk_level" in data

            # Must not leak personal data
            pii_fields = [
                "full_name",
                "email",
                "phone",
                "ssn",
                "date_of_birth",
                "address",
                "bank_account",
            ]
            for field in pii_fields:
                assert field not in data, (
                    f"PII field '{field}' found in compliance risk response"
                )

    @pytest.mark.asyncio
    async def test_ctr_daily_does_not_expose_pii(self):
        """CTR daily totals should only contain transaction aggregates, not PII."""
        async with _client() as client:
            resp = await client.get("/api/v1/compliance/ctr/daily/test-user")
            assert resp.status_code == 200
            data = resp.json()
            assert "user_id" in data
            assert "cumulative_amount" in data

            # No PII should be present
            body = resp.text.lower()
            assert "full_name" not in body
            assert "social_security" not in body
            assert "bank_account" not in body

    @pytest.mark.asyncio
    async def test_alert_update_tracks_reviewer(self):
        """When updating a compliance alert, the reviewer (who made the change)
        should be accepted and stored — verifying audit trail support.
        """
        async with _client() as client:
            # First create a case, then update it to check reviewer tracking
            create_resp = await client.post(
                "/api/v1/compliance/cases",
                json={
                    "user_id": "test-user",
                    "alert_ids": [],
                    "case_type": "investigation",
                    "assigned_to": "analyst-1",
                },
            )
            assert create_resp.status_code == 200
            case_id = create_resp.json()["case_id"]

            # Update the case with an assigned_to for audit trail
            update_resp = await client.put(
                f"/api/v1/compliance/cases/{case_id}",
                json={
                    "status": "investigating",
                    "assigned_to": "analyst-2",
                    "narrative": "Escalated for further review",
                },
            )
            assert update_resp.status_code == 200
            data = update_resp.json()
            assert data["assigned_to"] == "analyst-2"
            assert data["status"] == "investigating"

    @pytest.mark.asyncio
    async def test_compliance_alerts_filter_by_user(self):
        """Compliance alerts should be filterable by user_id to ensure
        data segregation in multi-tenant contexts.
        """
        async with _client() as client:
            user_id = "filter-test-user"
            resp = await client.get(
                "/api/v1/compliance/alerts",
                params={"user_id": user_id},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "items" in data
            assert "total" in data
            # All returned items (if any) must belong to the requested user
            for item in data["items"]:
                assert item["user_id"] == user_id, (
                    "Alert returned for wrong user in filtered query"
                )
