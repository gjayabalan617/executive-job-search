"""URL canonicalisation.

LinkedIn posting URLs: strip tracking/query strings, reduce to /jobs/view/<id>.
Employer URLs: keep only identity-bearing query parameters (e.g. gh_jid).
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

IDENTITY_PARAMS = {
    "gh_jid", "jid", "job_id", "jobid", "req_id", "reqid", "requisition_id", "jobreqid", "jr_id", "job",
}
_LINKEDIN_VIEW = re.compile(r"^/jobs/view/(?:.*?-)?(\d{6,})/?$")


def canonical_linkedin_url(url: str) -> Optional[tuple[str, str]]:
    """Return (canonical_url, job_id) for an individual LinkedIn posting URL, else None."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().split(":")[0]
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return None
    m = _LINKEDIN_VIEW.match(parts.path)
    if not m:
        return None
    return f"https://www.linkedin.com/jobs/view/{m.group(1)}", m.group(1)


def canonical_employer_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
    path = re.sub(r"/+$", "", parts.path) or "/"
    query = sorted(
        (k.lower(), v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if k.lower() in IDENTITY_PARAMS
    )
    return urlunsplit((scheme, parts.netloc.lower(), path, urlencode(query), ""))


def canonical_any(url: str) -> str:
    li = canonical_linkedin_url(url)
    return li[0] if li else canonical_employer_url(url)
