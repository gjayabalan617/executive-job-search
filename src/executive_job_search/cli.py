"""Command line interface."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import load_settings
from .fixtures_demo import DEMO_BOARDS_YAML, DEMO_LABEL, FixtureSession
from .http import HttpClient
from .logs import setup_logging
from .notify import SmtpSender, process_outbox
from .pipeline import Ctx, Pipeline
from .report import render_markdown, write_reports
from .seen import SeenFile
from .store import Store

EXIT = {"success": 0, "partial_failure": 2, "SOURCE_UNAVAILABLE": 3, "failed": 4, "NO_SOURCES_CONFIGURED": 5,
        "TRACKING_FILE_ERROR": 6, "RUN_IN_PROGRESS": 7}


def _print_summary(summary: dict) -> None:
    keys = ["status", "mode", "label", "configured_sources", "successfully_queried_sources", "postings_discovered",
            "postings_sufficiently_inspected", "new_discoveries", "previously_seen", "pending_retries", "new_qualifying_roles",
            "tracking_export_status", "notification_status", "source_failures", "coverage_limitations", "report_files"]
    print(json.dumps({k: summary.get(k) for k in keys}, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="executive-job-search", description="Read-only executive technology job discovery.")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a discovery pass")
    r.add_argument("--mode", choices=["linkedin_only", "employer_direct"], help="overrides EJS_MODE")
    d = sub.add_parser("demo", help="run against SYNTHETIC fixtures (NOT LIVE RESULTS)")
    d.add_argument("--fresh", action="store_true", help="wipe the demo data dir first")
    sub.add_parser("validate-boards", help="validate configured employer boards (read-only GETs)")
    sub.add_parser("init", help="create data dir, database and seen_jobs.json")
    j = sub.add_parser("jobs", help="list stored jobs")
    j.add_argument("--state")
    s = sub.add_parser("show", help="show one job in full")
    s.add_argument("id", type=int)
    rv = sub.add_parser("review", help="approve/reject a provisional score before notification")
    rv.add_argument("action", choices=["approve", "reject"])
    rv.add_argument("id", type=int)
    sub.add_parser("notify", help="queue approved/LLM-assessed roles and process the outbox now")
    o = sub.add_parser("outbox", help="inspect or process the notification outbox")
    o.add_argument("action", choices=["list", "send", "retry-failed"])
    rp = sub.add_parser("report", help="regenerate reports for the last run")
    rp.add_argument("--stdout", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    setup_logging(settings.log_level)

    if args.cmd == "demo":
        demo_dir = settings.data_dir / "demo"
        if args.fresh and demo_dir.exists():
            shutil.rmtree(demo_dir)
        demo_dir.mkdir(parents=True, exist_ok=True)
        (demo_dir / "boards.yaml").write_text(DEMO_BOARDS_YAML, encoding="utf-8")
        settings = load_settings(
            {}, mode="employer_direct", data_dir=demo_dir, seen_path=demo_dir / "seen_jobs.json", boards_file=demo_dir / "boards.yaml",
            notify_send_enabled=False, llm_enabled=False,
        )
        store = Store(settings.db_path)
        now = datetime.now(timezone.utc)
        pipe = Pipeline(settings, store, http=HttpClient(session=FixtureSession(now), sleep=lambda s: None), label=DEMO_LABEL)
        summary = pipe.run("employer_direct")
        print(f"*** {DEMO_LABEL} ***")
        _print_summary(summary)
        return EXIT.get(summary["status"], 1)

    store = Store(settings.db_path)
    if args.cmd == "init":
        SeenFile(settings.seen_path).load()
        print(f"initialised {settings.db_path} and {settings.seen_path}")
        return 0
    if args.cmd == "run":
        summary = Pipeline(settings, store).run(args.mode)
        _print_summary(summary)
        return EXIT.get(summary["status"], 1)
    if args.cmd == "validate-boards":
        statuses = Pipeline(settings, store).validate_boards()
        if not statuses:
            print(f"no boards configured in {settings.boards_file}")
            return 5
        for st in statuses:
            print(f"{st.status:14} {st.source}  {st.detail}")
        return 0 if all(s.status == "ok" for s in statuses) else 2
    if args.cmd == "jobs":
        rows = store.list_jobs("state=?", (args.state,)) if args.state else store.list_jobs()
        for r in rows:
            score = f"{r['total_score']:.1f}" if r.get("total_score") is not None else "  -"
            print(f"{r['id']:>4}  {r['state']:<20} {score:>5}  {r['title']} — {r['company']}")
        return 0
    if args.cmd == "show":
        row = store.get_job(args.id)
        if not row:
            print("not found")
            return 1
        print(json.dumps(row, indent=2, default=str))
        return 0
    if args.cmd == "review":
        store.update_job(args.id, review_status="approved" if args.action == "approve" else "rejected")
        print(f"job {args.id}: review_status={'approved' if args.action == 'approve' else 'rejected'}")
        return 0
    if args.cmd == "notify":
        now = datetime.now(timezone.utc)
        print(Pipeline(settings, store)._notify(Ctx(run_id="manual"), now))
        return 0
    if args.cmd == "outbox":
        now = datetime.now(timezone.utc)
        if args.action == "list":
            for e in store.outbox():
                print(f"{e['id']:>3} {e['status']:<8} attempts={e['attempts']} {e['subject']} :: {e['identity_key']}")
        elif args.action == "retry-failed":
            print(f"re-queued {store.retry_failed_outbox(now)} failed entries")
        else:
            print(process_outbox(store, settings, now, SmtpSender(settings)))
        return 0
    if args.cmd == "report":
        last = store.last_run()
        if not last or not last.get("summary"):
            print("no completed run to report on")
            return 1
        files = write_reports(store, last["summary"], settings.reports_dir, last["summary"].get("label"))
        if args.stdout:
            print(render_markdown(store, last["summary"], last["summary"].get("label")))
        else:
            print(json.dumps(files, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
