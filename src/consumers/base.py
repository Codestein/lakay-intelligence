"""Base Kafka consumer with schema validation, routing, and DB persistence."""

import json
from collections.abc import Callable
from typing import Any

import structlog
from aiokafka import AIOKafkaConsumer
from sqlalchemy.exc import IntegrityError

from src.db.database import async_session_factory
from src.db.models import RawEvent

logger = structlog.get_logger()


class BaseConsumer:
    def __init__(
        self,
        topics: list[str],
        bootstrap_servers: str,
        group_id: str,
        handlers: dict[str, Callable] | None = None,
    ):
        self.topics = topics
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.handlers: dict[str, Callable] = handlers or {}
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False

    def register_handler(self, event_type: str, handler: Callable) -> None:
        self.handlers[event_type] = handler

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            *self.topics,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="earliest",
            enable_auto_commit=True,
        )
        await self._consumer.start()
        self._running = True
        logger.info("consumer_started", topics=self.topics, group_id=self.group_id)
        try:
            async for msg in self._consumer:
                await self._process_message(msg)
        finally:
            await self._consumer.stop()

    async def _process_message(self, msg: Any) -> None:
        try:
            event = msg.value
            event_type = event.get("event_type", "unknown")
            event_id = event.get("event_id")

            # Route to domain handler
            handler = self.handlers.get(event_type)
            if handler:
                await handler(event)
            else:
                logger.warning("no_handler_for_event", event_type=event_type)

            # Persist to raw_events table
            if event_id:
                await self._persist_event(event_id, event_type, event)
        except Exception:
            logger.exception("message_processing_error", topic=msg.topic, offset=msg.offset)

    async def _persist_event(self, event_id: str, event_type: str, event: dict) -> None:
        try:
            async with async_session_factory() as session:
                row = RawEvent(
                    event_id=event_id,
                    event_type=event_type,
                    payload=event,
                    processed=True,
                )
                session.add(row)
                await session.commit()
        except IntegrityError:
            # Duplicate event_id — already persisted, idempotent skip
            logger.debug("duplicate_event_skipped", event_id=event_id)
        except Exception:
            logger.exception("event_persist_error", event_id=event_id)

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            logger.info("consumer_stopped", topics=self.topics)
