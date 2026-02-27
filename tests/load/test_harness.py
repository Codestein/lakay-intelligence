"""Unit tests for the Phase 10 load-test harness."""

from __future__ import annotations

import pytest

from tests.load.harness import (
    LoadTestConfig,
    LoadTestHarness,
    _merge_results,
)


class TestLoadTestConfig:
    def test_event_mix_must_sum_to_one(self) -> None:
        with pytest.raises(ValueError):
            LoadTestConfig(event_type_mix={"transaction": 0.4, "session": 0.4})


class TestLoadHarnessGeneration:
    def test_generate_event_targets_known_routes(self) -> None:
        cfg = LoadTestConfig(target_rps=1, duration_seconds=1, ramp_time_seconds=1)
        harness = LoadTestHarness(cfg)

        seen = set()
        for _ in range(200):
            event_type, method, url, body = harness.generate_event()
            seen.add(event_type)
            assert method == "POST"
            assert body is None or isinstance(body, dict)
            assert url.startswith(cfg.base_url)

            if event_type in {"transaction", "remittance"}:
                assert url.endswith("/api/v1/fraud/score")
            elif event_type == "session":
                assert url.endswith("/api/v1/behavior/sessions/score")
            elif event_type == "circle":
                assert "/api/v1/circles/" in url
                assert url.endswith("/score")
            else:
                pytest.fail(f"Unexpected event_type: {event_type}")

        assert seen == {"transaction", "session", "circle", "remittance"}

    def test_collect_results_computes_summary(self) -> None:
        cfg = LoadTestConfig(target_rps=1, duration_seconds=1, ramp_time_seconds=1)
        harness = LoadTestHarness(cfg)

        harness.recorder.record("fraud_scoring", 50.0, 200)
        harness.recorder.record("fraud_scoring", 150.0, 500)
        harness.recorder.record("session_scoring", 25.0, 200)

        results = harness.collect_results()

        assert results["summary"]["total_events"] == 3
        assert results["summary"]["overall_error_rate"] == pytest.approx(1 / 3, rel=1e-3)
        assert results["per_endpoint"]["fraud_scoring"]["error_count"] == 1
        assert results["per_endpoint"]["fraud_scoring"]["latency"]["count"] == 2


class TestResultsMerge:
    def test_merge_results_combines_phases(self) -> None:
        phase_1 = {
            "summary": {"total_events": 10},
            "throughput_curve": [{"elapsed_seconds": 1.0, "events_per_second": 10}],
            "per_endpoint": {
                "fraud_scoring": {
                    "latency": {"p95_ms": 100.0, "count": 10},
                    "error_count": 0,
                }
            },
        }
        phase_2 = {
            "summary": {"total_events": 5},
            "throughput_curve": [{"elapsed_seconds": 1.0, "events_per_second": 5}],
            "per_endpoint": {
                "fraud_scoring": {
                    "latency": {"p95_ms": 250.0, "count": 5},
                    "error_count": 1,
                }
            },
        }

        merged = _merge_results([phase_1, phase_2])

        assert merged["summary"]["total_events"] == 15
        assert merged["summary"]["phase_count"] == 2
        assert len(merged["throughput_curve"]) == 2
        assert merged["per_endpoint"]["fraud_scoring"]["latency"]["worst_p95_ms"] == 250.0
        assert merged["per_endpoint"]["fraud_scoring"]["error_count"] == 1
        assert merged["sla_compliance"]["fraud_scoring_p95_ms"]["pass"] is False
