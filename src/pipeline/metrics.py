"""Metrics collection and statistical analysis for A/B experiments."""

import math
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.pipeline.experiment_models import (
    GuardrailStatus,
    MetricSummary,
    SignificanceResult,
)
from src.pipeline.models import ExperimentDB, ExperimentMetricDB

logger = structlog.get_logger()

# Default minimum sample size before computing significance
DEFAULT_MIN_SAMPLE_SIZE = 100

# Default guardrail thresholds
GUARDRAIL_THRESHOLDS = {
    "scoring_latency_p95_ms": 200.0,  # Must stay below 200ms
    "alert_volume_multiplier": 2.0,  # Must not spike >2x
    "compliance_alert_coverage": 0.0,  # Must not decrease (delta check)
    "system_error_rate": 0.0,  # Must not increase (delta check)
}


async def record_metric(
    session: AsyncSession,
    experiment_id: str,
    variant_id: str,
    metric_name: str,
    value: float,
    sample_size: int = 1,
) -> None:
    """Record a single metric observation."""
    metric = ExperimentMetricDB(
        experiment_id=experiment_id,
        variant_id=variant_id,
        metric_name=metric_name,
        metric_value=value,
        sample_size=sample_size,
    )
    session.add(metric)
    await session.commit()


async def compute_summary(
    session: AsyncSession,
    experiment_id: str,
    metric_name: str,
) -> list[MetricSummary]:
    """Compute per-variant summary statistics for a metric."""
    # Get all metric values grouped by variant
    stmt = (
        select(
            ExperimentMetricDB.variant_id,
            func.avg(ExperimentMetricDB.metric_value).label("mean"),
            func.stddev(ExperimentMetricDB.metric_value).label("std"),
            func.count(ExperimentMetricDB.id).label("count"),
        )
        .where(
            ExperimentMetricDB.experiment_id == experiment_id,
            ExperimentMetricDB.metric_name == metric_name,
        )
        .group_by(ExperimentMetricDB.variant_id)
    )
    result = await session.execute(stmt)
    rows = result.all()

    summaries = []
    for row in rows:
        mean = float(row.mean or 0.0)
        std = float(row.std or 0.0)
        count = int(row.count or 0)

        # 95% confidence interval
        if count > 1 and std > 0:
            se = std / math.sqrt(count)
            ci = (round(mean - 1.96 * se, 6), round(mean + 1.96 * se, 6))
        else:
            ci = (mean, mean)

        summaries.append(MetricSummary(
            variant_id=row.variant_id,
            metric_name=metric_name,
            mean=round(mean, 6),
            std=round(std, 6),
            count=count,
            confidence_interval=ci,
        ))

    return summaries


async def compute_significance(
    session: AsyncSession,
    experiment_id: str,
    metric_name: str,
    alpha: float = 0.05,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
) -> SignificanceResult | None:
    """Two-sample t-test comparing control vs treatment.

    Returns None if insufficient data.
    """
    # Get experiment to find variant names
    exp_result = await session.execute(
        select(ExperimentDB).where(ExperimentDB.experiment_id == experiment_id)
    )
    experiment = exp_result.scalar_one_or_none()
    if not experiment:
        return None

    variants = experiment.variants or []
    if len(variants) < 2:
        return None

    # Identify control and treatment
    control_id = variants[0].get("variant_id", "control")
    treatment_id = variants[1].get("variant_id", "treatment")

    # Fetch raw values for each variant
    control_values = await _get_metric_values(session, experiment_id, control_id, metric_name)
    treatment_values = await _get_metric_values(session, experiment_id, treatment_id, metric_name)

    n_control = len(control_values)
    n_treatment = len(treatment_values)

    minimum_sample_met = n_control >= min_sample_size and n_treatment >= min_sample_size

    if n_control < 2 or n_treatment < 2:
        return SignificanceResult(
            metric_name=metric_name,
            control_variant=control_id,
            treatment_variant=treatment_id,
            control_mean=_mean(control_values),
            treatment_mean=_mean(treatment_values),
            p_value=1.0,
            effect_size=0.0,
            confidence_interval=(0.0, 0.0),
            control_sample_size=n_control,
            treatment_sample_size=n_treatment,
            is_significant=False,
            alpha=alpha,
            minimum_sample_met=minimum_sample_met,
        )

    # Welch's t-test
    mean_c = _mean(control_values)
    mean_t = _mean(treatment_values)
    var_c = _variance(control_values)
    var_t = _variance(treatment_values)

    se = math.sqrt(var_c / n_control + var_t / n_treatment) if (var_c + var_t) > 0 else 0.001
    t_stat = (mean_t - mean_c) / se if se > 0 else 0.0

    # Degrees of freedom (Welch-Satterthwaite)
    if var_c > 0 and var_t > 0:
        num = (var_c / n_control + var_t / n_treatment) ** 2
        denom = (
            (var_c / n_control) ** 2 / (n_control - 1)
            + (var_t / n_treatment) ** 2 / (n_treatment - 1)
        )
        df = num / denom if denom > 0 else 1.0
    else:
        df = n_control + n_treatment - 2

    # Approximate p-value using normal approximation for large samples
    p_value = _approximate_p_value(abs(t_stat), df)

    # Effect size (Cohen's d)
    pooled_std = math.sqrt(
        ((n_control - 1) * var_c + (n_treatment - 1) * var_t)
        / (n_control + n_treatment - 2)
    ) if (n_control + n_treatment > 2) else 1.0
    effect_size = (mean_t - mean_c) / pooled_std if pooled_std > 0 else 0.0

    # Confidence interval for difference
    diff = mean_t - mean_c
    ci = (round(diff - 1.96 * se, 6), round(diff + 1.96 * se, 6))

    return SignificanceResult(
        metric_name=metric_name,
        control_variant=control_id,
        treatment_variant=treatment_id,
        control_mean=round(mean_c, 6),
        treatment_mean=round(mean_t, 6),
        p_value=round(p_value, 6),
        effect_size=round(effect_size, 6),
        confidence_interval=ci,
        control_sample_size=n_control,
        treatment_sample_size=n_treatment,
        is_significant=p_value < alpha and minimum_sample_met,
        alpha=alpha,
        minimum_sample_met=minimum_sample_met,
    )


