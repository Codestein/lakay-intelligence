"""BSA/AML transaction monitoring. Stub for Phase 3."""

from datetime import UTC, datetime

import structlog

from .models import ComplianceRiskRequest, ComplianceRiskResponse, RiskLevel

logger = structlog.get_logger()


class ComplianceMonitor:
    async def assess_risk(self, request: ComplianceRiskRequest) -> ComplianceRiskResponse:
        logger.info("assessing_compliance_risk", user_id=request.user_id)
        return ComplianceRiskResponse(
            user_id=request.user_id,
            risk_level=RiskLevel.LOW,
            risk_score=0.0,
            factors={},
            model_version="stub",
            computed_at=datetime.now(UTC),
        )
