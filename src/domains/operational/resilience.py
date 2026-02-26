"""Chaos/resilience testing. Stub for later phases."""

import structlog

logger = structlog.get_logger()


class ResilienceTester:
    """Tools for testing system resilience and failure modes."""

    async def simulate_kafka_delay(self, delay_ms: int = 5000) -> dict:
        logger.info("resilience_test", test_type="kafka_delay", delay_ms=delay_ms)
        return {"test": "kafka_delay", "status": "stub"}

    async def simulate_db_failure(self) -> dict:
        logger.info("resilience_test", test_type="db_failure")
        return {"test": "db_failure", "status": "stub"}
