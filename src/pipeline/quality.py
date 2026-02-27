"""Data quality checks for the silver layer."""

from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Required fields per event type
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: dict[str, list[str]] = {
    "transaction-initiated": [
        "event_id", "event_type", "timestamp",
        "payload.transaction_id", "payload.user_id", "payload.amount", "payload.currency",
    ],
    "transaction-completed": [
        "event_id", "event_type", "timestamp",
        "payload.transaction_id", "payload.user_id",
    ],
    "transaction-failed": [
        "event_id", "event_type", "timestamp",
        "payload.transaction_id", "payload.user_id",
    ],
    "transaction-flagged": [
        "event_id", "event_type", "timestamp",
        "payload.transaction_id", "payload.user_id",
    ],
    "session-started": [
        "event_id", "event_type", "timestamp",
        "payload.session_id", "payload.user_id",
    ],
    "session-ended": [
        "event_id", "event_type", "timestamp",
        "payload.session_id", "payload.user_id",
    ],
    "circle-created": [
        "event_id", "event_type", "timestamp",
        "payload.circle_id", "payload.organizer_id",
    ],
    "circle-member-joined": [
        "event_id", "event_type", "timestamp",
        "payload.circle_id",
    ],
    "circle-member-dropped": [
        "event_id", "event_type", "timestamp",
        "payload.circle_id",
    ],
    "remittance-initiated": [
        "event_id", "event_type", "timestamp",
        "payload.remittance_id", "payload.sender_id",
        "payload.send_amount", "payload.send_currency",
    ],
    "remittance-completed": [
        "event_id", "event_type", "timestamp",
        "payload.remittance_id",
    ],
    "remittance-failed": [
        "event_id", "event_type", "timestamp",
        "payload.remittance_id",
    ],
}

# ---------------------------------------------------------------------------
# Numerical range constraints
# ---------------------------------------------------------------------------

RANGE_CHECKS: dict[str, dict[str, tuple[float | None, float | None]]] = {
    "transaction-initiated": {
        "payload.amount": (0.0, None),  # amount > 0
    },
    "remittance-initiated": {
        "payload.send_amount": (0.0, None),
        "payload.exchange_rate": (0.0, None),
    },
}


def _get_nested(obj: dict, dotted_key: str) -> Any:
    """Retrieve a value from a nested dict using dotted notation."""
    parts = dotted_key.split(".")
    current = obj
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


class QualityCheckResult:
    """Accumulates quality check results for a batch of events."""

    def __init__(self):
        self.total: int = 0
        self.passed: int = 0
        self.rejected: int = 0
        self.warnings: int = 0
        self.rejected_events: list[dict] = []
        self.warning_details: list[dict] = []

    def to_dict(self) -> dict:
        return {
            "total_events": self.total,
            "passed": self.passed,
            "rejected": self.rejected,
            "warnings": self.warnings,
        }


def validate_schema(event: dict, schema: dict | None = None) -> tuple[bool, str]:
    """Validate an event against a JSON schema (if available).

    Returns (is_valid, reason).
    """
    if schema is None:
        return True, ""

    try:
        import jsonschema

        jsonschema.validate(instance=event, schema=schema)
        return True, ""
    except Exception as e:
        return False, f"schema_validation_failed: {e!s}"


def check_completeness(event: dict) -> tuple[bool, list[str]]:
    """Verify required fields are present and non-null.

    Returns (is_complete, missing_fields).
    """
    event_type = event.get("event_type", "")
    required = REQUIRED_FIELDS.get(event_type, ["event_id", "event_type", "timestamp"])
    missing = []

    for field in required:
        value = _get_nested(event, field)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            missing.append(field)

    return len(missing) == 0, missing


def check_ranges(event: dict) -> tuple[bool, list[str]]:
    """Verify numerical values are within expected ranges.

    Returns (in_range, violations).
    """
    event_type = event.get("event_type", "")
    checks = RANGE_CHECKS.get(event_type, {})
    violations = []

    for field, (min_val, max_val) in checks.items():
        value = _get_nested(event, field)
        if value is None:
            continue  # handled by completeness check

        try:
            num_value = float(value)
        except (ValueError, TypeError):
            violations.append(f"{field}: not numeric ({value})")
            continue

        if min_val is not None and num_value <= min_val:
            violations.append(f"{field}: {num_value} <= {min_val}")
        if max_val is not None and num_value > max_val:
            violations.append(f"{field}: {num_value} > {max_val}")

    return len(violations) == 0, violations


def check_referential_integrity(
    event: dict,
    known_users: set[str] | None = None,
    known_circles: set[str] | None = None,
) -> list[str]:
    """Check that referenced entities exist.

    Returns list of warning messages (don't reject — references may arrive later).
    """
    warnings = []
    event_type = event.get("event_type", "")
    payload = event.get("payload", {})

    # Check user_id references
    if known_users is not None:
        for field in ("user_id", "sender_id", "organizer_id", "recipient_id"):
            uid = payload.get(field)
            if uid and uid not in known_users:
                warnings.append(f"unknown_{field}: {uid}")

    # Check circle_id references
    if known_circles is not None:
        cid = payload.get("circle_id")
        if cid and cid not in known_circles:
            warnings.append(f"unknown_circle_id: {cid}")

    return warnings


def check_timestamp(event: dict) -> tuple[bool, str]:
    """Verify timestamp is parseable and not in the far future."""
    ts = event.get("timestamp")
    if not ts:
        return False, "missing_timestamp"

    try:
        from datetime import timezone

        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif isinstance(ts, datetime):
            dt = ts
        else:
            return False, f"unparseable_timestamp: {ts}"

        # Allow 1 hour of clock skew into the future
        now = datetime.now(timezone.utc)
        from datetime import timedelta

        if dt > now + timedelta(hours=1):
            return False, f"future_timestamp: {dt.isoformat()}"

        return True, ""
    except Exception as e:
        return False, f"timestamp_parse_error: {e!s}"


def run_quality_checks(
    events: list[dict],
    schema: dict | None = None,
    known_users: set[str] | None = None,
    known_circles: set[str] | None = None,
) -> tuple[list[dict], list[dict], QualityCheckResult]:
    """Run all quality checks on a batch of events.

    Returns (passed_events, rejected_events, quality_result).
    """
    result = QualityCheckResult()
    passed = []
    rejected = []

    for event in events:
        result.total += 1
        reasons = []

        # Schema validation
        valid, reason = validate_schema(event, schema)
        if not valid:
            reasons.append(reason)

        # Completeness
        complete, missing = check_completeness(event)
        if not complete:
            reasons.append(f"missing_fields: {', '.join(missing)}")

        # Range checks
        in_range, violations = check_ranges(event)
        if not in_range:
            reasons.append(f"range_violations: {', '.join(violations)}")

        # Timestamp check
        ts_valid, ts_reason = check_timestamp(event)
        if not ts_valid:
            reasons.append(ts_reason)

        # Referential integrity (warnings only)
        ref_warnings = check_referential_integrity(event, known_users, known_circles)
        if ref_warnings:
            result.warnings += len(ref_warnings)
            result.warning_details.append({
                "event_id": event.get("event_id"),
                "warnings": ref_warnings,
            })

        if reasons:
            result.rejected += 1
            rejected.append({
                "event": event,
                "rejection_reasons": reasons,
            })
        else:
            result.passed += 1
            passed.append(event)

    return passed, rejected, result
