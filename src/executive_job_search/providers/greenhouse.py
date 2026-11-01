"""Greenhouse Job Board API (public, unauthenticated GET only).

Endpoints used (read-only):
  GET https://boards-api.greenhouse.io/v1/boards/{token}               board info
  GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true   published jobs with descriptions
  GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}     single job (used to verify a posting is still live)

Schema notes. The official page https://developers.greenhouse.io/job-board.html could NOT be fetched from the
build sandbox; field names below were confirmed only from secondary sources (see README). Parsing is defensive:
absent fields become None rather than being guessed. The application POST endpoint is never used.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..enrich import finalize_job
from ..http import HttpClient, SourceError
from ..models import BoardConfig, Job, SourceStatus
from ..text import html_to_text
from .base import ACTIVE, INACTIVE, UNVERIFIED

BASE = "https://boards-api.greenhouse.io/v1/boards"


def parse_dt(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class GreenhouseProvider:
    name = "greenhouse"

    def __init__(self, http: HttpClient):
        self.http = http

    def validate_board(self, board: BoardConfig) -> SourceStatus:
        key = board.key
        try:
            info = self.http.get_json(f"{BASE}/{board.token}")
        except SourceError as exc:
            detail = "board not found or not public" if exc.kind == "not_found" else f"{exc.kind}: {exc}"
            return SourceStatus(source=key, status="inaccessible", detail=detail)
        name = info.get("name") if isinstance(info, dict) else None
        return SourceStatus(source=key, status="ok", detail="board reachable", company=name)

    def fetch_jobs(self, board: BoardConfig) -> list[Job]:
        data = self.http.get_json(f"{BASE}/{board.token}/jobs", params={"content": "true"})
        if not isinstance(data, dict) or "jobs" not in data:
            raise SourceError("invalid_json", f"unexpected Greenhouse payload for {board.token}")
        total = (data.get("meta") or {}).get("total")
        if isinstance(total, int) and len(data["jobs"]) < total:
            # Never present a short listing as a complete one.
            raise SourceError("truncated", f"{board.token}: received {len(data['jobs'])} of {total} jobs; listing incomplete")
        company = board.company or board.token
        return [self.normalize(j, board.token, company) for j in data["jobs"]]

    def normalize(self, j: dict, token: str, company: str) -> Job:
        loc = (j.get("location") or {}).get("name")
        offices = j.get("offices") or []
        all_locs = [loc] if loc else []
        for o in offices:
            for cand in (o.get("location"), o.get("name")):
                if cand and cand not in all_locs:
                    all_locs.append(cand)
        raw = j.get("content") or ""
        text = html_to_text(raw)
        salary: dict = {}
        ranges = j.get("pay_input_ranges") or []
        if ranges:
            r = ranges[0]
            lo, hi = r.get("min_cents"), r.get("max_cents")
            cur = r.get("currency_type") or "USD"
            if lo is not None and hi is not None:
                salary = {
                    "salary_min": lo / 100, "salary_max": hi / 100, "salary_currency": cur,
                    "salary_text": f"{cur} {lo/100:,.0f} - {hi/100:,.0f}",
                }
        url = j.get("absolute_url") or ""
        job = Job(
            provider=self.name,
            source="employer_direct",
            provider_job_id=str(j.get("id")),
            board=token,
            company=company,
            title=(j.get("title") or "").strip(),
            location=loc,
            all_locations=all_locs,
            workplace_type="unknown",  # the Job Board API has no structured workplace type
            departments=[d.get("name") for d in (j.get("departments") or []) if d.get("name")],
            description=text,
            partial_description=not bool(raw),
            posted_at=parse_dt(j.get("first_published")),  # never updated_at
            updated_at=parse_dt(j.get("updated_at")),
            posting_url=url,
            application_url=url,
            **salary,
        )
        return finalize_job(job)

    def verify_active(self, job: Job) -> tuple[str, str]:
        try:
            self.http.get_json(f"{BASE}/{job.board}/jobs/{job.provider_job_id}")
        except SourceError as exc:
            if exc.kind == "not_found":
                return INACTIVE, "single-job endpoint returned 404/410"
            return UNVERIFIED, f"{exc.kind}: {exc}"
        return ACTIVE, "single-job endpoint returned 200"
