"""A/B experimentation framework: assignment, lifecycle, reporting."""

import hashlib
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.pipeline.experiment_models import (
    CreateExperimentRequest,
    ExperimentReport,
    ExperimentResponse,
    ExperimentStatus,
    ExperimentVariant,
    MetricSummary,
)
from src.pipeline.metrics import (
    check_guardrails,
    compute_significance,
    compute_summary,
)
from src.pipeline.models import ExperimentAssignmentDB, ExperimentDB

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Assignment engine
# ---------------------------------------------------------------------------


def _hash_assignment(user_id: str, experiment_id: str, num_variants: int) -> int:
    """Deterministic assignment using hash of user_id + experiment_id."""
    key = f"{user_id}:{experiment_id}".encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    return int(digest[:8], 16) % num_variants


async def assign_user(
    session: AsyncSession,
    user_id: str,
    experiment_id: str,
) -> str | None:
    """Assign a user to a variant deterministically.

    Returns variant_id, or None if the experiment is not running or mutual exclusion blocks it.
    """
    # Check experiment exists and is running
    exp_result = await session.execute(
        select(ExperimentDB).where(ExperimentDB.experiment_id == experiment_id)
    )
    experiment = exp_result.scalar_one_or_none()
    if not experiment or experiment.status != ExperimentStatus.RUNNING:
        return None

    # Check for existing assignment (immutable)
    existing = await get_assignment(session, user_id, experiment_id)
    if existing:
        return existing

    # Check mutual exclusion: user can only be in one experiment per layer
    layer = experiment.layer or "default"
    layer_check = await session.execute(
        select(ExperimentAssignmentDB)
        .join(ExperimentDB, ExperimentDB.experiment_id == ExperimentAssignmentDB.experiment_id)
        .where(
            ExperimentAssignmentDB.user_id == user_id,
            ExperimentDB.layer == layer,
            ExperimentDB.status == ExperimentStatus.RUNNING,
            ExperimentDB.experiment_id != experiment_id,
        )
    )
    if layer_check.scalar_one_or_none():
        logger.info(
            "mutual_exclusion_blocked",
            user_id=user_id,
            experiment_id=experiment_id,
            layer=layer,
        )
        return None

    # Deterministic assignment
    variants = experiment.variants or []
    if not variants:
        return None

    idx = _hash_assignment(user_id, experiment_id, len(variants))
    variant = variants[idx]
    variant_id = variant.get("variant_id", f"variant_{idx}")

    # Persist assignment
    stmt = (
        pg_insert(ExperimentAssignmentDB)
        .values(
            user_id=user_id,
            experiment_id=experiment_id,
            variant_id=variant_id,
        )
        .on_conflict_do_nothing(constraint="uq_user_experiment")
    )
    await session.execute(stmt)
    await session.commit()

    logger.info(
        "user_assigned",
        user_id=user_id,
        experiment_id=experiment_id,
        variant_id=variant_id,
    )
    return variant_id


async def get_assignment(
    session: AsyncSession,
    user_id: str,
    experiment_id: str,
) -> str | None:
    """Retrieve existing assignment for a user in an experiment."""
    result = await session.execute(
        select(ExperimentAssignmentDB).where(
            ExperimentAssignmentDB.user_id == user_id,
            ExperimentAssignmentDB.experiment_id == experiment_id,
        )
    )
    row = result.scalar_one_or_none()
    return row.variant_id if row else None


