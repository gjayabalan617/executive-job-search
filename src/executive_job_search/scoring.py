"""Deterministic, conservative fit scoring (0-100 per dimension, weighted total)."""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

from .eligibility import RemoteAssessment
from .models import Job
from .profile import FIT_MAP
from .screening import ScreenResult
from .signals import CORE_TOPICS, INDUSTRIES, Signals

WEIGHTS = {
    "functional_alignment": 0.30,
    "executive_scope": 0.20,
    "ma_ea_transformation": 0.20,
    "strategy_consulting": 0.15,
    "industry_relevance": 0.10,
    "compensation_progression": 0.05,
}
LEVEL_SCOPE_BASE = {"svp": 55, "vp": 50, "md": 50, "partner": 50, "exec_director": 45, "head": 40, "senior_director": 35, "director": 30, "principal": 30, "none": 0}
LEVEL_PROGRESSION = {"svp": 60, "vp": 50, "md": 50, "partner": 50, "exec_director": 45, "head": 40, "senior_director": 30, "director": 25, "principal": 30, "none": 0}
_REQ_MENTIONS = re.compile(r"\b(MBA|PMP|TOGAF|CISSP|PhD|Ph\.D|master'?s degree|bachelor'?s degree|security clearance|U\.S\. citizen(?:ship)?|visa sponsorship|CPA)\b", re.I)


class ScoreResult(BaseModel):
    dimensions: dict[str, float]
    total: float
    evidence: list[dict] = Field(default_factory=list)
    explanation: str = ""
    gaps: list[str] = Field(default_factory=list)
    rationale: dict[str, str] = Field(default_factory=dict)


def clamp(x: float) -> float:
    return max(0.0, min(100.0, float(x)))


def weighted_total(dims: dict[str, float]) -> float:
    return round(sum(clamp(dims[k]) * w for k, w in WEIGHTS.items()), 1)


def band(total: float) -> str:
    return "exceptional" if total >= 90 else "strong" if total >= 80 else "potential" if total >= 70 else "exclude"


def score_job(job: Job, screen: ScreenResult, remote: RemoteAssessment, sig: Signals) -> ScoreResult:
    ev: list[dict] = []

    def add(dim: str, cat: str, n: int = 1) -> None:
        for e in sig.evidence(cat, n):
            ev.append({"dimension": dim, "signal": cat, "excerpt": e})

    # functional alignment
    exact = bool(screen.intents_matched) and not screen.equivalent_responsibilities
    base = 70 if exact else 45 if screen.equivalent_responsibilities else 0
    distinct = [c for c in CORE_TOPICS if sig.has(c)]
    functional = clamp(base + 4 * min(7, len(distinct)))
    ev.append({"dimension": "functional_alignment", "signal": "title_intent", "excerpt": f"{job.title} -> {', '.join(screen.intents_matched) or 'no intent'}"})
    for c in distinct[:3]:
        add("functional_alignment", c)

    # executive scope
    scope = LEVEL_SCOPE_BASE.get(screen.level, 0)
    for cat, pts in (("strategy_ownership", 20), ("c_suite", 10), ("leadership", 8), ("enterprise_influence", 8), ("budget_portfolio", 8)):
        if sig.has(cat):
            scope += pts
            add("executive_scope", cat)
    scope = clamp(scope)

    # M&A / EA / transformation
    ma_ea = 0
    for cat, pts in (("ma", 25), ("ma_integration", 15), ("ea", 25), ("transformation", 20), ("rationalization", 10), ("cloud", 5)):
        if sig.has(cat):
            ma_ea += pts
            add("ma_ea_transformation", cat)
    ma_ea = clamp(ma_ea)

    # technology strategy / consulting
    strat = 0
    for cat, pts in (("tech_strategy", 25), ("advisory", 25), ("practice", 10), ("cloud", 15), ("strategy_ownership", 15), ("ai", 5), ("cost_opt", 5)):
        if sig.has(cat):
            strat += pts
            add("strategy_consulting", cat)
    strat = clamp(strat)

    # industry
    hits = [i for i in INDUSTRIES if sig.has(i)]
    if hits:
        top = 70 if any(h in ("healthcare", "life_sciences", "financial_services") for h in hits) else 50
        industry = clamp(top + 15 * (len(hits) - 1))
        for h in hits[:2]:
            add("industry_relevance", h)
    else:
        industry = 25.0  # industry not stated: neutral-low, never rewarded

    # compensation / progression (unknown salary earns nothing)
    comp = LEVEL_PROGRESSION.get(screen.level, 0)
    if job.salary_max:
        comp += 40 if job.salary_max >= 300_000 else 30 if job.salary_max >= 250_000 else 20 if job.salary_max >= 200_000 else 10 if job.salary_max >= 150_000 else 0
        ev.append({"dimension": "compensation_progression", "signal": "salary", "excerpt": job.salary_text or ""})
    comp = clamp(comp)

    dims = {
        "functional_alignment": round(functional, 1),
        "executive_scope": round(scope, 1),
        "ma_ea_transformation": round(ma_ea, 1),
        "strategy_consulting": round(strat, 1),
        "industry_relevance": round(industry, 1),
        "compensation_progression": round(comp, 1),
    }
    rationale = {
        "functional_alignment": f"{'exact title-intent match' if exact else 'equivalent responsibilities only' if base else 'no intent match'}; {len(distinct)} core topics evidenced",
        "executive_scope": f"level={screen.level}; evidence categories: " + (", ".join(c for c in ("strategy_ownership", "c_suite", "leadership", "enterprise_influence", "budget_portfolio") if sig.has(c)) or "none"),
        "compensation_progression": "salary " + ("disclosed" if job.salary_max else "NOT DISCLOSED (no credit given)"),
    }
    return ScoreResult(
        dimensions=dims,
        total=weighted_total(dims),
        evidence=ev,
        explanation=build_explanation(job, sig),
        gaps=build_gaps(job, screen, remote, sig, hits),
        rationale=rationale,
    )


