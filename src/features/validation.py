"""Training-serving skew validation utilities for Feast-backed feature retrieval."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.features.store import FeatureStore


@dataclass
class FeatureMismatch:
    feature: str
    entity_id: str
    training_value: Any
    serving_value: Any


def compute_training_features(
    store: FeatureStore,
    entity_df: pd.DataFrame,
    feature_refs: list[str],
) -> pd.DataFrame:
    """Compute training features through the historical/offline path."""
    return store.get_historical_features(entity_df=entity_df, feature_refs=feature_refs)


def compute_serving_features(
    store: FeatureStore,
    entity_ids: dict[str, list[str]],
    feature_refs: list[str],
) -> dict[str, Any]:
    """Compute serving features through the online path."""
    return store.get_online_features(entity_ids=entity_ids, feature_refs=feature_refs)


def compare_features(
    training_features: pd.DataFrame,
    serving_features: dict[str, Any],
    tolerance: float = 1e-6,
    entity_key: str = "user_id",
) -> list[FeatureMismatch]:
    """Compare offline/online feature values and return mismatches."""
    mismatches: list[FeatureMismatch] = []

    for row_idx, row in training_features.reset_index(drop=True).iterrows():
        entity_id = str(row[entity_key])
        for full_ref, online_values in serving_features.items():
            feature_name = full_ref.split(":", 1)[-1]
            if feature_name not in training_features.columns:
                continue

            left = row[feature_name]
            right = online_values[row_idx] if row_idx < len(online_values) else None

            if pd.isna(left) and pd.isna(right):
                continue
            if isinstance(left, float) or isinstance(right, float):
                if left is None or right is None or abs(float(left) - float(right)) > tolerance:
                    mismatches.append(
                        FeatureMismatch(feature_name, entity_id, left, right)
                    )
            elif left != right:
                mismatches.append(FeatureMismatch(feature_name, entity_id, left, right))

    return mismatches


def run_skew_check(sample_size: int = 25) -> int:
    """Run skew check against available backend and return process code."""
    store = FeatureStore()

    if store._memory.historical.empty:  # pragma: no cover - runtime behavior for CLI use
        print("No seeded features found in memory backend; skew check skipped.")
        return 0

    sample = store._memory.historical.head(sample_size).copy()
    refs = [f"fraud_user_features:{c}" for c in sample.columns if c not in {"user_id", "event_timestamp", "created_at"}]
    training = compute_training_features(store, sample[["user_id", "event_timestamp"]], refs)
    serving = compute_serving_features(store, {"user_id": sample["user_id"].astype(str).tolist()}, refs)
    mismatches = compare_features(training, serving)

    if mismatches:
        print(f"Skew detected: {len(mismatches)} mismatches")
        for mismatch in mismatches[:20]:
            print(mismatch)
        return 1

    print("Zero skew detected.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Feature training-serving skew validator")
    parser.add_argument("--check-skew", action="store_true", help="Run skew comparison")
    parser.add_argument("--sample-size", type=int, default=25)
    args = parser.parse_args()

    if args.check_skew:
        return run_skew_check(sample_size=args.sample_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
