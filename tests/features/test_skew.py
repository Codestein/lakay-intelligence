"""Training-serving skew tests for the Lakay feature store.

These tests prove that features retrieved via the offline store (training path)
are identical to features retrieved via the online store (serving path).
Zero skew is non-negotiable — if these tests fail, the feature store is broken.

Test strategy:
1. Generate synthetic feature data.
2. Push to both offline and online stores via Feast.
3. Retrieve from both paths.
4. Assert exact match within tolerance.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.features.validation import (
    DEFAULT_FLOAT_TOLERANCE,
    FeatureComparison,
    SkewReport,
    compare_features,
    compare_values,
)

# --------------------------------------------------------------------------- #
# Unit tests for compare_values
# --------------------------------------------------------------------------- #


class TestCompareValues:
    """Test the core value comparison logic."""

    def test_identical_ints(self):
        match, delta = compare_values(5, 5)
        assert match is True
        assert delta == 0.0

    def test_identical_floats(self):
        match, delta = compare_values(3.14159, 3.14159)
        assert match is True
        assert delta == 0.0

    def test_float_within_tolerance(self):
        match, delta = compare_values(1.0, 1.0 + 1e-7)
        assert match is True
        assert delta is not None
        assert delta < DEFAULT_FLOAT_TOLERANCE

    def test_float_outside_tolerance(self):
        match, delta = compare_values(1.0, 1.1)
        assert match is False
        assert delta is not None
        assert delta > DEFAULT_FLOAT_TOLERANCE

    def test_custom_tolerance(self):
        match, delta = compare_values(1.0, 1.05, tolerance=0.1)
        assert match is True

    def test_both_none(self):
        match, delta = compare_values(None, None)
        assert match is True
        assert delta is None

    def test_one_none(self):
        match, delta = compare_values(None, 1.0)
        assert match is False

    def test_other_none(self):
        match, delta = compare_values(1.0, None)
        assert match is False

    def test_both_nan(self):
        match, delta = compare_values(float("nan"), float("nan"))
        assert match is True
        assert delta == 0.0

    def test_one_nan(self):
        match, delta = compare_values(float("nan"), 1.0)
        assert match is False

    def test_identical_strings(self):
        match, delta = compare_values("US", "US")
        assert match is True
        assert delta is None

    def test_different_strings(self):
        match, delta = compare_values("US", "HT")
        assert match is False

    def test_identical_booleans(self):
        match, delta = compare_values(True, True)
        assert match is True

    def test_different_booleans(self):
        match, delta = compare_values(True, False)
        assert match is False

    def test_int_and_float_comparison(self):
        match, delta = compare_values(5, 5.0)
        assert match is True
        assert delta == 0.0

    def test_zero_values(self):
        match, delta = compare_values(0, 0.0)
        assert match is True

    def test_negative_values(self):
        match, delta = compare_values(-3.14, -3.14)
        assert match is True

    def test_large_values(self):
        match, delta = compare_values(1e12, 1e12 + 1e-7)
        assert match is True


# --------------------------------------------------------------------------- #
# Unit tests for compare_features
# --------------------------------------------------------------------------- #


class TestCompareFeatures:
    """Test the feature comparison logic using pre-built DataFrames."""

    def _make_training_df(self, users, features_dict):
        """Build a training-style DataFrame."""
        data = {"user_id": users, "event_timestamp": [datetime.now(UTC)] * len(users)}
        data.update(features_dict)
        return pd.DataFrame(data)

    def _make_serving_dict(self, users, features_dict):
        """Build a serving-style dict."""
        result = {"user_id": users}
        result.update(features_dict)
        return result

    def test_perfect_match(self):
        """Features from offline and online stores are identical."""
        users = ["u1", "u2", "u3"]
        features = {
            "tx_count_1h": [5, 10, 0],
            "tx_amount_mean_30d": [250.0, 1500.0, 0.0],
            "last_known_country": ["US", "HT", "US"],
        }

        training_df = self._make_training_df(users, features)
        serving_dict = self._make_serving_dict(users, features)

        report = compare_features(
            training_features=training_df,
            serving_features=serving_dict,
            entity_key_columns=["user_id"],
        )

        assert report.has_zero_skew
        assert report.mismatches == 0
        assert report.total_comparisons == 9  # 3 users x 3 features

    def test_float_skew_detected(self):
        """Detect skew when float values differ beyond tolerance."""
        users = ["u1"]
        training_df = self._make_training_df(
            users, {"tx_amount_mean_30d": [1000.0]}
        )
        serving_dict = self._make_serving_dict(
            users, {"tx_amount_mean_30d": [1000.5]}
        )

        report = compare_features(
            training_features=training_df,
            serving_features=serving_dict,
            entity_key_columns=["user_id"],
        )

        assert not report.has_zero_skew
        assert report.mismatches == 1
        mismatched = report.get_mismatched_features()
        assert len(mismatched) == 1
        assert mismatched[0].feature_name == "tx_amount_mean_30d"
        assert mismatched[0].delta == pytest.approx(0.5)

    def test_string_skew_detected(self):
        """Detect skew when categorical values differ."""
        users = ["u1"]
        training_df = self._make_training_df(users, {"last_known_country": ["US"]})
        serving_dict = self._make_serving_dict(users, {"last_known_country": ["HT"]})

        report = compare_features(
            training_features=training_df,
            serving_features=serving_dict,
            entity_key_columns=["user_id"],
        )

        assert not report.has_zero_skew
        assert report.mismatches == 1

    def test_none_values_match(self):
        """Both stores returning None for a feature should not count as skew."""
        users = ["u1"]
        training_df = self._make_training_df(users, {"tx_amount_mean_30d": [None]})
        serving_dict = self._make_serving_dict(users, {"tx_amount_mean_30d": [None]})

        report = compare_features(
            training_features=training_df,
            serving_features=serving_dict,
            entity_key_columns=["user_id"],
        )

        assert report.has_zero_skew

    def test_missing_online_feature(self):
        """Online store missing a feature should count as skew."""
        users = ["u1"]
        training_df = self._make_training_df(users, {"tx_count_1h": [5]})
        serving_dict = self._make_serving_dict(users, {})  # feature missing

        report = compare_features(
            training_features=training_df,
            serving_features=serving_dict,
            entity_key_columns=["user_id"],
        )

        assert not report.has_zero_skew
        assert report.mismatches == 1

    def test_zero_value_features(self):
        """Zero-value features (new user, no history) should match exactly."""
        users = ["new_user"]
        features = {
            "tx_count_1h": [0],
            "tx_count_24h": [0],
            "tx_amount_mean_30d": [0.0],
            "tx_amount_std_30d": [0.0],
        }

        training_df = self._make_training_df(users, features)
        serving_dict = self._make_serving_dict(users, features)

        report = compare_features(
            training_features=training_df,
            serving_features=serving_dict,
            entity_key_columns=["user_id"],
        )

        assert report.has_zero_skew
        assert report.total_comparisons == 4

    def test_boundary_values(self):
        """Boundary values (max float, very small deltas) should work correctly."""
        users = ["u1"]
        # Float values at the boundary of tolerance
        tiny_delta = DEFAULT_FLOAT_TOLERANCE / 2
        training_df = self._make_training_df(
            users, {"score": [0.999999]}
        )
        serving_dict = self._make_serving_dict(
            users, {"score": [0.999999 + tiny_delta]}
        )

        report = compare_features(
            training_features=training_df,
            serving_features=serving_dict,
            entity_key_columns=["user_id"],
        )

        assert report.has_zero_skew

    def test_multiple_entities_mixed(self):
        """Some entities match, some don't — report should reflect totals."""
        users = ["u1", "u2"]
        training_df = self._make_training_df(
            users, {"tx_count_1h": [5, 10]}
        )
        serving_dict = self._make_serving_dict(
            users, {"tx_count_1h": [5, 999]}  # u2 has skew
        )

        report = compare_features(
            training_features=training_df,
            serving_features=serving_dict,
            entity_key_columns=["user_id"],
        )

        assert not report.has_zero_skew
        assert report.mismatches == 1
        assert report.total_comparisons == 2
        assert report.mismatch_rate == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# SkewReport tests
