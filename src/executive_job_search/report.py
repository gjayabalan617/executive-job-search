"""Markdown / JSON / CSV reports and the run summary."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import QUALIFYING_STATES
from .store import Store

CSV_FIELDS = [
    "title", "company", "location", "work_arrangement", "posted_at", "freshness", "total_score", "score_source",
    "review_status", "salary", "employment_type", "application_url", "posting_url", "provider", "source", "state",
    "match_explanation", "potential_gaps",
]
_Q = ",".join("?" for _ in QUALIFYING_STATES)


def _ts(row: dict) -> float:
    try:
        return datetime.fromisoformat(row["posted_at"]).timestamp() if row.get("posted_at") else 0.0
    except ValueError:
        return 0.0


def rank(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (-(r.get("total_score") or 0), -_ts(r)))


def qualifying(store: Store, freshness: str) -> list[dict]:
    rows = store.list_jobs(f"state IN ({_Q}) AND duplicate_of IS NULL AND freshness=?", (*sorted(QUALIFYING_STATES), freshness))
    return rank(rows)


def salary_display(row: dict) -> str:
    return row.get("salary_text") or "Not disclosed"


def _provisional(row: dict) -> bool:
    return row.get("score_source") != "llm" and row.get("review_status") != "approved"


def render_job_md(row: dict, n: int) -> str:
    link = row.get("application_url") or row.get("posting_url")
    gaps = row.get("potential_gaps") or []
    label = "**PROVISIONAL (deterministic score; operator review required before notification)**\n\n" if _provisional(row) else ""
    ra = row.get("remote_assessment") or {}
    origin = "LinkedIn-origin" if row["source"] == "linkedin" else f"Employer-direct ({row['provider']}), NOT LinkedIn"
    return (
        f"### {n}. {row['title']} — {row['company']}\n\n{label}"
        f"- **Location:** {row.get('location') or 'Not stated'}\n"
        f"- **Work arrangement:** {row.get('work_arrangement')} ({ra.get('scope', 'unknown')}; NC: {row.get('nc_eligibility')})\n"
        f"- **Date posted (source):** {row.get('posted_at') or 'Unknown'}\n"
        f"- **Fit score:** {row['total_score']:.1f} ({row.get('score_source')})\n"
        f"- **Salary:** {salary_display(row)}\n"
        f"- **Source:** {origin}\n"
        f"- **Apply:** [{link}]({link})\n\n"
        f"**Why it fits:** {row.get('match_explanation')}\n\n"
        f"**Potential gaps:**\n" + ("\n".join(f"- {g}" for g in gaps) if gaps else "- None identified") + "\n"
    )


def render_summary_md(summary: dict) -> str:
    si = summary["search_intents_evaluated"]
    lines = [
        f"## Run summary ({summary['run_id']})",
        f"- **Status:** {summary['status']}",
        f"- **Mode:** {summary['mode']}",
        f"- **Configured sources:** {', '.join(summary['configured_sources']) or 'none'}",
        f"- **Successfully queried:** {', '.join(summary['successfully_queried_sources']) or 'none'}",
        f"- **Search intents evaluated:** {len(si['intents'])} ({si['method']}; external searches executed: {si['external_searches_executed']})",
        f"- **Postings discovered:** {summary['postings_discovered']}",
        f"- **Sufficiently inspected:** {summary['postings_sufficiently_inspected']}",
        f"- **New discoveries:** {summary['new_discoveries']}",
        f"- **Previously seen:** {summary['previously_seen']}",
        f"- **Pending retries:** {summary['pending_retries']}",
        f"- **New qualifying roles:** {summary['new_qualifying_roles']}",
        f"- **Tracking export:** {summary['tracking_export_status']}",
        f"- **Notification:** {summary['notification_status']}",
    ]
    if summary["source_failures"]:
        lines.append("- **SOURCE FAILURES (results below are NOT a complete zero-result search):**")
        lines += [f"  - {f}" for f in summary["source_failures"]]
    lines.append("- **Coverage limitations:**")
    lines += [f"  - {c}" for c in summary["coverage_limitations"]]
    lines.append("\n**Intent coverage (local matches per intent):**\n")
    lines += [f"- {k}: {v}" for k, v in si["intents"].items()]
    return "\n".join(lines)


def render_markdown(store: Store, summary: dict, label: Optional[str]) -> str:
    fresh, unknown = qualifying(store, "fresh"), qualifying(store, "unknown_date")
    head = f"# Executive technology roles report\n\n"
    if label:
        head += f"> **{label}**\n\n"
    if summary["status"] not in ("success",):
        head += f"> **Run status: {summary['status']}.** Do not read this report as a complete search.\n\n"
    parts = [head, render_summary_md(summary), "\n## Newly posted qualifying roles (source date within freshness window)\n"]
    parts += [render_job_md(r, i) for i, r in enumerate(fresh, 1)] or ["_None._\n"]
    parts.append("\n## Qualifying roles with unknown posting date (discovered, NOT confirmed newly posted)\n")
    parts += [render_job_md(r, i) for i, r in enumerate(unknown, 1)] or ["_None._\n"]
    return "\n".join(parts)


def render_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    w.writeheader()
    for r in rows:
        d = {k: r.get(k) for k in CSV_FIELDS}
        d["salary"] = salary_display(r)
        d["potential_gaps"] = " | ".join(r.get("potential_gaps") or [])
        w.writerow(d)
    return buf.getvalue()


def write_reports(store: Store, summary: dict, reports_dir: Path, label: Optional[str] = None) -> dict:
    out = Path(reports_dir) / summary["run_id"]
    out.mkdir(parents=True, exist_ok=True)
    fresh, unknown = qualifying(store, "fresh"), qualifying(store, "unknown_date")
    files = {
        "markdown": out / "report.md",
        "json": out / "report.json",
        "csv": out / "qualifying.csv",
        "summary": out / "run_summary.json",
    }
    files["markdown"].write_text(render_markdown(store, summary, label), encoding="utf-8")
    files["json"].write_text(json.dumps({"label": label, "run_summary": summary, "newly_posted_qualifying": fresh, "unknown_date_qualifying": unknown}, indent=2, default=str), encoding="utf-8")
    files["csv"].write_text(render_csv(fresh + unknown), encoding="utf-8")
    files["summary"].write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    latest = Path(reports_dir) / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    for name, p in files.items():
        (latest / p.name).write_bytes(p.read_bytes())
    return {k: str(v) for k, v in files.items()}
