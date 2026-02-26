"""Verify end-to-end event flow: produce to Kafka → consume → persist to Postgres."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import asyncpg
from aiokafka import AIOKafkaProducer

KAFKA_BOOTSTRAP = "kafka:29092"
DB_DSN = "postgresql://lakay:lakay_dev@postgres:5432/lakay"

TOPICS = [
    "trebanx.circle.events",
    "trebanx.transaction.events",
    "trebanx.user.events",
    "trebanx.remittance.events",
]

EVENT_TYPES = [
    "circle-created",
    "transaction-initiated",
    "login-attempt",
    "remittance-initiated",
]


def make_test_event(event_type: str) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "event_version": "1.0",
        "timestamp": datetime.now(UTC).isoformat(),
        "source_service": "verify-script",
        "correlation_id": str(uuid.uuid4()),
        "payload": {"_test": True, "event_type": event_type},
    }


async def main() -> None:
    # Produce one event to each topic
    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
    )
    await producer.start()

    sent_ids: list[str] = []
    try:
        for topic, event_type in zip(TOPICS, EVENT_TYPES, strict=True):
            event = make_test_event(event_type)
            sent_ids.append(event["event_id"])
            await producer.send_and_wait(topic, event)
            print(f"  Produced {event_type} -> {topic}  (id={event['event_id'][:8]}...)")
    finally:
        await producer.stop()

    # Wait for consumers to process
    print("\n  Waiting 5s for consumers to process...")
    await asyncio.sleep(5)

    # Query Postgres for the events
    conn = await asyncpg.connect(DB_DSN)
    try:
        rows = await conn.fetch(
            "SELECT event_id, event_type FROM raw_events WHERE event_id = ANY($1::text[])",
            sent_ids,
        )
        found_ids = {row["event_id"] for row in rows}

        print()
        all_ok = True
        for eid, etype in zip(sent_ids, EVENT_TYPES, strict=True):
            ok = eid in found_ids
            status = "PASS" if ok else "FAIL"
            print(f"  [{status}] {etype}: {'persisted' if ok else 'NOT FOUND'}")
            if not ok:
                all_ok = False

        total = await conn.fetchval("SELECT COUNT(*) FROM raw_events")
        print(f"\n  Total events in raw_events: {total}")

        if all_ok:
            print("\n  All events flowed from Kafka to Postgres!")
        else:
            print("\n  Some events did not arrive. Check consumer logs.")
            raise SystemExit(1)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
