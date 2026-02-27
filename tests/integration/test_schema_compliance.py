"""Schema compliance integration tests for Lakay Intelligence Phase 10.

Validates that all API responses conform to their documented schemas,
ensuring contract stability for downstream consumers (Trebanx platform,
dashboards, compliance systems).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.db.database import get_session
from src.main import app
from tests.conftest import override_get_session

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_session():
    """Create a mock async DB session that returns empty results."""
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


def _fraud_score_payload(**overrides) -> dict:
    """Minimal valid payload for POST /api/v1/fraud/score."""
    base = {
        "transaction_id": "txn-schema-001",
        "user_id": "user-schema-001",
        "amount": "250.00",
        "currency": "USD",
    }
    base.update(overrides)
    return base


def _circle_score_payload(**overrides) -> dict:
    """Minimal valid payload for POST /api/v1/circles/{id}/score."""
    base = {
        "circle_id": "circle-schema-001",
        "features": {
            "on_time_payment_rate": 0.95,
            "member_retention_rate": 0.90,
            "avg_contribution_amount": 100.0,
            "payout_completion_rate": 1.0,
            "dispute_rate": 0.0,
            "avg_days_delinquent": 0.0,
            "organizer_responsiveness": 0.85,
        },
    }
    base.update(overrides)
    return base


def _session_score_payload(**overrides) -> dict:
    """Minimal valid payload for POST /api/v1/behavior/sessions/score."""
    base = {
        "session_id": "sess-schema-001",
        "user_id": "user-schema-001",
        "session_duration_seconds": 120.0,
        "action_count": 5,
    }
    base.update(overrides)
    return base


def _ato_assess_payload(**overrides) -> dict:
    """Minimal valid payload for POST /api/v1/behavior/ato/assess."""
    base = {
        "session_id": "sess-ato-001",
        "user_id": "user-schema-001",
        "session_duration_seconds": 120.0,
        "action_count": 5,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# TestFraudAlertSchemaCompliance
# ---------------------------------------------------------------------------


class TestFraudAlertSchemaCompliance:
    """Verify that fraud scoring responses contain all required fields with
    correct types and value ranges."""

    @pytest.mark.asyncio
    async def test_fraud_score_response_has_all_required_fields(self):
        """POST /api/v1/fraud/score must return every documented field."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json=_fraud_score_payload(),
                )
            assert response.status_code == 200
            data = response.json()

            required_fields = [
                "transaction_id",
                "score",
                "composite_score",
                "risk_tier",
                "recommendation",
                "confidence",
                "risk_factors",
                "model_version",
                "computed_at",
            ]
            for field in required_fields:
                assert field in data, f"Missing required field: {field}"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_fraud_score_value_ranges(self):
        """Score 0-100, composite_score 0-1, risk_tier in allowed enum."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json=_fraud_score_payload(),
                )
            data = response.json()

            # score: 0-100
            assert 0 <= data["score"] <= 100, (
                f"score={data['score']} out of [0,100]"
            )

            # composite_score: 0-1
            assert 0.0 <= data["composite_score"] <= 1.0, (
                f"composite_score={data['composite_score']} out of [0,1]"
            )

            # risk_tier
            assert data["risk_tier"] in {"low", "medium", "high", "critical"}, (
                f"Unexpected risk_tier: {data['risk_tier']}"
            )
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_fraud_score_risk_factors_is_list_of_strings(self):
        """risk_factors must be a list whose every element is a string."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json=_fraud_score_payload(),
                )
            data = response.json()

            assert isinstance(data["risk_factors"], list)
            for factor in data["risk_factors"]:
                assert isinstance(factor, str), (
                    f"risk_factor element is not a string: {factor!r}"
                )
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_fraud_score_transaction_id_echoed(self):
        """The response must echo back the submitted transaction_id."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                payload = _fraud_score_payload(transaction_id="txn-echo-test-999")
                response = await client.post("/api/v1/fraud/score", json=payload)
            data = response.json()
            assert data["transaction_id"] == "txn-echo-test-999"
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# TestCircleTierChangeSchemaCompliance
# ---------------------------------------------------------------------------


class TestCircleTierChangeSchemaCompliance:
    """Verify that circle scoring responses conform to the documented schema."""

    @pytest.mark.asyncio
    async def test_circle_score_response_has_all_required_fields(self):
        """POST /api/v1/circles/{id}/score must return the full schema."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/circles/circle-schema-001/score",
                    json=_circle_score_payload(),
                )
            assert response.status_code == 200
            data = response.json()

            required_fields = [
                "circle_id",
                "health_score",
                "health_tier",
                "trend",
                "confidence",
                "dimension_scores",
                "anomaly_count",
                "classification",
                "scoring_version",
                "computed_at",
            ]
            for field in required_fields:
                assert field in data, f"Missing required field: {field}"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_circle_score_value_ranges(self):
        """health_score 0-100, confidence 0-1, valid tier and trend enums."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/circles/circle-schema-001/score",
                    json=_circle_score_payload(),
                )
            data = response.json()

            assert 0 <= data["health_score"] <= 100, (
                f"health_score={data['health_score']} out of [0,100]"
            )
            assert data["health_tier"] in {"healthy", "at-risk", "critical"}, (
                f"Unexpected health_tier: {data['health_tier']}"
            )
            assert data["trend"] in {"improving", "stable", "deteriorating"}, (
                f"Unexpected trend: {data['trend']}"
            )
            assert 0.0 <= data["confidence"] <= 1.0, (
                f"confidence={data['confidence']} out of [0,1]"
            )
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_circle_score_dimension_scores_is_dict(self):
        """dimension_scores must be a dict."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/circles/circle-schema-001/score",
                    json=_circle_score_payload(),
                )
            data = response.json()
            assert isinstance(data["dimension_scores"], dict)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_circle_score_classification_is_dict(self):
        """classification must be a dict with expected sub-fields."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/circles/circle-schema-001/score",
                    json=_circle_score_payload(),
                )
            data = response.json()

            classification = data["classification"]
            assert isinstance(classification, dict)
            assert "tier" in classification
            assert "recommended_actions" in classification
            assert "reason" in classification
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_circle_score_anomaly_count_is_int(self):
        """anomaly_count must be a non-negative integer."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/circles/circle-schema-001/score",
                    json=_circle_score_payload(),
                )
            data = response.json()
            assert isinstance(data["anomaly_count"], int)
            assert data["anomaly_count"] >= 0
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_circle_score_scoring_version_is_string(self):
        """scoring_version and computed_at must be strings."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/circles/circle-schema-001/score",
                    json=_circle_score_payload(),
                )
            data = response.json()
            assert isinstance(data["scoring_version"], str)
            assert isinstance(data["computed_at"], str)
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# TestATOAlertSchemaCompliance
# ---------------------------------------------------------------------------


class TestATOAlertSchemaCompliance:
    """Verify that ATO assessment responses contain all required fields with
    correct types and value constraints."""

    @pytest.mark.asyncio
    async def test_ato_assess_response_has_all_required_fields(self):
        """POST /api/v1/behavior/ato/assess must return every documented field."""
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

            required_fields = [
                "session_id",
                "user_id",
                "ato_risk_score",
                "risk_level",
                "contributing_signals",
                "recommended_response",
                "affected_transactions",
                "timestamp",
            ]
            for field in required_fields:
                assert field in data, f"Missing required field: {field}"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ato_assess_value_ranges(self):
        """ato_risk_score 0-1, risk_level in enum, recommended_response in enum."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/behavior/ato/assess",
                    json=_ato_assess_payload(),
                )
            data = response.json()

            assert 0.0 <= data["ato_risk_score"] <= 1.0, (
                f"ato_risk_score={data['ato_risk_score']} out of [0,1]"
            )
            assert data["risk_level"] in {"low", "moderate", "high", "critical"}, (
                f"Unexpected risk_level: {data['risk_level']}"
            )
            assert data["recommended_response"] in {
                "none",
                "re_authenticate",
                "step_up_auth",
                "lock_account",
            }, f"Unexpected recommended_response: {data['recommended_response']}"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ato_assess_contributing_signals_is_list(self):
        """contributing_signals must be a list."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/behavior/ato/assess",
                    json=_ato_assess_payload(),
                )
            data = response.json()
            assert isinstance(data["contributing_signals"], list)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ato_assess_affected_transactions_is_list(self):
        """affected_transactions must be a list."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/behavior/ato/assess",
                    json=_ato_assess_payload(),
                )
            data = response.json()
            assert isinstance(data["affected_transactions"], list)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ato_assess_timestamp_is_string(self):
        """timestamp must be a string (ISO 8601 format)."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/behavior/ato/assess",
                    json=_ato_assess_payload(),
                )
            data = response.json()
            assert isinstance(data["timestamp"], str)
            assert len(data["timestamp"]) > 0
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# TestComplianceAlertSchemaCompliance
# ---------------------------------------------------------------------------


class TestComplianceAlertSchemaCompliance:
    """Verify compliance alert/risk responses contain expected fields and
    that enum values are within the documented set."""

    @pytest.mark.asyncio
    async def test_compliance_risk_response_has_expected_fields(self):
        """POST /api/v1/compliance/risk must return documented fields."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/compliance/risk",
                json={"user_id": "user-compliance-001"},
            )
        assert response.status_code == 200
        data = response.json()

        required_fields = [
            "user_id",
            "risk_level",
            "risk_score",
            "factors",
            "edd_required",
            "model_version",
            "computed_at",
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

    @pytest.mark.asyncio
    async def test_compliance_alert_type_valid_enum(self):
        """alert_type values in listed alerts are from the AlertType enum."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/compliance/alerts")
        assert response.status_code == 200
        data = response.json()

        valid_alert_types = {
            "ctr_threshold",
            "structuring",
            "suspicious_activity",
            "ofac_match",
            "edd_trigger",
            "velocity_anomaly",
        }
        for item in data["items"]:
            assert item["alert_type"] in valid_alert_types, (
                f"Unexpected alert_type: {item['alert_type']}"
            )

    @pytest.mark.asyncio
    async def test_compliance_alert_priority_valid_enum(self):
        """priority values in listed alerts are from the AlertPriority enum."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/compliance/alerts")
        assert response.status_code == 200
        data = response.json()

        valid_priorities = {"routine", "elevated", "urgent", "critical"}
        for item in data["items"]:
            assert item["priority"] in valid_priorities, (
                f"Unexpected priority: {item['priority']}"
            )

    @pytest.mark.asyncio
    async def test_compliance_alerts_list_schema(self):
        """GET /api/v1/compliance/alerts returns items list with total/limit/offset."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/compliance/alerts")
        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert isinstance(data["items"], list)
        assert "total" in data
        assert isinstance(data["total"], int)
        assert "limit" in data
        assert isinstance(data["limit"], int)
        assert "offset" in data
        assert isinstance(data["offset"], int)

    @pytest.mark.asyncio
    async def test_compliance_risk_level_valid_enum(self):
        """risk_level from POST /api/v1/compliance/risk must be a valid RiskLevel."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/compliance/risk",
                json={"user_id": "user-compliance-enum-test"},
            )
        data = response.json()

        valid_risk_levels = {"low", "medium", "high", "prohibited"}
        assert data["risk_level"] in valid_risk_levels, (
            f"Unexpected risk_level: {data['risk_level']}"
        )


