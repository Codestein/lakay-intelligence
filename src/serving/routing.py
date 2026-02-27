"""A/B model routing for canary deployments.

Routes scoring requests between a champion (Production) and challenger
(Staging) model based on configurable traffic split percentages.
Uses deterministic hashing of user_id so the same user always gets
the same model during an experiment (no flickering).
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from .server import ModelServer, PredictionResult

logger = structlog.get_logger()


@dataclass
class RoutingConfig:
    """Traffic split configuration for A/B routing."""

    champion_pct: float = 95.0  # % of traffic to champion (Production)
    challenger_pct: float = 5.0  # % of traffic to challenger (Staging)
    enabled: bool = True

    def __post_init__(self):
        total = self.champion_pct + self.challenger_pct
        if abs(total - 100.0) > 0.01:
            raise ValueError(f"Traffic split must sum to 100%, got {total}%")


@dataclass
class RoutingDecision:
    """Record of which model was selected for a request."""

    user_id: str
    model_variant: str  # 'champion' or 'challenger'
    model_name: str
    model_version: str
    prediction: PredictionResult | None
    timestamp: str


@dataclass
class AutoPromotionConfig:
    """Configuration for automatic promotion of challenger models.

    Placeholder: defines the interface for statistical significance
    testing. The actual test is not yet implemented.
    """

    enabled: bool = False
    min_observations: int = 1000
    metric: str = "precision"
    improvement_threshold: float = 0.05
    confidence_level: float = 0.95


class ModelRouter:
    """Routes prediction requests between champion and challenger models.

    Deterministic assignment: uses hash(user_id) % 100 to decide routing,
    so the same user always hits the same model variant.
    """

    def __init__(
        self,
        champion: ModelServer | None = None,
        challenger: ModelServer | None = None,
        config: RoutingConfig | None = None,
        auto_promotion: AutoPromotionConfig | None = None,
    ) -> None:
        self._champion = champion
        self._challenger = challenger
        self._config = config or RoutingConfig()
        self._auto_promotion = auto_promotion or AutoPromotionConfig()
        self._metrics: list[dict[str, Any]] = []

    @property
    def config(self) -> RoutingConfig:
        return self._config

    @property
    def champion(self) -> ModelServer | None:
        return self._champion

    @property
    def challenger(self) -> ModelServer | None:
        return self._challenger

    def set_champion(self, server: ModelServer) -> None:
        self._champion = server

    def set_challenger(self, server: ModelServer) -> None:
        self._challenger = server

    def update_config(self, champion_pct: float, challenger_pct: float) -> None:
        """Update traffic split percentages."""
        self._config = RoutingConfig(
            champion_pct=champion_pct,
            challenger_pct=challenger_pct,
        )
        logger.info(
            "routing_config_updated",
            champion_pct=champion_pct,
            challenger_pct=challenger_pct,
        )

    def route(self, user_id: str, features: dict[str, Any]) -> RoutingDecision:
        """Route a scoring request to the appropriate model.

        Uses deterministic hashing so the same user_id always gets
        the same model during an experiment.
        """
        variant = self._assign_variant(user_id)

        if variant == "challenger" and self._challenger and self._challenger.is_loaded:
            server = self._challenger
        elif self._champion and self._champion.is_loaded:
            server = self._champion
            variant = "champion"  # Fallback if challenger unavailable
        else:
            # No models available
            return RoutingDecision(
                user_id=user_id,
                model_variant="none",
                model_name="none",
                model_version="none",
                prediction=None,
                timestamp=datetime.now(UTC).isoformat(),
            )

        prediction = server.predict(features)

        decision = RoutingDecision(
            user_id=user_id,
            model_variant=variant,
            model_name=server.model_name,
            model_version=server.model_version,
            prediction=prediction,
            timestamp=datetime.now(UTC).isoformat(),
        )

        # Log metrics for comparison
        self._record_metric(decision)

        return decision

    def _assign_variant(self, user_id: str) -> str:
        """Deterministically assign user to champion or challenger."""
        if not self._config.enabled or self._config.challenger_pct == 0:
            return "champion"

        hash_val = int(hashlib.sha256(user_id.encode()).hexdigest(), 16) % 100
        if hash_val < self._config.challenger_pct:
            return "challenger"
        return "champion"

    def _record_metric(self, decision: RoutingDecision) -> None:
        """Record metrics for model comparison."""
        metric = {
            "user_id": decision.user_id,
            "variant": decision.model_variant,
            "model_name": decision.model_name,
            "model_version": decision.model_version,
            "score": decision.prediction.score if decision.prediction else None,
            "latency_ms": (
                decision.prediction.prediction_latency_ms if decision.prediction else None
            ),
            "timestamp": decision.timestamp,
        }
        self._metrics.append(metric)

        # Keep only last 10000 metrics in memory
        if len(self._metrics) > 10000:
            self._metrics = self._metrics[-10000:]

    def get_metrics_summary(self) -> dict[str, Any]:
        """Summarize collected metrics by model variant."""
        if not self._metrics:
            return {"champion": {}, "challenger": {}, "total_observations": 0}

        import numpy as np

        summary: dict[str, Any] = {"total_observations": len(self._metrics)}

        for variant in ["champion", "challenger"]:
            variant_metrics = [m for m in self._metrics if m["variant"] == variant]
            if not variant_metrics:
                summary[variant] = {"count": 0}
                continue

            scores = [m["score"] for m in variant_metrics if m["score"] is not None]
            latencies = [m["latency_ms"] for m in variant_metrics if m["latency_ms"] is not None]

            summary[variant] = {
                "count": len(variant_metrics),
                "mean_score": float(np.mean(scores)) if scores else 0,
                "mean_latency_ms": float(np.mean(latencies)) if latencies else 0,
                "p95_latency_ms": float(np.percentile(latencies, 95)) if latencies else 0,
            }

        return summary

    def check_auto_promotion(self) -> bool:
        """Check if challenger should be auto-promoted based on criteria.

        Placeholder implementation: returns False until sufficient data
        and statistical testing are implemented.
        """
        if not self._auto_promotion.enabled:
            return False

        champion_metrics = [m for m in self._metrics if m["variant"] == "champion"]
        challenger_metrics = [m for m in self._metrics if m["variant"] == "challenger"]

        if (
            len(champion_metrics) < self._auto_promotion.min_observations
            or len(challenger_metrics) < self._auto_promotion.min_observations
        ):
            return False

        # TODO: Implement statistical significance test (e.g., chi-squared
        # or proportion z-test on precision). For now, this is a stub.
        logger.info(
            "auto_promotion_check",
            champion_count=len(champion_metrics),
            challenger_count=len(challenger_metrics),
            result="insufficient_data_for_test",
        )
        return False


# Module-level singleton
_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    """Get or create the global ModelRouter singleton."""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
