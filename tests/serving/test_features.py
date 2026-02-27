"""Tests for ML feature engineering."""

import numpy as np
import pandas as pd

from src.domains.fraud.ml.features import (
    TX_TYPE_MAP,
    extract_features,
    get_feature_names,
    prepare_labels,
)


def _make_paysim_df(n=100, seed=42):
    """Create a minimal PaySim-style DataFrame for testing."""
    rng = np.random.default_rng(seed)
    types = list(TX_TYPE_MAP.keys())[:5]
    return pd.DataFrame(
        {
            "step": rng.integers(1, 744, n),
            "type": rng.choice(types, n),
            "amount": rng.lognormal(4.5, 1.2, n),
            "nameOrig": [f"C{i % 20}" for i in range(n)],
            "oldbalanceOrg": rng.lognormal(7, 2, n),
            "newbalanceOrig": rng.lognormal(7, 2, n),
            "nameDest": [f"M{i % 10}" for i in range(n)],
            "oldbalanceDest": rng.lognormal(7, 2, n),
            "newbalanceDest": rng.lognormal(7, 2, n),
            "isFraud": (rng.random(n) < 0.1).astype(int),
            "isFlaggedFraud": np.zeros(n, dtype=int),
        }
    )


class TestExtractFeatures:
    def test_output_shape(self):
        df = _make_paysim_df(n=50)
        features = extract_features(df)
        assert len(features) == 50
        assert len(features.columns) == len(get_feature_names())

    def test_feature_names_match(self):
        df = _make_paysim_df(n=20)
        features = extract_features(df)
        assert list(features.columns) == get_feature_names()

    def test_amount_preserved(self):
        df = _make_paysim_df(n=10)
        features = extract_features(df)
        np.testing.assert_array_almost_equal(features["amount"].values, df["amount"].values)

    def test_tx_type_encoding(self):
        df = _make_paysim_df(n=50)
        features = extract_features(df)
        # All encoded values should be in TX_TYPE_MAP values or -1
        valid_codes = set(TX_TYPE_MAP.values()) | {-1}
        for code in features["tx_type_encoded"].unique():
            assert code in valid_codes

    def test_hour_of_day_range(self):
        df = _make_paysim_df(n=50)
        features = extract_features(df)
        assert features["hour_of_day"].min() >= 0
        assert features["hour_of_day"].max() <= 23

    def test_day_of_week_range(self):
        df = _make_paysim_df(n=50)
        features = extract_features(df)
        assert features["day_of_week"].min() >= 0
        assert features["day_of_week"].max() <= 6

    def test_balance_deltas(self):
        df = _make_paysim_df(n=20)
        features = extract_features(df)
        expected_sender = df["oldbalanceOrg"] - df["newbalanceOrig"]
        np.testing.assert_array_almost_equal(
            features["balance_delta_sender"].values, expected_sender.values
        )

    def test_velocity_counts_non_negative(self):
        df = _make_paysim_df(n=50)
        features = extract_features(df)
        assert (features["velocity_count_1h"] >= 0).all()
        assert (features["velocity_count_24h"] >= 0).all()
        assert (features["velocity_amount_1h"] >= 0).all()
        assert (features["velocity_amount_24h"] >= 0).all()

    def test_no_nans(self):
        df = _make_paysim_df(n=50)
        features = extract_features(df)
        assert not features.isna().any().any()


class TestPrepareLabels:
    def test_binary_labels(self):
        df = _make_paysim_df(n=50)
        labels = prepare_labels(df)
        assert set(labels.unique()).issubset({0, 1})
        assert len(labels) == 50


class TestGetFeatureNames:
    def test_returns_list(self):
        names = get_feature_names()
        assert isinstance(names, list)
        assert len(names) == 11
        assert "amount" in names
        assert "velocity_count_1h" in names
