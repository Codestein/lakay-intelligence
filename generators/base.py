"""Base generator class with seeded RNG, schema validation, and output handling."""

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np


class BaseGenerator:
    def __init__(self, config: dict[str, Any], seed: int = 42):
        self.config = config
        self.seed = seed
        random.seed(seed)
        np.random.seed(seed)
        self._event_counter = 0

    def _uuid(self) -> str:
        """Generate a deterministic UUID based on seed and counter."""
        self._event_counter += 1
        return str(uuid.UUID(int=random.getrandbits(128), version=4))

    def _envelope(
        self,
        event_type: str,
        source_service: str,
        payload: dict[str, Any],
        timestamp: datetime | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Wrap a payload in the standard event envelope."""
        return {
            "event_id": self._uuid(),
            "event_type": event_type,
            "event_version": "1.0",
            "timestamp": (timestamp or datetime.now(UTC)).isoformat(),
            "source_service": source_service,
            "correlation_id": correlation_id or self._uuid(),
            "payload": payload,
        }

    def _random_datetime(self, start: datetime, end: datetime) -> datetime:
        """Generate a random datetime between start and end."""
        delta = end - start
        random_seconds = random.randint(0, max(1, int(delta.total_seconds())))
        return start + timedelta(seconds=random_seconds)

    def _decimal_str(self, value: float) -> str:
        """Format a float as a decimal string with 2 decimal places."""
        return f"{value:.2f}"

    def _weighted_choice(self, options: dict[str, float]) -> str:
        """Choose from weighted options."""
        items = list(options.keys())
        weights = list(options.values())
        return random.choices(items, weights=weights, k=1)[0]
