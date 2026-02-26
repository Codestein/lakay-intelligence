"""Global exception handling."""

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

logger = structlog.get_logger()


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")

    if isinstance(exc, ValueError):
        logger.warning("bad_request", request_id=request_id, error=str(exc))
        return JSONResponse(
            status_code=400,
            content={"error": "bad_request", "message": str(exc), "request_id": request_id},
        )

    if isinstance(exc, PermissionError):
        logger.warning("forbidden", request_id=request_id, error=str(exc))
        return JSONResponse(
            status_code=403,
            content={"error": "forbidden", "message": str(exc), "request_id": request_id},
        )

    if isinstance(exc, (KeyError, LookupError)):
        logger.warning("not_found", request_id=request_id, error=str(exc))
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": str(exc), "request_id": request_id},
        )

    logger.exception("unhandled_exception", request_id=request_id, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred",
            "request_id": request_id,
        },
    )
