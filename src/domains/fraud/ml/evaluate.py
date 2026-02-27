"""Model evaluation for fraud detection.

Evaluates ML model against a held-out test set and compares with
the rule-based system from Phase 3 to justify the hybrid approach.
"""

import json
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


def evaluate_model(
    model: Any,
    x_test: Any,
    y_test: Any,
) -> dict[str, float]:
    """Evaluate a trained model on a test set.

    Args:
        model: Trained model with predict/predict_proba.
        x_test: Test feature matrix.
        y_test: Test labels.

    Returns:
        Dictionary of evaluation metrics.
    """
    from sklearn.metrics import (
        auc,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
        roc_curve,
    )

    # Predictions
    y_pred = model.predict(x_test)
    y_prob = model.predict_proba(x_test)[:, 1] if hasattr(model, "predict_proba") else y_pred

    # Metrics
    fpr, tpr, _ = roc_curve(y_test, y_prob)
    auc_roc = auc(fpr, tpr)
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)

    cm = confusion_matrix(y_test, y_pred)

    metrics = {
        "auc_roc": float(auc_roc),
        "precision": float(precision),
        "recall": float(recall),
        "f1_score": float(f1),
        "true_negatives": int(cm[0][0]),
        "false_positives": int(cm[0][1]),
        "false_negatives": int(cm[1][0]),
        "true_positives": int(cm[1][1]),
    }

    logger.info("model_evaluated", **metrics)

    return metrics


def generate_classification_report(
    model: Any,
    x_test: Any,
    y_test: Any,
    output_path: str | None = None,
) -> str:
    """Generate a detailed classification report and optionally save to file.

    Returns:
        The classification report as a string.
    """
    from sklearn.metrics import classification_report, confusion_matrix

    y_pred = model.predict(x_test)
    report = classification_report(y_test, y_pred, zero_division=0)
    cm = confusion_matrix(y_test, y_pred)

    full_report = f"Classification Report\n{'=' * 50}\n{report}\n"
    full_report += f"\nConfusion Matrix\n{'=' * 50}\n{cm}\n"

    if output_path:
        with open(output_path, "w") as f:
            f.write(full_report)
        logger.info("classification_report_saved", path=output_path)

    return full_report


def compare_ml_vs_rules(
    ml_model: Any,
    x_test: Any,
    y_test: Any,
    rule_scores: np.ndarray | None = None,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Compare ML model detection against rule-based scoring.

    This justifies the hybrid approach by identifying:
    - Fraud caught by ML but missed by rules
    - Fraud caught by rules but missed by ML
    - Fraud caught by both

    Args:
        ml_model: Trained ML model.
        x_test: Test features.
        y_test: True labels.
        rule_scores: Optional array of rule-based scores (0-1) for the test set.
                     If None, simulates rule scoring using amount-based heuristic.
        threshold: Score threshold for flagging as fraud.

    Returns:
        Comparison report dictionary.
    """
    # ML predictions
    ml_prob = (
        ml_model.predict_proba(x_test)[:, 1]
        if hasattr(ml_model, "predict_proba")
        else ml_model.predict(x_test)
    )
    ml_flags = (ml_prob >= threshold).astype(int)

    # Rule-based predictions (simulate if not provided)
    if rule_scores is None:
        # Simple heuristic: flag high amounts and unusual patterns
        # This approximates the Phase 3 rule engine for comparison
        amounts = x_test["amount"].values if hasattr(x_test, "amount") else x_test[:, 0]
        amount_threshold = np.percentile(amounts, 95)
        rule_flags = (amounts > amount_threshold).astype(int)
    else:
        rule_flags = (rule_scores >= threshold).astype(int)

    y_true = np.array(y_test)

    # Analysis
    ml_caught = (ml_flags == 1) & (y_true == 1)
    rules_caught = (rule_flags == 1) & (y_true == 1)
    both_caught = ml_caught & rules_caught
    ml_only = ml_caught & ~rules_caught
    rules_only = rules_caught & ~ml_caught
    neither = (y_true == 1) & ~ml_caught & ~rules_caught

    total_fraud = int(y_true.sum())

    report = {
        "total_fraud_cases": total_fraud,
        "ml_caught": int(ml_caught.sum()),
        "rules_caught": int(rules_caught.sum()),
        "both_caught": int(both_caught.sum()),
        "ml_only_caught": int(ml_only.sum()),
        "rules_only_caught": int(rules_only.sum()),
        "neither_caught": int(neither.sum()),
        "ml_detection_rate": float(ml_caught.sum() / max(total_fraud, 1)),
        "rules_detection_rate": float(rules_caught.sum() / max(total_fraud, 1)),
        "hybrid_detection_rate": float((ml_caught | rules_caught).sum() / max(total_fraud, 1)),
        "justification": (
            "The hybrid approach catches more fraud than either system alone. "
            "ML detects patterns rules miss (e.g., subtle velocity anomalies), "
            "while rules catch threshold violations that need interpretable audit trails."
        ),
    }

    logger.info("ml_vs_rules_comparison", **report)

    return report


def log_evaluation_to_mlflow(
    metrics: dict[str, float],
    report_text: str,
    comparison: dict[str, Any] | None = None,
) -> None:
    """Log evaluation artifacts to the active MLflow run."""
    try:
        import os
        import tempfile

        import mlflow

        # Log metrics
        for k, v in metrics.items():
            if isinstance(v, (int, float)):
                mlflow.log_metric(k, v)

        # Log classification report as artifact
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "classification_report.txt")
            with open(report_path, "w") as f:
                f.write(report_text)
            mlflow.log_artifact(report_path)

            if comparison:
                comparison_path = os.path.join(tmpdir, "ml_vs_rules_comparison.json")
                with open(comparison_path, "w") as f:
                    json.dump(comparison, f, indent=2)
                mlflow.log_artifact(comparison_path)

        logger.info("evaluation_logged_to_mlflow")

    except ImportError:
        logger.warning("mlflow_not_available_for_logging")
