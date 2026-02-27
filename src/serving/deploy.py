"""Model deployment pipeline: validate, promote, rollback.

Manages the lifecycle of model versions from Staging to Production,
with validation gates and rollback capability. Deployment metadata
is stored in PostgreSQL for auditability.
"""

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

from .config import ServingConfig, default_serving_config

logger = structlog.get_logger()


@dataclass
class ValidationResult:
    """Result of model validation before promotion."""

    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    latency_p95_ms: float = 0.0
    timestamp: str = ""


@dataclass
class DeploymentRecord:
    """Metadata for a model deployment event."""

    model_name: str
    model_version: str
    previous_version: str | None
    action: str  # 'promote', 'rollback', 'archive'
    triggered_by: str
    validation_result: ValidationResult | None
    timestamp: str
    success: bool


class DeploymentPipeline:
    """Orchestrates model validation, promotion, and rollback."""

    def __init__(
        self,
        tracking_uri: str = "http://localhost:5000",
        config: ServingConfig | None = None,
    ) -> None:
        self._tracking_uri = tracking_uri
        self._config = config or default_serving_config
        self._deployment_history: list[DeploymentRecord] = []

    def validate_model(
        self,
        name: str,
        version: str,
        synthetic_events: list[dict[str, Any]] | None = None,
        latency_sla_ms: float = 200.0,
    ) -> ValidationResult:
        """Run validation suite against a staged model before promotion.

        Checks:
        1. Model loads successfully
        2. Model scores synthetic events within latency SLA
        3. All scores are in expected range [0, 1], no NaN/Inf
        """
        checks: dict[str, bool] = {}
        details: dict[str, Any] = {}
        latencies: list[float] = []

        # Check 1: Model loads
        try:
            from .registry import ModelRegistry

            registry = ModelRegistry(tracking_uri=self._tracking_uri)
            model = registry.load_model(name=name, stage="Staging")
            checks["model_loads"] = True
        except Exception as e:
            checks["model_loads"] = False
            details["load_error"] = str(e)
            return ValidationResult(
                passed=False,
                checks=checks,
                details=details,
                timestamp=datetime.now(UTC).isoformat(),
            )

        # Check 2 & 3: Score synthetic events
        if synthetic_events is None:
            synthetic_events = _generate_validation_events(count=100)

        import pandas as pd

        scores = []
        for event in synthetic_events:
            start = time.perf_counter()
            try:
                df = pd.DataFrame([event])
                pred = model.predict(df)
                score = float(pred[0]) if hasattr(pred, "__len__") else float(pred)
                scores.append(score)
            except Exception as e:
                details["prediction_error"] = str(e)
                scores.append(float("nan"))
            latencies.append((time.perf_counter() - start) * 1000)

        scores_arr = np.array(scores)

        # Check scores are valid
        valid_scores = ~np.isnan(scores_arr) & ~np.isinf(scores_arr)
        in_range = (scores_arr >= 0) & (scores_arr <= 1)
        checks["scores_valid"] = bool(valid_scores.all())
        checks["scores_in_range"] = bool(in_range[valid_scores].all())

        # Check latency SLA
        latency_p95 = float(np.percentile(latencies, 95))
        checks["latency_within_sla"] = latency_p95 <= latency_sla_ms

        details["num_events_tested"] = len(synthetic_events)
        details["valid_score_pct"] = float(valid_scores.mean())
        details["mean_score"] = float(np.nanmean(scores_arr))
        details["latency_p50_ms"] = float(np.percentile(latencies, 50))
        details["latency_p95_ms"] = latency_p95
        details["latency_p99_ms"] = float(np.percentile(latencies, 99))

        passed = all(checks.values())

        result = ValidationResult(
            passed=passed,
            checks=checks,
            details=details,
            latency_p95_ms=latency_p95,
            timestamp=datetime.now(UTC).isoformat(),
        )

        logger.info(
            "model_validation_complete",
            name=name,
            version=version,
            passed=passed,
            checks=checks,
        )

        return result

    def promote_to_production(
        self,
        name: str,
        version: str,
        triggered_by: str = "manual",
        skip_validation: bool = False,
    ) -> DeploymentRecord:
        """Promote a Staging model to Production after validation.

        Archives the previous Production model automatically.
        """
        from .registry import ModelRegistry

        registry = ModelRegistry(tracking_uri=self._tracking_uri)

        # Get current production version for rollback tracking
        previous_version = None
        try:
            metadata = registry.get_model_metadata(name, stage="Production")
            if metadata:
                previous_version = metadata.version
        except Exception:
            pass

        # Validate unless explicitly skipped
        validation = None
        if not skip_validation:
            validation = self.validate_model(name, version)
            if not validation.passed:
                record = DeploymentRecord(
                    model_name=name,
                    model_version=version,
                    previous_version=previous_version,
                    action="promote",
                    triggered_by=triggered_by,
                    validation_result=validation,
                    timestamp=datetime.now(UTC).isoformat(),
                    success=False,
                )
                self._deployment_history.append(record)
                logger.warning(
                    "promotion_blocked_validation_failed",
                    name=name,
                    version=version,
                    checks=validation.checks,
                )
                return record

        # Promote
        registry.promote_model(name, version, "Production")

        record = DeploymentRecord(
            model_name=name,
            model_version=version,
            previous_version=previous_version,
            action="promote",
            triggered_by=triggered_by,
            validation_result=validation,
            timestamp=datetime.now(UTC).isoformat(),
            success=True,
        )
        self._deployment_history.append(record)

        logger.info(
            "model_promoted_to_production",
            name=name,
            version=version,
            previous_version=previous_version,
        )

        return record

    def rollback(self, name: str, triggered_by: str = "manual") -> DeploymentRecord:
        """Rollback to the previously archived Production model version.

        Finds the most recently archived version and promotes it back
        to Production.
        """
        try:
            from .registry import ModelRegistry

            registry = ModelRegistry(tracking_uri=self._tracking_uri)
        except Exception as e:
            record = DeploymentRecord(
                model_name=name,
                model_version="none",
                previous_version=None,
                action="rollback",
                triggered_by=triggered_by,
                validation_result=None,
                timestamp=datetime.now(UTC).isoformat(),
                success=False,
            )
            self._deployment_history.append(record)
            logger.error("rollback_failed_registry_unavailable", name=name, error=str(e))
            return record

        # Get current production version
        current_version = None
        try:
            metadata = registry.get_model_metadata(name, stage="Production")
            if metadata:
                current_version = metadata.version
        except Exception:
            pass

        # Find the most recent archived version
        try:
            versions = registry.list_model_versions(name)
        except Exception:
            versions = []
        archived = [v for v in versions if v.stage == "Archived"]
        if not archived:
            record = DeploymentRecord(
                model_name=name,
                model_version="none",
                previous_version=current_version,
                action="rollback",
                triggered_by=triggered_by,
                validation_result=None,
                timestamp=datetime.now(UTC).isoformat(),
                success=False,
            )
            self._deployment_history.append(record)
            logger.error("rollback_failed_no_archived_version", name=name)
            return record

        # Pick the highest version number among archived
        rollback_target = max(archived, key=lambda v: int(v.version))

        # Archive current production, promote rollback target
        if current_version:
            registry.promote_model(name, current_version, "Archived")
        registry.promote_model(name, rollback_target.version, "Production")

        record = DeploymentRecord(
            model_name=name,
            model_version=rollback_target.version,
            previous_version=current_version,
            action="rollback",
            triggered_by=triggered_by,
            validation_result=None,
            timestamp=datetime.now(UTC).isoformat(),
            success=True,
        )
        self._deployment_history.append(record)

        logger.info(
            "model_rolled_back",
            name=name,
            rolled_back_to=rollback_target.version,
            from_version=current_version,
        )

        return record

    @property
    def history(self) -> list[DeploymentRecord]:
        return list(self._deployment_history)


def _generate_validation_events(count: int = 100) -> list[dict[str, Any]]:
    """Generate synthetic feature vectors for model validation."""
    rng = np.random.default_rng(42)
    events = []
    for _ in range(count):
        events.append(
            {
                "amount": float(rng.lognormal(4.5, 1.2)),
                "amount_zscore": float(rng.normal(0, 1)),
                "hour_of_day": int(rng.integers(0, 24)),
                "day_of_week": int(rng.integers(0, 7)),
                "tx_type_encoded": int(rng.integers(0, 5)),
                "balance_delta_sender": float(rng.normal(100, 50)),
                "balance_delta_receiver": float(rng.normal(100, 50)),
                "velocity_count_1h": int(rng.integers(0, 10)),
                "velocity_count_24h": int(rng.integers(0, 30)),
                "velocity_amount_1h": float(rng.lognormal(3, 1)),
                "velocity_amount_24h": float(rng.lognormal(5, 1)),
            }
        )
    return events