async def get_active_experiments(session: AsyncSession) -> list[ExperimentResponse]:
    """List all running experiments."""
    result = await session.execute(
        select(ExperimentDB).where(ExperimentDB.status == ExperimentStatus.RUNNING)
    )
    rows = result.scalars().all()
    return [_db_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# Experiment lifecycle
# ---------------------------------------------------------------------------


async def create_experiment(
    session: AsyncSession,
    request: CreateExperimentRequest,
) -> ExperimentResponse:
    """Create a new experiment in draft status."""
    experiment_id = f"exp_{uuid.uuid4().hex[:12]}"

    # Build traffic allocation if not provided
    traffic = request.traffic_allocation
    if not traffic and request.variants:
        equal_share = round(1.0 / len(request.variants), 4)
        traffic = {v.variant_id: equal_share for v in request.variants}

    experiment = ExperimentDB(
        experiment_id=experiment_id,
        name=request.name,
        description=request.description,
        status=ExperimentStatus.DRAFT,
        hypothesis=request.hypothesis,
        variants=[v.model_dump() for v in request.variants],
        assignment_strategy=request.assignment_strategy,
        traffic_allocation=traffic,
        primary_metric=request.primary_metric,
        guardrail_metrics=request.guardrail_metrics,
        layer=request.layer,
        created_by=request.created_by,
    )
    session.add(experiment)
    await session.commit()
    await session.refresh(experiment)

    logger.info("experiment_created", experiment_id=experiment_id, name=request.name)
    return _db_to_response(experiment)


async def start_experiment(
    session: AsyncSession, experiment_id: str
) -> ExperimentResponse | None:
    """Start an experiment (draft → running)."""
    experiment = await _get_experiment(session, experiment_id)
    if not experiment:
        return None
    if experiment.status not in (ExperimentStatus.DRAFT, ExperimentStatus.PAUSED):
        logger.warning(
            "invalid_state_transition",
            experiment_id=experiment_id,
            current=experiment.status,
            target="running",
        )
        return _db_to_response(experiment)

    experiment.status = ExperimentStatus.RUNNING
    experiment.start_date = datetime.now(UTC)
    await session.commit()
    await session.refresh(experiment)

    logger.info("experiment_started", experiment_id=experiment_id)
    return _db_to_response(experiment)


async def pause_experiment(
    session: AsyncSession, experiment_id: str
) -> ExperimentResponse | None:
    """Pause an experiment (running → paused)."""
    experiment = await _get_experiment(session, experiment_id)
    if not experiment:
        return None
    if experiment.status != ExperimentStatus.RUNNING:
        return _db_to_response(experiment)

    experiment.status = ExperimentStatus.PAUSED
    await session.commit()
    await session.refresh(experiment)

    logger.info("experiment_paused", experiment_id=experiment_id)
    return _db_to_response(experiment)


async def complete_experiment(
    session: AsyncSession, experiment_id: str
) -> ExperimentResponse | None:
    """Complete an experiment and generate a final report."""
    experiment = await _get_experiment(session, experiment_id)
    if not experiment:
        return None
    if experiment.status not in (ExperimentStatus.RUNNING, ExperimentStatus.PAUSED):
        return _db_to_response(experiment)

    # Generate report
    report = await _generate_report(session, experiment)

    experiment.status = ExperimentStatus.COMPLETED
    experiment.end_date = datetime.now(UTC)
    experiment.report = report.model_dump(mode="json")
    await session.commit()
    await session.refresh(experiment)

    logger.info(
        "experiment_completed",
        experiment_id=experiment_id,
        recommendation=report.recommendation,
    )
    return _db_to_response(experiment)


async def get_experiment(
    session: AsyncSession, experiment_id: str
) -> ExperimentResponse | None:
    """Get experiment details."""
    experiment = await _get_experiment(session, experiment_id)
    return _db_to_response(experiment) if experiment else None


async def list_experiments(
    session: AsyncSession, status: str | None = None
) -> list[ExperimentResponse]:
    """List experiments, optionally filtered by status."""
    stmt = select(ExperimentDB).order_by(ExperimentDB.created_at.desc())
    if status:
        stmt = stmt.where(ExperimentDB.status == status)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_db_to_response(r) for r in rows]


