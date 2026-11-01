"""LinkedIn source policy.

LinkedIn offers no public general job-search API. This module therefore implements NO scraping, guest
endpoints, CAPTCHA handling, cookie reuse or authentication workarounds. The only supported integration
is an *authorised feed*: a JSON or JSON-Lines file produced by a provider the operator is licensed to use.
Every record must carry an actual individual LinkedIn posting URL (https://www.linkedin.com/jobs/view/<id>),
otherwise it is rejected. With no provider configured the pipeline reports SOURCE_UNAVAILABLE and never
falls back to employer-direct results.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import Settings
from ..enrich import finalize_job
from ..models import Job
from ..urls import canonical_linkedin_url
from .base import ACTIVE, INACTIVE, UNVERIFIED
from .greenhouse import parse_dt

REQUIRED = ("provider_job_id", "title", "company", "linkedin_url", "description")


class AuthorizedFeedProvider:
    name = "authorized_feed"

    def __init__(self, path: Path):
        self.path = Path(path)
        self.rejected: list[str] = []

    def fetch(self) -> list[Job]:
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        if raw.startswith("["):
            records = json.loads(raw)
        else:
            records = [json.loads(line) for line in raw.splitlines() if line.strip()]
        jobs: list[Job] = []
        self.rejected = []
        for r in records:
            missing = [k for k in REQUIRED if not r.get(k)]
            li = canonical_linkedin_url(r.get("linkedin_url", ""))
            if missing or not li:
                self.rejected.append(f"{r.get('provider_job_id', '?')}: missing {missing or 'valid individual LinkedIn posting URL'}")
                continue
            jobs.append(
                finalize_job(
                    Job(
                        provider=self.name,
                        source="linkedin",
                        provider_job_id=str(r["provider_job_id"]),
                        company=r["company"],
                        title=r["title"],
                        location=r.get("location"),
                        all_locations=[r["location"]] if r.get("location") else [],
                        workplace_type=str(r.get("workplace_type") or "unknown").lower(),
                        description=r["description"],
                        employment_type=r.get("employment_type"),
                        salary_text=r.get("salary_text"),
                        posted_at=parse_dt(r.get("posted_at")),
                        updated_at=parse_dt(r.get("updated_at")),
                        posting_url=li[0],
                        linkedin_url=li[0],
                        application_url=r.get("application_url") or li[0],
                        source_active_hint=r.get("active") if isinstance(r.get("active"), bool) else None,
                    )
                )
            )
        return jobs

    def verify_active(self, job: Job) -> tuple[str, str]:
        if job.source_active_hint is True:
            return ACTIVE, "feed asserts the posting is active"
        if job.source_active_hint is False:
            return INACTIVE, "feed asserts the posting is not active"
        return UNVERIFIED, "feed supplied no active flag; liveness cannot be verified without scraping"


def get_linkedin_provider(settings: Settings) -> Optional[AuthorizedFeedProvider]:
    """Return a configured authorised provider, or None (=> SOURCE_UNAVAILABLE)."""
    if settings.linkedin_provider == "authorized_feed" and settings.linkedin_feed_path:
        if Path(settings.linkedin_feed_path).exists():
            return AuthorizedFeedProvider(settings.linkedin_feed_path)
    return None
