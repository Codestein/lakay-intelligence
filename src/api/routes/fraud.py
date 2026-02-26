"""Fraud detection endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/fraud", tags=["fraud"])


class FraudScoreRequest(BaseModel):
    transaction_id: str
    user_id: str
    amount: str
    currency: str = "USD"
    ip_address: str | None = None
    device_id: str | None = None


@router.post("/score")
async def score_fraud(request: FraudScoreRequest) -> dict:
    return {
        "transaction_id": request.transaction_id,
        "score": 0,
        "confidence": 0.0,
        "risk_factors": [],
        "model_version": "stub",
        "computed_at": datetime.now(UTC).isoformat(),
    }


@router.get("/alerts")
async def list_alerts(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    severity: str | None = None,
    status: str | None = None,
) -> dict:
    return {
        "items": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
    }
