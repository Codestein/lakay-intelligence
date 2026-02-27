"""Load test harness for Lakay Intelligence.

Usage:
    python tests/load/harness.py --target-rps 100 --duration 60 --ramp-time 30
    python tests/load/harness.py --profile throughput
    python tests/load/harness.py --profile stress
    python tests/load/harness.py --profile burst
    python tests/load/harness.py --profile stability --duration 3600
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_EVENT_TYPE_MIX: dict[str, float] = {
    "transaction": 0.40,
    "session": 0.30,
    "circle": 0.15,
    "remittance": 0.15,
}


@dataclass
class LoadTestConfig:
    """All tunables for a single load-test run."""

    target_rps: int = 100
    duration_seconds: int = 60
    ramp_time_seconds: int = 30
    base_url: str = "http://localhost:8000"
    fraud_mix_pct: float = 0.05
    event_type_mix: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_EVENT_TYPE_MIX))
    # Connection pool / concurrency limits
    max_concurrent: int = 200
    timeout_seconds: float = 30.0
    # Output
    output_file: str | None = None

    def __post_init__(self) -> None:
        total = sum(self.event_type_mix.values())
        if not math.isclose(total, 1.0, abs_tol=0.01):
            raise ValueError(
                f"event_type_mix weights must sum to ~1.0, got {total:.3f}"
            )


# ---------------------------------------------------------------------------
# SLA targets
# ---------------------------------------------------------------------------

SLA_TARGETS: dict[str, float] = {
    "fraud_scoring_p95_ms": 200.0,
    "session_scoring_p95_ms": 100.0,
    "feature_store_lookup_p95_ms": 10.0,
    "circle_health_p95_ms": 500.0,
}


# ---------------------------------------------------------------------------
# Latency Recorder
# ---------------------------------------------------------------------------


class LatencyRecorder:
    """Thread-safe (single-event-loop safe) latency & error recorder per endpoint."""

    def __init__(self) -> None:
        self._latencies: dict[str, list[float]] = {}
        self._errors: dict[str, int] = {}
        self._status_codes: dict[str, dict[int, int]] = {}
        self._throughput_samples: list[tuple[float, int]] = []
        self._sample_lock = asyncio.Lock()
        self._start_time: float | None = None

    def record(self, endpoint: str, latency_ms: float, status_code: int) -> None:
        """Record a single request outcome."""
        self._latencies.setdefault(endpoint, []).append(latency_ms)
        self._status_codes.setdefault(endpoint, {})
        self._status_codes[endpoint][status_code] = (
            self._status_codes[endpoint].get(status_code, 0) + 1
        )
        if status_code >= 400:
            self._errors[endpoint] = self._errors.get(endpoint, 0) + 1

    async def record_throughput_sample(self, events_this_second: int) -> None:
        """Append a (wall-clock, count) tuple for throughput curves."""
        async with self._sample_lock:
            now = time.monotonic()
            if self._start_time is None:
                self._start_time = now
            self._throughput_samples.append((now - self._start_time, events_this_second))

    # ---- aggregation helpers ------------------------------------------------

    def _percentile(self, data: list[float], pct: float) -> float:
        if not data:
            return 0.0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * (pct / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)

    def percentiles(self, endpoint: str) -> dict[str, float]:
        """Return p50 / p95 / p99 for *endpoint*."""
        data = self._latencies.get(endpoint, [])
        return {
            "p50_ms": round(self._percentile(data, 50), 2),
            "p95_ms": round(self._percentile(data, 95), 2),
            "p99_ms": round(self._percentile(data, 99), 2),
            "mean_ms": round(statistics.mean(data), 2) if data else 0.0,
            "min_ms": round(min(data), 2) if data else 0.0,
            "max_ms": round(max(data), 2) if data else 0.0,
            "count": len(data),
        }

    def error_count(self, endpoint: str) -> int:
        return self._errors.get(endpoint, 0)

    def error_rate(self, endpoint: str) -> float:
        total = len(self._latencies.get(endpoint, []))
        if total == 0:
            return 0.0
        return self._errors.get(endpoint, 0) / total

    def total_events(self) -> int:
        return sum(len(v) for v in self._latencies.values())

    def endpoints(self) -> list[str]:
        return list(self._latencies.keys())

    def throughput_curve(self) -> list[dict[str, float]]:
        return [
            {"elapsed_seconds": round(t, 1), "events_per_second": c}
            for t, c in self._throughput_samples
        ]


# ---------------------------------------------------------------------------
# Synthetic payload generators (inline, no external deps)
# ---------------------------------------------------------------------------

# Country codes used for geo locations
_US_CITIES = [
    ("New York", "NY", 40.7128, -74.0060),
    ("Miami", "FL", 25.7617, -80.1918),
    ("Boston", "MA", 42.3601, -71.0589),
    ("Chicago", "IL", 41.8781, -87.6298),
    ("Atlanta", "GA", 33.7490, -84.3880),
    ("Houston", "TX", 29.7604, -95.3698),
    ("Los Angeles", "CA", 34.0522, -118.2437),
    ("Brooklyn", "NY", 40.6782, -73.9442),
    ("Philadelphia", "PA", 39.9526, -75.1652),
    ("Orlando", "FL", 28.5383, -81.3792),
]

_DEVICE_TYPES = ["ios", "android", "web_desktop", "web_mobile"]

_TX_TYPES = [
    "circle_contribution",
    "circle_payout",
    "remittance",
    "fee",
    "refund",
]

_ACTION_TYPES = [
    "page_view",
    "button_click",
    "form_submit",
    "circle_browse",
    "circle_join_request",
    "contribution_initiate",
    "remittance_initiate",
    "settings_change",
]


def _uuid() -> str:
    return str(uuid.uuid4())


def _random_ip() -> str:
    return (
        f"{random.randint(1, 223)}.{random.randint(0, 255)}"
        f".{random.randint(0, 255)}.{random.randint(1, 254)}"
    )


def _random_geo() -> dict[str, Any]:
    city, state, lat, lon = random.choice(_US_CITIES)
    return {
        "city": city,
        "state": state,
        "country": "US",
        "latitude": round(lat + random.uniform(-0.05, 0.05), 4),
        "longitude": round(lon + random.uniform(-0.05, 0.05), 4),
    }


def _random_amount(fraud: bool = False) -> str:
    """Return a decimal-string amount.  If *fraud*, bias toward structuring."""
    if fraud:
        # Structuring near $3k or $10k thresholds
        amount = (
            random.uniform(2800, 2999)
            if random.random() < 0.5
            else random.uniform(9500, 9999)
        )
    else:
        amount = random.lognormvariate(4.5, 1.2)
        amount = max(1.0, min(amount, 50_000.0))
    return f"{amount:.2f}"


def generate_fraud_score_payload(*, fraud: bool = False) -> dict[str, Any]:
    """Build a ``FraudScoreRequest``-compatible dict."""
    geo = _random_geo()
    return {
        "transaction_id": _uuid(),
        "user_id": _uuid(),
        "amount": _random_amount(fraud=fraud),
        "currency": "USD",
        "ip_address": _random_ip(),
        "device_id": _uuid(),
        "geo_location": geo,
        "transaction_type": random.choice(_TX_TYPES),
        "initiated_at": datetime.now(UTC).isoformat(),
        "recipient_id": _uuid(),
    }


def generate_session_score_payload(*, fraud: bool = False) -> dict[str, Any]:
    """Build a ``SessionScoreRequest``-compatible dict."""
    device_type = random.choice(_DEVICE_TYPES)
    geo = _random_geo()
    action_count = random.randint(1, 50)
    if fraud:
        # ATO-like pattern: unusual device, high-value actions
        actions = random.choices(
            ["remittance_initiate", "settings_change", "form_submit"],
            k=action_count,
        )
    else:
        actions = random.choices(_ACTION_TYPES, k=action_count)
    return {
        "session_id": _uuid(),
        "user_id": _uuid(),
        "device_id": _uuid(),
        "device_type": device_type,
        "ip_address": _random_ip(),
        "geo_location": geo,
        "session_start": datetime.now(UTC).isoformat(),
        "session_duration_seconds": round(random.lognormvariate(6.0, 1.0), 1),
        "action_count": action_count,
        "actions": actions,
    }


def generate_circle_score_payload() -> tuple[str, dict[str, Any] | None]:
    """Return ``(circle_id, optional body)`` for ``POST /circles/{id}/score``."""
    circle_id = _uuid()
    # Provide synthetic feature overrides so the endpoint can score without a
    # real feature store.
    features = {
        "payment_timeliness": round(random.uniform(0.5, 1.0), 3),
        "member_retention": round(random.uniform(0.4, 1.0), 3),
        "contribution_consistency": round(random.uniform(0.3, 1.0), 3),
        "payout_success_rate": round(random.uniform(0.7, 1.0), 3),
        "dispute_rate": round(random.uniform(0.0, 0.15), 4),
        "avg_days_late": round(random.uniform(0, 5), 2),
        "member_count": random.randint(5, 20),
        "completed_cycles": random.randint(0, 12),
        "total_cycles": random.randint(6, 24),
        "organizer_score": round(random.uniform(0.5, 1.0), 3),
    }
    body = {"circle_id": circle_id, "features": features}
    return circle_id, body


def generate_remittance_payload(*, fraud: bool = False) -> dict[str, Any]:
    """Build a fraud-score payload styled as a remittance transaction."""
    geo = _random_geo()
    if fraud:
        amount = f"{random.uniform(4500, 4999):.2f}"
    else:
        amount = f"{random.lognormvariate(5.0, 0.9):.2f}"
    return {
        "transaction_id": _uuid(),
        "user_id": _uuid(),
        "amount": amount,
        "currency": "USD",
        "ip_address": _random_ip(),
        "device_id": _uuid(),
        "geo_location": geo,
        "transaction_type": "remittance",
        "initiated_at": datetime.now(UTC).isoformat(),
        "recipient_id": _uuid(),
    }


# ---------------------------------------------------------------------------
# Load Test Harness
# ---------------------------------------------------------------------------


class LoadTestHarness:
    """Drives configurable load against the Lakay Intelligence API."""

    def __init__(self, config: LoadTestConfig) -> None:
        self.config = config
        self.recorder = LatencyRecorder()
        self._semaphore: asyncio.Semaphore | None = None
        self._client: httpx.AsyncClient | None = None
        self._running = False
        self._events_sent = 0
        self._event_types = list(config.event_type_mix.keys())
        self._event_weights = list(config.event_type_mix.values())

    # ---- event generation ---------------------------------------------------

    def generate_event(self) -> tuple[str, str, str, dict[str, Any] | None]:
        """Return (event_type, method, url, body) for a random event.

        The event type is sampled according to ``event_type_mix`` weights and
        the ``fraud_mix_pct`` controls how many events carry fraud indicators.
        """
        event_type: str = random.choices(
            self._event_types, weights=self._event_weights, k=1
        )[0]
        is_fraud = random.random() < self.config.fraud_mix_pct
        base = self.config.base_url.rstrip("/")

        if event_type == "transaction":
            payload = generate_fraud_score_payload(fraud=is_fraud)
            return event_type, "POST", f"{base}/api/v1/fraud/score", payload

        if event_type == "session":
            payload = generate_session_score_payload(fraud=is_fraud)
            return event_type, "POST", f"{base}/api/v1/behavior/sessions/score", payload

        if event_type == "circle":
            circle_id, body = generate_circle_score_payload()
            return event_type, "POST", f"{base}/api/v1/circles/{circle_id}/score", body

        # remittance -- scored through the fraud endpoint
        payload = generate_remittance_payload(fraud=is_fraud)
        return event_type, "POST", f"{base}/api/v1/fraud/score", payload

    # ---- individual request senders -----------------------------------------

    async def _send_request(
        self,
        endpoint_label: str,
        method: str,
        url: str,
        body: dict[str, Any] | None,
    ) -> None:
        """Fire one HTTP request, record latency and status."""
        assert self._client is not None
        assert self._semaphore is not None
        async with self._semaphore:
            t0 = time.monotonic()
            try:
                if method == "POST":
                    resp = await self._client.post(url, json=body)
                else:
                    resp = await self._client.get(url)
                status = resp.status_code
            except httpx.TimeoutException:
                status = 408  # synthetic timeout code
            except httpx.ConnectError:
                status = 503
            except Exception:
                status = 500
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            self.recorder.record(endpoint_label, elapsed_ms, status)
            self._events_sent += 1

    async def send_fraud_score(self, payload: dict[str, Any]) -> None:
        """POST /api/v1/fraud/score with timing."""
        url = f"{self.config.base_url.rstrip('/')}/api/v1/fraud/score"
        await self._send_request("fraud_scoring", "POST", url, payload)

    async def send_session_score(self, payload: dict[str, Any]) -> None:
        """POST /api/v1/behavior/sessions/score with timing."""
        url = f"{self.config.base_url.rstrip('/')}/api/v1/behavior/sessions/score"
        await self._send_request("session_scoring", "POST", url, payload)

    async def send_circle_score(self, circle_id: str, body: dict[str, Any] | None) -> None:
        """POST /api/v1/circles/{id}/score with timing."""
        url = f"{self.config.base_url.rstrip('/')}/api/v1/circles/{circle_id}/score"
        await self._send_request("circle_health", "POST", url, body)

    # ---- ramp calculation ---------------------------------------------------

    @staticmethod
    def _current_rps(
        elapsed: float,
        ramp_time: float,
        target_rps: int,
        duration: float,
    ) -> float:
        """Determine the desired RPS at *elapsed* seconds into the test.

        Phases:
        1. **Ramp-up** (0 .. ramp_time): linear increase from 1 to target_rps.
        2. **Sustain** (ramp_time .. duration - 5): hold at target_rps.
        3. **Cool-down** (last 5 s): linear decrease to 0.
        """
        cooldown_start = max(ramp_time, duration - 5.0)
        if elapsed < ramp_time:
            fraction = elapsed / ramp_time if ramp_time > 0 else 1.0
            return max(1.0, fraction * target_rps)
        if elapsed >= cooldown_start:
            remaining = duration - elapsed
            fraction = max(0.0, remaining / 5.0)
            return max(0.0, fraction * target_rps)
        return float(target_rps)

    # ---- main execution loop ------------------------------------------------

    async def run(self) -> dict[str, Any]:
        """Execute the full load test: ramp-up, sustain, cool-down.

        Returns the aggregated results dict (same as ``collect_results``).
        """
        cfg = self.config
        self._semaphore = asyncio.Semaphore(cfg.max_concurrent)
        self._running = True
        self._events_sent = 0

        transport = httpx.AsyncHTTPTransport(
            retries=0,
            limits=httpx.Limits(
                max_connections=cfg.max_concurrent,
                max_keepalive_connections=cfg.max_concurrent // 2,
            ),
        )
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(cfg.timeout_seconds),
        )

        start = time.monotonic()
        pending: set[asyncio.Task[None]] = set()
        second_counter = 0

        _log(
            f"Starting load test: target_rps={cfg.target_rps}, "
            f"duration={cfg.duration_seconds}s, ramp={cfg.ramp_time_seconds}s"
        )

        try:
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= cfg.duration_seconds:
                    break

                desired_rps = self._current_rps(
                    elapsed, cfg.ramp_time_seconds, cfg.target_rps, cfg.duration_seconds
                )
                events_this_tick = max(0, int(desired_rps))

                # Fire events for this second
                for _ in range(events_this_tick):
                    event_type, method, url, body = self.generate_event()
                    # Map event type to the endpoint label
                    if event_type in ("transaction", "remittance"):
                        label = "fraud_scoring"
                    elif event_type == "session":
                        label = "session_scoring"
                    else:
                        label = "circle_health"
                    task = asyncio.create_task(
                        self._send_request(label, method, url, body)
                    )
                    pending.add(task)
                    task.add_done_callback(pending.discard)

                # Record throughput sample
                await self.recorder.record_throughput_sample(events_this_tick)

                second_counter += 1
                if second_counter % 10 == 0:
                    _log(
                        f"  [{int(elapsed):>4d}s] target_rps={desired_rps:.0f}  "
                        f"sent={self._events_sent}  pending={len(pending)}"
                    )

                # Sleep until the next 1-second tick
                next_tick = start + second_counter
                sleep_for = next_tick - time.monotonic()
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)

            # Drain remaining in-flight requests
            if pending:
                _log(f"  Draining {len(pending)} in-flight requests ...")
                await asyncio.gather(*pending, return_exceptions=True)

        finally:
            self._running = False
            await self._client.aclose()
            self._client = None

        wall_time = time.monotonic() - start
        _log(
            f"Load test complete: {self._events_sent} events in "
            f"{wall_time:.1f}s ({self._events_sent / max(wall_time, 0.001):.1f} avg RPS)"
        )

        return self.collect_results()

    # ---- results aggregation ------------------------------------------------

    def collect_results(self) -> dict[str, Any]:
        """Aggregate recorder data into the final JSON-serialisable report."""
        rec = self.recorder

        per_endpoint: dict[str, Any] = {}
        for ep in rec.endpoints():
            pcts = rec.percentiles(ep)
            per_endpoint[ep] = {
                "latency": pcts,
                "error_count": rec.error_count(ep),
                "error_rate": round(rec.error_rate(ep), 4),
            }

        sla_results = self._evaluate_sla(per_endpoint)

        results: dict[str, Any] = {
            "test_config": {
                "target_rps": self.config.target_rps,
                "duration_seconds": self.config.duration_seconds,
                "ramp_time_seconds": self.config.ramp_time_seconds,
                "base_url": self.config.base_url,
                "fraud_mix_pct": self.config.fraud_mix_pct,
                "event_type_mix": self.config.event_type_mix,
            },
            "summary": {
                "total_events": rec.total_events(),
                "overall_error_rate": round(
                    sum(rec.error_count(ep) for ep in rec.endpoints())
                    / max(rec.total_events(), 1),
                    4,
                ),
            },
            "per_endpoint": per_endpoint,
            "throughput_curve": rec.throughput_curve(),
            "sla_compliance": sla_results,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        return results

    @staticmethod
    def _evaluate_sla(per_endpoint: dict[str, Any]) -> dict[str, Any]:
        """Check each endpoint's p95 against the SLA targets."""
        sla: dict[str, Any] = {}

        mapping = {
            "fraud_scoring": "fraud_scoring_p95_ms",
            "session_scoring": "session_scoring_p95_ms",
            "feature_store_lookup": "feature_store_lookup_p95_ms",
            "circle_health": "circle_health_p95_ms",
        }

        all_pass = True
        for ep_key, sla_key in mapping.items():
            target = SLA_TARGETS[sla_key]
            ep_data = per_endpoint.get(ep_key)
            if ep_data is None:
                sla[sla_key] = {
                    "target_ms": target,
                    "actual_p95_ms": None,
                    "pass": True,
                    "note": "no data (endpoint not exercised)",
                }
                continue
            actual_p95 = ep_data["latency"]["p95_ms"]
            passed = actual_p95 <= target
            if not passed:
                all_pass = False
            sla[sla_key] = {
                "target_ms": target,
                "actual_p95_ms": actual_p95,
                "pass": passed,
            }

        sla["overall_pass"] = all_pass
        return sla


