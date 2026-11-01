"""Shared test helpers. Every posting used by these tests is SYNTHETIC (see executive_job_search.fixtures_demo)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import requests

from executive_job_search.config import load_settings
from executive_job_search.fixtures_demo import DEMO_BOARDS_YAML, DEMO_LABEL, FixtureSession, _Resp
from executive_job_search.http import HttpClient
from executive_job_search.pipeline import Pipeline
from executive_job_search.store import Store

NOW = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)

GH_ONLY_YAML = """\
boards:
  - provider: greenhouse
    token: synthetic-gh
    company: Synthetic Health Co (SYNTHETIC)
"""
LEVER_ONLY_YAML = """\
boards:
  - provider: lever
    token: synthetic-lever
    company: Synthetic Advisory Group (SYNTHETIC)
"""

QUALIFYING_VP = "Vice President, Enterprise Architecture & Technology M&A"


def make_settings(tmp_path, boards_yaml: str = DEMO_BOARDS_YAML, **overrides):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "boards.yaml").write_text(boards_yaml, encoding="utf-8")
    base = dict(
        mode="employer_direct", data_dir=tmp_path / "data", seen_path=tmp_path / "seen_jobs.json",
        boards_file=tmp_path / "boards.yaml", notify_send_enabled=False, llm_enabled=False,
    )
    base.update(overrides)
    return load_settings({}, **base)


def make_pipeline(tmp_path, session: Any = None, boards_yaml: str = DEMO_BOARDS_YAML, sender=None, now: datetime = NOW, **overrides):
    s = make_settings(tmp_path, boards_yaml, **overrides)
    store = Store(s.db_path)
    session = session or FixtureSession(now)
    http = HttpClient(session=session, sleep=lambda _s: None, max_retries=s.http_max_retries)
    pipe = Pipeline(s, store, http=http, clock=lambda: now, label=DEMO_LABEL, sender=sender)
    return s, store, pipe, session


def row_by_title(store: Store, title: str) -> dict:
    rows = [r for r in store.list_jobs() if r["title"] == title]
    assert len(rows) == 1, f"expected exactly one stored job titled {title!r}, got {len(rows)}"
    return rows[0]


class Scripted:
    """Session double: `script` maps URL -> list of responses/exceptions consumed in order (last one repeats)."""

    def __init__(self, script: dict[str, list]):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[tuple[str, dict]] = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):  # noqa: A002
        self.calls.append((url, dict(params or {})))
        items = self.script.get(url)
        if items is None:
            return _Resp(404)
        item = items.pop(0) if len(items) > 1 else items[0]
        if isinstance(item, BaseException):
            raise item
        return item


def ok(data: Any, headers: Optional[dict] = None) -> _Resp:
    return _Resp(200, data, headers)


TIMEOUT = requests.Timeout("simulated timeout")

# Mirrors executive_job_search.providers.base.ACTIVE; imported so tests follow the code's vocabulary.
from executive_job_search.providers.base import ACTIVE as ACTIVE_STATUS  # noqa: E402,F401
