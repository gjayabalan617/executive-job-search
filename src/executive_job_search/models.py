"""Core data models."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .urls import canonical_employer_url, canonical_linkedin_url


class State(str, enum.Enum):
    DISCOVERED = "discovered"
    PENDING_INSPECTION = "pending_inspection"
    INSPECTED = "inspected"
    EXCLUDED = "excluded"
    QUALIFIED = "qualified"
    NOTIFICATION_PENDING = "notification_pending"
    NOTIFIED = "notified"
    RETRYABLE_FAILURE = "retryable_failure"


# States that count as "sufficiently inspected" (eligible for the seen-jobs export).
INSPECTED_STATES = {
    State.INSPECTED.value,
    State.EXCLUDED.value,
    State.QUALIFIED.value,
    State.NOTIFICATION_PENDING.value,
    State.NOTIFIED.value,
}
RETRY_STATES = {State.PENDING_INSPECTION.value, State.RETRYABLE_FAILURE.value, State.DISCOVERED.value}
QUALIFYING_STATES = {State.QUALIFIED.value, State.NOTIFICATION_PENDING.value, State.NOTIFIED.value}


class Job(BaseModel):
    provider: str
    source: Literal["employer_direct", "linkedin"]
    provider_job_id: str
    board: Optional[str] = None
    company: str
    title: str
    location: Optional[str] = None
    all_locations: list[str] = Field(default_factory=list)
    workplace_type: str = "unknown"  # remote | hybrid | onsite | unknown (as reported by the source)
    country_code: Optional[str] = None
    departments: list[str] = Field(default_factory=list)
    description: str = ""
    partial_description: bool = False
    required_experience: Optional[str] = None
    responsibilities: list[str] = Field(default_factory=list)
    salary_text: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    salary_interval: Optional[str] = None
    employment_type: Optional[str] = None
    posted_at: Optional[datetime] = None  # SOURCE posting date only. Never updated_at / first_seen.
    updated_at: Optional[datetime] = None
    posting_url: str
    application_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    source_active_hint: Optional[bool] = None  # only set by sources that assert active status

    @property
    def identity_key(self) -> str:
        return f"{self.provider}:{self.board or ''}:{self.provider_job_id}"

    @property
    def canonical_url(self) -> str:
        if self.source == "linkedin" and self.linkedin_url:
            li = canonical_linkedin_url(self.linkedin_url)
            if li:
                return li[0]
        return canonical_employer_url(self.posting_url)


class BoardConfig(BaseModel):
    provider: str
    token: str
    company: Optional[str] = None
    region: str = "global"  # Lever only: global | eu
    enabled: bool = True

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.token}"


class SourceStatus(BaseModel):
    source: str
    status: str  # ok | inaccessible | unsupported | invalid_config | fetch_failed | not_configured
    detail: str = ""
    jobs_fetched: int = 0
    company: Optional[str] = None
