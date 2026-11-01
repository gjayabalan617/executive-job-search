"""Reports (Markdown/JSON/CSV/summary), ranking, and the Streamlit-free dashboard data layer."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from executive_job_search import ui_data
from executive_job_search.fixtures_demo import DEMO_LABEL
from helpers import QUALIFYING_VP, make_pipeline, row_by_title


def _run(tmp_path):
    s, store, pipe, _ = make_pipeline(tmp_path)
    return s, store, pipe.run("employer_direct")


def test_all_four_report_files_are_written_and_labelled_not_live(tmp_path):
    s, store, summary = _run(tmp_path)
    files = {k: Path(v) for k, v in summary["report_files"].items()}
    assert set(files) == {"markdown", "json", "csv", "summary"} and all(p.exists() for p in files.values())
    md = files["markdown"].read_text()
    assert "NOT LIVE RESULTS" in md and DEMO_LABEL.split(" (")[0] in md
    assert "Not disclosed" in md, "missing salary is shown as Not disclosed, not estimated"
    assert "Unknown posting date" in md or "unknown" in md.lower()


def test_run_summary_contains_every_required_field(tmp_path):
    _, _, summary = _run(tmp_path)
    for key in ("configured_sources", "successfully_queried_sources", "search_intents_evaluated", "postings_discovered",
                "postings_sufficiently_inspected", "new_discoveries", "previously_seen", "pending_retries",
                "new_qualifying_roles", "tracking_export_status", "notification_status", "source_failures", "coverage_limitations"):
        assert key in summary, key
    assert summary["postings_discovered"] == 14 and summary["pending_retries"] == 1


def test_csv_ranked_by_score_then_date_and_unknown_dates_separated(tmp_path):
    _, store, summary = _run(tmp_path)
    rows = list(csv.DictReader(open(summary["report_files"]["csv"], encoding="utf-8")))
    assert rows, "qualifying rows expected from the synthetic fixtures"
    for group in ("fresh", "unknown_date"):
        scores = [float(r["total_score"]) for r in rows if r["freshness"] == group]
        assert scores == sorted(scores, reverse=True), f"{group} rows must be ranked by fit score"
    j = json.loads(Path(summary["report_files"]["json"]).read_text())
    titles_fresh = {r["title"] for r in j["newly_posted_qualifying"]}
    titles_unknown = {r["title"] for r in j["unknown_date_qualifying"]}
    assert QUALIFYING_VP in titles_fresh
    assert "Executive Director, IT Transformation" in titles_unknown
    assert not (titles_fresh & titles_unknown), "an unknown-date role must never be labelled newly posted"


def test_report_entries_carry_link_explanation_and_gaps(tmp_path):
    _, store, _ = _run(tmp_path)
    r = row_by_title(store, QUALIFYING_VP)
    assert r["application_url"].startswith("https://")
    assert len(r["match_explanation"].split(". ")) >= 2
    assert isinstance(r["potential_gaps"], list) and r["potential_gaps"]


def test_dashboard_data_layer_and_full_description_preserved(tmp_path):
    _, store, _ = _run(tmp_path)
    ov = ui_data.overview(store)
    assert ov["counts"]["qualified"] >= 1 and ov["last_run"]["status"] == "partial_failure"
    assert ov["pending"] and ov["newly_posted"] and ov["unknown_date"]
    r = row_by_title(store, QUALIFYING_VP)
    detail = ui_data.job_detail(store, r["id"])
    assert "post-merger integration" in detail["description"].lower()
    assert all(v["apply"] for v in ov["newly_posted"])


def test_report_command_regenerates_from_database(tmp_path, monkeypatch, capsys):
    s, store, summary = _run(tmp_path)
    from executive_job_search import cli
    monkeypatch.setenv("EJS_DATA_DIR", str(s.data_dir))
    monkeypatch.setenv("EJS_SEEN_PATH", str(s.seen_path))
    assert cli.main(["report", "--stdout"]) == 0
    assert QUALIFYING_VP in capsys.readouterr().out
