"""SQLite persistence (primary state). All mutations run inside explicit transactions."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

from .models import Job, State
from .text import sha256_text

JSON_COLS = {
    "all_locations", "eligible_countries", "eligible_states", "responsibilities", "evidence",
    "dimension_scores", "potential_gaps", "intents_matched", "remote_assessment", "departments",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  identity_key TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL, source TEXT NOT NULL, provider_job_id TEXT NOT NULL, board TEXT,
  company TEXT NOT NULL, title TEXT NOT NULL, location TEXT, all_locations TEXT, departments TEXT,
  work_arrangement TEXT, eligible_countries TEXT, eligible_states TEXT, nc_eligibility TEXT,
  travel_requirements TEXT, remote_assessment TEXT,
  description TEXT, description_hash TEXT, required_experience TEXT, responsibilities TEXT,
  salary_text TEXT, salary_min REAL, salary_max REAL, salary_currency TEXT, salary_interval TEXT,
  employment_type TEXT, posted_at TEXT, updated_at TEXT, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  posting_url TEXT NOT NULL, canonical_url TEXT NOT NULL, application_url TEXT, linkedin_url TEXT,
  active_status TEXT DEFAULT 'unverified', verified_at TEXT, active_detail TEXT,
  evidence TEXT, dimension_scores TEXT, total_score REAL, score_source TEXT, match_explanation TEXT,
  potential_gaps TEXT, intents_matched TEXT, freshness TEXT,
  state TEXT NOT NULL DEFAULT 'discovered', state_reason TEXT, retry_count INTEGER DEFAULT 0, last_error TEXT,
  review_status TEXT DEFAULT 'none', fuzzy_key TEXT, duplicate_of INTEGER, last_run_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS idx_jobs_fuzzy ON jobs(fuzzy_key);
CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(canonical_url);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, mode TEXT, status TEXT, summary TEXT
);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL UNIQUE, identity_key TEXT NOT NULL,
  source TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
  next_attempt_at TEXT, sent_at TEXT
);
CREATE TABLE IF NOT EXISTS llm_cache (
  description_hash TEXT, profile_version TEXT, scoring_version TEXT, model TEXT, result TEXT, created_at TEXT,
  PRIMARY KEY (description_hash, profile_version, scoring_version, model)
);
CREATE TABLE IF NOT EXISTS cross_dupes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, new_identity TEXT, existing_identity TEXT, fuzzy_key TEXT, reason TEXT, created_at TEXT
);
"""


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def fuzzy_key(company: str, title: str, location: Optional[str]) -> str:
    n = lambda s: re.sub(r"[^a-z0-9]+", "", (s or "").lower())  # noqa: E731
    return f"{n(company)}|{n(title)}|{n(location)}"


