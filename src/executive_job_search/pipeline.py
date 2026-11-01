"""Run orchestration: fetch -> dedupe -> inspect -> screen -> score -> verify -> persist -> notify -> report."""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from .config import Settings
from .eligibility import assess_remote
from .http import HttpClient, SourceError
from .llm import LLMEvaluator
from .logs import get_logger
from .models import INSPECTED_STATES, RETRY_STATES, BoardConfig, Job, SourceStatus, State
from .notify import SmtpSender, build_entry, process_outbox, subject_for
from .providers.base import ACTIVE, INACTIVE, UNVERIFIED
from .providers.greenhouse import GreenhouseProvider
from .providers.lever import LeverProvider
from .providers.linkedin import get_linkedin_provider
from .providers.registry import load_registry
from .report import write_reports
from .scoring import score_job, weighted_total
from .screening import Intent, load_intents, screen_job
from .seen import FileLock, RunInProgress, SeenFile, SeenFileError
from .signals import compute_signals
from .store import Store

log = get_logger("pipeline")


def classify_freshness(posted_at: Optional[datetime], now: datetime, days: int) -> str:
    """Freshness is judged ONLY from the source posting date; updated_at / first_seen never count."""
    if posted_at is None:
        return "unknown_date"
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    if posted_at > now + timedelta(days=1):
        return "unknown_date"  # future-dated: unreliable
    return "fresh" if (now - posted_at) <= timedelta(days=days) else "stale"


