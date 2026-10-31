"""FastAPI application.

Run locally:   uvicorn gst_copilot.api.main:app --reload
In Docker:     see Dockerfile and docker-compose.yml
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gst_copilot import __version__
from gst_copilot.api.ask import router as ask_router
from gst_copilot.api.check_invoice import router as check_invoice_router
from gst_copilot.api.feedback import router as feedback_router
from gst_copilot.api.health import router as health_router
from gst_copilot.api.reconcile import router as reconcile_router
from gst_copilot.api.warmup import warm_up
from gst_copilot.config import get_settings
from gst_copilot.db.session import get_engine
from gst_copilot.logging import configure_logging, request_id_var

log = logging.getLogger("gst_copilot.request")


def create_app() -> FastAPI:
    """App factory: tests and production build the app the same way."""
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Start warm-up in the background: the server accepts /health at once, and
        # /ready turns green when the models are loaded.
        task = asyncio.create_task(warm_up()) if settings.warmup_enabled else None
        yield
        if task is not None and not task.done():
            task.cancel()
        await get_engine().dispose()

    app = FastAPI(title="GST Copilot", version=__version__, lifespan=lifespan)

    # CORS support for frontend clients, accounting portals and sidecars (ADR 0029)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(ask_router)
    app.include_router(feedback_router)
    app.include_router(reconcile_router)
    app.include_router(check_invoice_router)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = request_id_var.get()
        log.exception(
            "unhandled server exception",
            extra={"fields": {"request_id": request_id, "path": request.url.path}},
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred.", "request_id": request_id},
            headers={"x-request-id": request_id or ""},
        )

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

        # Standard production security headers and tracing ID (ADR 0029)
        response.headers["x-request-id"] = request_id
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "strict-origin-when-cross-origin"

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
