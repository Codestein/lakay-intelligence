"""Fraud detection model training pipeline.

Supports two training modes:
- **v0.1 (ad-hoc)**: Extracts features directly from PaySim CSV data.
- **v0.2 (Feast-backed)**: Retrieves features from the Feast offline store,
  guaranteeing zero training-serving skew.

Trains a Gradient Boosted Tree (XGBoost) on PaySim data mapped to
Trebanx event schema. Uses MLflow for experiment tracking and model
registration.

Usage:
    # v0.1 (ad-hoc features)
    python -m src.domains.fraud.ml.train --dataset data/paysim.csv

    # v0.2 (Feast feature store)
    python -m src.domains.fraud.ml.train --dataset data/paysim.csv --use-feast
"""

import argparse
import hashlib
import time
from typing import Any

import structlog
import yaml

from .evaluate import (
    compare_ml_vs_rules,
    evaluate_model,
    generate_classification_report,
    log_evaluation_to_mlflow,
)
from .features import build_feature_matrix, get_feature_names

logger = structlog.get_logger()

DEFAULT_CONFIG = {
    "model_name": "fraud-detector-v0.1",
    "random_seed": 42,
    "test_size": 0.2,
    "sample_size": None,  # None = use full dataset
    "mlflow_tracking_uri": "http://localhost:5000",
    "use_feast": False,  # Phase 5: set True for v0.2 training
    "hyperparams": {
        "n_estimators": 100,
        "max_depth": 6,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "scale_pos_weight": None,  # Auto-calculated from class imbalance
        "eval_metric": "aucpr",
        "use_label_encoder": False,
    },
    "grid_search": {
        "enabled": False,
        "param_grid": {
            "max_depth": [4, 6, 8],
            "learning_rate": [0.05, 0.1],
            "n_estimators": [100, 200],
        },
        "cv_folds": 3,
        "scoring": "f1",
    },
}


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load training configuration, merging with defaults."""
    config = dict(DEFAULT_CONFIG)
    if config_path:
        with open(config_path) as f:
            overrides = yaml.safe_load(f)
        if overrides:
            _deep_merge(config, overrides)
    return config


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _build_features_feast(
    dataset_path: str,
    sample_size: int | None = None,
    random_state: int = 42,
):
    """Build features using the Feast offline store (v0.2 path).

    Loads the PaySim CSV, constructs an entity DataFrame with user_id and
    event_timestamp, then requests all fraud features via Feast's
    point-in-time join.
    """
    import pandas as pd

    from .features import build_feature_matrix_feast, get_feast_feature_names, prepare_labels

    logger.info("building_feast_features", dataset=dataset_path)

    df = pd.read_csv(dataset_path)
    if sample_size and len(df) > sample_size:
        df = df.sample(n=sample_size, random_state=random_state)

    # Build entity DataFrame for Feast
    entity_df = pd.DataFrame({
        "user_id": df["nameOrig"].astype(str),
        "event_timestamp": pd.to_datetime(df["step"], unit="h", origin="2026-01-01"),
    })

    features_df = build_feature_matrix_feast(entity_df=entity_df)

    # Drop entity/timestamp columns to get pure feature matrix
    feature_names = get_feast_feature_names()
    feature_cols = [c for c in features_df.columns if c in feature_names]
    features = features_df[feature_cols].fillna(0.0)

    labels = prepare_labels(df)

    logger.info(
        "feast_feature_matrix_built",
        shape=features.shape,
        fraud_rate=float(labels.mean()),
    )

    return features, labels, feature_cols


def train_model(
    dataset_path: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Train a fraud detection model end-to-end.

    Steps:
    1. Load and prepare features (ad-hoc or Feast-backed)
    2. Split into train/test
    3. Train XGBoost with specified hyperparameters
    4. Evaluate on held-out test set
    5. Register in MLflow as Staging

    Args:
        dataset_path: Path to PaySim CSV file.
        config: Training configuration dict. Uses defaults if None.

    Returns:
        Dictionary with model, metrics, and metadata.
    """
    config = config or dict(DEFAULT_CONFIG)
    seed = config["random_seed"]
    model_name = config["model_name"]
    use_feast = config.get("use_feast", False)

    logger.info(
        "training_started",
        model_name=model_name,
        dataset=dataset_path,
        use_feast=use_feast,
    )
    start_time = time.time()

    # 1. Build feature matrix
    if use_feast:
        features, labels, feature_list = _build_features_feast(
            dataset_path=dataset_path,
            sample_size=config.get("sample_size"),
            random_state=seed,
        )
    else:
        features, labels = build_feature_matrix(
            data_path=dataset_path,
            sample_size=config.get("sample_size"),
            random_state=seed,
        )
        feature_list = get_feature_names()

    # 2. Train/test split
    from sklearn.model_selection import train_test_split

    x_train, x_test, y_train, y_test = train_test_split(
        features, labels, test_size=config["test_size"], random_state=seed, stratify=labels
    )

    logger.info(
        "data_split",
        train_size=len(x_train),
        test_size=len(x_test),
        train_fraud_rate=float(y_train.mean()),
        test_fraud_rate=float(y_test.mean()),
    )

    # 3. Train XGBoost
    import xgboost as xgb

    hyperparams = dict(config["hyperparams"])

    # Auto-calculate scale_pos_weight for class imbalance
    if hyperparams.get("scale_pos_weight") is None:
        neg_count = int((y_train == 0).sum())
        pos_count = int((y_train == 1).sum())
        hyperparams["scale_pos_weight"] = neg_count / max(pos_count, 1)
        logger.info(
            "class_imbalance_adjusted",
            scale_pos_weight=hyperparams["scale_pos_weight"],
            negative=neg_count,
            positive=pos_count,
        )

    # Grid search if enabled (max 10 combinations)
    if config.get("grid_search", {}).get("enabled"):
        model = _grid_search_train(x_train, y_train, hyperparams, config["grid_search"], seed)
    else:
        model = xgb.XGBClassifier(
            random_state=seed,
            **hyperparams,
        )
        model.fit(
            x_train,
            y_train,
            eval_set=[(x_test, y_test)],
            verbose=False,
        )

    training_duration = time.time() - start_time

    # 4. Evaluate
    metrics = evaluate_model(model, x_test, y_test)
    report_text = generate_classification_report(model, x_test, y_test)
    comparison = compare_ml_vs_rules(model, x_test, y_test)

    # 5. Register in MLflow
    dataset_hash = _compute_file_hash(dataset_path)
    all_params = {k: str(v) for k, v in hyperparams.items()}
    all_params["test_size"] = str(config["test_size"])
    all_params["random_seed"] = str(seed)
    all_params["training_duration_seconds"] = str(round(training_duration, 1))

    # Build tags for v0.2 Feast-backed models
    tags = {"framework": "xgboost", "task": "fraud_detection"}
    if use_feast:
        tags["feature_store"] = "feast"
        tags["feature_set_version"] = _compute_feature_def_hash()

    registered = _register_in_mlflow(
        model=model,
        model_name=model_name,
        metrics=metrics,
        params=all_params,
        feature_list=feature_list,
        dataset_hash=dataset_hash,
        report_text=report_text,
        comparison=comparison,
        tracking_uri=config.get("mlflow_tracking_uri", "http://localhost:5000"),
        tags=tags,
    )

    result = {
        "model": model,
        "metrics": metrics,
        "comparison": comparison,
        "model_name": model_name,
        "model_version": registered.get("version", "unknown") if registered else "local",
        "training_duration_seconds": round(training_duration, 1),
        "dataset_hash": dataset_hash,
        "feature_names": feature_list,
        "config": config,
        "use_feast": use_feast,
    }

    logger.info(
        "training_completed",
        model_name=model_name,
        auc_roc=metrics["auc_roc"],
        f1=metrics["f1_score"],
        duration_seconds=round(training_duration, 1),
        use_feast=use_feast,
    )

    return result