@dataclass
class Ctx:
    run_id: str
    seen_urls: set = field(default_factory=set)
    discovered: int = 0
    inspected: int = 0
    new: int = 0
    previously_seen: int = 0
    pending: int = 0
    excluded: int = 0
    below_threshold: int = 0
    high_score_ineligible: int = 0
    stale: int = 0
    new_qualified_ids: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    intent_counts: dict = field(default_factory=dict)


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        http: Optional[HttpClient] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        llm: Optional[LLMEvaluator] = None,
        sender: Optional[SmtpSender] = None,
        label: Optional[str] = None,
    ):
        self.s, self.store, self.clock, self.label, self.sender = settings, store, clock, label, sender
        self.http = http or HttpClient(timeout=settings.http_timeout, max_retries=settings.http_max_retries)
        self.providers = {
            "greenhouse": GreenhouseProvider(self.http),
            "lever": LeverProvider(self.http, settings.lever_page_size, settings.lever_max_pages),
        }
        self.llm = llm if llm is not None else (LLMEvaluator(settings, self.http, store, clock) if settings.llm_ready() else None)
        self.intents: list[Intent] = load_intents(settings.intents_file)
        self.seen = SeenFile(settings.seen_path)

    # ------------------------------------------------------------------ public
    def validate_boards(self) -> list[SourceStatus]:
        boards, problems = load_registry(self.s.boards_file)
        out = list(problems)
        for b in boards:
            out.append(self.providers[b.provider].validate_board(b))
        return out

    def run(self, mode: Optional[str] = None) -> dict:
        mode = mode or self.s.mode
        now = self.clock()
        run_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        summary = self._blank_summary(run_id, mode, now)
        try:
            with FileLock(self.s.run_lock_path, blocking=False):
                return self._run_locked(mode, run_id, summary)
        except RunInProgress as exc:
            summary.update(status="RUN_IN_PROGRESS", finished_at=self.clock().isoformat())
            summary["source_failures"].append(str(exc))
            return summary

    # ------------------------------------------------------------------ internals
    def _blank_summary(self, run_id: str, mode: str, now: datetime) -> dict:
        return {
            "run_id": run_id, "mode": mode, "label": self.label, "started_at": now.isoformat(), "finished_at": None,
            "status": "running", "configured_sources": [], "successfully_queried_sources": [], "source_status": [],
            "search_intents_evaluated": {"method": "", "external_searches_executed": 0, "intents": {i.name: 0 for i in self.intents}},
            "postings_discovered": 0, "postings_sufficiently_inspected": 0, "new_discoveries": 0, "previously_seen": 0,
            "pending_retries": 0, "new_qualifying_roles": 0, "excluded": 0, "below_threshold": 0,
            "high_score_not_us_remote_confirmed": 0, "stale": 0,
            "tracking_export_status": "not_run", "notification_status": "not_run",
            "source_failures": [], "coverage_limitations": [], "report_files": {},
        }

    def _run_locked(self, mode: str, run_id: str, summary: dict) -> dict:
        s, now = self.s, self.clock()
        ctx = Ctx(run_id=run_id, intent_counts={i.name: 0 for i in self.intents})
        try:
            ctx.seen_urls = self.seen.urls()
        except SeenFileError as exc:
            summary.update(status="TRACKING_FILE_ERROR", tracking_export_status=f"error: {exc}", finished_at=self.clock().isoformat())
            summary["source_failures"].append(str(exc))
            return summary
        self.store.start_run(run_id, mode, now)

        jobs: list[Job] = []
        if mode == "linkedin_only":
            jobs = self._collect_linkedin(summary)
        elif mode == "employer_direct":
            jobs = self._collect_employer(summary)
        else:
            raise ValueError(f"unknown mode {mode}")
        self._limitations(summary, mode)

        if summary["status"] not in ("SOURCE_UNAVAILABLE", "NO_SOURCES_CONFIGURED"):
            unique: dict[str, Job] = {}
            for j in jobs:  # remove duplicates inside the current run
                unique.setdefault(j.identity_key, j)
            ctx.discovered = len(unique)
            for job in unique.values():
                try:
                    self._process_job(job, ctx)
                except Exception as exc:  # noqa: BLE001 - never mark a failed assessment as processed
                    ctx.errors.append(f"{job.identity_key}: {type(exc).__name__}: {exc}")
                    row = self.store.get_by_identity(job.identity_key)
                    if row:
                        self.store.update_job(row["id"], state=State.RETRYABLE_FAILURE, last_error=str(exc)[:500], retry_count=(row.get("retry_count") or 0) + 1)
                    log.exception("job processing failed")
            summary["tracking_export_status"] = self._export_seen()
            summary["notification_status"] = self._notify(ctx, now)
        else:
            summary["tracking_export_status"] = "skipped (no source data)"
            summary["notification_status"] = "none: no source data"

        pend = self.store.count("state IN (?,?)", (State.PENDING_INSPECTION.value, State.RETRYABLE_FAILURE.value))
        summary.update(
            postings_discovered=ctx.discovered, postings_sufficiently_inspected=ctx.inspected, new_discoveries=ctx.new,
            previously_seen=ctx.previously_seen, pending_retries=pend, new_qualifying_roles=len(ctx.new_qualified_ids),
            excluded=ctx.excluded, below_threshold=ctx.below_threshold, high_score_not_us_remote_confirmed=ctx.high_score_ineligible,
            stale=ctx.stale,
        )
        summary["search_intents_evaluated"]["intents"] = ctx.intent_counts
        summary["source_failures"] += ctx.errors
        if ctx.errors and summary["status"] == "success":
            summary["status"] = "partial_failure"
        summary["finished_at"] = self.clock().isoformat()
        summary["report_files"] = write_reports(self.store, summary, s.reports_dir, self.label)
        self.store.finish_run(run_id, summary["status"], summary, self.clock())
        return summary

    # ---- sources
    def _collect_linkedin(self, summary: dict) -> list[Job]:
        summary["search_intents_evaluated"]["method"] = "provider-defined; no LinkedIn search is performed by this application"
        prov = get_linkedin_provider(self.s)
        if prov is None:
            summary["status"] = "SOURCE_UNAVAILABLE"
            summary["source_status"].append({"source": "linkedin", "status": "not_configured",
                                             "detail": "No documented, authorised LinkedIn provider is configured (set EJS_LINKEDIN_PROVIDER=authorized_feed and EJS_LINKEDIN_FEED_PATH). No fallback to employer-direct results was attempted."})
            summary["source_failures"].append("SOURCE_UNAVAILABLE: no authorised LinkedIn provider configured")
            return []
        self.providers[prov.name] = prov
        summary["configured_sources"] = [f"linkedin:{prov.name}"]
        try:
            jobs = prov.fetch()
        except Exception as exc:  # noqa: BLE001
            summary["status"] = "failed"
            summary["source_failures"].append(f"linkedin:{prov.name}: {type(exc).__name__}: {exc}")
            return []
        summary["successfully_queried_sources"] = [f"linkedin:{prov.name}"]
        summary["status"] = "success"
        for r in prov.rejected:
            summary["coverage_limitations"].append(f"feed record rejected: {r}")
        return jobs

    def _collect_employer(self, summary: dict) -> list[Job]:
        summary["search_intents_evaluated"]["method"] = "local matching of fetched employer-board postings (no external searches)"
        boards, problems = load_registry(self.s.boards_file)
        summary["configured_sources"] = [b.key for b in boards] + [p.source for p in problems]
        statuses: list[SourceStatus] = list(problems)
        jobs: list[Job] = []

        def work(b: BoardConfig) -> tuple[SourceStatus, list[Job]]:
            prov = self.providers[b.provider]
            st = prov.validate_board(b)
            if st.status != "ok":
                return st, []
            try:
                got = prov.fetch_jobs(b)
            except SourceError as exc:
                return SourceStatus(source=b.key, status="fetch_failed", detail=f"{exc.kind}: {exc}"), []
            st.jobs_fetched = len(got)
            return st, got

        if boards:
            with ThreadPoolExecutor(max_workers=max(1, self.s.max_concurrency)) as pool:
                for st, got in pool.map(work, boards):
                    statuses.append(st)
                    jobs += got
        summary["source_status"] = [st.model_dump() for st in statuses]
        ok = [st.source for st in statuses if st.status == "ok"]
        bad = [st for st in statuses if st.status != "ok"]
        summary["successfully_queried_sources"] = ok
        summary["source_failures"] += [f"{st.source}: {st.status} ({st.detail})" for st in bad]
        if not boards and not problems:
            summary["status"] = "NO_SOURCES_CONFIGURED"
            summary["source_failures"].append(f"no employer boards configured in {self.s.boards_file}; this is NOT a zero-results search")
        elif not ok:
            summary["status"] = "failed"
        elif bad:
            summary["status"] = "partial_failure"
        else:
            summary["status"] = "success"
        return jobs

    def _limitations(self, summary: dict, mode: str) -> None:
        lim = summary["coverage_limitations"]
        if mode == "employer_direct":
            lim.append("Employer-direct results are NOT LinkedIn-origin; coverage is limited to the configured Greenhouse/Lever boards.")
            lim.append("Intent coverage is local matching on fetched postings; no external searches were executed.")
            lim.append("Greenhouse posting date = first_published when supplied, otherwise unknown; Lever = createdAt. updated_at/first_seen are never used as the posting date.")
            lim.append("Active status is verified with a single-posting GET only for roles that otherwise qualify.")
        if self.llm is None:
            lim.append("LLM evaluator not enabled: scores are deterministic and PROVISIONAL; operator review is required before notifications.")

    # ---- per-job
    def _process_job(self, job: Job, ctx: Ctx) -> None:
        now = self.clock()
        existing = self.store.get_by_identity(job.identity_key)
        if existing and existing["state"] not in RETRY_STATES:
            self.store.update_job(existing["id"], last_seen_at=now, last_run_id=ctx.run_id)
            ctx.previously_seen += 1
            return
        if existing is None and job.canonical_url in ctx.seen_urls:
            ctx.previously_seen += 1
            return
        row_id, is_new = self.store.upsert_job(job, now, ctx.run_id)
        if is_new:
            ctx.new += 1
        row = self.store.get_job(row_id)
        if row["duplicate_of"]:
            self.store.update_job(row_id, state=State.EXCLUDED, state_reason=f"cross-source duplicate of job {row['duplicate_of']}")
            ctx.excluded += 1
            return
        if len(job.description.strip()) < self.s.min_description_chars or job.partial_description:
            self.store.update_job(row_id, state=State.PENDING_INSPECTION, retry_count=(row.get("retry_count") or 0) + 1,
                                  state_reason="description missing or too short to inspect; will retry", last_run_id=ctx.run_id)
            ctx.pending += 1
            return
        ctx.inspected += 1
        sig = compute_signals(job.description)
        scr = screen_job(job, self.intents, sig)
        for name in scr.intents_matched:
            if name in ctx.intent_counts:
                ctx.intent_counts[name] += 1
        if scr.excluded:
            self.store.update_job(row_id, state=State.EXCLUDED, state_reason="; ".join(scr.reasons), intents_matched=scr.intents_matched)
            ctx.excluded += 1
            return
        remote = assess_remote(job)
        det = score_job(job, scr, remote, sig)
        dims, total, source = det.dimensions, det.total, "deterministic_provisional"
        evidence, gaps = list(det.evidence), list(det.gaps)
        if self.llm is not None and remote.confirmed_us_remote and det.total >= 70:
            out = self.llm.evaluate(job, det.dimensions)
            if out is not None:
                dims, total, source = out.dimensions, weighted_total(out.dimensions), "llm"
                evidence += out.evidence
                if out.rationale:
                    evidence.append({"dimension": "llm_rationale", "signal": "llm_rationale", "excerpt": out.rationale[:500]})
                gaps += [g for g in out.potential_gaps if g not in gaps]
        freshness = classify_freshness(job.posted_at, now, self.s.freshness_days)
        common = dict(
            work_arrangement=remote.arrangement, eligible_countries=remote.eligible_countries, eligible_states=remote.eligible_states,
            nc_eligibility=remote.nc_eligibility, travel_requirements=remote.travel, remote_assessment=remote.model_dump(),
            evidence=evidence, dimension_scores=dims, total_score=total, score_source=source,
            match_explanation=det.explanation, potential_gaps=gaps, intents_matched=scr.intents_matched, freshness=freshness,
            last_run_id=ctx.run_id,
        )
        if total < self.s.min_score:
            self.store.update_job(row_id, state=State.INSPECTED, state_reason=f"score {total} below threshold {self.s.min_score}", **common)
            ctx.below_threshold += 1
            return
        if not remote.confirmed_us_remote:
            self.store.update_job(row_id, state=State.INSPECTED, state_reason="US-remote not confirmed: " + "; ".join(remote.reasons), **common)
            ctx.high_score_ineligible += 1
            return
        if freshness == "stale":
            self.store.update_job(row_id, state=State.INSPECTED, state_reason=f"source posting date {job.posted_at.date()} older than {self.s.freshness_days} days", **common)
            ctx.stale += 1
            return
        prov = self.providers.get(job.provider)
        status, detail = prov.verify_active(job) if prov else (UNVERIFIED, "no provider to verify with")
        common.update(active_status=status, verified_at=self.clock(), active_detail=detail)
        if status == ACTIVE:
            self.store.update_job(row_id, state=State.QUALIFIED, state_reason="qualified", **common)
            ctx.new_qualified_ids.append(row_id)
        elif status == INACTIVE:
            self.store.update_job(row_id, state=State.EXCLUDED, state_reason=f"expired or inaccessible: {detail}", **common)
            ctx.excluded += 1
        else:
            self.store.update_job(row_id, state=State.RETRYABLE_FAILURE, state_reason=f"could not verify posting is active: {detail}",
                                  last_error=detail, retry_count=(row.get("retry_count") or 0) + 1, **common)

    # ---- tracking export
    def _export_seen(self) -> str:
        try:
            marks = ",".join("?" for _ in INSPECTED_STATES)
            urls = [r["canonical_url"] for r in self.store.list_jobs(f"state IN ({marks})", tuple(sorted(INSPECTED_STATES)))]
            added = self.seen.append(urls)
            return f"updated: +{added} new URL(s) in {self.s.seen_path}" if added else f"unchanged: {self.s.seen_path}"
        except SeenFileError as exc:
            return f"error: {exc}"
        except OSError as exc:
            return f"error: could not write {self.s.seen_path}: {exc}"

    # ---- notifications
    def _notify(self, ctx: Ctx, now: datetime) -> str:
        queued = held = 0
        for row in self.store.list_jobs("state=? AND duplicate_of IS NULL", (State.QUALIFIED.value,)):
            fresh_ok = row["freshness"] == "fresh" or (row["freshness"] == "unknown_date" and self.s.notify_unknown_date)
            assessed = row["score_source"] == "llm" or row["review_status"] == "approved"
            if row["review_status"] == "rejected" or not fresh_ok:
                continue
            if not assessed or row["active_status"] != ACTIVE:
                held += 1  # provisional scores need operator review first
                continue
            if self.store.enqueue_outbox(row["id"], row["identity_key"], row["source"], subject_for(row["source"]), build_entry(row), now):
                queued += 1
        res = process_outbox(self.store, self.s, now, self.sender)
        parts = []
        if queued == 0 and res["status"] == "nothing_to_send":
            parts.append("none: no new qualifying roles ready to notify")
        else:
            parts.append(f"queued:{queued}; {res['status']}")
        if held:
            parts.append(f"{held} qualified role(s) held: provisional score, run `review approve <id>` first")
        return "; ".join(parts)
