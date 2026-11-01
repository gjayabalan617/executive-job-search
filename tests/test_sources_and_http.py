"""Source adapters, pagination, retry/backoff and partial-failure semantics (all synthetic transports)."""
from __future__ import annotations

import requests

from executive_job_search.fixtures_demo import _Resp
from executive_job_search.http import HttpClient, SourceError, parse_retry_after
from executive_job_search.logs import redact
from executive_job_search.models import BoardConfig
from executive_job_search.providers.greenhouse import GreenhouseProvider
from executive_job_search.providers.lever import LeverProvider
import pytest

from helpers import GH_ONLY_YAML, LEVER_ONLY_YAML, NOW, TIMEOUT, Scripted, make_pipeline, ok

LV = "https://api.lever.co/v0/postings/synthetic-lever"
GH = "https://boards-api.greenhouse.io/v1/boards/synthetic-gh"


def _lever_posting(i: int) -> dict:
    return {
        "id": f"00000000-0000-0000-0000-{i:012d}", "text": f"SYNTHETIC Director {i}", "categories": {"location": "Remote - US"},
        "country": "US", "workplaceType": "remote", "descriptionPlain": "SYNTHETIC " * 80, "lists": [], "additionalPlain": "",
        "createdAt": int(NOW.timestamp() * 1000), "hostedUrl": f"https://jobs.synthetic.example.invalid/x/{i}",
        "applyUrl": f"https://jobs.synthetic.example.invalid/x/{i}/apply",
    }