# ---------------------------------------------------------------------------
# Built-in test profiles
# ---------------------------------------------------------------------------


def _profile_throughput() -> list[LoadTestConfig]:
    """Ramp 100 -> 500 -> 1000 RPS over 5 min, sustain 1000 for 10 min.

    Implemented as three sequential configs (the harness runner chains them).
    """
    return [
        LoadTestConfig(target_rps=100, duration_seconds=60, ramp_time_seconds=20),
        LoadTestConfig(target_rps=500, duration_seconds=120, ramp_time_seconds=40),
        LoadTestConfig(target_rps=1000, duration_seconds=600, ramp_time_seconds=60),
    ]


def _profile_stress() -> list[LoadTestConfig]:
    """Push beyond 1000 to find the breaking point: 1000 -> 1500 -> 2000 -> 2500."""
    return [
        LoadTestConfig(target_rps=1000, duration_seconds=120, ramp_time_seconds=30),
        LoadTestConfig(target_rps=1500, duration_seconds=120, ramp_time_seconds=30),
        LoadTestConfig(target_rps=2000, duration_seconds=120, ramp_time_seconds=30),
        LoadTestConfig(target_rps=2500, duration_seconds=120, ramp_time_seconds=30),
    ]


def _profile_burst() -> list[LoadTestConfig]:
    """Baseline 200 RPS, spike to 2000 for 60 s, return to baseline."""
    return [
        LoadTestConfig(target_rps=200, duration_seconds=60, ramp_time_seconds=15),
        LoadTestConfig(target_rps=2000, duration_seconds=60, ramp_time_seconds=5),
        LoadTestConfig(target_rps=200, duration_seconds=60, ramp_time_seconds=5),
    ]