def build_explanation(job: Job, sig: Signals) -> str:
    labels = {"ea": "enterprise architecture", "ma": "technology M&A due diligence", "ma_integration": "M&A integration and separation",
              "tech_strategy": "technology strategy and operating models", "transformation": "transformation leadership",
              "cloud": "cloud strategy", "advisory": "consulting and advisory", "practice": "practice leadership",
              "rationalization": "application rationalization"}
    focus = [labels[c] for c in labels if sig.has(c)][:3]
    first = f"{job.title} at {job.company} centers on {', '.join(focus) if focus else 'technology leadership'}."
    mapped = []
    for cat in ("ma", "ma_integration", "ea", "rationalization", "tech_strategy", "practice", "advisory", "cloud", "financial_services", "healthcare", "life_sciences"):
        if sig.has(cat) and FIT_MAP[cat] not in mapped:
            mapped.append(FIT_MAP[cat])
        if len(mapped) == 2:
            break
    second = ("That lines up with " + " and ".join(mapped) + ".") if mapped else "Overlap with his documented experience is limited to general technology leadership."
    third = "Scoring is based only on what the posting states; unstated scope is not credited."
    return " ".join([first, second, third])


def build_gaps(job: Job, screen: ScreenResult, remote: RemoteAssessment, sig: Signals, industry_hits: list[str]) -> list[str]:
    gaps: list[str] = []
    if not job.salary_max and not job.salary_text:
        gaps.append("Salary not disclosed.")
    if not sig.has("c_suite"):
        gaps.append("No explicit C-suite/executive stakeholder exposure stated.")
    if not sig.has("leadership"):
        gaps.append("No explicit people-leadership scope stated.")
    if not sig.has("budget_portfolio"):
        gaps.append("No budget or portfolio responsibility stated.")
    if not industry_hits:
        gaps.append("Industry not stated or outside his healthcare/life sciences/financial services/manufacturing/logistics background.")
    if remote.scope == "state_restricted":
        gaps.append("State-restricted remote: " + ", ".join(remote.eligible_states) + ".")
    if remote.travel_flag:
        gaps.append("Material travel flagged: " + (remote.travel or ""))
    elif remote.travel:
        gaps.append("Travel mentioned: " + remote.travel)
    if job.posted_at is None:
        gaps.append("Source posting date not available; recency unverified.")
    for m in sorted({m.group(0) for m in _REQ_MENTIONS.finditer(job.description)}, key=str.lower):
        gaps.append(f"Posting mentions '{m}'; the candidate profile does not state this, so verify.")
    if job.required_experience:
        gaps.append(f"Requires {job.required_experience} (candidate has 23+ years overall; relevance of specific domains unverified).")
    return gaps