async def check_guardrails(
    session: AsyncSession,
    experiment_id: str,
) -> list[GuardrailStatus]:
    """Check guardrail metrics for all variants."""
    # Get experiment
    exp_result = await session.execute(
        select(ExperimentDB).where(ExperimentDB.experiment_id == experiment_id)
    )
    experiment = exp_result.scalar_one_or_none()
    if not experiment:
        return []

    guardrail_metrics = experiment.guardrail_metrics or []
    variants = experiment.variants or []
    statuses = []

    for metric_name in guardrail_metrics:
        threshold = GUARDRAIL_THRESHOLDS.get(metric_name, 0.0)

        for variant in variants:
            vid = variant.get("variant_id", "")
            # Get latest metric value for this variant
            stmt = (
                select(func.avg(ExperimentMetricDB.metric_value))
                .where(
                    ExperimentMetricDB.experiment_id == experiment_id,
                    ExperimentMetricDB.variant_id == vid,
                    ExperimentMetricDB.metric_name == metric_name,
                )
            )
            result = await session.execute(stmt)
            avg_value = result.scalar() or 0.0

            breached = False
            if metric_name == "scoring_latency_p95_ms":
                breached = avg_value > threshold
            elif metric_name == "alert_volume_multiplier":
                breached = avg_value > threshold
            elif metric_name in ("compliance_alert_coverage", "system_error_rate"):
                # These are delta checks; for now check if degraded
                breached = avg_value < 0  # negative delta = degradation

            status = GuardrailStatus(
                metric_name=metric_name,
                variant_id=vid,
                current_value=round(float(avg_value), 6),
                threshold=threshold,
                breached=breached,
                description=f"{'BREACHED' if breached else 'OK'}: {metric_name} = {avg_value:.4f}",
            )
            statuses.append(status)

            if breached:
                logger.warning(
                    "guardrail_breached",
                    experiment_id=experiment_id,
                    variant_id=vid,
                    metric=metric_name,
                    value=avg_value,
                    threshold=threshold,
                )

    return statuses


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


async def _get_metric_values(
    session: AsyncSession,
    experiment_id: str,
    variant_id: str,
    metric_name: str,
) -> list[float]:
    stmt = (
        select(ExperimentMetricDB.metric_value)
        .where(
            ExperimentMetricDB.experiment_id == experiment_id,
            ExperimentMetricDB.variant_id == variant_id,
            ExperimentMetricDB.metric_name == metric_name,
        )
        .order_by(ExperimentMetricDB.recorded_at)
    )
    result = await session.execute(stmt)
    return [float(r[0]) for r in result.all()]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return sum((x - m) ** 2 for x in values) / (len(values) - 1)


def _approximate_p_value(t_abs: float, df: float) -> float:
    """Approximate two-tailed p-value from t-statistic using normal approx.

    For df > 30, t-distribution ≈ normal distribution.
    Uses a simple polynomial approximation.
    """
    if df <= 0 or t_abs <= 0:
        return 1.0

    # For large df, use normal approximation
    # P(|Z| > t) ≈ 2 * (1 - Φ(t))
    # Using Abramowitz & Stegun approximation for Φ
    z = t_abs
    p = 0.2316419
    b1 = 0.319381530
    b2 = -0.356563782
    b3 = 1.781477937
    b4 = -1.821255978
    b5 = 1.330274429

    t_val = 1.0 / (1.0 + p * z)
    phi = (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-z * z / 2.0)
    cdf = 1.0 - phi * (b1 * t_val + b2 * t_val**2 + b3 * t_val**3 + b4 * t_val**4 + b5 * t_val**5)

    p_value = 2.0 * (1.0 - cdf)
    return max(0.0, min(1.0, p_value))
