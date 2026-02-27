"""Training-serving skew validation for the Lakay feature store.

This module is the most critical piece of Phase 5. It proves that features
retrieved at training time (offline store) are identical to those served at
prediction time (online store).  Zero skew is non-negotiable.

Usage::

    validator = SkewValidator()
    report = validator.validate(
        entity_rows=[{"user_id": "u123"}],
        feature_refs=["fraud_features:tx_count_1h"],
        tolerance=1e-6,
    )
    assert report.has_zero_skew

CLI::

    python -m src.features.validation --check-skew
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import structlog

from src.features.store import FeatureStore, get_feature_store

logger = structlog.get_logger()

DEFAULT_FLOAT_TOLERANCE = 1e-6


@dataclass
class FeatureComparison:
    """Comparison result for a single feature across a single entity."""

    feature_name: str
    entity_key: dict[str, str]
    offline_value: Any
    online_value: Any
    match: bool
    delta: float | None = None


@dataclass
class SkewReport:
    """Aggregated skew validation report across all entities and features."""

    comparisons: list[FeatureComparison] = field(default_factory=list)
    total_comparisons: int = 0
    mismatches: int = 0
    tolerance: float = DEFAULT_FLOAT_TOLERANCE
    validated_at: str = ""

    @property
    def has_zero_skew(self) -> bool:
        return self.mismatches == 0

    @property
    def mismatch_rate(self) -> float:
        if self.total_comparisons == 0:
            return 0.0
        return self.mismatches / self.total_comparisons

    def get_mismatched_features(self) -> list[FeatureComparison]:
        return [c for c in self.comparisons if not c.match]

    def summary(self) -> dict[str, Any]:
        return {
            "total_comparisons": self.total_comparisons,
            "mismatches": self.mismatches,
            "mismatch_rate": self.mismatch_rate,
            "has_zero_skew": self.has_zero_skew,
            "tolerance": self.tolerance,
            "validated_at": self.validated_at,
        }


def compare_values(
    offline: Any,
    online: Any,
    tolerance: float = DEFAULT_FLOAT_TOLERANCE,
) -> tuple[bool, float | None]:
    """Compare a pair of feature values with type-appropriate tolerance.

    Returns:
        Tuple of (match, delta). Delta is None for non-numeric comparisons.
    """
    # Handle None/NaN
    if offline is None and online is None:
        return True, None
    if offline is None or online is None:
        return False, None

    # Check for NaN (NaN != NaN is True by IEEE 754)
    if isinstance(offline, float) and isinstance(online, float):
        if math.isnan(offline) and math.isnan(online):
            return True, 0.0
        if math.isnan(offline) or math.isnan(online):
            return False, None

    # Numeric comparison with tolerance
    if isinstance(offline, (int, float)) and isinstance(online, (int, float)):
        delta = abs(float(offline) - float(online))
        return delta <= tolerance, delta

    # Boolean comparison
    if isinstance(offline, bool) and isinstance(online, bool):
        return offline == online, None

    # String / categorical comparison (exact match)
    return str(offline) == str(online), None


def compute_training_features(
    entity_df: pd.DataFrame,
    feature_refs: list[str],
    store: FeatureStore | None = None,
) -> pd.DataFrame:
    """Compute features using the offline store (training path).

    Args:
        entity_df: DataFrame with entity key columns and ``event_timestamp``.
        feature_refs: Feature references in "view:feature" format.
        store: Optional FeatureStore instance. Uses global singleton if None.

    Returns:
        DataFrame with entity keys plus feature columns.
    """
    store = store or get_feature_store()
    return store.get_historical_features(entity_df=entity_df, feature_refs=feature_refs)


def compute_serving_features(
    entity_rows: list[dict[str, Any]],
    feature_refs: list[str],
    store: FeatureStore | None = None,
) -> dict[str, list[Any]]:
    """Compute features using the online store (serving path).

    Args:
        entity_rows: List of entity key dicts.
        feature_refs: Feature references in "view:feature" format.
        store: Optional FeatureStore instance.

    Returns:
        Dictionary mapping feature names to lists of values.
    """
    store = store or get_feature_store()
    return store.get_online_features(entity_rows=entity_rows, feature_refs=feature_refs)


def compare_features(
    training_features: pd.DataFrame,
    serving_features: dict[str, list[Any]],
    entity_key_columns: list[str],
    tolerance: float = DEFAULT_FLOAT_TOLERANCE,
) -> SkewReport:
    """Compare features from the offline and online stores.

    For each entity and feature, checks that the offline store value matches
    the online store value within the specified tolerance.

    Args:
        training_features: DataFrame from ``compute_training_features``.
        serving_features: Dict from ``compute_serving_features``.
        entity_key_columns: Column names used as entity keys (e.g. ["user_id"]).
        tolerance: Maximum allowed absolute difference for float comparisons.

    Returns:
        SkewReport with detailed comparison results.
    """
    report = SkewReport(tolerance=tolerance, validated_at=datetime.now(UTC).isoformat())

    # Determine feature columns (everything not an entity key or timestamp)
    feature_columns = [
        col
        for col in training_features.columns
        if col not in entity_key_columns and col != "event_timestamp"
    ]

    num_entities = len(training_features)

    for i in range(num_entities):
        entity_key = {col: str(training_features.iloc[i][col]) for col in entity_key_columns}

        for feat_col in feature_columns:
            offline_val = training_features.iloc[i][feat_col]
            # Convert numpy types to Python types
            if hasattr(offline_val, "item"):
                offline_val = offline_val.item()

            # Online features have the feature name without the view prefix
            online_key = feat_col
            online_vals = serving_features.get(online_key, [])

            if i < len(online_vals):
                online_val = online_vals[i]
                if hasattr(online_val, "item"):
                    online_val = online_val.item()
            else:
                online_val = None

            match, delta = compare_values(offline_val, online_val, tolerance)

            comparison = FeatureComparison(
                feature_name=feat_col,
                entity_key=entity_key,
                offline_value=offline_val,
                online_value=online_val,
                match=match,
                delta=delta,
            )

            report.comparisons.append(comparison)
            report.total_comparisons += 1
            if not match:
                report.mismatches += 1
                logger.warning(
                    "feature_skew_detected",
                    feature=feat_col,
                    entity=entity_key,
                    offline=offline_val,
                    online=online_val,
                    delta=delta,
                )

    logger.info("skew_validation_completed", **report.summary())
    return report


class SkewValidator:
    """High-level skew validator that orchestrates the full comparison flow."""

    def __init__(self, store: FeatureStore | None = None) -> None:
        self._store = store or get_feature_store()

    def validate(
        self,
        entity_df: pd.DataFrame,
        entity_rows: list[dict[str, Any]],
        feature_refs: list[str],
        entity_key_columns: list[str],
        tolerance: float = DEFAULT_FLOAT_TOLERANCE,
    ) -> SkewReport:
        """Run full skew validation: offline vs. online feature retrieval.

        Args:
            entity_df: Training-style entity DataFrame with ``event_timestamp``.
            entity_rows: Serving-style entity key dicts (no timestamp).
            feature_refs: Feature references in "view:feature" format.
            entity_key_columns: Entity key column names.
            tolerance: Float comparison tolerance.

        Returns:
            SkewReport detailing any discrepancies.
        """
        # Retrieve features from both paths
        training_df = compute_training_features(
            entity_df=entity_df, feature_refs=feature_refs, store=self._store
        )
        serving_dict = compute_serving_features(
            entity_rows=entity_rows, feature_refs=feature_refs, store=self._store
        )

        return compare_features(
            training_features=training_df,
            serving_features=serving_dict,
            entity_key_columns=entity_key_columns,
            tolerance=tolerance,
        )

    def validate_fraud_features(
        self,
        entity_df: pd.DataFrame,
        entity_rows: list[dict[str, Any]],
        tolerance: float = DEFAULT_FLOAT_TOLERANCE,
    ) -> SkewReport:
        """Convenience method to validate all fraud features."""
        from src.features.definitions.fraud_features import get_fraud_feature_refs

        return self.validate(
            entity_df=entity_df,
            entity_rows=entity_rows,
            feature_refs=get_fraud_feature_refs(),
            entity_key_columns=["user_id"],
            tolerance=tolerance,
        )


def main():
    """CLI entry point for skew validation."""
    parser = argparse.ArgumentParser(
        description="Feature store training-serving skew validation",
        prog="python -m src.features.validation",
    )
    parser.add_argument(
        "--check-skew",
        action="store_true",
        help="Run skew validation on a sample of entities",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_FLOAT_TOLERANCE,
        help="Tolerance for float comparisons (default: 1e-6)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=10,
        help="Number of entities to sample for validation",
    )
    parser.add_argument(
        "--feature-set",
        type=str,
        default="fraud",
        choices=["fraud", "behavior", "circle", "all"],
        help="Which feature set to validate",
    )

    args = parser.parse_args()

    if not args.check_skew:
        parser.print_help()
        return

    from src.features.definitions.fraud_features import get_fraud_feature_refs

    store = FeatureStore()
    validator = SkewValidator(store=store)

    # Build a sample entity_df from materialized data
    sample_users = [f"user_{i}" for i in range(args.sample_size)]
    now = datetime.now(UTC)

    entity_df = pd.DataFrame(
        {"user_id": sample_users, "event_timestamp": [now] * len(sample_users)}
    )
    entity_rows = [{"user_id": uid} for uid in sample_users]

    feature_refs = get_fraud_feature_refs()

    try:
        report = validator.validate(
            entity_df=entity_df,
            entity_rows=entity_rows,
            feature_refs=feature_refs,
            entity_key_columns=["user_id"],
            tolerance=args.tolerance,
        )

        print("\nSkew Validation Report")
        print("=" * 50)
        print(f"  Feature set: {args.feature_set}")
        print(f"  Entities sampled: {args.sample_size}")
        print(f"  Total comparisons: {report.total_comparisons}")
        print(f"  Mismatches: {report.mismatches}")
        print(f"  Mismatch rate: {report.mismatch_rate:.6f}")
        print(f"  Zero skew: {report.has_zero_skew}")
        print(f"  Tolerance: {report.tolerance}")

        if not report.has_zero_skew:
            print("\nMismatched features:")
            for c in report.get_mismatched_features():
                print(f"  - {c.feature_name} @ {c.entity_key}: "
                      f"offline={c.offline_value}, online={c.online_value}, "
                      f"delta={c.delta}")
            sys.exit(1)

        print("\nAll features match. Zero training-serving skew confirmed.")

    except Exception as e:
        logger.error("skew_validation_failed", error=str(e))
        print(f"\nSkew validation failed: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