class Store:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._tx = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(jobs)")}

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._tx:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    # ---------------- decoding ----------------
    @staticmethod
    def _decode(row: Optional[sqlite3.Row]) -> Optional[dict]:
        if row is None:
            return None
        d = dict(row)
        for c in JSON_COLS:
            if c in d and isinstance(d[c], str):
                try:
                    d[c] = json.loads(d[c])
                except ValueError:
                    pass
        return d

    # ---------------- jobs ----------------
    def upsert_job(self, job: Job, now: datetime, run_id: str = "") -> tuple[int, bool]:
        """Insert or refresh a job. Returns (row id, is_new)."""
        key, h = job.identity_key, sha256_text(job.description)
        fk = fuzzy_key(job.company, job.title, job.location)
        with self.transaction() as c:
            row = c.execute("SELECT id, description_hash, state FROM jobs WHERE identity_key=?", (key,)).fetchone()
            if row is None:
                cur = c.execute(
                    """INSERT INTO jobs (identity_key, provider, source, provider_job_id, board, company, title, location,
                       all_locations, departments, work_arrangement, description, description_hash, required_experience,
                       responsibilities, salary_text, salary_min, salary_max, salary_currency, salary_interval,
                       employment_type, posted_at, updated_at, first_seen_at, last_seen_at, posting_url, canonical_url,
                       application_url, linkedin_url, state, fuzzy_key, last_run_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (key, job.provider, job.source, job.provider_job_id, job.board, job.company, job.title, job.location,
                     json.dumps(job.all_locations), json.dumps(job.departments), job.workplace_type, job.description, h,
                     job.required_experience, json.dumps(job.responsibilities), job.salary_text, job.salary_min,
                     job.salary_max, job.salary_currency, job.salary_interval, job.employment_type, iso(job.posted_at),
                     iso(job.updated_at), iso(now), iso(now), job.posting_url, job.canonical_url, job.application_url,
                     job.linkedin_url, State.DISCOVERED.value, fk, run_id),
                )
                new_id = cur.lastrowid
                dup = c.execute(
                    "SELECT id, identity_key FROM jobs WHERE fuzzy_key=? AND id<>? AND duplicate_of IS NULL AND provider<>? ORDER BY id LIMIT 1",
                    (fk, new_id, job.provider),
                ).fetchone() or c.execute(
                    "SELECT id, identity_key FROM jobs WHERE fuzzy_key=? AND id<>? AND duplicate_of IS NULL AND board IS NOT ? ORDER BY id LIMIT 1",
                    (fk, new_id, job.board),
                ).fetchone()
                if dup:
                    c.execute("UPDATE jobs SET duplicate_of=? WHERE id=?", (dup["id"], new_id))
                    c.execute(
                        "INSERT INTO cross_dupes (new_identity, existing_identity, fuzzy_key, reason, created_at) VALUES (?,?,?,?,?)",
                        (key, dup["identity_key"], fk, "exact normalised company+title+location match across boards/providers", iso(now)),
                    )
                return new_id, True
            changed = row["description_hash"] != h
            c.execute(
                """UPDATE jobs SET last_seen_at=?, updated_at=COALESCE(?, updated_at), posted_at=COALESCE(?, posted_at),
                   title=?, location=?, all_locations=?, work_arrangement=?, description=?, description_hash=?,
                   posting_url=?, canonical_url=?, application_url=?, last_run_id=? WHERE id=?""",
                (iso(now), iso(job.updated_at), iso(job.posted_at), job.title, job.location, json.dumps(job.all_locations),
                 job.workplace_type, job.description, h, job.posting_url, job.canonical_url, job.application_url, run_id, row["id"]),
            )
            if changed and row["state"] != State.NOTIFIED.value:
                c.execute("UPDATE jobs SET state=?, state_reason='description changed; re-inspecting' WHERE id=?", (State.DISCOVERED.value, row["id"]))
            return row["id"], False

    def update_job(self, job_id: int, **fields: Any) -> None:
        bad = set(fields) - self._cols
        if bad:
            raise KeyError(f"unknown job columns: {sorted(bad)}")
        vals = []
        for k, v in fields.items():
            if k in JSON_COLS and not isinstance(v, str):
                v = json.dumps(v, default=str)
            elif isinstance(v, datetime):
                v = v.isoformat()
            elif isinstance(v, State):
                v = v.value
            vals.append(v)
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.transaction() as c:
            c.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*vals, job_id))

    def get_job(self, job_id: int) -> Optional[dict]:
        return self._decode(self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def get_by_identity(self, key: str) -> Optional[dict]:
        return self._decode(self._conn.execute("SELECT * FROM jobs WHERE identity_key=?", (key,)).fetchone())

    def list_jobs(self, where: str = "1=1", params: tuple = (), order: str = "id") -> list[dict]:
        rows = self._conn.execute(f"SELECT * FROM jobs WHERE {where} ORDER BY {order}", params).fetchall()
        return [self._decode(r) for r in rows]

    def count(self, where: str = "1=1", params: tuple = ()) -> int:
        return self._conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {where}", params).fetchone()[0]

    def cross_dupes(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM cross_dupes ORDER BY id")]

    # ---------------- runs ----------------
    def start_run(self, run_id: str, mode: str, now: datetime) -> None:
        with self.transaction() as c:
            c.execute("INSERT INTO runs (run_id, started_at, mode, status) VALUES (?,?,?,?)", (run_id, iso(now), mode, "running"))

    def finish_run(self, run_id: str, status: str, summary: dict, now: datetime) -> None:
        with self.transaction() as c:
            c.execute("UPDATE runs SET finished_at=?, status=?, summary=? WHERE run_id=?", (iso(now), status, json.dumps(summary, default=str), run_id))

    def last_run(self) -> Optional[dict]:
        r = self._conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
        if not r:
            return None
        d = dict(r)
        d["summary"] = json.loads(d["summary"]) if d.get("summary") else None
        return d

    # ---------------- outbox ----------------
    def enqueue_outbox(self, job_id: int, identity_key: str, source: str, subject: str, body: str, now: datetime) -> bool:
        """Transactionally queue a notification and mark the job notification_pending. Idempotent per job."""
        with self.transaction() as c:
            if c.execute("SELECT 1 FROM outbox WHERE job_id=?", (job_id,)).fetchone():
                return False
            c.execute(
                "INSERT INTO outbox (job_id, identity_key, source, subject, body, created_at, status, next_attempt_at) VALUES (?,?,?,?,?,?,?,?)",
                (job_id, identity_key, source, subject, body, iso(now), "pending", iso(now)),
            )
            c.execute("UPDATE jobs SET state=? WHERE id=?", (State.NOTIFICATION_PENDING.value, job_id))
            return True

    def outbox(self, status: Optional[str] = None) -> list[dict]:
        q, p = "SELECT * FROM outbox", ()
        if status:
            q, p = q + " WHERE status=?", (status,)
        return [dict(r) for r in self._conn.execute(q + " ORDER BY id", p)]

    def due_outbox(self, now: datetime) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM outbox WHERE status='pending' AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY id", (iso(now),))]

    def mark_sent(self, outbox_ids: list[int], now: datetime) -> None:
        with self.transaction() as c:
            for oid in outbox_ids:
                row = c.execute("SELECT job_id FROM outbox WHERE id=?", (oid,)).fetchone()
                c.execute("UPDATE outbox SET status='sent', sent_at=?, last_error=NULL WHERE id=?", (iso(now), oid))
                c.execute("UPDATE jobs SET state=? WHERE id=?", (State.NOTIFIED.value, row["job_id"]))

    def mark_send_failed(self, outbox_ids: list[int], error: str, now: datetime, next_attempt: datetime, max_attempts: int) -> None:
        with self.transaction() as c:
            for oid in outbox_ids:
                row = c.execute("SELECT attempts FROM outbox WHERE id=?", (oid,)).fetchone()
                attempts = row["attempts"] + 1
                status = "failed" if attempts >= max_attempts else "pending"
                c.execute("UPDATE outbox SET attempts=?, status=?, last_error=?, next_attempt_at=? WHERE id=?",
                          (attempts, status, error[:500], iso(next_attempt), oid))

    def retry_failed_outbox(self, now: datetime) -> int:
        with self.transaction() as c:
            cur = c.execute("UPDATE outbox SET status='pending', attempts=0, next_attempt_at=? WHERE status='failed'", (iso(now),))
            return cur.rowcount

    # ---------------- llm cache ----------------
    def cache_get(self, desc_hash: str, profile_v: str, scoring_v: str, model: str) -> Optional[dict]:
        r = self._conn.execute(
            "SELECT result FROM llm_cache WHERE description_hash=? AND profile_version=? AND scoring_version=? AND model=?",
            (desc_hash, profile_v, scoring_v, model)).fetchone()
        return json.loads(r["result"]) if r else None

    def cache_put(self, desc_hash: str, profile_v: str, scoring_v: str, model: str, result: dict, now: datetime) -> None:
        with self.transaction() as c:
            c.execute("INSERT OR REPLACE INTO llm_cache VALUES (?,?,?,?,?,?)",
                      (desc_hash, profile_v, scoring_v, model, json.dumps(result), iso(now)))
