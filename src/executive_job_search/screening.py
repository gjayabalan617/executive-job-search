"""Deterministic screening: level, intent matching, and hard exclusions."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from .models import Job
from .signals import Signals, compute_signals

LEVEL_PATTERNS = [
    ("svp", re.compile(r"\b(?:svp|senior vice president|evp|executive vice president)\b", re.I)),
    ("vp", re.compile(r"\b(?:vp|vice president)\b", re.I)),
    ("md", re.compile(r"\bmanaging director\b", re.I)),
    ("partner", re.compile(r"\bpartner\b(?!\s*(?:success|manager|marketing|enablement|program))", re.I)),
    ("exec_director", re.compile(r"\bexecutive director\b", re.I)),
    ("senior_director", re.compile(r"\b(?:senior|sr\.?) director\b", re.I)),
    ("director", re.compile(r"(?<!associate )(?<!assistant )\bdirector\b", re.I)),
    ("head", re.compile(r"\bhead\s+of\b|\bhead,", re.I)),
    ("principal", re.compile(r"\bprincipal\b", re.I)),
]
LEVEL_RANK = {"svp": 6, "vp": 5, "md": 5, "partner": 5, "exec_director": 4, "senior_director": 3, "director": 2, "head": 3, "principal": 2, "none": 0}
DIRECTOR_GROUP = {"director", "senior_director", "exec_director", "head"}
VP_GROUP = {"vp", "svp"}

_EA = r"enterprise architecture|enterprise architect(?:ure)? (?:strategy|practice)"
_TRANSFORM = r"(?:digital|enterprise|technology|it|business|cloud) transformation|transformation"
_MA_TECH = r"(?:technology|it)\s+m\s?&\s?a|m\s?&\s?a\s+(?:technology|it|integration|advisory)|(?:technology|it)\s+(?:due diligence|mergers)|technology\s+(?:m&a|integration)"
_STRAT = r"(?:technology|it|digital|cloud)\s+strategy|strategy"
_ADV = r"(?:technology|it|digital|cloud)\s+(?:consulting|advisory)|advisory|consulting"

DEFAULT_INTENTS = [
    {"name": "Director Enterprise Architecture", "levels": ["director", "senior_director", "exec_director"], "topics": [_EA]},
    {"name": "VP Enterprise Architecture", "levels": ["vp", "svp"], "topics": [_EA]},
    {"name": "Director Digital Transformation", "levels": ["director", "senior_director", "exec_director"], "topics": [_TRANSFORM]},
    {"name": "Director Technology M&A", "levels": ["director", "senior_director", "exec_director"], "topics": [_MA_TECH, r"m\s?&\s?a"]},
    {"name": "VP Technology Strategy", "levels": ["vp", "svp"], "topics": [_STRAT]},
    {"name": "Director Cloud Strategy", "levels": ["director", "senior_director", "exec_director"], "topics": [r"cloud\s+(?:strategy|transformation|advisory|consulting)"]},
    {"name": "Director IT Strategy Consulting", "levels": ["director", "senior_director", "exec_director"], "topics": [r"(?:it|technology)\s+strategy", _ADV]},
    {"name": "VP Corporate Development Technology", "levels": ["vp", "svp", "exec_director"], "topics": [r"corporate development", r"corp(?:orate)? dev"]},
    {"name": "Director Technology Due Diligence", "levels": ["director", "senior_director", "exec_director"], "topics": [r"due diligence"]},
    {"name": "Managing Director Technology Advisory", "levels": ["md", "partner"], "topics": [_ADV, r"technology"]},
    {"name": "Head of Enterprise Architecture", "levels": ["head"], "topics": [_EA, r"technology strategy", r"digital transformation"]},
    {"name": "Principal Technology Consulting", "levels": ["principal"], "topics": [r"(?:technology|it|cloud|digital)\s+(?:consulting|advisory|strategy)", _EA]},
    {"name": "VP Technology Transformation", "levels": ["vp", "svp"], "topics": [_TRANSFORM]},
    {"name": "Director M&A Integration", "levels": ["director", "senior_director", "exec_director"], "topics": [r"(?:m\s?&\s?a|merger|post-merger|acquisition)\s*(?:technology\s*)?integration", r"integration management"]},
]

_SALES = re.compile(r"\b(?:sales|account (?:executive|manager)|business development|marketing|recruit(?:er|ing)|talent acquisition|human resources|\bhr\b|people (?:partner|operations)|customer success|sdr|bdr)\b", re.I)
_COMMISSION = re.compile(r"commission[- ]only|100% commission|commission[- ]based", re.I)
_HANDS_ON = re.compile(r"\b(?:software|devops|sre|data|cloud|solutions?|security|network|infrastructure|platform|application|systems?|full[- ]stack|backend|frontend)\s+(?:engineer|developer)\b|\b(?:engineer|developer|programmer)\b", re.I)
_ENG_MGMT = re.compile(r"\b(?:engineering manager|manager,? engineering|(?:director|vp|head) (?:of )?engineering)\b", re.I)
_INFRA_OPS = re.compile(r"\b(?:infrastructure|operations|data ?center|network|noc|sysadmin|site reliability|service desk|help ?desk|support)\b", re.I)
_STRATEGY_TITLE = re.compile(r"strateg|architecture|transformation|m\s?&\s?a|advisory|consulting|due diligence|corporate development", re.I)
_BELOW = re.compile(r"\b(?:manager|analyst|associate|specialist|consultant|lead|coordinator|intern|engineer|developer|administrator)\b", re.I)
_PROGRAM = re.compile(r"\b(?:program|project) (?:manager|management)\b", re.I)
_UNRELATED = re.compile(r"\b(?:sap|salesforce|workday|servicenow|oracle (?:ebs|fusion)|netsuite|cyber ?security|information security|ciso|clinical|nurs(?:e|ing)|pharmac(?:y|ist)|legal|counsel|accounting|tax|procurement|supply chain|data scien(?:ce|tist)|machine learning|research scientist)\b", re.I)
_ARCHITECT = re.compile(r"\barchitect\b", re.I)


class Intent(BaseModel):
    name: str
    levels: list[str]
    topics: list[str]

    def compiled(self) -> list[re.Pattern]:
        return [re.compile(t, re.I) for t in self.topics]


class ScreenResult(BaseModel):
    level: str = "none"
    intents_matched: list[str] = Field(default_factory=list)
    equivalent_responsibilities: bool = False
    excluded: bool = False
    reasons: list[str] = Field(default_factory=list)


def load_intents(path: Optional[Path] = None) -> list[Intent]:
    if path and Path(path).exists():
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return [Intent(**i) for i in doc.get("intents", [])]
    return [Intent(**i) for i in DEFAULT_INTENTS]


def classify_level(title: str) -> str:
    for name, rx in LEVEL_PATTERNS:
        if rx.search(title):
            return name
    return "none"


def exec_advisory_evidence(sig: Signals) -> bool:
    """Genuine executive-advisory scope required for Principal-level roles."""
    return sig.has("c_suite") and sig.has("advisory") and (sig.has("strategy_ownership") or sig.has("practice"))


def screen_job(job: Job, intents: list[Intent], sig: Optional[Signals] = None) -> ScreenResult:
    sig = sig or compute_signals(job.description)
    title = job.title
    r = ScreenResult(level=classify_level(title))
    ex = r.reasons

    if _COMMISSION.search(job.description) or _COMMISSION.search(title):
        ex.append("commission-only compensation")
    if _SALES.search(title):
        ex.append("sales/marketing/HR/recruiting title")
    if re.search(r"\b(?:software|developer|programmer)\b", title, re.I) or re.search(r"\bengineer(?:ing)?\b", title, re.I) and r.level in ("none", "principal"):
        ex.append("hands-on engineering role")
    if _ENG_MGMT.search(title) and not _STRATEGY_TITLE.search(title):
        ex.append("engineering management without technology strategy ownership")
    if r.level in DIRECTOR_GROUP | VP_GROUP | {"md"} and _INFRA_OPS.search(title) and not _STRATEGY_TITLE.search(title):
        ex.append("infrastructure/operations management without strategy ownership")
    if _PROGRAM.search(title) and not (_STRATEGY_TITLE.search(title) and sig.has("strategy_ownership")):
        ex.append("program/project management without strategy authority")
    if _UNRELATED.search(title):
        ex.append("unrelated deep specialization")
    if r.level == "none":
        ex.append("below Director level / no executive level in title")
    elif r.level == "principal":
        if not exec_advisory_evidence(sig):
            ex.append("Principal title without executive-advisory evidence (C-suite exposure, advisory, strategy/practice ownership)")
        elif _ARCHITECT.search(title) and not exec_advisory_evidence(sig):
            ex.append("individual-contributor architecture role")
    elif r.level in DIRECTOR_GROUP:
        if not sig.has("strategy_ownership") or not (sig.has("c_suite") or sig.has("transformation")):
            ex.append("Director-level role lacking strategic ownership, executive visibility or transformation responsibility")
    if r.level == "none" and _ARCHITECT.search(title):
        ex.append("individual-contributor architecture role")

    # --- intent coverage (local matching only; no external searches are implied) ---
    for intent in intents:
        if r.level in intent.levels and any(rx.search(title) for rx in intent.compiled()):
            r.intents_matched.append(intent.name)
    if not r.intents_matched and r.level != "none":
        distinct = sum(sig.has(c) for c in ("ea", "ma", "tech_strategy", "transformation", "cloud", "advisory"))
        if distinct >= 4:
            r.equivalent_responsibilities = True
            r.intents_matched.append("equivalent_responsibilities")
        else:
            ex.append("title/responsibilities do not match any configured search intent")

    r.excluded = bool(ex)
    r.reasons = list(dict.fromkeys(ex))
    return r
