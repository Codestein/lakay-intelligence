"""Model serving layer with in-process MLflow pyfunc loading.

Uses Option A from the architecture plan: direct in-process serving
within the FastAPI service. This avoids managing a separate serving
process and is sufficient for infrastructure validation.

Why in-process over TF Serving/TorchServe: We're using XGBoost (GBT),
which doesn't need a GPU serving runtime. In-process loading via
mlflow.pyfunc is simpler, Docker-compatible, and meets the latency SLA.
"""

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

from .config import ServingConfig, default_serving_config

logger = structlog.get_logger()


@dataclass
class PredictionResult:
    """Standardized prediction output from the ML model."""

    score: float
    model_name: str
    model_version: str
    prediction_latency_ms: float
    feature_vector: dict[str, Any] = field(default_factory=dict)


class ModelServer:
    """Manages model lifecycle and serves predictions.

    On startup, loads the Production-stage model from MLflow.
    Supports hot-reloading when a new model version is promoted.
    Falls back to None (caller should use rule-based scoring).
    """

    def __init__(self, config: ServingConfig | None = None) -> None:
        self._config = config or default_serving_config
        self._model = None
        self._model_name: str = self._config.model.name
        self._model_version: str = "unknown"
        self._model_stage: str = self._config.model.stage
        self._loaded_at: float = 0.0
        self._load_error: str | None = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def loaded_at(self) -> float:
        return self._loaded_at

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load_model(self, tracking_uri: str = "http://localhost:5000") -> bool:
        """Load the current Production model from MLflow registry.

        Returns True if model loaded successfully, False otherwise.
        On failure, the server remains in fallback mode (no model).
        """
        try:
            from .registry import ModelRegistry

            registry = ModelRegistry(tracking_uri=tracking_uri)
            self._model = registry.load_model(
                name=self._model_name,
                stage=self._model_stage,
            )

            metadata = registry.get_model_metadata(
                name=self._model_name,
                stage=self._model_stage,
            )
            if metadata:
                self._model_version = metadata.version

            self._loaded_at = time.time()
            self._load_error = None

            logger.info(
                "model_loaded_for_serving",
                name=self._model_name,
                version=self._model_version,
                stage=self._model_stage,
            )
            return True

        except Exception as e:
            self._load_error = str(e)
            self._model = None
            logger.warning(
                "model_load_failed_fallback_active",
                name=self._model_name,
                stage=self._model_stage,
                error=str(e),
            )
            return False

    def reload_model(self, tracking_uri: str = "http://localhost:5000") -> bool:
        """Hot-reload the model from registry. Returns True on success."""
        logger.info("model_reload_triggered", name=self._model_name)
        return self.load_model(tracking_uri=tracking_uri)

    def predict(self, features: dict[str, Any]) -> PredictionResult | None:
        """Score a single transaction using the loaded ML model.

        Args:
            features: Dictionary mapping feature names to values.

        Returns:
            PredictionResult if model is loaded, None otherwise (fallback signal).
        """
        if not self.is_loaded:
            logger.debug("predict_skipped_no_model")
            return None

        start = time.perf_counter()
        try:
            import pandas as pd

            # Build feature vector in the expected order
            expected_features = self._config.features.features
            feature_vector = {f: features.get(f, 0.0) for f in expected_features}
            df = pd.DataFrame([feature_vector])

            raw_prediction = self._model.predict(df)

            # Extract score — handle both array and scalar outputs
            if isinstance(raw_prediction, np.ndarray):
                score = float(raw_prediction[0])
            else:
                score = float(raw_prediction)

            # Clamp to [0, 1]
            score = max(0.0, min(1.0, score))

            latency_ms = (time.perf_counter() - start) * 1000

            return PredictionResult(
                score=score,
                model_name=self._model_name,
                model_version=self._model_version,
                prediction_latency_ms=round(latency_ms, 2),
                feature_vector=feature_vector,
            )

        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "prediction_failed",
                error=str(e),
                latency_ms=round(latency_ms, 2),
            )
            return None

    def predict_batch(self, feature_list: list[dict[str, Any]]) -> list[PredictionResult | None]:
        """Score a batch of transactions. Returns list aligned with input."""
        return [self.predict(f) for f in feature_list]


# Module-level singleton for the serving layer
_model_server: ModelServer | None = None


def get_model_server(config: ServingConfig | None = None) -> ModelServer:
    """Get or create the global ModelServer singleton."""
    global _model_server
    if _model_server is None:
        _model_server = ModelServer(config=config)
    return _model_server
