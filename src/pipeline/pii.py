"""PII tokenization: deterministic, reversible tokenization for data lake privacy."""

import base64
import hashlib
import hmac
import os
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.pipeline.models import PIITokenMapping

logger = structlog.get_logger()

# Secret key for HMAC-based tokenization (deterministic + keyed)
_TOKEN_SECRET = os.environ.get("PII_TOKEN_SECRET", "lakay-pii-token-secret-dev-only")

# Simple XOR-based "encryption" for dev; production should use Fernet or AES-GCM
_ENCRYPTION_KEY = os.environ.get("PII_ENCRYPTION_KEY", "lakay-encryption-key-dev-only")

# ---------------------------------------------------------------------------
# PII field registry: which fields are PII per event type
# ---------------------------------------------------------------------------

# Global PII fields that apply to all events
GLOBAL_PII_FIELDS = {
    "user_id",
    "sender_id",
    "organizer_id",
    "recipient_id",
}

# Event-type-specific PII fields (payload-level)
EVENT_PII_FIELDS: dict[str, set[str]] = {
    "transaction-initiated": {
        "user_id", "ip_address", "device_id", "recipient_id",
        "geo_location.latitude", "geo_location.longitude",
    },
    "transaction-completed": {
        "user_id", "ip_address", "device_id", "recipient_id",
    },
    "transaction-failed": {
        "user_id", "ip_address", "device_id",
    },
    "transaction-flagged": {
        "user_id", "ip_address", "device_id",
    },
    "session-started": {
        "user_id", "ip_address", "device_id",
        "geo_location.latitude", "geo_location.longitude",
    },
    "session-ended": {
        "user_id", "ip_address", "device_id",
    },
    "circle-created": {
        "organizer_id",
    },
    "circle-member-joined": {
        "user_id", "organizer_id",
    },
    "circle-member-dropped": {
        "user_id",
    },
    "remittance-initiated": {
        "sender_id", "recipient_name", "recipient_phone",
    },
    "remittance-completed": {
        "sender_id", "recipient_name", "recipient_phone",
    },
    "remittance-failed": {
        "sender_id",
    },
}

# Fields that are always PII regardless of event type
ALL_PII_FIELDS = {
    "user_id", "sender_id", "organizer_id", "recipient_id",
    "email", "phone", "ip_address", "device_id",
    "full_name", "recipient_name", "recipient_phone",
    "address", "government_id",
    "geo_location.latitude", "geo_location.longitude",
}


def _compute_token(field_name: str, value: str) -> str:
    """Compute a deterministic token for a field value using HMAC-SHA256."""
    message = f"{field_name}:{value}".encode("utf-8")
    digest = hmac.new(_TOKEN_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"tok_{field_name}_{digest[:24]}"


def _encrypt_value(value: str) -> str:
    """Simple base64 encoding for dev; replace with Fernet in production."""
    key_bytes = hashlib.sha256(_ENCRYPTION_KEY.encode()).digest()
    value_bytes = value.encode("utf-8")
    # XOR with repeating key for dev (NOT production-grade)
    encrypted = bytes(v ^ key_bytes[i % len(key_bytes)] for i, v in enumerate(value_bytes))
    return base64.urlsafe_b64encode(encrypted).decode("utf-8")


def _decrypt_value(encrypted: str) -> str:
    """Reverse the encryption."""
    key_bytes = hashlib.sha256(_ENCRYPTION_KEY.encode()).digest()
    encrypted_bytes = base64.urlsafe_b64decode(encrypted.encode("utf-8"))
    decrypted = bytes(v ^ key_bytes[i % len(key_bytes)] for i, v in enumerate(encrypted_bytes))
    return decrypted.decode("utf-8")


class PIITokenizer:
    """Deterministic, reversible PII tokenization."""

    def __init__(self):
        # In-memory cache of known tokens (field_name:value → token)
        self._cache: dict[str, str] = {}

    def tokenize(self, field_name: str, value: Any) -> str:
        """Return a deterministic token for a PII value."""
        str_value = str(value)
        cache_key = f"{field_name}:{str_value}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        token = _compute_token(field_name, str_value)
        self._cache[cache_key] = token
        return token

    def get_encrypted_value(self, value: Any) -> str:
        """Return an encrypted representation of the original value."""
        return _encrypt_value(str(value))

    def detokenize_encrypted(self, encrypted_value: str) -> str:
        """Decrypt an encrypted value back to the original."""
        return _decrypt_value(encrypted_value)

    def tokenize_event(self, event: dict, event_type: str | None = None) -> dict:
        """Tokenize all PII fields in an event dict.

        Returns a new dict with PII fields replaced by tokens.
        """
        result = dict(event)

        # Determine which fields to tokenize
        pii_fields = set(ALL_PII_FIELDS)
        if event_type and event_type in EVENT_PII_FIELDS:
            pii_fields = pii_fields | EVENT_PII_FIELDS[event_type]

        # Tokenize top-level fields
        for field in list(pii_fields):
            if "." not in field and field in result:
                val = result[field]
                if val is not None:
                    result[field] = self.tokenize(field, val)

        # Tokenize payload fields
        if "payload" in result and isinstance(result["payload"], dict):
            result["payload"] = dict(result["payload"])
            for field in pii_fields:
                if "." in field:
                    # Handle nested fields like geo_location.latitude
                    parts = field.split(".")
                    self._tokenize_nested(result["payload"], parts, field)
                elif field in result["payload"]:
                    val = result["payload"][field]
                    if val is not None:
                        result["payload"][field] = self.tokenize(field, val)

        return result

    def _tokenize_nested(self, obj: dict, parts: list[str], full_field: str) -> None:
        """Tokenize a nested field path."""
        if len(parts) == 1:
            if parts[0] in obj and obj[parts[0]] is not None:
                obj[parts[0]] = self.tokenize(full_field, obj[parts[0]])
        elif parts[0] in obj and isinstance(obj[parts[0]], dict):
            obj[parts[0]] = dict(obj[parts[0]])
            self._tokenize_nested(obj[parts[0]], parts[1:], full_field)


async def persist_token_mapping(
    session: AsyncSession,
    field_name: str,
    token: str,
    original_value: str,
) -> None:
    """Store a token→encrypted_value mapping in the database."""
    encrypted = _encrypt_value(original_value)
    stmt = (
        pg_insert(PIITokenMapping)
        .values(field_name=field_name, token=token, encrypted_value=encrypted)
        .on_conflict_do_nothing(index_elements=["token"])
    )
    await session.execute(stmt)
    await session.commit()


async def batch_persist_token_mappings(
    session: AsyncSession,
    mappings: list[tuple[str, str, str]],
) -> None:
    """Batch persist multiple (field_name, token, original_value) mappings."""
    if not mappings:
        return
    values = [
        {
            "field_name": field_name,
            "token": token,
            "encrypted_value": _encrypt_value(original_value),
        }
        for field_name, token, original_value in mappings
    ]
    stmt = pg_insert(PIITokenMapping).values(values).on_conflict_do_nothing(index_elements=["token"])
    await session.execute(stmt)
    await session.commit()


async def detokenize(session: AsyncSession, token: str) -> str | None:
    """Reverse a token back to the original value (access-controlled)."""
    result = await session.execute(
        select(PIITokenMapping).where(PIITokenMapping.token == token)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return _decrypt_value(row.encrypted_value)