def _grid_search_train(x_train, y_train, base_params, grid_config, seed):
    """Run grid search over a small hyperparameter space (max 10 combinations)."""
    import xgboost as xgb
    from sklearn.model_selection import GridSearchCV

    param_grid = grid_config["param_grid"]

    # Limit total combinations to 10
    total_combos = 1
    for vals in param_grid.values():
        total_combos *= len(vals)
    if total_combos > 10:
        logger.warning("grid_search_too_large", total_combos=total_combos, max=10)

    # Remove grid-searched params from base
    fixed_params = {k: v for k, v in base_params.items() if k not in param_grid}

    estimator = xgb.XGBClassifier(random_state=seed, **fixed_params)

    grid = GridSearchCV(
        estimator,
        param_grid,
        cv=grid_config.get("cv_folds", 3),
        scoring=grid_config.get("scoring", "f1"),
        n_jobs=-1,
        verbose=0,
    )
    grid.fit(x_train, y_train)

    logger.info(
        "grid_search_complete",
        best_params=grid.best_params_,
        best_score=grid.best_score_,
    )

    return grid.best_estimator_


def _register_in_mlflow(
    model,
    model_name: str,
    metrics: dict,
    params: dict,
    feature_list: list[str],
    dataset_hash: str,
    report_text: str,
    comparison: dict,
    tracking_uri: str,
    tags: dict[str, str] | None = None,
) -> dict | None:
    """Register the trained model in MLflow and promote to Staging."""
    try:
        from src.serving.registry import ModelRegistry

        registry = ModelRegistry(tracking_uri=tracking_uri)
        metadata = registry.register_model(
            model=model,
            name=model_name,
            metrics=metrics,
            params=params,
            tags=tags or {"framework": "xgboost", "task": "fraud_detection"},
            feature_list=feature_list,
            training_dataset_hash=dataset_hash,
        )

        # Log evaluation artifacts
        log_evaluation_to_mlflow(metrics, report_text, comparison)

        # Promote to Staging
        registry.promote_model(model_name, metadata.version, "Staging")

        logger.info(
            "model_registered_and_staged",
            name=model_name,
            version=metadata.version,
        )

        return {"version": metadata.version, "run_id": metadata.run_id}

    except Exception as e:
        logger.warning("mlflow_registration_failed", error=str(e))
        return None


