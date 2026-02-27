"""Tests for feature drift detection."""

import numpy as np

from src.serving.drift import (
    DriftConfig,
    FeatureDriftDetector,
    get_drift_detector,
)


class TestFeatureDriftDetector:
    def test_no_drift_on_same_distribution(self):
        rng = np.random.default_rng(42)
        config = DriftConfig(
            min_observations=500,
            check_interval_observations=500,
            num_bins=10,
        )
        detector = FeatureDriftDetector(feature_names=["amount"], config=config)

        # Set reference from normal distribution (large sample)
        reference = rng.normal(100, 20, 5000)
        detector.set_reference_distribution("amount", reference)

        # Feed same distribution — need enough samples for stable PSI
        alerts = []
        for _ in range(1000):
            obs = float(rng.normal(100, 20))
            new_alerts = detector.record_observation({"amount": obs})
            alerts.extend(new_alerts)

        # No drift alerts expected with large enough sample
        assert len(alerts) == 0

    def test_drift_detected_on_shifted_distribution(self):
        rng = np.random.default_rng(42)
        config = DriftConfig(
            min_observations=50,
            check_interval_observations=50,
            psi_warning_threshold=0.05,
        )
        detector = FeatureDriftDetector(feature_names=["amount"], config=config)

        # Set reference from normal(100, 20)
        reference = rng.normal(100, 20, 1000)
        detector.set_reference_distribution("amount", reference)

        # Feed drastically shifted distribution
        alerts = []
        for _ in range(200):
            obs = float(rng.normal(500, 50))  # Very different
            new_alerts = detector.record_observation({"amount": obs})
            alerts.extend(new_alerts)

        assert len(alerts) > 0
        assert alerts[0].feature_name == "amount"
        assert alerts[0].drift_method == "psi"

    def test_drift_report(self):
        config = DriftConfig(min_observations=10, check_interval_observations=10)
        detector = FeatureDriftDetector(
            feature_names=["amount", "velocity"],
            config=config,
        )

        # Only set reference for amount
        rng = np.random.default_rng(42)
        detector.set_reference_distribution("amount", rng.normal(100, 20, 100))

        for i in range(20):
            detector.record_observation({"amount": float(100 + i), "velocity": float(i)})

        report = detector.get_drift_report()
        assert "amount" in report["features"]
        assert "velocity" in report["features"]
        assert report["features"]["velocity"]["status"] == "no_reference"

    def test_psi_computation_stable(self):
        rng = np.random.default_rng(42)
        config = DriftConfig(min_observations=10)
        detector = FeatureDriftDetector(feature_names=["x"], config=config)

        ref = rng.normal(0, 1, 1000)
        detector.set_reference_distribution("x", ref)

        # Same distribution should have low PSI
        current = rng.normal(0, 1, 1000)
        psi = detector._compute_psi("x", current)
        assert psi is not None
        assert psi < 0.1  # No significant drift

    def test_psi_computation_drifted(self):
        rng = np.random.default_rng(42)
        detector = FeatureDriftDetector(feature_names=["x"])

        ref = rng.normal(0, 1, 1000)
        detector.set_reference_distribution("x", ref)

        # Very different distribution
        current = rng.normal(10, 3, 1000)
        psi = detector._compute_psi("x", current)
        assert psi is not None
        assert psi > 0.25  # Significant drift

    def test_multiple_features(self):
        rng = np.random.default_rng(42)
        config = DriftConfig(min_observations=50, check_interval_observations=50)
        features = ["amount", "velocity", "hour"]
        detector = FeatureDriftDetector(feature_names=features, config=config)

        for f in features:
            detector.set_reference_distribution(f, rng.normal(0, 1, 500))

        for _ in range(100):
            detector.record_observation(
                {
                    "amount": float(rng.normal(0, 1)),
                    "velocity": float(rng.normal(0, 1)),
                    "hour": float(rng.normal(0, 1)),
                }
            )

        report = detector.get_drift_report()
        assert len(report["features"]) == 3


class TestGetDriftDetector:
    def test_singleton(self):
        import src.serving.drift as drift_module

        drift_module._detector = None
        d1 = get_drift_detector()
        d2 = get_drift_detector()
        assert d1 is d2
        drift_module._detector = None