def _profile_stability(duration: int = 3600) -> list[LoadTestConfig]:
    """500 RPS for *duration* seconds (default 1 hour)."""
    return [
        LoadTestConfig(target_rps=500, duration_seconds=duration, ramp_time_seconds=60),
    ]


PROFILES: dict[str, Any] = {
    "throughput": _profile_throughput,
    "stress": _profile_stress,
    "burst": _profile_burst,
    "stability": _profile_stability,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _merge_results(all_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge multiple sequential phase results into a single report."""
    if len(all_results) == 1:
        return all_results[0]

    merged: dict[str, Any] = {
        "phases": all_results,
        "summary": {
            "total_events": sum(r["summary"]["total_events"] for r in all_results),
            "phase_count": len(all_results),
        },
        "throughput_curve": [],
        "sla_compliance": {},
        "generated_at": datetime.now(UTC).isoformat(),
    }

    # Concatenate throughput curves with offset
    offset = 0.0
    for r in all_results:
        for pt in r.get("throughput_curve", []):
            merged["throughput_curve"].append(
                {
                    "elapsed_seconds": round(pt["elapsed_seconds"] + offset, 1),
                    "events_per_second": pt["events_per_second"],
                }
            )
        if r.get("throughput_curve"):
            offset += r["throughput_curve"][-1]["elapsed_seconds"]

    # Merge per-endpoint latencies across phases for aggregate SLA
    combined_latency: dict[str, list[dict[str, Any]]] = {}
    for r in all_results:
        for ep, data in r.get("per_endpoint", {}).items():
            combined_latency.setdefault(ep, []).append(data)

    merged_per_endpoint: dict[str, Any] = {}
    for ep, data_list in combined_latency.items():
        all_p95 = [d["latency"]["p95_ms"] for d in data_list if d["latency"]["count"] > 0]
        all_counts = [d["latency"]["count"] for d in data_list]
        all_errors = [d["error_count"] for d in data_list]
        total_count = sum(all_counts)
        total_errors = sum(all_errors)
        merged_per_endpoint[ep] = {
            "latency": {
                "worst_p95_ms": round(max(all_p95), 2) if all_p95 else 0.0,
                "count": total_count,
            },
            "error_count": total_errors,
            "error_rate": round(total_errors / max(total_count, 1), 4),
        }

    merged["per_endpoint"] = merged_per_endpoint

    # SLA check using worst-case p95 across phases
    sla_ep_for_check: dict[str, Any] = {}
    for ep, data in merged_per_endpoint.items():
        sla_ep_for_check[ep] = {
            "latency": {"p95_ms": data["latency"]["worst_p95_ms"]},
        }
    merged["sla_compliance"] = LoadTestHarness._evaluate_sla(sla_ep_for_check)

    return merged


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load test harness for Lakay Intelligence API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--profile",
        choices=list(PROFILES.keys()),
        help="Run a built-in test profile instead of custom parameters.",
    )
    parser.add_argument(
        "--target-rps",
        type=int,
        default=100,
        help="Target requests per second (default: 100).",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Test duration in seconds (default: 60).",
    )
    parser.add_argument(
        "--ramp-time",
        type=int,
        default=30,
        help="Ramp-up time in seconds (default: 30).",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8000",
        help="Base URL of the Lakay API (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--fraud-pct",
        type=float,
        default=0.05,
        help="Fraction of events that carry fraud signals (default: 0.05).",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=200,
        help="Maximum concurrent HTTP connections (default: 200).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write JSON results to this file path.",
    )
    return parser


async def async_main(args: argparse.Namespace) -> None:
    if args.profile:
        profile_fn = PROFILES[args.profile]
        if args.profile == "stability":
            configs = profile_fn(duration=args.duration)
        else:
            configs = profile_fn()
        # Propagate CLI overrides that make sense for profiles
        for cfg in configs:
            cfg.base_url = args.base_url
            cfg.fraud_mix_pct = args.fraud_pct
            cfg.max_concurrent = args.max_concurrent
    else:
        configs = [
            LoadTestConfig(
                target_rps=args.target_rps,
                duration_seconds=args.duration,
                ramp_time_seconds=args.ramp_time,
                base_url=args.base_url,
                fraud_mix_pct=args.fraud_pct,
                max_concurrent=args.max_concurrent,
            )
        ]

    all_results: list[dict[str, Any]] = []
    for i, cfg in enumerate(configs):
        _log(f"=== Phase {i + 1}/{len(configs)} ===")
        harness = LoadTestHarness(cfg)
        result = await harness.run()
        all_results.append(result)

    final = _merge_results(all_results)

    # Pretty-print summary to stdout
    _print_summary(final)

    # Write full JSON to file if requested
    output_path = args.output
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(final, indent=2, default=str))
        _log(f"Full results written to {path}")
    else:
        # Dump JSON to stdout as well
        print(json.dumps(final, indent=2, default=str))


def _print_summary(results: dict[str, Any]) -> None:
    """Human-readable summary printed to stderr."""
    line = "-" * 60
    print(f"\n{line}", file=sys.stderr)
    print("  LOAD TEST RESULTS SUMMARY", file=sys.stderr)
    print(f"{line}", file=sys.stderr)

    summary = results.get("summary", {})
    print(f"  Total events:   {summary.get('total_events', 'N/A')}", file=sys.stderr)
    if "overall_error_rate" in summary:
        print(
            f"  Error rate:     {summary['overall_error_rate'] * 100:.2f}%",
            file=sys.stderr,
        )
    if "phase_count" in summary:
        print(f"  Phases:         {summary['phase_count']}", file=sys.stderr)

    # Per-endpoint latencies
    per_ep = results.get("per_endpoint", {})
    if per_ep:
        print(f"\n  {'Endpoint':<25} {'p95 (ms)':>10} {'Errors':>8} {'Count':>8}", file=sys.stderr)
        print(f"  {'-'*25} {'-'*10} {'-'*8} {'-'*8}", file=sys.stderr)
        for ep, data in per_ep.items():
            lat = data.get("latency", {})
            p95 = lat.get("p95_ms", lat.get("worst_p95_ms", "N/A"))
            count = lat.get("count", "N/A")
            errors = data.get("error_count", 0)
            print(f"  {ep:<25} {p95:>10} {errors:>8} {count:>8}", file=sys.stderr)

    # SLA compliance
    sla = results.get("sla_compliance", {})
    if sla:
        overall = sla.get("overall_pass", "N/A")
        status = "PASS" if overall else "FAIL"
        print(f"\n  SLA Compliance: {status}", file=sys.stderr)
        for key, val in sla.items():
            if key == "overall_pass":
                continue
            if isinstance(val, dict):
                mark = "PASS" if val.get("pass") else "FAIL"
                target = val.get("target_ms", "?")
                actual = val.get("actual_p95_ms", "N/A")
                print(
                    f"    [{mark}] {key}: target={target}ms, actual_p95={actual}ms",
                    file=sys.stderr,
                )

    print(f"{line}\n", file=sys.stderr)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
