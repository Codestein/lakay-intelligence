"""Model performance monitoring: score distributions, latency tracking, alerts.

Tracks the distribution of model output scores and prediction latency
over sliding windows (1hr, 24hr, 7d). Generates alerts when metrics
deviate significantly from the baseline established at deployment time.
"""

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class MonitoringAlert:
    """Alert generated when a monitored metric exceeds thresholds."""

    alert_type: str  # 'score_distribution_shift', 'latency_sla_breach'
    severity: str  # 'warning', 'critical'
    metric_name: str
    current_value: float
    baseline_value: float
    threshold: float
    window: str
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreDistribution:
    """Summary statistics for a window of model scores."""

    mean: float = 0.0
    std: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    count: int = 0


@dataclass
class LatencyStats:
    """Latency percentiles for prediction serving."""

    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    count: int = 0


@dataclass
class MonitoringConfig:
    """Configuration for monitoring thresholds and windows."""

    score_shift_std_threshold: float = 2.0
    latency_sla_p95_ms: float = 200.0
    latency_sla_p99_ms: float = 500.0
    max_observations: int = 100000


class ModelMonitor:
    """Tracks model performance metrics over time.

    Maintains sliding windows of score observations and latency
    measurements. Compares current window statistics against the
    baseline established at model deployment time.
    """

    def __init__(self, config: MonitoringConfig | None = None) -> None:
        self._config = config or MonitoringConfig()
        self._scores: deque[tuple[float, float]] = deque(
            maxlen=self._config.max_observations
        )  # (timestamp, score)
        self._latencies: deque[tuple[float, float]] = deque(
            maxlen=self._config.max_observations
        )  # (timestamp, latency_ms)
        self._baseline_scores: ScoreDistribution | None = None
        self._alerts: list[MonitoringAlert] = []
        self._model_version: str = "unknown"
        self._loaded_at: float = 0.0

    def set_baseline(
        self,
        scores: list[float],
        model_version: str,
    ) -> None:
        """Establish baseline score distribution from deployment-time evaluation."""
        scores_arr = np.array(scores)
        self._baseline_scores = ScoreDistribution(
            mean=float(np.mean(scores_arr)),
            std=float(np.std(scores_arr)),
            p50=float(np.percentile(scores_arr, 50)),
            p95=float(np.percentile(scores_arr, 95)),
            p99=float(np.percentile(scores_arr, 99)),
            count=len(scores),
        )
        self._model_version = model_version
        self._loaded_at = time.time()
        logger.info(
            "monitoring_baseline_set",
            model_version=model_version,
            mean=self._baseline_scores.mean,
            std=self._baseline_scores.std,
        )

    def record_prediction(self, score: float, latency_ms: float) -> list[MonitoringAlert]:
        """Record a single prediction observation and check for alerts."""
        now = time.time()
        self._scores.append((now, score))
        self._latencies.append((now, latency_ms))

        # Check for alerts periodically (every 100 observations)
        if len(self._scores) % 100 == 0:
            return self._check_alerts()
        return []

    def get_score_distribution(self, window_hours: float = 1.0) -> ScoreDistribution:
        """Get score distribution for the specified time window."""
        cutoff = time.time() - (window_hours * 3600)
        scores = [s for t, s in self._scores if t >= cutoff]
        if not scores:
            return ScoreDistribution()
        arr = np.array(scores)
        return ScoreDistribution(
            mean=float(np.mean(arr)),
            std=float(np.std(arr)),
            p50=float(np.percentile(arr, 50)),
            p95=float(np.percentile(arr, 95)),
            p99=float(np.percentile(arr, 99)),
            count=len(scores),
        )

    def get_latency_stats(self, window_hours: float = 1.0) -> LatencyStats:
        """Get latency percentiles for the specified time window."""
        cutoff = time.time() - (window_hours * 3600)
        latencies = [lat for t, lat in self._latencies if t >= cutoff]
        if not latencies:
            return LatencyStats()
        arr = np.array(latencies)
        return LatencyStats(
            p50_ms=float(np.percentile(arr, 50)),
            p95_ms=float(np.percentile(arr, 95)),
            p99_ms=float(np.percentile(arr, 99)),
            count=len(latencies),
        )

    def get_health_report(self) -> dict[str, Any]:
        """Get current model health metrics for the monitoring API."""
        score_1h = self.get_score_distribution(window_hours=1.0)
        score_24h = self.get_score_distribution(window_hours=24.0)
        latency_1h = self.get_latency_stats(window_hours=1.0)

        return {
            "model_version": self._model_version,
            "last_reload_timestamp": (
                datetime.fromtimestamp(self._loaded_at, tz=UTC).isoformat()
                if self._loaded_at
                else None
            ),
            "total_predictions": len(self._scores),
            "score_distribution_1h": {
                "mean": score_1h.mean,
                "std": score_1h.std,
                "p50": score_1h.p50,
                "p95": score_1h.p95,
                "count": score_1h.count,
            },
            "score_distribution_24h": {
                "mean": score_24h.mean,
                "std": score_24h.std,
                "p50": score_24h.p50,
                "p95": score_24h.p95,
                "count": score_24h.count,
            },
            "latency_1h": {
                "p50_ms": latency_1h.p50_ms,
                "p95_ms": latency_1h.p95_ms,
                "p99_ms": latency_1h.p99_ms,
                "count": latency_1h.count,
            },
            "baseline": (
                {
                    "mean": self._baseline_scores.mean,
                    "std": self._baseline_scores.std,
                }
                if self._baseline_scores
                else None
            ),
            "recent_alerts": [
                {
                    "type": a.alert_type,
                    "severity": a.severity,
                    "metric": a.metric_name,
                    "timestamp": a.timestamp,
                }
                for a in self._alerts[-10:]
            ],
        }

    def _check_alerts(self) -> list[MonitoringAlert]:
        """Check current metrics against thresholds and generate alerts."""
        new_alerts: list[MonitoringAlert] = []
        now = datetime.now(UTC).isoformat()

        # Check score distribution shift (1h vs baseline)
        if self._baseline_scores and self._baseline_scores.std > 0:
            current = self.get_score_distribution(window_hours=1.0)
            if current.count >= 10:
                z_shift = abs(current.mean - self._baseline_scores.mean) / max(
                    self._baseline_scores.std, 0.001
                )
                if z_shift > self._config.score_shift_std_threshold:
                    alert = MonitoringAlert(
                        alert_type="score_distribution_shift",
                        severity="warning" if z_shift < 3 else "critical",
                        metric_name="score_mean",
                        current_value=current.mean,
                        baseline_value=self._baseline_scores.mean,
                        threshold=self._config.score_shift_std_threshold,
                        window="1h",
                        timestamp=now,
                        details={"z_shift": z_shift},
                    )
                    new_alerts.append(alert)
                    logger.warning(
                        "score_distribution_shift_detected",
                        z_shift=z_shift,
                        current_mean=current.mean,
                        baseline_mean=self._baseline_scores.mean,
                    )

        # Check latency SLA
        latency = self.get_latency_stats(window_hours=1.0)
        if latency.count >= 10 and latency.p95_ms > self._config.latency_sla_p95_ms:
            alert = MonitoringAlert(
                alert_type="latency_sla_breach",
                severity="critical",
                metric_name="latency_p95",
                current_value=latency.p95_ms,
                baseline_value=self._config.latency_sla_p95_ms,
                threshold=self._config.latency_sla_p95_ms,
                window="1h",
                timestamp=now,
            )
            new_alerts.append(alert)
            logger.warning(
                "latency_sla_breach",
                p95_ms=latency.p95_ms,
                sla_ms=self._config.latency_sla_p95_ms,
            )

        self._alerts.extend(new_alerts)
        # Keep only last 1000 alerts
        if len(self._alerts) > 1000:
            self._alerts = self._alerts[-1000:]

        return new_alerts


# Module-level singleton
_monitor: ModelMonitor | None = None


def get_model_monitor(config: MonitoringConfig | None = None) -> ModelMonitor:
    """Get or create the global ModelMonitor singleton."""
    global _monitor
    if _monitor is None:
        _monitor = ModelMonitor(config=config)
    return _monitor
