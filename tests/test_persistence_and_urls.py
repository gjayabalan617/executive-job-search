"""URL identity, seen_jobs.json safety, locking and repeat-run deduplication."""
from __future__ import annotations

import json
import threading

import pytest

from executive_job_search.seen import FileLock, RunInProgress, SeenFile, SeenFileError
from executive_job_search.urls import canonical_any, canonical_employer_url, canonical_linkedin_url
from helpers import make_pipeline


def test_linkedin_urls_lose_tracking_and_query_strings():
    u = "https://www.linkedin.com/jobs/view/director-enterprise-architecture-at-acme-3812345678/?trackingId=abc&refId=x&utm_source=y"
    assert canonical_linkedin_url(u) == ("https://www.linkedin.com/jobs/view/3812345678", "3812345678")
    assert canonical_any("https://www.linkedin.com/jobs/view/3812345678?currentJobId=1") == "https://www.linkedin.com/jobs/view/3812345678"


def test_linkedin_search_pages_are_not_individual_postings():
    assert canonical_linkedin_url("https://www.linkedin.com/jobs/search/?keywords=vp") is None
    assert canonical_linkedin_url("https://www.linkedin.com/company/acme/") is None
    assert canonical_linkedin_url("https://example.com/jobs/view/3812345678") is None


def test_employer_urls_keep_identity_bearing_params_only():
    a = canonical_employer_url("https://careers.example.invalid/jobs?gh_jid=123&utm_source=x&utm_campaign=y#frag")
    b = canonical_employer_url("https://careers.example.invalid/jobs/?utm_medium=z&gh_jid=123")
    c = canonical_employer_url("https://careers.example.invalid/jobs?gh_jid=124")
    assert a == b == "https://careers.example.invalid/jobs?gh_jid=123"
    assert a != c, "different gh_jid must remain different postings"


def test_seen_file_initialised_as_empty_list(tmp_path):
    p = tmp_path / "sub" / "seen_jobs.json"
    SeenFile(p).load()
    assert json.loads(p.read_text()) == []


def test_seen_file_preserves_existing_entries_and_appends_only_new(tmp_path):
    p = tmp_path / "seen_jobs.json"
    legacy = ["https://www.linkedin.com/jobs/view/3812345678", {"url": "https://x.invalid/a", "note": "keep me"}, 42]
    p.write_text(json.dumps(legacy))
    sf = SeenFile(p)
    assert sf.append(["https://www.linkedin.com/jobs/view/3812345678", "https://x.invalid/new"]) == 1
    data = json.loads(p.read_text())
    assert data[:3] == legacy and data[3] == "https://x.invalid/new"
    assert sf.append(["https://x.invalid/new"]) == 0
    assert len(json.loads(p.read_text())) == 4  # never shrinks


@pytest.mark.parametrize("content", ["{not json", '{"a": 1}', "[1, 2"])
def test_corrupt_seen_file_fails_safe_and_is_never_overwritten(tmp_path, content):
    p = tmp_path / "seen_jobs.json"
    p.write_text(content)
    with pytest.raises(SeenFileError):
        SeenFile(p).append(["https://x.invalid/a"])
    assert p.read_text() == content


def test_run_with_corrupt_tracking_file_aborts_without_marking_anything_processed(tmp_path):
    s, store, pipe, _ = make_pipeline(tmp_path)
    s.seen_path.write_text("{broken")
    summary = pipe.run("employer_direct")
    assert summary["status"] == "TRACKING_FILE_ERROR"
    assert s.seen_path.read_text() == "{broken"
    assert store.count() == 0


def test_run_lock_prevents_concurrent_runs(tmp_path):
    s, store, pipe, _ = make_pipeline(tmp_path)
    with FileLock(s.run_lock_path, blocking=False):
        summary = pipe.run("employer_direct")
    assert summary["status"] == "RUN_IN_PROGRESS"
    assert store.count() == 0
    assert pipe.run("employer_direct")["status"] != "RUN_IN_PROGRESS"  # released afterwards


def test_file_lock_raises_when_held(tmp_path):
    with FileLock(tmp_path / "l"):
        with pytest.raises(RunInProgress):
            with FileLock(tmp_path / "l", blocking=False):
                pass


def test_concurrent_appends_do_not_lose_entries(tmp_path):
    sf = SeenFile(tmp_path / "seen_jobs.json")
    ts = [threading.Thread(target=lambda i=i: sf.append([f"https://x.invalid/{i}-{j}" for j in range(5)])) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(json.loads((tmp_path / "seen_jobs.json").read_text())) == 40


def test_repeat_run_deduplicates_and_keeps_history(tmp_path):
    s, store, pipe, _ = make_pipeline(tmp_path)
    first = pipe.run("employer_direct")
    seen_after_first = json.loads(s.seen_path.read_text())
    ids_after_first = {r["identity_key"]: r["id"] for r in store.list_jobs()}
    second = pipe.run("employer_direct")
    assert first["new_discoveries"] == 14
    assert second["new_discoveries"] == 0
    assert second["new_qualifying_roles"] == 0
    assert second["previously_seen"] >= 11
    assert json.loads(s.seen_path.read_text()) == seen_after_first
    assert {r["identity_key"]: r["id"] for r in store.list_jobs()} == ids_after_first
    # the pending (insufficiently described) posting is retried, never permanently skipped
    assert second["pending_retries"] == first["pending_retries"]


def test_seen_file_urls_suppress_rediscovery_in_a_fresh_database(tmp_path):
    s, store, pipe, _ = make_pipeline(tmp_path)
    pipe.run("employer_direct")
    s2, store2, pipe2, _ = make_pipeline(tmp_path / "again")
    s2.seen_path.write_text(s.seen_path.read_text())
    summary = pipe2.run("employer_direct")
    assert summary["new_qualifying_roles"] == 0
    assert summary["previously_seen"] >= 11