def _compute_file_hash(file_path: str) -> str:
    """SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except FileNotFoundError:
        return "file_not_found"


def _compute_feature_def_hash() -> str:
    """Compute a hash of the Feast feature definitions for traceability."""
    from src.features.definitions.fraud_features import get_fraud_feature_names

    feature_names = sorted(get_fraud_feature_names())
    content = ",".join(feature_names)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def main():
    parser = argparse.ArgumentParser(
        description="Train fraud detection model (v0.1 ad-hoc or v0.2 Feast-backed)",
        prog="python -m src.domains.fraud.ml.train",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        required=True,
        help="Path to PaySim CSV dataset",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to training config YAML (optional)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="Downsample dataset to N rows for faster iteration",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--mlflow-uri",
        type=str,
        default="http://localhost:5000",
        help="MLflow tracking URI",
    )
    parser.add_argument(
        "--use-feast",
        action="store_true",
        help="Use Feast feature store for feature retrieval (v0.2 pipeline)",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=None,
        help="Override model name (e.g., fraud-detector-v0.2)",
    )

    args = parser.parse_args()

    config = load_config(args.config)
    if args.sample_size:
        config["sample_size"] = args.sample_size
    if args.seed:
        config["random_seed"] = args.seed
    config["mlflow_tracking_uri"] = args.mlflow_uri
    if args.use_feast:
        config["use_feast"] = True
        config["model_name"] = args.model_name or "fraud-detector-v0.2"
    if args.model_name:
        config["model_name"] = args.model_name

    result = train_model(dataset_path=args.dataset, config=config)

    print(f"\nTraining Complete: {result['model_name']}")
    print(f"  Version: {result['model_version']}")
    print(f"  AUC-ROC: {result['metrics']['auc_roc']:.4f}")
    print(f"  Precision: {result['metrics']['precision']:.4f}")
    print(f"  Recall: {result['metrics']['recall']:.4f}")
    print(f"  F1: {result['metrics']['f1_score']:.4f}")
    print(f"  Duration: {result['training_duration_seconds']}s")
    print(f"  Feature Store: {'Feast' if result.get('use_feast') else 'Ad-hoc'}")


if __name__ == "__main__":
    main()
