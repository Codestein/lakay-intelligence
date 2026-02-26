"""Kafka producer/consumer helpers."""

import json

import structlog
from aiokafka import AIOKafkaProducer

logger = structlog.get_logger()

TOPIC_MAP: dict[str, str] = {
    "circle": "trebanx.circle.events",
    "transaction": "trebanx.transaction.events",
    "user": "trebanx.user.events",
    "remittance": "trebanx.remittance.events",
    "security": "trebanx.security.events",
}


def event_type_to_topic(event_type: str) -> str:
    """Map an event type to its Kafka topic."""
    for prefix, topic in TOPIC_MAP.items():
        if event_type.startswith(prefix) or event_type.startswith(f"{prefix}-"):
            return topic
    # Fallback mapping for event types that don't match prefix directly
    prefixes = {
        "login-": "trebanx.user.events",
        "session-": "trebanx.user.events",
        "device-": "trebanx.user.events",
        "exchange-": "trebanx.remittance.events",
        "account-": "trebanx.security.events",
        "step-up-": "trebanx.security.events",
    }
    for prefix, topic in prefixes.items():
        if event_type.startswith(prefix):
            return topic
    raise ValueError(f"Cannot determine topic for event type: {event_type}")


async def create_producer(bootstrap_servers: str) -> AIOKafkaProducer:
    """Create and start a Kafka producer."""
    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
    )
    await producer.start()
    logger.info("kafka_producer_started", bootstrap_servers=bootstrap_servers)
    return producer


async def produce_event(producer: AIOKafkaProducer, event: dict) -> None:
    """Send an event to the appropriate Kafka topic."""
    event_type = event.get("event_type", "unknown")
    topic = event_type_to_topic(event_type)
    await producer.send_and_wait(topic, event)
    logger.debug("event_produced", topic=topic, event_type=event_type)
