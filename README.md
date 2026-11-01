# executive-job-search

Read-only discovery and screening of US-remote executive technology roles (enterprise architecture, technology
strategy, transformation, technology M&A advisory) for one candidate profile. SQLite is the system of record;
`seen_jobs.json` is kept as a compatibility export.

## Status at a glance

| Item | Status |
|---|---|
| Unit/integration tests | **61 passed** (`docs/test-output.txt`) — all against SYNTHETIC fixtures |
| Fixture demo | Works; output is labelled **NOT LIVE RESULTS** (`docs/demo-output.txt`) |
| **Live run** | **Not performed — blocked** (see below). No live job results exist. |
| Streamlit dashboard | Written, **never launched** (Streamlit could not be installed); its data layer is tested |
| Docker / compose / systemd / cron | Written, **never executed** (no Docker or systemd in the build sandbox) |
| Anthropic evaluator | Implemented and tested against a fake transport; **never called against the real API** |

## Why there is no live run

1. **Network:** the sandbox egress proxy answered `403` to `boards-api.greenhouse.io`, `api.lever.co`,
   `developers.greenhouse.io`, `raw.githubusercontent.com` and PyPI. Job-board APIs are unreachable from there.
2. **Configuration:** no employer board tokens were supplied, and none are invented. `boards.yaml` must list real
   Greenhouse/Lever tokens you choose.
3. **LinkedIn:** there is no public general job-search API and no authorised provider is configured, so
   `linkedin_only` correctly returns `SOURCE_UNAVAILABLE` (exit code 3) and does not fall back to employer boards.

To go live: copy `boards.example.yaml` → `boards.yaml`, add tokens, run `validate-boards`, then `run` with
`EJS_NOTIFY_SEND_ENABLED=false` (the default). Nothing is sent, applied to, or contacted.

## Commands

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"            # add ",ui" for the dashboard
export EJS_MODE=employer_direct EJS_DATA_DIR=./data EJS_SEEN_PATH=./data/seen_jobs.json EJS_BOARDS_FILE=./boards.yaml

executive-job-search demo --fresh      # SYNTHETIC fixtures, NOT LIVE RESULTS
executive-job-search validate-boards   # read-only GET per configured board
executive-job-search run               # one discovery pass (exit 0 ok, 2 partial, 3 SOURCE_UNAVAILABLE, 4 failed, 5 no sources, 6 tracking file error, 7 already running)
executive-job-search jobs [--state qualified]
executive-job-search show <id>         # full description, evidence, dimension scores
executive-job-search review approve <id>   # required for provisional (non-LLM) scores before any notification
executive-job-search outbox list|send|retry-failed
executive-job-search report [--stdout]
streamlit run src/executive_job_search/dashboard.py --server.address 127.0.0.1
pytest
```

Reports (Markdown, JSON, CSV, run summary) are written to `$EJS_DATA_DIR/reports/<run-id>/`.

## Behaviour that matters

* **Modes are separate and explicit.** `linkedin_only` accepts only an operator-supplied *authorised feed* file
  (`EJS_LINKEDIN_PROVIDER=authorized_feed`, `EJS_LINKEDIN_FEED_PATH`); every record needs an individual
  `linkedin.com/jobs/view/<id>` URL or it is rejected. No scraping, guest endpoints, cookies, or CAPTCHA handling.
  `employer_direct` uses Greenhouse and Lever public GET endpoints only and labels results *employer-direct*.
* **Intents are evaluated locally** on fetched postings; reports say `external_searches_executed: 0`.
* **Eligibility:** a role is "confirmed US-remote" only with explicit remote *and* US evidence. Hybrid, non-US
  remote, state-restricted remote excluding North Carolina, and bare "Remote" are not confirmed matches.
* **Scoring:** six dimensions (0–100) weighted 30/20/20/15/10/5; unknown salary is never credited; threshold 80.
* **Provisional scores:** without the LLM evaluator, scores are labelled provisional and nothing is queued for
  email until you run `review approve <id>`.
* **Dates:** `posted_at` comes only from a source posting date (Greenhouse `first_published`, Lever `createdAt`).
  `updated_at`/`first_seen` are never substituted. Roles without a reliable date are reported in a separate
  "unknown posting date" section and never labelled newly posted. Default freshness window: 14 days.
* **State machine:** discovered → pending_inspection → inspected → excluded | qualified → notification_pending →
  notified, with retryable_failure. Short/partial descriptions stay pending and are *not* written to
  `seen_jobs.json`; all sufficiently inspected URLs (including non-qualifying) are.
* **Tracking file:** missing → `[]`; malformed → run aborts with `TRACKING_FILE_ERROR`, file untouched; entries are
  never removed; atomic replace under an exclusive lock; a separate run lock prevents concurrent runs.
* **Notifications:** SMTP, off by default, transactional outbox with backoff. Delivery is **at-least-once**: if the
  server accepts a message but the connection drops before the final reply, the retry can deliver a duplicate.
* **A failed or partial source is never a "zero results" success:** status is `partial_failure`/`failed`, and the
  report says so at the top.

## Deviations from the specification (honest list)

* **`requests` instead of `httpx`.** httpx could not be installed (PyPI blocked). All HTTP goes through
  `http.HttpClient`, so swapping is a one-file change. Retries, backoff, `Retry-After`, timeouts and redaction are
  implemented and tested there.
* **Anthropic via raw HTTPS** (`/v1/messages`), not the SDK (not installable). No default model is assumed;
  `EJS_ANTHROPIC_MODEL` must be set. The LLM can only lift a dimension a bounded amount above the deterministic
  score, claims over 60 need verbatim evidence found in the posting, and eligibility/URLs stay deterministic.
* **API schemas were not verified against the official documents.** `developers.greenhouse.io` and the Lever
  GitHub README were unreachable from the sandbox. Field names (`jobs[].first_published`, `location.name`,
  `content` (entity-escaped HTML), `meta.total`; Lever `createdAt` (ms), `workplaceType`, `salaryRange`,
  `skip`/`limit`) come from secondary sources and must be re-checked against the official pages before relying on
  a live run. In particular, Greenhouse pay ranges may only exist on the single-job endpoint; salary is therefore
  captured only when present in a payload or stated in the posting text, otherwise "Not disclosed".
* The unfinished tail of the original brief (it stopped at "Use SQLite transactions as primary") was completed from
  its later sections.

## Coverage limitations

Only boards you configure are searched; Greenhouse/Lever cover a subset of employers, and many large employers use
other systems (unsupported providers are reported, not skipped silently). Heuristic text matching can miss or
misread eligibility wording; scores are conservative aids to human review, not decisions. Credentials are redacted
from logs; never put secrets in `boards.yaml`.
