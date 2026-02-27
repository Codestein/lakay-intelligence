"""Feature drift detection using Population Stability Index (PSI).

Monitors input feature distributions over time and alerts when drift
is detected above configurable thresholds. Uses PSI as the primary
drift metric — it's widely used in financial model monitoring and
interpretable for compliance reporting.

Why PSI over KS-test: PSI gives a single interpretable number with
established thresholds (< 0.1 no drift, 0.1-0.25 moderate, > 0.25
significant). KS-test p-values are harder to threshold in production.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class DriftAlert:
    """Alert generated when feature drift is detected."""

    feature_name: str
    drift_score: float
    drift_method: str  # 'psi'
    severity: str  # 'warning', 'critical'
    window: str
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DriftConfig:
    """Configuration for feature drift detection."""

    psi_warning_threshold: float = 0.1
    psi_critical_threshold: float = 0.25
    num_bins: int = 10
    min_observations: int = 100
    check_interval_observations: int = 500
    max_observations: int = 50000


class FeatureDriftDetector:
    """Detects distribution drift in input features using PSI.

    Maintains a reference distribution (from training data) and
    compares current window distributions against it.
    """

    def __init__(
        self,
        feature_names: list[str],
        config: DriftConfig | None = None,
    ) -> None:
        self._feature_names = feature_names
        self._config = config or DriftConfig()
        self._reference_distributions: dict[str, np.ndarray] = {}
        self._reference_bin_edges: dict[str, np.ndarray] = {}
        self._observations: dict[str, deque] = {
            name: deque(maxlen=self._config.max_observations) for name in feature_names
        }
        self._observation_count = 0
        self._alerts: list[DriftAlert] = []

    def set_reference_distribution(
        self,
        feature_name: str,
        values: np.ndarray | list[float],
    ) -> None:
        """Set the reference (training) distribution for a feature.

        Computes and stores the histogram for PSI comparison.
        """
        values = np.array(values, dtype=float)
        values = values[~np.isnan(values)]
        if len(values) < self._config.num_bins:
            logger.warning(
                "insufficient_reference_data",
                feature=feature_name,
                count=len(values),
            )
            return

        # Compute histogram with equal-width bins
        hist, bin_edges = np.histogram(values, bins=self._config.num_bins)
        # Normalize to proportions, add small epsilon to avoid division by zero
        proportions = hist / hist.sum()
        proportions = np.clip(proportions, 1e-6, None)

        self._reference_distributions[feature_name] = proportions
        self._reference_bin_edges[feature_name] = bin_edges

        logger.info(
            "reference_distribution_set",
            feature=feature_name,
            num_values=len(values),
        )

    def set_reference_from_dataframe(self, df: Any) -> None:
        """Set reference distributions from a training DataFrame."""
        for feature in self._feature_names:
            if feature in df.columns:
                self.set_reference_distribution(feature, df[feature].values)

    def record_observation(self, features: dict[str, float]) -> list[DriftAlert]:
        """Record a single observation and periodically check for drift."""
        for name in self._feature_names:
            if name in features:
                self._observations[name].append(features[name])

        self._observation_count += 1

        # Check drift periodically
        if self._observation_count % self._config.check_interval_observations == 0:
            return self.check_drift()
        return []

    def check_drift(self) -> list[DriftAlert]:
        """Check all features for distribution drift against reference."""
        alerts: list[DriftAlert] = []
        now = datetime.now(UTC).isoformat()

        for feature_name in self._feature_names:
            if feature_name not in self._reference_distributions:
                continue

            obs = list(self._observations.get(feature_name, []))
            if len(obs) < self._config.min_observations:
                continue

            psi = self._compute_psi(feature_name, np.array(obs))
            if psi is None:
                continue

            severity = None
            if psi >= self._config.psi_critical_threshold:
                severity = "critical"
            elif psi >= self._config.psi_warning_threshold:
                severity = "warning"

            if severity:
                alert = DriftAlert(
                    feature_name=feature_name,
                    drift_score=round(psi, 4),
                    drift_method="psi",
                    severity=severity,
                    window=f"last_{len(obs)}_observations",
                    timestamp=now,
                    details={
                        "psi_threshold_warning": self._config.psi_warning_threshold,
                        "psi_threshold_critical": self._config.psi_critical_threshold,
                        "observation_count": len(obs),
                    },
                )
                alerts.append(alert)
                logger.warning(
                    "feature_drift_detected",
                    feature=feature_name,
                    psi=psi,
                    severity=severity,
                )

        self._alerts.extend(alerts)
        if len(self._alerts) > 1000:
            self._alerts = self._alerts[-1000:]

        return alerts

    def _compute_psi(self, feature_name: str, current_values: np.ndarray) -> float | None:
        """Compute Population Stability Index between reference and current.

        PSI = sum( (current_pct - reference_pct) * ln(current_pct / reference_pct) )

        Interpretation:
        - PSI < 0.1: No significant drift
        - 0.1 <= PSI < 0.25: Moderate drift (investigate)
        - PSI >= 0.25: Significant drift (retrain recommended)
        """
        reference = self._reference_distributions.get(feature_name)
        bin_edges = self._reference_bin_edges.get(feature_name)
        if reference is None or bin_edges is None:
            return None

        # Compute current distribution using reference bin edges
        current_hist, _ = np.histogram(current_values, bins=bin_edges)
        current_proportions = current_hist / max(current_hist.sum(), 1)
        current_proportions = np.clip(current_proportions, 1e-6, None)

        # PSI formula
        psi = float(
            np.sum((current_proportions - reference) * np.log(current_proportions / reference))
        )

        return psi

    def get_drift_report(self) -> dict[str, Any]:
        """Get current drift status for all monitored features."""
        report: dict[str, Any] = {
            "features": {},
            "total_observations": self._observation_count,
            "recent_alerts": [
                {
                    "feature": a.feature_name,
                    "psi": a.drift_score,
                    "severity": a.severity,
                    "timestamp": a.timestamp,
                }
                for a in self._alerts[-10:]
            ],
        }

        for feature_name in self._feature_names:
            obs = list(self._observations.get(feature_name, []))
            if len(obs) < self._config.min_observations:
                report["features"][feature_name] = {
                    "status": "insufficient_data",
                    "observation_count": len(obs),
                }
                continue

            psi = self._compute_psi(feature_name, np.array(obs))
            if psi is None:
                report["features"][feature_name] = {
                    "status": "no_reference",
                    "observation_count": len(obs),
                }
                continue

            status = "ok"
            if psi >= self._config.psi_critical_threshold:
                status = "critical_drift"
            elif psi >= self._config.psi_warning_threshold:
                status = "moderate_drift"

            report["features"][feature_name] = {
                "status": status,
                "psi": round(psi, 4),
                "observation_count": len(obs),
            }

        return report


# Module-level singleton
_detector: FeatureDriftDetector | None = None


def get_drift_detector(
    feature_names: list[str] | None = None,
    config: DriftConfig | None = None,
) -> FeatureDriftDetector:
    """Get or create the global drift detector."""
    global _detector
    if _detector is None:
        from .config import default_serving_config

        names = feature_names or default_serving_config.features.features
        _detector = FeatureDriftDetector(feature_names=names, config=config)
    return _detector
