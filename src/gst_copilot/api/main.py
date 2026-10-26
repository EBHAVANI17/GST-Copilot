"""FastAPI application.

Run locally:   uvicorn gst_copilot.api.main:app --reload
In Docker:     see Dockerfile and docker-compose.yml
"""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from gst_copilot import __version__
from gst_copilot.api.ask import router as ask_router
from gst_copilot.api.feedback import router as feedback_router
from gst_copilot.api.health import router as health_router
from gst_copilot.config import get_settings
from gst_copilot.logging import configure_logging, request_id_var

log = logging.getLogger("gst_copilot.request")


def create_app() -> FastAPI:
    """App factory: tests and production build the app the same way."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="GST Copilot", version=__version__)
    app.include_router(health_router)
    app.include_router(ask_router)
    app.include_router(feedback_router)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Reuse the caller's request ID if it sent one (e.g. from a gateway),
        # otherwise make a new one. It goes into every log line and back to the caller.
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            request_id_var.reset(token)
        response.headers["x-request-id"] = request_id
        log.info(
            "request",
            extra={
                "fields": {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                }
            },
        )
        return response

    log.info("app started", extra={"fields": {"env": settings.app_env, "version": __version__}})
    return app


app = create_app()