# ---------------------------------------------------------------------------
# TestSessionAnomalySchemaCompliance
# ---------------------------------------------------------------------------


class TestSessionAnomalySchemaCompliance:
    """Verify session scoring responses conform to the documented schema."""

    @pytest.mark.asyncio
    async def test_session_score_response_has_all_required_fields(self):
        """POST /api/v1/behavior/sessions/score must return every documented field."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/behavior/sessions/score",
                    json=_session_score_payload(),
                )
            assert response.status_code == 200
            data = response.json()

            required_fields = [
                "session_id",
                "user_id",
                "composite_score",
                "classification",
                "dimension_scores",
                "profile_maturity",
                "recommended_action",
                "timestamp",
            ]
            for field in required_fields:
                assert field in data, f"Missing required field: {field}"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_session_score_value_ranges(self):
        """composite_score 0-1, valid classification and recommended_action enums."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/behavior/sessions/score",
                    json=_session_score_payload(),
                )
            data = response.json()

            assert 0.0 <= data["composite_score"] <= 1.0, (
                f"composite_score={data['composite_score']} out of [0,1]"
            )
            assert data["classification"] in {
                "normal",
                "suspicious",
                "high_risk",
                "critical",
            }, f"Unexpected classification: {data['classification']}"
            assert data["recommended_action"] in {
                "none",
                "monitor",
                "challenge",
                "terminate",
            }, f"Unexpected recommended_action: {data['recommended_action']}"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_session_score_dimension_scores_is_list(self):
        """dimension_scores must be a list."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/behavior/sessions/score",
                    json=_session_score_payload(),
                )
            data = response.json()
            assert isinstance(data["dimension_scores"], list)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_session_score_profile_maturity_is_int(self):
        """profile_maturity must be a non-negative integer."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/behavior/sessions/score",
                    json=_session_score_payload(),
                )
            data = response.json()
            assert isinstance(data["profile_maturity"], int)
            assert data["profile_maturity"] >= 0
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_session_score_timestamp_is_string(self):
        """timestamp must be a non-empty string (ISO 8601)."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/behavior/sessions/score",
                    json=_session_score_payload(),
                )
            data = response.json()
            assert isinstance(data["timestamp"], str)
            assert len(data["timestamp"]) > 0
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# TestSchemaEvolution
# ---------------------------------------------------------------------------


class TestSchemaEvolution:
    """Verify backward-compatible schema evolution: extra fields ignored,
    missing optional fields tolerated, required fields enforced."""

    @pytest.mark.asyncio
    async def test_extra_fields_in_request_do_not_break_fraud_score(self):
        """Requests with unknown extra fields should be handled gracefully.
        Pydantic will either ignore or forbid extras; either 200 or 422 is
        acceptable as long as the server does not crash (5xx)."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                payload = _fraud_score_payload(
                    future_field="some_value",
                    another_new_field=42,
                )
                response = await client.post("/api/v1/fraud/score", json=payload)
            # 200 (extra ignored) or 422 (extra forbidden) are both valid
            assert response.status_code in {200, 422}
            if response.status_code == 200:
                data = response.json()
                assert "transaction_id" in data
                assert "score" in data
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_extra_fields_in_request_do_not_break_session_score(self):
        """Session score requests with unknown fields should succeed.
        Pydantic will either ignore or forbid extras; either 200 or 422 is
        acceptable as long as the server does not crash (5xx)."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                payload = _session_score_payload(
                    unknown_future_dimension="test_value",
                )
                response = await client.post(
                    "/api/v1/behavior/sessions/score", json=payload
                )
            # 200 (extra ignored) or 422 (extra forbidden) are both valid
            assert response.status_code in {200, 422}
            if response.status_code == 200:
                data = response.json()
                assert "session_id" in data
                assert "composite_score" in data
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_missing_optional_fields_fraud_score(self):
        """Omitting optional fields (ip_address, device_id, etc.) must not
        break the fraud scoring endpoint."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Only required fields
                payload = {
                    "transaction_id": "txn-minimal-001",
                    "user_id": "user-minimal-001",
                    "amount": "50.00",
                }
                response = await client.post("/api/v1/fraud/score", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert data["transaction_id"] == "txn-minimal-001"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_missing_optional_fields_ato_assess(self):
        """Omitting optional ATO fields (device_id, ip_address, geo_location,
        etc.) must not break the assessment when the scoring-critical fields
        (session_duration_seconds, action_count) are provided."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Required fields plus scoring-critical defaults
                payload = {
                    "session_id": "sess-minimal-001",
                    "user_id": "user-minimal-001",
                    "session_duration_seconds": 60.0,
                    "action_count": 3,
                }
                response = await client.post(
                    "/api/v1/behavior/ato/assess", json=payload
                )
            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == "sess-minimal-001"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_missing_required_field_fraud_score_returns_422(self):
        """Omitting a required field (transaction_id) must return 422."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Missing transaction_id and user_id
                response = await client.post(
                    "/api/v1/fraud/score",
                    json={"amount": "100.00"},
                )
            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_missing_required_field_session_score_returns_422(self):
        """Omitting a required field (session_id, user_id) must return 422."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Empty body
                response = await client.post(
                    "/api/v1/behavior/sessions/score",
                    json={},
                )
            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_missing_required_field_ato_assess_returns_422(self):
        """Omitting required ATO fields must return 422."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/behavior/ato/assess",
                    json={},
                )
            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_malformed_amount_does_not_crash_server(self):
        """A non-numeric amount string must not cause a 5xx crash.
        The rules engine handles per-rule failures gracefully, so the server
        may return 200 (with a zero score) or a 4xx validation error."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                payload = _fraud_score_payload(amount="not-a-number")
                response = await client.post("/api/v1/fraud/score", json=payload)
            # The server must not crash; 200 (graceful degradation), 400, or 422 are OK
            assert response.status_code in {200, 400, 422}
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# TestAPIResponseConsistency
# ---------------------------------------------------------------------------


class TestAPIResponseConsistency:
    """Verify that all paginated list endpoints follow a consistent schema:
    {items: list, total: int, limit: int, offset: int}."""

    @pytest.mark.asyncio
    async def test_fraud_alerts_pagination_schema(self):
        """GET /api/v1/fraud/alerts must return items/total/limit/offset."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/fraud/alerts")
            assert response.status_code == 200
            data = response.json()
            self._assert_pagination_schema(data)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_compliance_alerts_pagination_schema(self):
        """GET /api/v1/compliance/alerts must return items/total/limit/offset."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/compliance/alerts")
        assert response.status_code == 200
        data = response.json()
        self._assert_pagination_schema(data)

    @pytest.mark.asyncio
    async def test_compliance_cases_pagination_schema(self):
        """GET /api/v1/compliance/cases must return items/total/limit/offset."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/compliance/cases")
        assert response.status_code == 200
        data = response.json()
        self._assert_pagination_schema(data)

    @pytest.mark.asyncio
    async def test_circle_health_summary_pagination_schema(self):
        """GET /api/v1/circles/health/summary must return items/total/limit/offset."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/circles/health/summary")
            assert response.status_code == 200
            data = response.json()
            self._assert_pagination_schema(data)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_circle_at_risk_pagination_schema(self):
        """GET /api/v1/circles/at-risk must return items/total/limit/offset."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/circles/at-risk")
            assert response.status_code == 200
            data = response.json()
            self._assert_pagination_schema(data)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ato_alerts_pagination_schema(self):
        """GET /api/v1/behavior/ato/alerts must return items/total/limit/offset."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/behavior/ato/alerts")
            assert response.status_code == 200
            data = response.json()
            self._assert_pagination_schema(data)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_fraud_alerts_respects_limit_offset_params(self):
        """GET /api/v1/fraud/alerts?limit=10&offset=5 must echo the parameters."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/fraud/alerts", params={"limit": 10, "offset": 5}
                )
            assert response.status_code == 200
            data = response.json()
            assert data["limit"] == 10
            assert data["offset"] == 5
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_compliance_alerts_respects_limit_offset_params(self):
        """GET /api/v1/compliance/alerts?limit=25&offset=10 must echo the parameters."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/compliance/alerts", params={"limit": 25, "offset": 10}
            )
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 25
        assert data["offset"] == 10

    @pytest.mark.asyncio
    async def test_circle_health_summary_respects_limit_offset_params(self):
        """GET /api/v1/circles/health/summary?limit=5&offset=0 must echo the parameters."""
        mock_session = _mock_session()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/circles/health/summary",
                    params={"limit": 5, "offset": 0},
                )
            assert response.status_code == 200
            data = response.json()
            assert data["limit"] == 5
            assert data["offset"] == 0
        finally:
            app.dependency_overrides.clear()

    # -- helper --

    def _assert_pagination_schema(self, data: dict) -> None:
        """Assert that a response dict follows the standard pagination schema."""
        assert "items" in data, "Missing 'items' key in paginated response"
        assert isinstance(data["items"], list), "'items' must be a list"
        assert "total" in data, "Missing 'total' key in paginated response"
        assert isinstance(data["total"], int), "'total' must be an int"
        assert "limit" in data, "Missing 'limit' key in paginated response"
        assert isinstance(data["limit"], int), "'limit' must be an int"
        assert "offset" in data, "Missing 'offset' key in paginated response"
        assert isinstance(data["offset"], int), "'offset' must be an int"
