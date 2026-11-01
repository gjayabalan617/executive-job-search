"""Remote-work, US and North Carolina eligibility assessment.

"Remote" alone never proves US eligibility. Hybrid, non-US and unknown-eligibility roles are never reported as
confirmed US-remote. State restrictions are parsed from location strings and explicit description cues.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .models import Job
from .text import excerpt, sentences

_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_NAME_TO_ABBR = {v.lower(): k for k, v in _STATES.items()}
_NAMES_BY_LEN = sorted(_NAME_TO_ABBR, key=len, reverse=True)
_ABBR_TOKEN = re.compile(r"\b([A-Z]{2})\b")

REMOTE_RE = re.compile(r"\b(?:remote|telecommute|work[- ]from[- ]home)\b", re.I)
REMOTE_DESC_RE = re.compile(
    r"\b(?:fully|100%|completely)\s+remote\b|\bremote[- ](?:first|position|role|opportunity|eligible)\b|"
    r"\bthis (?:is a )?remote\b|\bwork(?:ing)? remotely\b|\bremote within the (?:US|U\.S\.|United States)\b|\bUS remote\b",
    re.I,
)
HYBRID_RE = re.compile(
    r"\bhybrid\b(?!\s+(?:cloud|multi-?cloud|it\b|infrastructure|environments?|integration|data|architectures?|network))"
    r"|\b(?:one|two|three|four|[1-4])\s+days?\s+(?:per|a|each)\s+week\s+(?:in|at|onsite|on-site)"
    r"|\bin[- ]office\s+(?:one|two|three|[1-4])\b",
    re.I,
)
ONSITE_RE = re.compile(
    r"\b(?:on-?site|in-?office)\s+(?:role|position)\b|\brequired to (?:work|be) (?:on-?site|in the office)\b|"
    r"\bmust (?:work|be) (?:on-?site|in (?:the|our) office)\b",
    re.I,
)
US_NAME_RE = re.compile(r"\b(?:united states(?: of america)?|u\.s\.a?\.?|nationwide)\b", re.I)
US_TOKEN_RE = re.compile(r"\b(?:US|USA)\b")
NON_US_RE = re.compile(
    r"\b(?:Canada|Canadian|United Kingdom|UK|England|Ireland|India|Germany|France|Spain|Netherlands|Poland|Mexico|"
    r"Brazil|Argentina|Colombia|Australia|New Zealand|Singapore|Japan|China|Philippines|Israel|EMEA|APAC|LATAM|EU|"
    r"Europe|Ontario|Quebec|British Columbia|Toronto|Vancouver|London|Bangalore|Bengaluru|Hyderabad)\b",
    re.I,
)
US_DESC_RE = re.compile(
    r"\b(?:located|based|reside|residing|live|living|work(?:ing)?)\s+(?:anywhere\s+)?(?:in|within)\s+the\s+"
    r"(?:continental\s+)?(?:US|U\.S\.|USA|United States)\b|"
    r"\banywhere in the (?:continental )?(?:US|U\.S\.|United States)\b|\bU\.?S\.?-based\b|"
    r"\bauthorized to work in the (?:US|U\.S\.|United States)\b|\bremote within the (?:US|U\.S\.|United States)\b|"
    r"\bUS remote\b|\bopen to candidates located anywhere in the United States\b",
    re.I,
)
_STATE_CUES = [
    re.compile(r"(?:reside|live|located|based)[^.\n]{0,60}?(?:following states?|one of the following|in the states? of|only in)\s*[:\-–]?\s*(?P<list>[^.\n]{2,300})", re.I),
    re.compile(r"(?:remote|hire|hiring|eligible|available)[^.\n]{0,40}?(?:following states?|only in|in the states? of)\s*[:\-–]?\s*(?P<list>[^.\n]{2,300})", re.I),
    re.compile(r"(?:eligible|approved|hiring) states?\s*[:\-–]\s*(?P<list>[^.\n]{2,300})", re.I),
]
_EXCLUDE_CUE = re.compile(
    r"(?:excluding|except(?: for)?|not (?:available|eligible|hiring) in|unable to hire in)\s+(?P<list>[^.\n]{2,200})", re.I
)
_TRAVEL_PCT = re.compile(r"travel(?:ing|s)?[^.\n]{0,60}?(\d{1,3})\s?%|(\d{1,3})\s?%[^.\n]{0,30}?travel", re.I)
_TRAVEL_HEAVY = re.compile(r"\b(?:extensive|frequent|significant|heavy|substantial|regular(?:ly)?)\b", re.I)


class RemoteAssessment(BaseModel):
    arrangement: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    us_eligibility: Literal["confirmed", "not_us", "unknown"] = "unknown"
    scope: Literal["nationwide", "state_restricted", "unknown"] = "unknown"
    eligible_countries: list[str] = Field(default_factory=list)
    eligible_states: list[str] = Field(default_factory=list)
    excluded_states: list[str] = Field(default_factory=list)
    nc_eligibility: Literal["eligible", "ineligible", "not_restricted", "unknown"] = "unknown"
    travel: Optional[str] = None
    travel_flag: bool = False
    evidence: list[str] = Field(default_factory=list)
    confirmed_us_remote: bool = False
    reasons: list[str] = Field(default_factory=list)


def extract_states(text: str) -> list[str]:
    found: list[str] = []
    work = text
    for name in _NAMES_BY_LEN:
        for m in list(re.finditer(rf"\b{re.escape(name)}\b", work, re.I)):
            if name == "washington" and re.match(r"\s*,?\s*D\.?C\b", work[m.end():], re.I):
                continue
            abbr = _NAME_TO_ABBR[name]
            if abbr not in found:
                found.append(abbr)
        work = re.sub(rf"\b{re.escape(name)}\b", " ", work, flags=re.I)
    for m in _ABBR_TOKEN.finditer(text):
        tok = m.group(1)
        if tok in _STATES and tok not in found:
            found.append(tok)
    return found


def assess_remote(job: Job) -> RemoteAssessment:
    a = RemoteAssessment()
    locs = [x for x in ([job.location] + job.all_locations) if x]
    loc_text = " | ".join(dict.fromkeys(locs))
    desc = job.description or ""
    wt = job.workplace_type

    # --- arrangement (hybrid/onsite take precedence: conservative) ---
    hybrid = wt == "hybrid" or bool(HYBRID_RE.search(loc_text)) or bool(HYBRID_RE.search(job.title)) or bool(HYBRID_RE.search(desc))
    onsite = wt == "onsite" or bool(ONSITE_RE.search(desc))
    remote_signal = wt == "remote" or bool(REMOTE_RE.search(loc_text)) or bool(REMOTE_DESC_RE.search(desc))
    if hybrid:
        a.arrangement = "hybrid"
        a.reasons.append("hybrid arrangement")
    elif onsite:
        a.arrangement = "onsite"
        a.reasons.append("on-site arrangement")
    elif remote_signal:
        a.arrangement = "remote"
        ev = loc_text if REMOTE_RE.search(loc_text) else (REMOTE_DESC_RE.search(desc).group(0) if REMOTE_DESC_RE.search(desc) else f"workplaceType={wt}")
        a.evidence.append(f"remote evidence: {excerpt(ev, 120)}")
    else:
        a.reasons.append("no explicit remote evidence")

    # --- country ---
    us_loc = bool(US_NAME_RE.search(loc_text) or US_TOKEN_RE.search(loc_text)) or (job.country_code or "").upper() == "US"
    non_us = NON_US_RE.search(loc_text)
    us_desc = US_DESC_RE.search(desc)
    loc_states = extract_states(loc_text) if loc_text else []
    if non_us and not us_loc:
        a.us_eligibility = "not_us"
        a.eligible_countries = [non_us.group(0)]
        a.reasons.append(f"location indicates non-US ({non_us.group(0)})")
    elif us_loc or us_desc:
        a.us_eligibility = "confirmed"
        a.eligible_countries = ["US"] + ([non_us.group(0)] if non_us else [])
        a.evidence.append("US evidence: " + (loc_text if us_loc else excerpt(us_desc.group(0), 120)))
    elif loc_states and a.arrangement == "remote":
        a.us_eligibility = "confirmed"
        a.eligible_countries = ["US"]
        a.evidence.append(f"US inferred from US state restriction in location: {loc_text}")
    else:
        a.reasons.append("US eligibility not explicitly stated ('remote' alone is not proof)")

    # --- state restrictions ---
    states: list[str] = list(loc_states)
    excluded: list[str] = []
    for sent in sentences(desc):
        for rx in _STATE_CUES:
            m = rx.search(sent)
            if m:
                for s in extract_states(m.group("list")):
                    if s not in states:
                        states.append(s)
        m = _EXCLUDE_CUE.search(sent)
        if m:
            for s in extract_states(m.group("list")):
                if s not in excluded:
                    excluded.append(s)
    states = [s for s in states if s not in excluded]
    a.eligible_states, a.excluded_states = states, excluded
    if states:
        a.scope = "state_restricted"
        a.evidence.append("state restriction: " + ", ".join(states))
    elif a.us_eligibility == "confirmed":
        a.scope = "nationwide"

    # --- North Carolina ---
    if a.us_eligibility == "not_us":
        a.nc_eligibility = "ineligible"
    elif states:
        a.nc_eligibility = "eligible" if "NC" in states else "ineligible"
    elif "NC" in excluded:
        a.nc_eligibility = "ineligible"
    elif a.us_eligibility == "confirmed":
        a.nc_eligibility = "not_restricted"
    if a.nc_eligibility == "ineligible" and a.us_eligibility != "not_us":
        a.reasons.append("North Carolina not an eligible state")

    # --- travel ---
    for sent in sentences(desc):
        if re.search(r"\btravel", sent, re.I):
            a.travel = excerpt(sent, 200)
            m = _TRAVEL_PCT.search(sent)
            pct = int(m.group(1) or m.group(2)) if m else None
            a.travel_flag = bool((pct is not None and pct >= 25) or _TRAVEL_HEAVY.search(sent))
            break

    a.confirmed_us_remote = (
        a.arrangement == "remote"
        and a.us_eligibility == "confirmed"
        and a.nc_eligibility in ("eligible", "not_restricted")
    )
    return a
