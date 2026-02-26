"""Load and validate events against trebanx-contracts JSON schemas."""

import json
from functools import lru_cache
from pathlib import Path

import jsonschema
import structlog

logger = structlog.get_logger()

CATEGORY_MAP: dict[str, str] = {
    "circle-": "circle",
    "transaction-": "transaction",
    "user-": "user",
    "login-": "user",
    "session-": "user",
    "device-": "user",
    "remittance-": "remittance",
    "exchange-": "remittance",
    "security-": "security",
    "account-": "security",
    "step-up-": "security",
}


@lru_cache(maxsize=64)
def load_schema(event_type: str, contracts_path: str = "../trebanx-contracts/schemas") -> dict:
    """Load a JSON Schema for the given event type."""
    category = None
    for prefix, cat in CATEGORY_MAP.items():
        if event_type.startswith(prefix):
            category = cat
            break

    if not category:
        raise ValueError(f"Unknown event type: {event_type}")

    schema_path = Path(contracts_path) / "events" / category / f"{event_type}.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")

    with open(schema_path) as f:
        return json.load(f)


def validate_event(event: dict, contracts_path: str = "../trebanx-contracts/schemas") -> bool:
    """Validate an event against its JSON Schema. Returns True if valid."""
    event_type = event.get("event_type")
    if not event_type:
        raise ValueError("Event missing event_type field")

    schema = load_schema(event_type, contracts_path)
    jsonschema.validate(instance=event, schema=schema)
    return True
