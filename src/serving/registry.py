"""MLflow Model Registry client wrapper.

Abstracts MLflow operations for model registration, promotion, loading,
and metadata retrieval. Designed for the Lakay Intelligence fraud detection
pipeline but generic enough for any domain model.

Why MLflow: Provides a unified model registry with experiment tracking,
artifact storage, and model versioning out of the box. Integrates well
with scikit-learn/XGBoost/LightGBM model formats via pyfunc.
"""

import hashlib
import json
import platform
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class ModelMetadata:
    """Metadata associated with a registered model version."""

    name: str
    version: str
    stage: str
    metrics: dict[str, float] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    training_dataset_hash: str = ""
    feature_list: list[str] = field(default_factory=list)
    training_timestamp: str = ""
    run_id: str = ""


class ModelRegistry:
    """Wraps MLflow client operations for model lifecycle management.

    Provides register, promote, load, and query operations against the
    MLflow tracking server configured via MLFLOW_TRACKING_URI env var
    or constructor parameter.
    """

    def __init__(self, tracking_uri: str = "http://localhost:5000") -> None:
        self._tracking_uri = tracking_uri
        self._client = None
        self._mlflow = None

    def _ensure_client(self):
        """Lazy-initialize MLflow client to avoid import errors when MLflow is not installed."""
        if self._client is not None:
            return
        try:
            import mlflow
            from mlflow.tracking import MlflowClient

            mlflow.set_tracking_uri(self._tracking_uri)
            self._client = MlflowClient(tracking_uri=self._tracking_uri)
            self._mlflow = mlflow
            logger.info("mlflow_client_initialized", tracking_uri=self._tracking_uri)
        except ImportError:
            logger.warning("mlflow_not_installed", msg="MLflow operations will be unavailable")
            raise

    def register_model(
        self,
        model: Any,
        name: str,
        metrics: dict[str, float] | None = None,
        params: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
        feature_list: list[str] | None = None,
        training_dataset_hash: str = "",
        artifact_path: str = "model",
    ) -> ModelMetadata:
        """Log a trained model with its metadata and register it in the model registry.

        Args:
            model: Trained model (compatible with mlflow.sklearn or mlflow.xgboost).
            name: Registered model name (e.g., 'fraud-detector-v0.1').
            metrics: Evaluation metrics (AUC, precision, recall, F1).
            params: Hyperparameters used during training.
            tags: Additional tags for the model version.
            feature_list: List of feature names used by the model.
            training_dataset_hash: SHA-256 hash of the training dataset.
            artifact_path: Path within the MLflow artifact store.

        Returns:
            ModelMetadata with the registered version information.
        """
        self._ensure_client()
        import mlflow

        metrics = metrics or {}
        params = params or {}
        tags = tags or {}
        feature_list = feature_list or []

        experiment_name = f"lakay-{name}"
        mlflow.set_experiment(experiment_name)

        with mlflow.start_run() as run:
            # Log parameters
            for k, v in params.items():
                mlflow.log_param(k, v)

            # Log metrics
            for k, v in metrics.items():
                mlflow.log_metric(k, v)

            # Log reproducibility metadata
            training_ts = datetime.now(UTC).isoformat()
            mlflow.set_tag("training_timestamp", training_ts)
            mlflow.set_tag("training_dataset_hash", training_dataset_hash)
            mlflow.set_tag("feature_list", json.dumps(feature_list))
            mlflow.set_tag("python_version", platform.python_version())

            for k, v in tags.items():
                mlflow.set_tag(k, v)

            # Log model — try xgboost first, fall back to sklearn pyfunc
            try:
                import mlflow.xgboost

                mlflow.xgboost.log_model(
                    model,
                    artifact_path=artifact_path,
                    registered_model_name=name,
                )
            except Exception:
                import mlflow.sklearn

                mlflow.sklearn.log_model(
                    model,
                    artifact_path=artifact_path,
                    registered_model_name=name,
                )

            # Get the registered version
            versions = self._client.search_model_versions(f"name='{name}'")
            latest_version = max(versions, key=lambda v: int(v.version))

            logger.info(
                "model_registered",
                name=name,
                version=latest_version.version,
                run_id=run.info.run_id,
                metrics=metrics,
            )

            return ModelMetadata(
                name=name,
                version=latest_version.version,
                stage=latest_version.current_stage,
                metrics=metrics,
                params=params,
                tags=tags,
                training_dataset_hash=training_dataset_hash,
                feature_list=feature_list,
                training_timestamp=training_ts,
                run_id=run.info.run_id,
            )

    def promote_model(self, name: str, version: str, stage: str) -> None:
        """Transition a model version to a new stage.

        Valid stages: 'Staging', 'Production', 'Archived'.
        When promoting to Production, the previous Production version
        is automatically archived.

        Args:
            name: Registered model name.
            version: Model version number.
            stage: Target stage ('Staging', 'Production', 'Archived').
        """
        self._ensure_client()
        valid_stages = {"Staging", "Production", "Archived", "None"}
        if stage not in valid_stages:
            raise ValueError(f"Invalid stage '{stage}'. Must be one of {valid_stages}")

        # If promoting to Production, archive current Production version
        if stage == "Production":
            try:
                current_prod = self._get_production_version(name)
                if current_prod and current_prod.version != version:
                    self._client.transition_model_version_stage(
                        name=name,
                        version=current_prod.version,
                        stage="Archived",
                    )
                    logger.info(
                        "model_archived",
                        name=name,
                        version=current_prod.version,
                    )
            except Exception:
                pass  # No existing production version

        self._client.transition_model_version_stage(
            name=name,
            version=version,
            stage=stage,
        )
        logger.info("model_promoted", name=name, version=version, stage=stage)

    def load_model(self, name: str, stage: str = "Production") -> Any:
        """Load the current model for a given stage.

        Args:
            name: Registered model name.
            stage: Stage to load from (default: 'Production').

        Returns:
            The loaded model object ready for inference.

        Raises:
            ValueError: If no model is found at the given stage.
        """
        self._ensure_client()
        import mlflow.pyfunc

        model_uri = f"models:/{name}/{stage}"
        try:
            model = mlflow.pyfunc.load_model(model_uri)
            logger.info("model_loaded", name=name, stage=stage, uri=model_uri)
            return model
        except Exception as e:
            logger.error("model_load_failed", name=name, stage=stage, error=str(e))
            raise ValueError(f"Failed to load model '{name}' at stage '{stage}': {e}") from e

    def get_model_metadata(self, name: str, stage: str = "Production") -> ModelMetadata | None:
        """Retrieve metrics, parameters, and tags for a model version at a given stage.

        Args:
            name: Registered model name.
            stage: Stage to query (default: 'Production').

        Returns:
            ModelMetadata or None if no model is found at the stage.
        """
        self._ensure_client()

        version_info = self._get_version_at_stage(name, stage)
        if not version_info:
            return None

        run = self._client.get_run(version_info.run_id)
        tags = run.data.tags

        return ModelMetadata(
            name=name,
            version=version_info.version,
            stage=stage,
            metrics=run.data.metrics,
            params=run.data.params,
            tags={k: v for k, v in tags.items() if not k.startswith("mlflow.")},
            training_dataset_hash=tags.get("training_dataset_hash", ""),
            feature_list=json.loads(tags.get("feature_list", "[]")),
            training_timestamp=tags.get("training_timestamp", ""),
            run_id=version_info.run_id,
        )

    def list_model_versions(self, name: str) -> list[ModelMetadata]:
        """List all versions of a registered model."""
        self._ensure_client()
        versions = self._client.search_model_versions(f"name='{name}'")
        result = []
        for v in versions:
            run = self._client.get_run(v.run_id)
            tags = run.data.tags
            result.append(
                ModelMetadata(
                    name=name,
                    version=v.version,
                    stage=v.current_stage,
                    metrics=run.data.metrics,
                    params=run.data.params,
                    tags={k: val for k, val in tags.items() if not k.startswith("mlflow.")},
                    training_dataset_hash=tags.get("training_dataset_hash", ""),
                    feature_list=json.loads(tags.get("feature_list", "[]")),
                    training_timestamp=tags.get("training_timestamp", ""),
                    run_id=v.run_id,
                )
            )
        return result

    def _get_production_version(self, name: str):
        """Get the current Production version of a model, if any."""
        return self._get_version_at_stage(name, "Production")

    def _get_version_at_stage(self, name: str, stage: str):
        """Get the model version at a specific stage."""
        versions = self._client.search_model_versions(f"name='{name}'")
        for v in versions:
            if v.current_stage == stage:
                return v
        return None

    @staticmethod
    def compute_dataset_hash(data_path: str) -> str:
        """Compute SHA-256 hash of a dataset file for reproducibility tracking."""
        sha256 = hashlib.sha256()
        with open(data_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