def test_lever_pagination_collects_every_page():
    pages = [[_lever_posting(i) for i in range(0, 100)], [_lever_posting(i) for i in range(100, 200)], [_lever_posting(i) for i in range(200, 250)]]
    class Paged(Scripted):
        def request(self, method, url, params=None, **kw):
            self.calls.append((url, dict(params or {})))
            skip = int((params or {}).get("skip", 0))
            return ok(pages[skip // 100] if skip < 250 else [])
    sess = Paged({})
    jobs = LeverProvider(HttpClient(session=sess, sleep=lambda s: None), page_size=100, max_pages=50).fetch_jobs(BoardConfig(provider="lever", token="synthetic-lever"))
    assert len(jobs) == 250
    assert [c[1]["skip"] for c in sess.calls] == [0, 100, 200]
    assert len({j.provider_job_id for j in jobs}) == 250


def test_lever_pagination_cap_is_reported_not_silently_truncated():
    class Endless(Scripted):  # every page is full and new: the listing never ends
        def request(self, method, url, params=None, **kw):
            self.calls.append((url, dict(params or {})))
            skip = int((params or {}).get("skip", 0))
            return ok([_lever_posting(i) for i in range(skip, skip + 100)])
    sess = Endless({})
    with pytest.raises(SourceError) as e:
        LeverProvider(HttpClient(session=sess, sleep=lambda s: None), page_size=100, max_pages=3).fetch_jobs(BoardConfig(provider="lever", token="synthetic-lever"))
    assert "page" in str(e.value).lower()


def test_429_with_retry_after_then_timeout_then_success():
    sleeps: list[float] = []
    sess = Scripted({LV: [_Resp(429, None, {"Retry-After": "7"}), TIMEOUT, ok([])]})
    out = HttpClient(session=sess, sleep=sleeps.append, backoff_base=1.0).get_json(LV)
    assert out == []
    assert len(sess.calls) == 3
    assert sleeps[0] >= 7.0, "Retry-After must be honoured"
    assert sleeps[1] >= 2.0, "exponential backoff after the second failure"


def test_retries_are_bounded_and_reported():
    sess = Scripted({LV: [_Resp(503)]})
    with pytest.raises(SourceError) as e:
        HttpClient(session=sess, sleep=lambda s: None, max_retries=2).get_json(LV)
    assert e.value.kind == "server_error"
    assert len(sess.calls) == 3


def test_persistent_timeout_raises_timeout_error():
    sess = Scripted({LV: [requests.Timeout("t")]})
    with pytest.raises(SourceError) as e:
        HttpClient(session=sess, sleep=lambda s: None, max_retries=1).get_json(LV)
    assert e.value.kind == "timeout"


def test_not_found_is_not_retried():
    sess = Scripted({LV: [_Resp(404)]})
    with pytest.raises(SourceError):
        HttpClient(session=sess, sleep=lambda s: None).get_json(LV)
    assert len(sess.calls) == 1


def test_retry_after_http_date_and_garbage():
    assert parse_retry_after("12") == 12.0
    assert parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT", NOW.replace(year=2026, month=10, day=21, hour=7, minute=27, second=0)) == 60.0
    assert parse_retry_after("soon") is None and parse_retry_after(None) is None


def test_only_get_is_used_against_job_boards(tmp_path):
    s, store, pipe, session = make_pipeline(tmp_path)
    methods = []
    orig = session.request
    session.request = lambda method, *a, **k: (methods.append(method), orig(method, *a, **k))[1]
    pipe.run("employer_direct")
    assert methods and set(methods) == {"GET"}


def test_greenhouse_total_mismatch_is_flagged_as_partial():
    jobs = {"jobs": [{"id": 1, "title": "T", "absolute_url": "https://x.invalid/1", "location": {"name": "Remote - US"}, "content": ""}], "meta": {"total": 5}}
    sess = Scripted({f"{GH}/jobs": [ok(jobs)]})
    with pytest.raises(SourceError):
        GreenhouseProvider(HttpClient(session=sess, sleep=lambda s: None)).fetch_jobs(BoardConfig(provider="greenhouse", token="synthetic-gh"))


def test_partial_source_outage_is_partial_failure_not_success(tmp_path):
    s, store, pipe, _ = make_pipeline(tmp_path)  # demo registry contains an inaccessible and an unsupported board
    summary = pipe.run("employer_direct")
    assert summary["status"] == "partial_failure"
    assert "greenhouse:synthetic-missing" in " ".join(summary["source_failures"])
    assert "workday:synthetic-workday" in " ".join(summary["source_failures"])
    assert set(summary["successfully_queried_sources"]) == {"greenhouse:synthetic-gh", "lever:synthetic-lever"}
    assert len(summary["configured_sources"]) == 4


def test_total_outage_is_failed_never_a_zero_result_success(tmp_path):
    s, store, pipe, _ = make_pipeline(tmp_path, session=Scripted({}), boards_yaml=GH_ONLY_YAML)
    summary = pipe.run("employer_direct")
    assert summary["status"] == "failed"
    assert summary["new_qualifying_roles"] == 0
    assert summary["source_failures"]


def test_mid_run_fetch_failure_marks_source_failed(tmp_path):
    sess = Scripted({LV: [_Resp(200, {"name": "x"})], f"{LV}": [_Resp(500)]})
    s, store, pipe, _ = make_pipeline(tmp_path, session=sess, boards_yaml=LEVER_ONLY_YAML)
    summary = pipe.run("employer_direct")
    assert summary["status"] in ("failed", "partial_failure")
    assert store.count() == 0


def test_no_boards_configured_is_not_reported_as_zero_results(tmp_path):
    s, store, pipe, _ = make_pipeline(tmp_path, boards_yaml="boards: []\n")
    summary = pipe.run("employer_direct")
    assert summary["status"] == "NO_SOURCES_CONFIGURED"
    assert summary["configured_sources"] == []


def test_validate_boards_reports_inaccessible_and_unsupported(tmp_path):
    s, store, pipe, _ = make_pipeline(tmp_path)
    by = {st.source: st.status for st in pipe.validate_boards()}
    assert by["greenhouse:synthetic-gh"] == "ok" and by["lever:synthetic-lever"] == "ok"
    assert by["greenhouse:synthetic-missing"] == "inaccessible"
    assert by["workday:synthetic-workday"] == "unsupported"


def test_credentials_are_redacted_in_log_text():
    out = redact("x-api-key: sk-ant-abcdef123456 password=hunter22 Authorization: Bearer tok_123456")
    assert "sk-ant-abcdef123456" not in out and "hunter22" not in out
