"""Data access for the dashboard (kept free of Streamlit so it is unit-testable)."""
from __future__ import annotations

from .models import QUALIFYING_STATES, State
from .report import qualifying, rank, salary_display
from .store import Store


def overview(store: Store) -> dict:
    last = store.last_run()
    counts = {s.value: store.count("state=?", (s.value,)) for s in State}
    return {
        "last_run": last,
        "counts": counts,
        "newly_posted": [row_view(r) for r in qualifying(store, "fresh")],
        "unknown_date": [row_view(r) for r in qualifying(store, "unknown_date")],
        "pending": [row_view(r) for r in store.list_jobs("state IN (?,?)", (State.PENDING_INSPECTION.value, State.RETRYABLE_FAILURE.value))],
        "outbox": store.outbox(),
    }


def row_view(r: dict) -> dict:
    return {
        "id": r["id"], "title": r["title"], "company": r["company"], "location": r.get("location"),
        "work_arrangement": r.get("work_arrangement"), "posted_at": r.get("posted_at") or "Unknown",
        "score": r.get("total_score"), "score_source": r.get("score_source"), "review_status": r.get("review_status"),
        "salary": salary_display(r), "apply": r.get("application_url") or r.get("posting_url"), "state": r["state"],
        "provider": r["provider"], "source": r["source"], "reason": r.get("state_reason"),
    }


def job_detail(store: Store, job_id: int) -> dict | None:
    return store.get_job(job_id)


def all_jobs(store: Store) -> list[dict]:
    return [row_view(r) for r in rank(store.list_jobs())]