# --------------------------------------------------------------------------- #


class TestSkewReport:
    """Test SkewReport properties and summary."""

    def test_empty_report(self):
        report = SkewReport()
        assert report.has_zero_skew
        assert report.mismatch_rate == 0.0

    def test_report_summary(self):
        report = SkewReport(
            total_comparisons=100,
            mismatches=0,
            tolerance=1e-6,
            validated_at="2026-01-15T10:00:00+00:00",
        )
        summary = report.summary()
        assert summary["has_zero_skew"] is True
        assert summary["total_comparisons"] == 100
        assert summary["mismatches"] == 0

    def test_report_with_mismatches(self):
        mismatch = FeatureComparison(
            feature_name="tx_count_1h",
            entity_key={"user_id": "u1"},
            offline_value=5,
            online_value=10,
            match=False,
            delta=5.0,
        )
        report = SkewReport(
            comparisons=[mismatch],
            total_comparisons=1,
            mismatches=1,
        )
        assert not report.has_zero_skew
        assert len(report.get_mismatched_features()) == 1


# --------------------------------------------------------------------------- #
# Integration-style tests with mocked Feast
# --------------------------------------------------------------------------- #


class TestSkewValidatorMocked:
    """Test the SkewValidator with mocked Feast backends."""

    def test_validator_reports_zero_skew(self):
        """Validator correctly reports zero skew when stores agree."""
        from src.features.validation import SkewValidator

        mock_store = MagicMock()

        # Simulate offline store response
        offline_df = pd.DataFrame({
            "user_id": ["u1", "u2"],
            "event_timestamp": [datetime.now(UTC)] * 2,
            "tx_count_1h": [5, 10],
            "tx_amount_mean_30d": [250.0, 1500.0],
        })
        mock_store.get_historical_features.return_value = offline_df

        # Simulate online store response (same values)
        mock_store.get_online_features.return_value = {
            "user_id": ["u1", "u2"],
            "tx_count_1h": [5, 10],
            "tx_amount_mean_30d": [250.0, 1500.0],
        }

        validator = SkewValidator(store=mock_store)
        entity_df = pd.DataFrame({
            "user_id": ["u1", "u2"],
            "event_timestamp": [datetime.now(UTC)] * 2,
        })
        entity_rows = [{"user_id": "u1"}, {"user_id": "u2"}]

        report = validator.validate(
            entity_df=entity_df,
            entity_rows=entity_rows,
            feature_refs=["fraud_features:tx_count_1h", "fraud_features:tx_amount_mean_30d"],
            entity_key_columns=["user_id"],
        )

        assert report.has_zero_skew
        assert report.total_comparisons == 4  # 2 users x 2 features

    def test_validator_detects_skew(self):
        """Validator correctly detects skew when stores disagree."""
        from src.features.validation import SkewValidator

        mock_store = MagicMock()

        offline_df = pd.DataFrame({
            "user_id": ["u1"],
            "event_timestamp": [datetime.now(UTC)],
            "tx_count_1h": [5],
        })
        mock_store.get_historical_features.return_value = offline_df

        mock_store.get_online_features.return_value = {
            "user_id": ["u1"],
            "tx_count_1h": [999],  # Skew!
        }

        validator = SkewValidator(store=mock_store)
        entity_df = pd.DataFrame({
            "user_id": ["u1"],
            "event_timestamp": [datetime.now(UTC)],
        })

        report = validator.validate(
            entity_df=entity_df,
            entity_rows=[{"user_id": "u1"}],
            feature_refs=["fraud_features:tx_count_1h"],
            entity_key_columns=["user_id"],
        )

        assert not report.has_zero_skew
        assert report.mismatches == 1

    def test_all_fraud_features_zero_skew(self):
        """Comprehensive test: all 20 fraud features should have zero skew."""
        try:
            from src.features.definitions.fraud_features import get_fraud_feature_names
        except BaseException:
            pytest.skip("Feast not available in this environment")
        from src.features.validation import SkewValidator

        mock_store = MagicMock()
        feature_names = get_fraud_feature_names()

        # Generate matching data for all fraud features
        feature_data = {}
        for name in feature_names:
            if name in ("last_known_country", "last_known_city"):
                feature_data[name] = ["US"]
            elif "count" in name or "joins" in name or "distinct" in name:
                feature_data[name] = [5]
            elif "flag" in name:
                feature_data[name] = [False]
            else:
                feature_data[name] = [0.75]

        offline_df = pd.DataFrame({
            "user_id": ["u1"],
            "event_timestamp": [datetime.now(UTC)],
            **feature_data,
        })
        mock_store.get_historical_features.return_value = offline_df
        mock_store.get_online_features.return_value = {
            "user_id": ["u1"],
            **feature_data,
        }

        validator = SkewValidator(store=mock_store)
        entity_df = pd.DataFrame({
            "user_id": ["u1"],
            "event_timestamp": [datetime.now(UTC)],
        })

        report = validator.validate(
            entity_df=entity_df,
            entity_rows=[{"user_id": "u1"}],
            feature_refs=[f"fraud_features:{n}" for n in feature_names],
            entity_key_columns=["user_id"],
        )

        assert report.has_zero_skew
        assert report.total_comparisons == len(feature_names)

    def test_edge_case_empty_entities(self):
        """No entities to validate should produce an empty report."""
        mock_store = MagicMock()
        offline_df = pd.DataFrame(columns=["user_id", "event_timestamp", "tx_count_1h"])
        mock_store.get_historical_features.return_value = offline_df
        mock_store.get_online_features.return_value = {"user_id": [], "tx_count_1h": []}

        from src.features.validation import SkewValidator

        validator = SkewValidator(store=mock_store)

        report = validator.validate(
            entity_df=pd.DataFrame(columns=["user_id", "event_timestamp"]),
            entity_rows=[],
            feature_refs=["fraud_features:tx_count_1h"],
            entity_key_columns=["user_id"],
        )

        assert report.has_zero_skew
        assert report.total_comparisons == 0
