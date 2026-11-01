"""Extract structured facts from posting text. Only explicit statements are extracted; nothing is estimated."""
from __future__ import annotations

import re
from typing import Optional

from .models import Job
from .text import excerpt, sentences

_SAL_RE = re.compile(
    r"\$\s?(\d{2,3}(?:,\d{3})+|\d{2,3}\s?[kK])\s*(?:-|–|—|to)\s*\$?\s?(\d{2,3}(?:,\d{3})+|\d{2,3}\s?[kK])"
)
_EXP_RE = re.compile(r"(\d{1,2})\s?\+?\s*(?:or more\s+)?years?", re.I)
_RESP_HEAD = re.compile(
    r"^(?:key |core |primary )?(?:responsibilit(?:y|ies)|what you(?:'|’)?ll do|what you will do|in this role|the role)\b", re.I
)
_RESP_STOP = re.compile(
    r"^(?:required |minimum |basic )?(?:qualifications|requirements|what you(?:'|’)?ll bring|about you|preferred|who you are|benefits|compensation)\b",
    re.I,
)


def _num(s: str) -> float:
    s = s.replace(",", "").replace(" ", "")
    return float(s[:-1]) * 1000 if s[-1] in "kK" else float(s)


def extract_salary_from_text(text: str) -> Optional[dict]:
    m = _SAL_RE.search(text)
    if not m:
        return None
    lo, hi = _num(m.group(1)), _num(m.group(2))
    ctx = text[max(0, m.start() - 60): m.end() + 60].lower()
    interval = "hour" if "hour" in ctx else "year" if re.search(r"year|annual|salary|base", ctx) else None
    return {"text": m.group(0).strip(), "min": min(lo, hi), "max": max(lo, hi), "currency": "USD", "interval": interval}


def extract_required_experience(text: str) -> Optional[str]:
    for sent in sentences(text):
        if "experience" in sent.lower():
            m = _EXP_RE.search(sent)
            if m:
                plus = "+" if "+" in sent[m.start(): m.end() + 2] or "or more" in sent.lower() else ""
                return f"{m.group(1)}{plus} years"
    return None


def extract_responsibilities(text: str, limit: int = 15) -> list[str]:
    lines = [ln.strip(" •-\t") for ln in text.splitlines()]
    out: list[str] = []
    collecting = False
    for ln in lines:
        if not ln:
            continue
        head = ln.rstrip(":").strip()
        if not collecting:
            if _RESP_HEAD.match(head) and len(head) < 60:
                collecting = True
            continue
        if _RESP_STOP.match(head) and len(head) < 60:
            break
        out.append(excerpt(ln, 300))
        if len(out) >= limit:
            break
    return out


def finalize_job(job: Job) -> Job:
    """Fill derived fields from the description when the source did not supply them."""
    if job.salary_min is None and job.salary_max is None and not job.salary_text:
        sal = extract_salary_from_text(job.description)
        if sal:
            job.salary_text, job.salary_min, job.salary_max = sal["text"], sal["min"], sal["max"]
            job.salary_currency, job.salary_interval = sal["currency"], sal["interval"]
    if not job.required_experience:
        job.required_experience = extract_required_experience(job.description)
    if not job.responsibilities:
        job.responsibilities = extract_responsibilities(job.description)
    return job
