"""SYNTHETIC FIXTURES - NOT REAL JOBS.

Everything here is invented for tests and the demo: company names, URLs (.invalid TLD) and postings. A
FixtureSession stands in for the network so the full pipeline can be exercised offline. Results produced from
it must always be labelled NOT LIVE RESULTS.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta
from typing import Any, Optional

DEMO_LABEL = "NOT LIVE RESULTS — SYNTHETIC FIXTURES (no network access used; companies and postings are invented)"

DEMO_BOARDS_YAML = """\
# SYNTHETIC demo registry - these boards do not exist.
boards:
  - provider: greenhouse
    token: synthetic-gh
    company: Synthetic Health Co (SYNTHETIC)
  - provider: lever
    token: synthetic-lever
    company: Synthetic Advisory Group (SYNTHETIC)
  - provider: greenhouse
    token: synthetic-missing        # deliberately inaccessible -> demonstrates partial_failure
  - provider: workday               # deliberately unsupported -> reported, not silently ignored
    token: synthetic-workday
"""

RICH_RESP = [
    "Define and own the enterprise technology strategy and multi-year architecture roadmap across the organization, chairing the architecture review board.",
    "Lead technology due diligence and post-merger integration planning for acquisitions, including TSA and separation planning.",
    "Advise the CIO, CFO and executive leadership team on technology investment decisions and a portfolio of applications within a multi-million dollar budget.",
    "Build and lead a team of enterprise architects and drive cloud transformation across AWS and Azure.",
    "Lead application rationalization and technology cost optimization programs, advising clients and business units.",
]
RICH_QUAL = [
    "15+ years of experience in enterprise architecture, technology strategy or technology consulting.",
    "Experience in healthcare, life sciences or financial services preferred.",
]


_ABOUT = ("SYNTHETIC FIXTURE TEXT. This company, its team and every statement in this posting are invented for software testing. "
          "We value collaboration, curiosity and a culture of continuous learning, and we offer standard benefits.")


def build_html(intro: str, resp: list[str], qual: list[str], tail: str = "") -> str:
    li = lambda xs: "".join(f"<li>{x}</li>" for x in xs)  # noqa: E731
    return (f"<p>{intro}</p><p><strong>Responsibilities:</strong></p><ul>{li(resp)}</ul>"
            f"<p><strong>Qualifications:</strong></p><ul>{li(qual)}</ul><p>{tail}</p><p>{_ABOUT}</p>")


def _rich(intro: str, tail: str = "Travel up to 10% for leadership meetings.") -> str:
    return build_html(intro, RICH_RESP, RICH_QUAL, tail)


ADMIN_RESP = [
    "Manage the day-to-day queue of change requests and track vendor invoices against purchase orders.",
    "Schedule weekly status meetings, maintain status reports and coordinate with the service desk on ticket backlogs.",
    "Prepare monthly slide decks summarising open tickets and escalate overdue items to the support team.",
    "Maintain the intake spreadsheet, update the shared calendar and take meeting minutes for working groups.",
]
ENG_RESP = [
    "Design and implement microservices in Java and Kotlin, writing unit and integration tests.",
    "Review pull requests, improve CI/CD pipelines and fix production defects as part of the on-call rotation.",
    "Optimize SQL queries and build REST APIs consumed by internal teams across the platform.",
]


def _gh_jobs(now: datetime) -> list[dict]:
    d = lambda n: (now - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%S-00:00")  # noqa: E731

    def job(jid, title, loc, content, posted=None, updated=1):
        j = {
            "id": jid, "internal_job_id": jid + 1, "title": title, "updated_at": d(updated),
            "location": {"name": loc}, "absolute_url": f"https://synthetic.example.invalid/careers/{jid}?gh_jid={jid}&utm_source=demo",
            "requisition_id": f"SYN-{jid}", "language": "en", "metadata": None, "departments": [{"id": 1, "name": "Technology"}],
            "offices": [], "content": html.escape(content),
        }
        if posted is not None:
            j["first_published"] = d(posted)
        return j

    return [
        job(9001, "Vice President, Enterprise Architecture & Technology M&A", "Remote - United States",
            _rich("Synthetic Health Co is hiring a Vice President, Enterprise Architecture and Technology M&A for a healthcare and life sciences services company. This is a remote role open to candidates located anywhere in the United States.",
                  "Travel up to 10% for leadership meetings. Compensation: $280,000 - $340,000 base salary."), posted=3),
        job(9002, "Principal Software Engineer", "Remote - United States",
            build_html("Synthetic Health Co seeks a Principal Software Engineer. Remote within the United States.", ENG_RESP, ["10+ years of experience building distributed systems in Java."]), posted=2),
        job(9003, "Director, Digital Transformation", "Remote - United States",
            build_html("Synthetic Health Co needs a Director, Digital Transformation Office to keep the program office running. Remote within the United States.", ADMIN_RESP, ["8+ years of experience in IT service management."]), posted=4),
        job(9004, "Vice President, Enterprise Architecture", "Raleigh, NC (Hybrid)",
            _rich("Synthetic Health Co is hiring a Vice President, Enterprise Architecture. This is a hybrid role with three days per week in the Raleigh office.", ""), posted=5),
        job(9005, "Director, Cloud Strategy", "Remote - Canada",
            _rich("Synthetic Health Co is hiring a Director, Cloud Strategy based in Canada.", ""), posted=6),
        job(9006, "Senior Director, Technology Strategy", "Remote - California, Washington, Texas",
            _rich("Synthetic Health Co is hiring a Senior Director, Technology Strategy. Remote work is available only in the states listed.", ""), posted=2),
        job(9007, "Managing Director, Technology Advisory", "Remote",
            _rich("Synthetic Health Co is hiring a Managing Director, Technology Advisory to lead client engagements.", ""), posted=1),
        job(9008, "Executive Director, IT Transformation", "Remote - United States",
            _rich("Synthetic Health Co is hiring an Executive Director, IT Transformation. Fully remote; candidates must be located in the United States.", ""), posted=None),
        job(9009, "Senior Vice President, Technology Strategy", "Remote - United States",
            _rich("Synthetic Health Co is hiring a Senior Vice President, Technology Strategy. Open to candidates anywhere in the United States.", ""), posted=2),
        job(9010, "VP, Enterprise Architecture", "Remote - United States",
            "<p>Join us as VP of Enterprise Architecture.</p>", posted=1),
    ]


def _lever_postings(now: datetime) -> list[dict]:
    ms = lambda n: int((now - timedelta(days=n)).timestamp() * 1000)  # noqa: E731

    def post(pid, text, loc, wt, created, resp, qual, plain, extra=None, sal=None, country="US"):
        li = lambda xs: "".join(f"<li>{x}</li>" for x in xs)  # noqa: E731
        plain = f"{plain} {_ABOUT}"
        p = {
            "id": pid, "text": text, "categories": {"commitment": "Full-time", "location": loc, "team": "Advisory", "department": "Consulting", "allLocations": [loc]},
            "country": country, "workplaceType": wt, "descriptionPlain": plain, "description": f"<div>{plain}</div>",
            "lists": [{"text": "Responsibilities:", "content": li(resp)}, {"text": "Qualifications:", "content": li(qual)}],
            "additionalPlain": extra or "", "additional": extra or "", "createdAt": ms(created),
            "hostedUrl": f"https://jobs.synthetic.example.invalid/synthetic-lever/{pid}", "applyUrl": f"https://jobs.synthetic.example.invalid/synthetic-lever/{pid}/apply",
        }
        if sal:
            p["salaryRange"] = {"min": sal[0], "max": sal[1], "currency": "USD", "interval": "per-year-salary"}
        return p

    bd_resp = RICH_RESP + ["Contribute to business development and proposal pursuit as one part of growing the practice and building the advisory practice with strategic partnerships."]
    return [
        post("11111111-0000-0000-0000-000000000001", "Partner, Technology Advisory & Cloud Practice Lead", "Remote - US", "remote", 5, bd_resp, RICH_QUAL,
             "Synthetic Advisory Group is hiring a Partner to lead its technology advisory and cloud practice for healthcare and financial services clients. This role is fully remote within the US.",
             extra="Travel up to 20% for client engagements.", sal=(300000, 360000)),
        post("11111111-0000-0000-0000-000000000002", "Director, Enterprise Architecture", "Raleigh, NC", "hybrid", 4, RICH_RESP, RICH_QUAL,
             "Synthetic Advisory Group is hiring a Director, Enterprise Architecture for a hybrid position in Raleigh."),
        post("11111111-0000-0000-0000-000000000003", "Principal, Technology Consulting", "Remote - US", "remote", 6,
             ["Define and own technology strategy and operating model recommendations for client executives.", "Advise the CIO and executive leadership team of client organizations on cloud transformation and M&A technology integration.",
              "Build the practice through thought leadership and lead engagement teams of consultants."], RICH_QUAL,
             "Synthetic Advisory Group is hiring a Principal, Technology Consulting to advise C-suite clients. Remote within the US."),
        post("11111111-0000-0000-0000-000000000004", "Principal Cloud Engineer", "Remote - US", "remote", 3, ENG_RESP, ["8+ years of experience in infrastructure as code."],
             "Synthetic Advisory Group is hiring a Principal Cloud Engineer. Remote within the US."),
    ]


class _Resp:
    def __init__(self, status: int, data: Any = None, headers: Optional[dict] = None):
        self.status_code, self._data, self.headers = status, data, headers or {}

    def json(self):
        if self._data is None:
            raise ValueError("no body")
        return self._data


class FixtureSession:
    """Drop-in for requests.Session serving SYNTHETIC Greenhouse/Lever responses. Read-only."""

    GH = "https://boards-api.greenhouse.io/v1/boards/"
    LV = "https://api.lever.co/v0/postings/"
    EXPIRED_GH_IDS = {9009}

    def __init__(self, now: datetime):
        self.gh = {j["id"]: j for j in _gh_jobs(now)}
        self.lv = _lever_postings(now)
        self.calls: list[str] = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):  # noqa: A002
        if method != "GET":
            return _Resp(405)
        self.calls.append(url)
        params = params or {}
        if url.startswith(self.GH):
            parts = url[len(self.GH):].split("/")
            token = parts[0]
            if token == "synthetic-gh":
                if len(parts) == 1:
                    return _Resp(200, {"name": "Synthetic Health Co (SYNTHETIC)", "content": ""})
                if len(parts) == 2 and parts[1] == "jobs":
                    return _Resp(200, {"jobs": list(self.gh.values()), "meta": {"total": len(self.gh)}})
                if len(parts) == 3:
                    jid = int(parts[2])
                    if jid in self.gh and jid not in self.EXPIRED_GH_IDS:
                        return _Resp(200, self.gh[jid])
            return _Resp(404)
        if url.startswith(self.LV):
            parts = url[len(self.LV):].split("/")
            if parts[0] == "synthetic-lever":
                if len(parts) == 1:
                    skip, limit = int(params.get("skip", 0)), int(params.get("limit", 100))
                    return _Resp(200, self.lv[skip: skip + limit])
                for p in self.lv:
                    if p["id"] == parts[1]:
                        return _Resp(200, p)
            return _Resp(404)
        return _Resp(404)
