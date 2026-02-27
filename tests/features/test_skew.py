"""Training-serving skew tests for feature store plumbing."""

from datetime import UTC, datetime, timedelta

import pandas as pd

from src.features.definitions.fraud_features import FRAUD_FEATURE_REFS
from src.features.store import FeatureStore
from src.features.validation import (
    compare_features,
    compute_serving_features,
    compute_training_features,
)


def _seed_rows() -> pd.DataFrame:
    now = datetime.now(UTC)
    return pd.DataFrame(
        {
            "user_id": ["u1", "u2", "u3"],
            "event_timestamp": [now - timedelta(minutes=5), now - timedelta(hours=1), now - timedelta(days=30)],
            "login_count_10m": [3, 1, 0],
            "login_count_1h": [6, 2, 0],
            "tx_count_1h": [2, 1, 0],
            "tx_count_24h": [8, 2, 0],
            "circle_joins_24h": [1, 0, 0],
            "tx_amount_last": [42.0, 10.0, 0.0],
            "tx_amount_mean_30d": [30.5, 12.5, 0.0],
            "tx_amount_std_30d": [5.0, 2.0, 0.0],
            "tx_amount_zscore": [2.3, -1.2, 0.0],
            "tx_cumulative_24h": [500.0, 90.0, 0.0],
            "tx_cumulative_7d": [1100.0, 100.0, 0.0],
            "ctr_proximity_score": [0.7, 0.1, 0.0],
            "last_known_country": ["US", "CA", None],
            "last_known_city": ["Miami", "Montreal", None],
            "distinct_countries_7d": [2, 1, 0],
            "max_travel_speed_24h": [500.0, 120.0, 0.0],
            "duplicate_tx_count_1h": [1, 0, 0],
            "same_recipient_tx_sum_24h": [150.0, 25.0, 0.0],
            "round_amount_ratio_30d": [0.5, 0.2, 0.0],
            "tx_time_regularity_score": [0.9, 0.4, 0.0],
        }
    )


def test_zero_skew_for_seeded_rows():
    store = FeatureStore()
    rows = _seed_rows()
    store.update_memory_features(rows)

    entity_df = rows[["user_id", "event_timestamp"]]
    training = compute_training_features(store, entity_df=entity_df, feature_refs=FRAUD_FEATURE_REFS)
    serving = compute_serving_features(
        store,
        entity_ids={"user_id": rows["user_id"].tolist()},
        feature_refs=FRAUD_FEATURE_REFS,
    )

    mismatches = compare_features(training, serving, tolerance=1e-6)
    assert mismatches == []


def test_skew_detects_mismatch_and_handles_missing_data():
    store = FeatureStore()
    rows = _seed_rows()
    store.update_memory_features(rows)

    serving = compute_serving_features(
        store,
        entity_ids={"user_id": rows["user_id"].tolist()},
        feature_refs=FRAUD_FEATURE_REFS,
    )
    serving["fraud_user_features:tx_cumulative_24h"][1] += 10

    training = compute_training_features(
        store,
        entity_df=rows[["user_id", "event_timestamp"]],
        feature_refs=FRAUD_FEATURE_REFS,
    )

    mismatches = compare_features(training, serving, tolerance=1e-6)
    assert any(m.feature == "tx_cumulative_24h" for m in mismatches)
