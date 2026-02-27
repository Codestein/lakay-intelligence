"""Integration tests for health endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.db.database import get_session
from src.main import app
from tests.conftest import override_get_session

pytestmark = pytest.mark.integration


def _mock_session_with_no_results():
    """Create a mock session that returns empty results for queries."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()

    # Mock execute to return empty results for SELECT queries
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalar_one.return_value = 0
    mock_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
    session.execute = AsyncMock(return_value=mock_result)

    return session


class TestHealthEndpoints:
    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "version" in data
            assert "uptime_seconds" in data

    @pytest.mark.asyncio
    async def test_fraud_score_stub(self):
        mock_session = _mock_session_with_no_results()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/fraud/score",
                    json={
                        "transaction_id": "550e8400-e29b-41d4-a716-446655440000",
                        "user_id": "660e8400-e29b-41d4-a716-446655440001",
                        "amount": "100.00",
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert "score" in data
                assert data["model_version"] == "rules-v2"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_fraud_alerts_stub(self):
        mock_session = _mock_session_with_no_results()
        app.dependency_overrides[get_session] = override_get_session(mock_session)
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/fraud/alerts")
                assert response.status_code == 200
                data = response.json()
                assert data["items"] == []
                assert data["total"] == 0
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_circle_health_stub(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/circles/health",
                json={
                    "circle_id": "550e8400-e29b-41d4-a716-446655440000",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["model_version"] == "stub"

    @pytest.mark.asyncio
    async def test_behavior_anomaly_stub(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/behavior/anomaly",
                json={
                    "session_id": "550e8400-e29b-41d4-a716-446655440000",
                    "user_id": "660e8400-e29b-41d4-a716-446655440001",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["is_anomalous"] is False

    @pytest.mark.asyncio
    async def test_compliance_risk_stub(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/compliance/risk",
                json={
                    "user_id": "550e8400-e29b-41d4-a716-446655440000",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["risk_level"] == "low"
