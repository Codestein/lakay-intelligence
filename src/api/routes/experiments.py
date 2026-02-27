"""API routes for the A/B experimentation framework."""

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_session
from src.pipeline.experiment_models import CreateExperimentRequest
from src.pipeline.experimentation import (
    complete_experiment,
    create_experiment,
    get_experiment,
    get_experiment_guardrails,
    get_experiment_results,
    list_experiments,
    pause_experiment,
    start_experiment,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/experiments", tags=["experiments"])


@router.post("")
async def create_experiment_endpoint(
    request: CreateExperimentRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create a new experiment."""
    exp = await create_experiment(session, request)
    return exp.model_dump(mode="json")


@router.put("/{experiment_id}/start")
async def start_experiment_endpoint(
    experiment_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Start an experiment."""
    exp = await start_experiment(session, experiment_id)
    if not exp:
        return {"error": "experiment_not_found", "experiment_id": experiment_id}
    return exp.model_dump(mode="json")


@router.put("/{experiment_id}/pause")
async def pause_experiment_endpoint(
    experiment_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Pause an experiment."""
    exp = await pause_experiment(session, experiment_id)
    if not exp:
        return {"error": "experiment_not_found", "experiment_id": experiment_id}
    return exp.model_dump(mode="json")


@router.put("/{experiment_id}/complete")
async def complete_experiment_endpoint(
    experiment_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Complete an experiment and generate final report."""
    exp = await complete_experiment(session, experiment_id)
    if not exp:
        return {"error": "experiment_not_found", "experiment_id": experiment_id}
    return exp.model_dump(mode="json")


@router.get("")
async def list_experiments_endpoint(
    status: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List experiments, optionally filtered by status."""
    experiments = await list_experiments(session, status)
    return {
        "experiments": [e.model_dump(mode="json") for e in experiments],
        "count": len(experiments),
    }


@router.get("/{experiment_id}")
async def get_experiment_endpoint(
    experiment_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get experiment details."""
    exp = await get_experiment(session, experiment_id)
    if not exp:
        return {"error": "experiment_not_found", "experiment_id": experiment_id}
    return exp.model_dump(mode="json")


@router.get("/{experiment_id}/results")
async def get_results_endpoint(
    experiment_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get statistical analysis results for an experiment."""
    results = await get_experiment_results(session, experiment_id)
    if not results:
        return {"error": "experiment_not_found", "experiment_id": experiment_id}
    return results


@router.get("/{experiment_id}/guardrails")
async def get_guardrails_endpoint(
    experiment_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get guardrail check status for an experiment."""
    statuses = await get_experiment_guardrails(session, experiment_id)
    if statuses is None:
        return {"error": "experiment_not_found", "experiment_id": experiment_id}
    return {"guardrails": statuses, "any_breached": any(s.get("breached") for s in statuses)}
