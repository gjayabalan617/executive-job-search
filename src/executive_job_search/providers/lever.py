"""Lever Postings API (public, unauthenticated GET only).

  GET https://api.lever.co/v0/postings/{site}?mode=json&skip=N&limit=M       (EU: api.eu.lever.co)
  GET https://api.lever.co/v0/postings/{site}/{id}?mode=json                 single posting (liveness check)

The official README https://github.com/lever/postings-api could NOT be fetched from the build sandbox; field
names were confirmed only from secondary sources (see README). The apply POST endpoint is never used.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..enrich import finalize_job
from ..http import HttpClient, SourceError
from ..models import BoardConfig, Job, SourceStatus
from ..text import html_to_text
from .base import ACTIVE, INACTIVE, UNVERIFIED

HOSTS = {"global": "https://api.lever.co/v0/postings", "eu": "https://api.eu.lever.co/v0/postings"}
_WT = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite", "on site": "onsite"}


def _ms(value: Any) -> Optional[datetime]:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    return None


class LeverProvider:
    name = "lever"

    def __init__(self, http: HttpClient, page_size: int = 100, max_pages: int = 50):
        self.http = http
        self.page_size = page_size
        self.max_pages = max_pages

    def _base(self, board: BoardConfig) -> str:
        return f"{HOSTS.get(board.region, HOSTS['global'])}/{board.token}"

    def validate_board(self, board: BoardConfig) -> SourceStatus:
        try:
            self.http.get_json(self._base(board), params={"mode": "json", "limit": 1})
        except SourceError as exc:
            detail = "site not found or not public" if exc.kind == "not_found" else f"{exc.kind}: {exc}"
            return SourceStatus(source=board.key, status="inaccessible", detail=detail)
        return SourceStatus(source=board.key, status="ok", detail="site reachable", company=board.company)

    def fetch_jobs(self, board: BoardConfig) -> list[Job]:
        out: list[Job] = []
        seen_ids: set[str] = set()
        skip = 0
        for _ in range(self.max_pages):
            page = self.http.get_json(
                self._base(board), params={"mode": "json", "skip": skip, "limit": self.page_size}
            )
            if not isinstance(page, list):
                raise SourceError("invalid_json", f"unexpected Lever payload for {board.token}")
            fresh = [p for p in page if str(p.get("id")) not in seen_ids]
            if not fresh:
                break  # server ignored skip, or no more data
            for p in fresh:
                seen_ids.add(str(p.get("id")))
                out.append(self.normalize(p, board))
            if len(page) < self.page_size:
                break
            skip += self.page_size
        else:
            # Hit the page cap with data still flowing: do not pretend the listing is complete.
            raise SourceError("truncated", f"{board.token}: exceeded {self.max_pages} pages; listing incomplete")
        return out

    def normalize(self, p: dict, board: BoardConfig) -> Job:
        cats = p.get("categories") or {}
        locs = [x for x in (cats.get("allLocations") or []) if x]
        primary = cats.get("location")
        if primary and primary not in locs:
            locs.insert(0, primary)
        parts = [p.get("descriptionPlain") or html_to_text(p.get("description"))]
        for lst in p.get("lists") or []:
            parts.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content'))}")
        parts.append(p.get("additionalPlain") or html_to_text(p.get("additional")))
        description = "\n\n".join(x.strip() for x in parts if x and x.strip())
        sal: dict = {}
        sr = p.get("salaryRange") or {}
        if sr.get("min") is not None and sr.get("max") is not None:
            cur = sr.get("currency") or "USD"
            sal = {
                "salary_min": float(sr["min"]), "salary_max": float(sr["max"]), "salary_currency": cur,
                "salary_interval": sr.get("interval"),
                "salary_text": p.get("salaryDescriptionPlain") or f"{cur} {sr['min']:,} - {sr['max']:,}",
            }
        wt = _WT.get(str(p.get("workplaceType") or "").lower(), "unknown")
        job = Job(
            provider=self.name,
            source="employer_direct",
            provider_job_id=str(p.get("id")),
            board=board.token,
            company=board.company or board.token,
            title=(p.get("text") or "").strip(),
            location=primary or (locs[0] if locs else None),
            all_locations=locs,
            workplace_type=wt,
            country_code=p.get("country"),
            departments=[x for x in (cats.get("department"), cats.get("team")) if x],
            description=description,
            partial_description=not bool(description),
            employment_type=cats.get("commitment"),
            posted_at=_ms(p.get("createdAt")),
            updated_at=None,  # the Postings API exposes no updated timestamp
            posting_url=p.get("hostedUrl") or "",
            application_url=p.get("applyUrl") or p.get("hostedUrl"),
            **sal,
        )
        return finalize_job(job)

    def verify_active(self, job: Job) -> tuple[str, str]:
        region = "eu" if "api.eu.lever.co" in (job.application_url or "") else "global"
        base = f"{HOSTS[region]}/{job.board}/{job.provider_job_id}"
        try:
            self.http.get_json(base, params={"mode": "json"})
        except SourceError as exc:
            if exc.kind == "not_found":
                return INACTIVE, "single-posting endpoint returned 404/410"
            return UNVERIFIED, f"{exc.kind}: {exc}"
        return ACTIVE, "single-posting endpoint returned 200"
