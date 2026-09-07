"""
Observability: structured logging, per-request context, optional Sentry,
and a lightweight in-process metrics snapshot.

Everything here is single-instance and dependency-light on purpose, matching
the rest of the scaling work. Sentry is the one optional external hook —
inert unless SENTRY_DSN is set.

Env:
  LOG_LEVEL   default INFO
  LOG_FORMAT  "json" (default in a non-TTY / on the server) or "plain"
  SENTRY_DSN  enables error reporting when present
  SENTRY_TRACES_SAMPLE_RATE  default 0.0
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from collections import Counter, defaultdict, deque
from contextvars import ContextVar
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

_STD_LOGRECORD_KEYS = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}


def current_request_id() -> str | None:
    return _request_id.get()


# --------------------------------------------------------------------------
# logging
# --------------------------------------------------------------------------
class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if getattr(record, "request_id", None):
            payload["request_id"] = record.request_id
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _STD_LOGRECORD_KEYS and key != "request_id":
                payload.setdefault(key, value)
        return json.dumps(payload, default=str)


class _PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = getattr(record, "request_id", None)
        prefix = f"[{rid[:8]}] " if rid else ""
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {record.name}: {prefix}{record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    fmt = os.getenv("LOG_FORMAT", "").lower()
    if not fmt:
        fmt = "plain" if sys.stderr.isatty() else "json"

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter() if fmt == "json" else _PlainFormatter())
    handler.addFilter(_RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # uvicorn brings its own handlers; let them propagate to ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# --------------------------------------------------------------------------
# sentry (optional)
# --------------------------------------------------------------------------
def init_sentry() -> bool:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        logging.getLogger("paysentinel").warning("SENTRY_DSN set but sentry-sdk is not installed")
        return False

    sentry_sdk.init(
        dsn=dsn,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0") or 0),
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
    )
    return True


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
class _Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started = time.time()
        self.requests: Counter = Counter()          # "METHOD /route/{id}" -> count
        self.statuses: Counter = Counter()          # status code -> count
        self.errors = 0                             # 5xx count
        self.latency_ms: dict[str, deque] = defaultdict(lambda: deque(maxlen=256))
        self.decisions: Counter = Counter()         # decision label -> count

    def record_request(self, method: str, route: str, status: int, ms: float) -> None:
        with self._lock:
            self.requests[f"{method} {route}"] += 1
            self.statuses[str(status)] += 1
            if status >= 500:
                self.errors += 1
            self.latency_ms[route].append(ms)

    def record_decision(self, decision: str) -> None:
        with self._lock:
            self.decisions[decision] += 1

    def reset(self) -> None:
        with self._lock:
            self.__init__()

    def snapshot(self) -> dict:
        with self._lock:
            def pct(samples: deque, p: float) -> float:
                if not samples:
                    return 0.0
                ordered = sorted(samples)
                return round(ordered[min(len(ordered) - 1, int(p * len(ordered)))], 1)

            return {
                "uptime_seconds": round(time.time() - self.started, 1),
                "requests_total": sum(self.requests.values()),
                "requests_by_route": dict(self.requests.most_common()),
                "responses_by_status": dict(sorted(self.statuses.items())),
                "server_errors_total": self.errors,
                "latency_ms_by_route": {
                    route: {"p50": pct(s, 0.50), "p95": pct(s, 0.95), "samples": len(s)}
                    for route, s in sorted(self.latency_ms.items())
                },
                "decisions": dict(self.decisions.most_common()),
            }


metrics = _Metrics()


# --------------------------------------------------------------------------
# middleware
# --------------------------------------------------------------------------
class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns/propagates a request id, times the request, logs one line per
    request, records metrics, and echoes X-Request-ID on the response."""

    _log = logging.getLogger("paysentinel.request")

    async def dispatch(self, request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = _request_id.set(rid)
        start = time.perf_counter()
        status = 500  # stays 500 if call_next raises before returning a response
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            route = getattr(request.scope.get("route"), "path", request.url.path)
            self._log.info(
                "%s %s -> %s (%.1fms)",
                request.method, route, status, elapsed_ms,
                extra={"http_method": request.method, "route": route,
                       "status": status, "duration_ms": round(elapsed_ms, 1)},
            )
            metrics.record_request(request.method, route, status, elapsed_ms)
            _request_id.reset(token)
