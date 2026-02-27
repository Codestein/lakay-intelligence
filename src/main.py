"""FastAPI application entry point for Lakay Intelligence."""

import asyncio
import contextlib
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.middleware.error_handler import global_exception_handler
from src.api.middleware.logging import StructuredLoggingMiddleware
from src.api.routes.behavior import router as behavior_router
from src.api.routes.circles import router as circles_router
from src.api.routes.compliance import router as compliance_router
from src.api.routes.compliance_reports import router as compliance_reports_router
from src.api.routes.dashboards import router as dashboards_router
from src.api.routes.experiments import router as experiments_router
from src.api.routes.features import router as features_router
from src.api.routes.fraud import router as fraud_router
from src.api.routes.health import router as health_router
from src.api.routes.pipeline import router as pipeline_router
from src.api.routes.serving import router as serving_router
from src.serving.server import get_model_server
from src.config import settings
from src.shared.logging import setup_logging

logger = structlog.get_logger()

# Track app start time for uptime calculation
APP_START_TIME: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown logic."""
    global APP_START_TIME
    APP_START_TIME = time.time()
    setup_logging(settings.log_level)

    logger.info(
        "lakay_starting",
        app_name=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
    )

    # Initialize database tables
    from src.db.database import init_db

    await init_db()

    # Start Kafka consumers as background tasks
    consumer_tasks: list[asyncio.Task] = []
    consumers = []
    # Initialize model server (best-effort, rules engine remains authoritative fallback)
    try:
        model_server = get_model_server()
        model_server.load_model(tracking_uri=settings.mlflow_tracking_uri)
    except Exception:
        logger.warning("model_server_startup_load_failed", exc_info=True)

    try:
        from src.consumers.circle_consumer import CircleConsumer
        from src.consumers.remittance_consumer import RemittanceConsumer
        from src.consumers.session_consumer import SessionConsumer
        from src.consumers.transaction_consumer import TransactionConsumer

        kafka_servers = settings.kafka_bootstrap_servers
        group_id = settings.kafka_consumer_group

        consumers = [
            CircleConsumer(bootstrap_servers=kafka_servers, group_id=group_id),
            TransactionConsumer(bootstrap_servers=kafka_servers, group_id=group_id),
            SessionConsumer(bootstrap_servers=kafka_servers, group_id=group_id),
            RemittanceConsumer(bootstrap_servers=kafka_servers, group_id=group_id),
        ]
        for consumer in consumers:
            task = asyncio.create_task(consumer.start())
            consumer_tasks.append(task)

        logger.info("kafka_consumers_started", count=len(consumers))
    except Exception:
        logger.warning("kafka_consumers_failed_to_start", exc_info=True)

    yield

    # Shutdown consumers
    for consumer in consumers:
        with contextlib.suppress(Exception):
            await consumer.stop()
    for task in consumer_tasks:
        task.cancel()
    logger.info("lakay_shutting_down")


app = FastAPI(
    title="Lakay Intelligence",
    description="AI/ML intelligence microservice for the Trebanx fintech platform",
    version=settings.app_version,
    lifespan=lifespan,
)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Structured logging middleware
app.add_middleware(StructuredLoggingMiddleware)

# Global exception handler
app.add_exception_handler(Exception, global_exception_handler)

# Register routers
app.include_router(health_router)
app.include_router(fraud_router)
app.include_router(circles_router)
app.include_router(behavior_router)
app.include_router(compliance_router)
app.include_router(serving_router)
app.include_router(pipeline_router)
app.include_router(experiments_router)
app.include_router(dashboards_router)
app.include_router(compliance_reports_router)
app.include_router(features_router)


def get_uptime() -> int:
    """Get application uptime in seconds."""
    if APP_START_TIME == 0.0:
        return 0
    return int(time.time() - APP_START_TIME)
