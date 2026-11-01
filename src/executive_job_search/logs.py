"""Structured JSON logging with credential redaction."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

_REDACT = re.compile(
    r"(?i)(x-api-key|api[_-]?key|authorization|password|secret|bearer)(['\"]?\s*[:=]?\s*['\"]?)([^\s,'\";}]{4,})"
)


def redact(value: object) -> str:
    """Mask credential-looking values in free text."""
    return _REDACT.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", str(value))


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        ctx = getattr(record, "ctx", None)
        if isinstance(ctx, dict):
            for k, v in ctx.items():
                payload[k] = redact(v) if isinstance(v, str) else v
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger("executive_job_search")
    root.setLevel(level.upper())
    if not any(getattr(h, "_ejs", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(RedactingJsonFormatter())
        handler._ejs = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"executive_job_search.{name}")
