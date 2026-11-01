from __future__ import annotations

from typing import Protocol

from ..models import BoardConfig, Job, SourceStatus

ACTIVE = "verified_active"
INACTIVE = "inactive_or_inaccessible"
UNVERIFIED = "unverified"


class Provider(Protocol):
    name: str

    def validate_board(self, board: BoardConfig) -> SourceStatus: ...

    def fetch_jobs(self, board: BoardConfig) -> list[Job]: ...

    def verify_active(self, job: Job) -> tuple[str, str]:
        """Return (status, detail). status is one of ACTIVE / INACTIVE / UNVERIFIED."""
        ...
