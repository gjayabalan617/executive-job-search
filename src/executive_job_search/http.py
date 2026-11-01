"""Read-only HTTP client: bounded retries, exponential backoff, Retry-After, timeouts.

The specification names httpx; it was not installable in the build sandbox, so this thin
wrapper sits on `requests`. All provider code depends only on HttpClient, so swapping the
transport is a one-file change.
"""
from __future__ import annotations

import random
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

import requests

from .logs import get_logger, redact

log = get_logger("http")

RETRY_STATUS = {429, 500, 502, 503, 504, 529}


class SourceError(Exception):
    """A source could not be read. `kind` distinguishes retryable from permanent failures."""

    def __init__(self, kind: str, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.kind = kind
        self.status = status


def parse_retry_after(value: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (dt - (now or datetime.now(timezone.utc))).total_seconds())


class HttpClient:
    def __init__(
        self,
        session: Any = None,
        timeout: float = 20.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_cap: float = 30.0,
        retry_after_cap: float = 120.0,
        sleep: Callable[[float], None] = time.sleep,
        user_agent: str = "executive-job-search/0.1 (read-only)",
    ):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.retry_after_cap = retry_after_cap
        self.sleep = sleep
        self.user_agent = user_agent

    def get_json(self, url: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        data, _ = self.request_json("GET", url, params=params)
        return data

    def request_json(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Any] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> tuple[Any, Mapping[str, str]]:
        merged = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if headers:
            merged.update(headers)
        attempt = 0
        while True:
            kind, status, retry_after, detail = "network", None, None, ""
            try:
                resp = self.session.request(
                    method, url, params=params, json=json_body, headers=merged, timeout=self.timeout
                )
            except requests.Timeout as exc:
                kind, detail = "timeout", f"timeout: {exc}"
            except requests.RequestException as exc:
                kind, detail = "network", f"network error: {exc}"
            else:
                status = resp.status_code
                if status == 200:
                    try:
                        return resp.json(), resp.headers
                    except ValueError as exc:
                        raise SourceError("invalid_json", f"invalid JSON from {url}: {exc}", status)
                if status in (404, 410):
                    raise SourceError("not_found", f"HTTP {status} for {url}", status)
                if status in RETRY_STATUS:
                    kind = "rate_limited" if status == 429 else "server_error"
                    detail = f"HTTP {status}"
                    retry_after = parse_retry_after(resp.headers.get("Retry-After"))
                else:
                    raise SourceError("http_error", f"HTTP {status} for {url}", status)

            if attempt >= self.max_retries:
                raise SourceError(kind, f"{detail} for {url} after {attempt + 1} attempts", status)
            delay = min(self.backoff_cap, self.backoff_base * (2**attempt))
            delay *= 1 + random.random() * 0.1
            if retry_after is not None:
                delay = max(delay, min(retry_after, self.retry_after_cap))
            log.warning(
                redact(f"retrying {method} {url}: {detail}"),
                extra={"ctx": {"attempt": attempt + 1, "delay_s": round(delay, 2)}},
            )
            self.sleep(delay)
            attempt += 1