async def get_experiment_results(
    session: AsyncSession, experiment_id: str
) -> dict | None:
    """Get statistical analysis results for an experiment."""
    experiment = await _get_experiment(session, experiment_id)
    if not experiment:
        return None

    primary_metric = experiment.primary_metric
    results: dict = {
        "experiment_id": experiment_id,
        "primary_metric": primary_metric,
        "significance": None,
        "metric_summaries": {},
    }

    if primary_metric:
        sig = await compute_significance(session, experiment_id, primary_metric)
        if sig:
            results["significance"] = sig.model_dump()

        summaries = await compute_summary(session, experiment_id, primary_metric)
        results["metric_summaries"][primary_metric] = [s.model_dump() for s in summaries]

    # Also compute summaries for guardrail metrics
    for metric in (experiment.guardrail_metrics or []):
        summaries = await compute_summary(session, experiment_id, metric)
        results["metric_summaries"][metric] = [s.model_dump() for s in summaries]

    return results


async def get_experiment_guardrails(
    session: AsyncSession, experiment_id: str
) -> list[dict] | None:
    """Get guardrail check status for an experiment."""
    experiment = await _get_experiment(session, experiment_id)
    if not experiment:
        return None

    statuses = await check_guardrails(session, experiment_id)
    return [s.model_dump() for s in statuses]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_experiment(session: AsyncSession, experiment_id: str) -> ExperimentDB | None:
    result = await session.execute(
        select(ExperimentDB).where(ExperimentDB.experiment_id == experiment_id)
    )
    return result.scalar_one_or_none()


async def _generate_report(
    session: AsyncSession, experiment: ExperimentDB
) -> ExperimentReport:
    """Generate a comprehensive experiment report."""
    experiment_id = experiment.experiment_id
    variants = [
        ExperimentVariant(**v) for v in (experiment.variants or [])
    ]

    # Compute metric summaries
    metric_summaries: dict[str, list[MetricSummary]] = {}
    all_metrics = set()
    if experiment.primary_metric:
        all_metrics.add(experiment.primary_metric)
    all_metrics.update(experiment.guardrail_metrics or [])

    for metric in all_metrics:
        summaries = await compute_summary(session, experiment_id, metric)
        metric_summaries[metric] = summaries

    # Compute significance for primary metric
    significance_results = []
    if experiment.primary_metric:
        sig = await compute_significance(session, experiment_id, experiment.primary_metric)
        if sig:
            significance_results.append(sig)

    # Check guardrails
    guardrail_statuses = await check_guardrails(session, experiment_id)

    # Determine recommendation
    recommendation = "inconclusive"
    any_breached = any(g.breached for g in guardrail_statuses)
    if any_breached:
        recommendation = "dont_ship"
    elif significance_results:
        sig = significance_results[0]
        if sig.is_significant and sig.effect_size > 0:
            recommendation = "ship"
        elif sig.is_significant and sig.effect_size < 0:
            recommendation = "dont_ship"

    return ExperimentReport(
        experiment_id=experiment_id,
        name=experiment.name,
        hypothesis=experiment.hypothesis or "",
        variants=variants,
        metric_summaries={
            k: [s.model_dump() for s in v] for k, v in metric_summaries.items()
        },
        significance_results=[s.model_dump() for s in significance_results],
        guardrail_statuses=[g.model_dump() for g in guardrail_statuses],
        recommendation=recommendation,
        generated_at=datetime.now(UTC),
    )


def _db_to_response(experiment: ExperimentDB) -> ExperimentResponse:
    """Convert DB model to API response."""
    return ExperimentResponse(
        experiment_id=experiment.experiment_id,
        name=experiment.name,
        description=experiment.description or "",
        status=experiment.status,
        hypothesis=experiment.hypothesis or "",
        variants=[ExperimentVariant(**v) for v in (experiment.variants or [])],
        assignment_strategy=experiment.assignment_strategy or "user_hash",
        traffic_allocation=experiment.traffic_allocation or {},
        primary_metric=experiment.primary_metric or "",
        guardrail_metrics=experiment.guardrail_metrics or [],
        layer=experiment.layer or "default",
        start_date=experiment.start_date,
        end_date=experiment.end_date,
        created_by=experiment.created_by or "system",
        created_at=experiment.created_at,
        report=experiment.report,
    )
