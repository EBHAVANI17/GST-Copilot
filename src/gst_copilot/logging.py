"""Structured JSON logging.

In production, logs go to a log system (Loki, CloudWatch, Datadog...) that
searches by field. One JSON object per line, with a request_id on every
line, lets you pull up everything that happened during one request.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# Holds the current request's ID; set by the middleware in api/main.py.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        # Anything passed as logger.info("...", extra={"fields": {...}}) is included.
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Uvicorn's access log duplicates our request log; keep only its errors.
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False
