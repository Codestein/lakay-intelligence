"""Compliance risk assessment endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])


class ComplianceRiskRequest(BaseModel):
    user_id: str


@router.post("/risk")
async def assess_risk(request: ComplianceRiskRequest) -> dict:
    return {
        "user_id": request.user_id,
        "risk_level": "low",
        "risk_score": 0.0,
        "factors": {},
        "model_version": "stub",
        "computed_at": datetime.now(UTC).isoformat(),
    }
