"""Health and readiness endpoints."""

from fastapi import APIRouter

from src.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    from src.main import get_uptime

    return {
        "status": "healthy",
        "version": settings.app_version,
        "uptime_seconds": get_uptime(),
    }


@router.get("/ready")
async def ready() -> dict:
    db_ok = False
    kafka_ok = False
    redis_ok = False

    # Check database
    try:
        from src.db.database import check_db

        db_ok = await check_db()
    except Exception:
        pass

    # Check Redis
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        redis_ok = True
        await r.aclose()
    except Exception:
        pass

    all_ready = db_ok and redis_ok
    status_code = 200 if all_ready else 503
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_ready else "degraded",
            "kafka": kafka_ok,
            "database": db_ok,
            "redis": redis_ok,
        },
    )
