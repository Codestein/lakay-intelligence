"""Tests for model performance monitoring."""

import numpy as np

from src.serving.monitoring import (
    ModelMonitor,
    MonitoringConfig,
    get_model_monitor,
)


class TestModelMonitor:
    def test_initial_state(self):
        monitor = ModelMonitor()
        report = monitor.get_health_report()
        assert report["total_predictions"] == 0
        assert report["model_version"] == "unknown"

    def test_record_predictions(self):
        monitor = ModelMonitor()
        monitor.set_baseline([0.1, 0.2, 0.3, 0.4, 0.5], model_version="1")

        for _ in range(10):
            monitor.record_prediction(score=0.3, latency_ms=5.0)

        report = monitor.get_health_report()
        assert report["total_predictions"] == 10
        assert report["model_version"] == "1"

    def test_score_distribution(self):
        monitor = ModelMonitor()
        scores = np.random.default_rng(42).uniform(0, 1, 50)
        for s in scores:
            monitor.record_prediction(score=float(s), latency_ms=5.0)

        dist = monitor.get_score_distribution(window_hours=1.0)
        assert dist.count == 50
        assert 0 <= dist.mean <= 1
        assert dist.p50 > 0

    def test_latency_stats(self):
        monitor = ModelMonitor()
        for i in range(50):
            monitor.record_prediction(score=0.5, latency_ms=float(i))

        stats = monitor.get_latency_stats(window_hours=1.0)
        assert stats.count == 50
        assert stats.p50_ms > 0
        assert stats.p95_ms > stats.p50_ms

    def test_score_shift_alert(self):
        config = MonitoringConfig(score_shift_std_threshold=1.0)
        monitor = ModelMonitor(config=config)

        # Set baseline with low scores that have some variation
        monitor.set_baseline([0.08, 0.10, 0.12, 0.09, 0.11], model_version="1")

        # Feed high scores to trigger alert (100 to trigger check)
        alerts = []
        for _ in range(100):
            new_alerts = monitor.record_prediction(score=0.9, latency_ms=5.0)
            alerts.extend(new_alerts)

        assert len(alerts) > 0
        assert alerts[0].alert_type == "score_distribution_shift"

    def test_latency_sla_alert(self):
        config = MonitoringConfig(latency_sla_p95_ms=10.0)
        monitor = ModelMonitor(config=config)
        monitor.set_baseline([0.5] * 10, model_version="1")

        alerts = []
        for _ in range(100):
            new_alerts = monitor.record_prediction(score=0.5, latency_ms=50.0)
            alerts.extend(new_alerts)

        latency_alerts = [a for a in alerts if a.alert_type == "latency_sla_breach"]
        assert len(latency_alerts) > 0

    def test_no_alert_when_within_baseline(self):
        monitor = ModelMonitor()
        monitor.set_baseline([0.5, 0.5, 0.5, 0.5, 0.5], model_version="1")

        alerts = []
        for _ in range(100):
            new_alerts = monitor.record_prediction(score=0.5, latency_ms=5.0)
            alerts.extend(new_alerts)

        score_alerts = [a for a in alerts if a.alert_type == "score_distribution_shift"]
        assert len(score_alerts) == 0


class TestGetModelMonitor:
    def test_singleton(self):
        import src.serving.monitoring as mon_module

        mon_module._monitor = None
        m1 = get_model_monitor()
        m2 = get_model_monitor()
        assert m1 is m2
        mon_module._monitor = None
