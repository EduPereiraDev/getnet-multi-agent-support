"""Structured JSON logging with trace spans (one log line per span)."""

import json
import logging
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger("getnet.agents")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False


def new_trace_id() -> str:
    return uuid.uuid4().hex


def log_event(msg: str, **fields: Any) -> None:
    logger.info(msg, extra={"fields": fields})


@contextmanager
def span(name: str, trace_id: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """Times a unit of work and logs it. Callers may add fields to the yielded dict."""
    extra: dict[str, Any] = {}
    start = time.perf_counter()
    status = "ok"
    try:
        yield extra
    except Exception as exc:
        status = "error"
        extra["error"] = repr(exc)
        raise
    finally:
        log_event(
            name,
            span=name,
            trace_id=trace_id,
            status=status,
            latency_ms=int((time.perf_counter() - start) * 1000),
            **fields,
            **extra,
        )
