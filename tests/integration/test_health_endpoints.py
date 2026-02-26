"""Integration tests for health endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app

pytestmark = pytest.mark.integration


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
            assert data["score"] == 0
            assert data["model_version"] == "stub"

    @pytest.mark.asyncio
    async def test_fraud_alerts_stub(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/fraud/alerts")
            assert response.status_code == 200
            data = response.json()
            assert data["items"] == []
            assert data["total"] == 0

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
