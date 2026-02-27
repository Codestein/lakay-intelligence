"""Gold layer aggregation definitions for 6 materialized datasets."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Dataset definitions
# ---------------------------------------------------------------------------

GOLD_DATASETS: dict[str, dict[str, Any]] = {
    "daily-transaction-summary": {
        "description": "Per-user, per-day transaction metrics",
        "grain": "per-user, per-day",
        "refresh_schedule": "daily",
        "source_event_types": [
            "transaction-initiated", "transaction-completed", "transaction-failed",
        ],
    },
    "circle-lifecycle-summary": {
        "description": "Per-circle lifecycle and health metrics",
        "grain": "per-circle",
        "refresh_schedule": "daily",
        "source_event_types": [
            "circle-created", "circle-member-joined", "circle-member-dropped",
        ],
    },
    "user-risk-dashboard": {
        "description": "Per-user risk metrics across fraud, compliance, behavior",
        "grain": "per-user",
        "refresh_schedule": "daily",
        "source_event_types": [
            "transaction-initiated", "session-started",
        ],
    },
    "compliance-reporting": {
        "description": "Per-day compliance metrics for BSA officer dashboard",
        "grain": "per-day, per-metric",
        "refresh_schedule": "daily",
        "source_event_types": [
            "transaction-initiated", "transaction-completed",
        ],
    },
    "platform-health": {
        "description": "Per-day platform-wide health metrics",
        "grain": "per-day",
        "refresh_schedule": "hourly",
        "source_event_types": [
            "transaction-initiated", "session-started", "circle-created",
            "remittance-initiated",
        ],
    },
    "haiti-corridor-analytics": {
        "description": "Per-day, per-corridor remittance analytics",
        "grain": "per-day, per-corridor-segment",
        "refresh_schedule": "daily",
        "source_event_types": [
            "remittance-initiated", "remittance-completed", "remittance-failed",
        ],
    },
}


def _parse_event_payload(event: dict) -> dict:
    """Extract payload from an event, handling both dict and JSON string."""
    payload = event.get("payload", {})
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            payload = {}
    payload_json = event.get("payload_json")
    if payload_json and not payload:
        try:
            payload = json.loads(payload_json)
        except (json.JSONDecodeError, TypeError):
            payload = {}
    return payload


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _parse_ts(ts: Any) -> datetime | None:
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    return None


# ---------------------------------------------------------------------------
# G-1: Daily Transaction Summary
# ---------------------------------------------------------------------------


def aggregate_daily_transactions(events: list[dict]) -> list[dict]:
    """Aggregate transaction events to per-user, per-day summaries."""
    buckets: dict[str, dict] = {}

    for event in events:
        payload = _parse_event_payload(event)
        user_id = payload.get("user_id", "unknown")
        ts = _parse_ts(event.get("timestamp"))
        if not ts:
            continue
        day = ts.strftime("%Y-%m-%d")
        key = f"{user_id}:{day}"

        if key not in buckets:
            buckets[key] = {
                "user_id": user_id,
                "date": day,
                "transaction_count": 0,
                "total_amount": 0.0,
                "amounts": [],
                "recipients": set(),
                "corridors": set(),
            }

        b = buckets[key]
        b["transaction_count"] += 1
        amount = _safe_float(payload.get("amount"))
        b["total_amount"] += amount
        b["amounts"].append(amount)

        if rec := payload.get("recipient_id"):
            b["recipients"].add(rec)
        if cor := payload.get("corridor"):
            b["corridors"].add(cor)

    results = []
    for b in buckets.values():
        amounts = b["amounts"]
        results.append({
            "user_id": b["user_id"],
            "date": b["date"],
            "transaction_count": b["transaction_count"],
            "total_amount": round(b["total_amount"], 2),
            "average_amount": round(b["total_amount"] / len(amounts), 2) if amounts else 0.0,
            "min_amount": round(min(amounts), 2) if amounts else 0.0,
            "max_amount": round(max(amounts), 2) if amounts else 0.0,
            "distinct_recipients": len(b["recipients"]),
            "distinct_corridors": len(b["corridors"]),
        })
    return results


# ---------------------------------------------------------------------------
# G-2: Circle Lifecycle Summary
# ---------------------------------------------------------------------------


def aggregate_circle_lifecycle(events: list[dict]) -> list[dict]:
    """Aggregate circle events to per-circle lifecycle summaries."""
    circles: dict[str, dict] = {}

    for event in events:
        payload = _parse_event_payload(event)
        event_type = event.get("event_type", "")
        circle_id = payload.get("circle_id", "unknown")

        if circle_id not in circles:
            circles[circle_id] = {
                "circle_id": circle_id,
                "health_score": 0.0,
                "current_tier": "unknown",
                "member_count_original": 0,
                "member_count_current": 0,
                "member_count_dropped": 0,
                "total_collected": 0.0,
                "expected_collected": 0.0,
                "collection_ratio": 0.0,
                "payout_completion_rate": 0.0,
                "days_active": 0,
                "estimated_completion_date": None,
                "created_at": None,
            }

        c = circles[circle_id]

        if event_type == "circle-created":
            c["member_count_original"] = payload.get("max_members", 0)
            c["member_count_current"] = 1  # organizer
            ts = _parse_ts(event.get("timestamp"))
            if ts:
                c["created_at"] = ts.isoformat()
                c["days_active"] = (datetime.now(UTC) - ts).days

            contribution = _safe_float(payload.get("contribution_amount"))
            max_members = int(payload.get("max_members", 10))
            c["expected_collected"] = contribution * max_members

        elif event_type == "circle-member-joined":
            c["member_count_current"] += 1

        elif event_type == "circle-member-dropped":
            c["member_count_current"] = max(0, c["member_count_current"] - 1)
            c["member_count_dropped"] += 1

        # Update collection ratio
        if c["expected_collected"] > 0:
            c["collection_ratio"] = round(
                c["total_collected"] / c["expected_collected"], 4
            )

    return list(circles.values())


# ---------------------------------------------------------------------------
# G-3: User Risk Dashboard
# ---------------------------------------------------------------------------


def aggregate_user_risk(
    events: list[dict],
    fraud_scores: dict[str, float] | None = None,
    compliance_levels: dict[str, str] | None = None,
    engagement_stages: dict[str, str] | None = None,
) -> list[dict]:
    """Aggregate per-user risk metrics combining cross-domain data."""
    fraud_scores = fraud_scores or {}
    compliance_levels = compliance_levels or {}
    engagement_stages = engagement_stages or {}

    users: dict[str, dict] = {}

    for event in events:
        payload = _parse_event_payload(event)
        user_id = payload.get("user_id") or payload.get("sender_id") or "unknown"
        ts = _parse_ts(event.get("timestamp"))

        if user_id not in users:
            users[user_id] = {
                "user_id": user_id,
                "fraud_score": fraud_scores.get(user_id, 0.0),
                "compliance_risk_level": compliance_levels.get(user_id, "low"),
                "engagement_stage": engagement_stages.get(user_id, "unknown"),
                "ato_alert_count": 0,
                "compliance_alert_count": 0,
                "ctr_filing_count": 0,
                "txn_volume_7d": 0.0,
                "txn_volume_30d": 0.0,
                "txn_volume_90d": 0.0,
                "circle_participation_count": 0,
            }

        u = users[user_id]
        event_type = event.get("event_type", "")
        now = datetime.now(UTC)

        if event_type.startswith("transaction") and ts:
            amount = _safe_float(payload.get("amount"))
            days_ago = (now - ts).days if ts else 999
            if days_ago <= 7:
                u["txn_volume_7d"] += amount
            if days_ago <= 30:
                u["txn_volume_30d"] += amount
            if days_ago <= 90:
                u["txn_volume_90d"] += amount

        elif event_type == "circle-member-joined":
            u["circle_participation_count"] += 1

    # Round amounts
    for u in users.values():
        u["txn_volume_7d"] = round(u["txn_volume_7d"], 2)
        u["txn_volume_30d"] = round(u["txn_volume_30d"], 2)
        u["txn_volume_90d"] = round(u["txn_volume_90d"], 2)

    return list(users.values())


# ---------------------------------------------------------------------------
# G-4: Compliance Reporting
# ---------------------------------------------------------------------------


def aggregate_compliance_reporting(events: list[dict]) -> list[dict]:
    """Aggregate compliance metrics per day."""
    days: dict[str, dict] = {}

    for event in events:
        payload = _parse_event_payload(event)
        ts = _parse_ts(event.get("timestamp"))
        if not ts:
            continue
        day = ts.strftime("%Y-%m-%d")

        if day not in days:
            days[day] = {
                "date": day,
                "ctr_filing_count": 0,
                "ctr_total_amount": 0.0,
                "sar_filing_count": 0,
                "compliance_alerts_by_type": {},
                "compliance_alerts_by_priority": {},
                "structuring_detections": {},
                "customers_by_risk_level": {"low": 0, "medium": 0, "high": 0, "critical": 0},
                "edd_reviews_due": 0,
            }

        d = days[day]
        event_type = event.get("event_type", "")

        # Count CTR-eligible transactions (amounts >= $10,000)
        if event_type in ("transaction-initiated", "transaction-completed"):
            amount = _safe_float(payload.get("amount"))
            if amount >= 10000:
                d["ctr_filing_count"] += 1
                d["ctr_total_amount"] += amount

    # Round amounts
    for d in days.values():
        d["ctr_total_amount"] = round(d["ctr_total_amount"], 2)

    return sorted(days.values(), key=lambda x: x["date"])


# ---------------------------------------------------------------------------
# G-5: Platform Health
# ---------------------------------------------------------------------------


def aggregate_platform_health(events: list[dict]) -> list[dict]:
    """Aggregate platform-wide health metrics per day."""
    days: dict[str, dict] = {}

    for event in events:
        payload = _parse_event_payload(event)
        ts = _parse_ts(event.get("timestamp"))
        if not ts:
            continue
        day = ts.strftime("%Y-%m-%d")

        if day not in days:
            days[day] = {
                "date": day,
                "active_users": set(),
                "new_users": set(),
                "sessions": 0,
                "transaction_count": 0,
                "transaction_volume": 0.0,
                "remittance_count": 0,
                "remittance_volume": 0.0,
                "remittance_corridors": set(),
                "circles_active": 0,
                "circles_created": 0,
                "avg_fraud_score": 0.0,
                "avg_circle_health": 0.0,
            }

        d = days[day]
        event_type = event.get("event_type", "")

        uid = payload.get("user_id") or payload.get("sender_id") or payload.get("organizer_id")
        if uid:
            d["active_users"].add(uid)

        if event_type == "session-started":
            d["sessions"] += 1

        elif event_type.startswith("transaction"):
            d["transaction_count"] += 1
            d["transaction_volume"] += _safe_float(payload.get("amount"))

        elif event_type.startswith("remittance"):
            d["remittance_count"] += 1
            d["remittance_volume"] += _safe_float(payload.get("send_amount"))
            if rc := payload.get("recipient_country"):
                d["remittance_corridors"].add(rc)

        elif event_type == "circle-created":
            d["circles_created"] += 1
            d["circles_active"] += 1

    # Serialize sets
    results = []
    for d in days.values():
        results.append({
            "date": d["date"],
            "active_users": len(d["active_users"]),
            "sessions": d["sessions"],
            "transaction_count": d["transaction_count"],
            "transaction_volume": round(d["transaction_volume"], 2),
            "remittance_count": d["remittance_count"],
            "remittance_volume": round(d["remittance_volume"], 2),
            "remittance_corridors": len(d["remittance_corridors"]),
            "circles_active": d["circles_active"],
            "circles_created": d["circles_created"],
            "avg_fraud_score": d["avg_fraud_score"],
            "avg_circle_health": d["avg_circle_health"],
        })

    return sorted(results, key=lambda x: x["date"])


# ---------------------------------------------------------------------------
# G-6: Haiti Corridor Analytics
# ---------------------------------------------------------------------------


def aggregate_haiti_corridor(events: list[dict]) -> list[dict]:
    """Aggregate remittance metrics per day, per corridor segment."""
    buckets: dict[str, dict] = {}

    for event in events:
        payload = _parse_event_payload(event)
        event_type = event.get("event_type", "")

        if not event_type.startswith("remittance"):
            continue

        ts = _parse_ts(event.get("timestamp"))
        if not ts:
            continue
        day = ts.strftime("%Y-%m-%d")

        # Corridor: sender location → recipient country
        recipient_country = payload.get("recipient_country", "HT")
        sender_state = payload.get("sender_state", "US")
        corridor = f"{sender_state}->{recipient_country}"

        key = f"{day}:{corridor}"
        if key not in buckets:
            buckets[key] = {
                "date": day,
                "corridor": corridor,
                "remittance_count": 0,
                "total_volume_usd": 0.0,
                "amounts": [],
                "exchange_rates": [],
                "delivery_success_count": 0,
                "delivery_fail_count": 0,
                "delivery_times": [],
            }

        b = buckets[key]

        if event_type == "remittance-initiated":
            b["remittance_count"] += 1
            amount = _safe_float(payload.get("send_amount"))
            b["total_volume_usd"] += amount
            b["amounts"].append(amount)
            rate = _safe_float(payload.get("exchange_rate"))
            if rate > 0:
                b["exchange_rates"].append(rate)

        elif event_type == "remittance-completed":
            b["delivery_success_count"] += 1

        elif event_type == "remittance-failed":
            b["delivery_fail_count"] += 1

    results = []
    for b in buckets.values():
        total_deliveries = b["delivery_success_count"] + b["delivery_fail_count"]
        results.append({
            "date": b["date"],
            "corridor": b["corridor"],
            "remittance_count": b["remittance_count"],
            "total_volume_usd": round(b["total_volume_usd"], 2),
            "average_amount": (
                round(sum(b["amounts"]) / len(b["amounts"]), 2) if b["amounts"] else 0.0
            ),
            "average_exchange_rate": (
                round(sum(b["exchange_rates"]) / len(b["exchange_rates"]), 4)
                if b["exchange_rates"]
                else 0.0
            ),
            "delivery_success_rate": (
                round(b["delivery_success_count"] / total_deliveries, 4)
                if total_deliveries > 0
                else 0.0
            ),
            "average_delivery_time": None,  # Stubbed for future agent data
            "active_agent_count": None,  # Stubbed for future
        })

    return sorted(results, key=lambda x: (x["date"], x["corridor"]))
