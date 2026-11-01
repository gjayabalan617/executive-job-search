"""Evidence extraction: sentence-level signal detection with verbatim excerpts."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import excerpt, sentences

_OWN_VERB = re.compile(
    r"\b(?:own|owns|owning|define|defines|defining|set|sets|setting|lead|leads|leading|drive|drives|driving|"
    r"develop|develops|developing|establish|establishes|shape|shapes|accountable for|responsible for|direct|directs)\b",
    re.I,
)
_STRAT_OBJ = re.compile(
    r"\b(?:technology|IT|enterprise|architecture|architectural|digital|cloud|transformation|M&A|integration|application|portfolio)"
    r"\s+(?:\w+\s+)?(?:strategy|strategies|roadmap|roadmaps|vision|operating models?|target state)\b",
    re.I,
)

PATTERNS: dict[str, re.Pattern] = {
    k: re.compile(v, re.I)
    for k, v in {
        "enterprise_influence": r"enterprise[- ]wide|across the (?:enterprise|organization|company|business)|architecture review board|governance|cross-functional|standards",
        "leadership": r"direct reports|manages? (?:a )?team|lead(?:s|ing)? (?:a )?(?:high-performing )?team|build and lead|leadership team|people leader|team of \d+|hire and develop|mentor",
        "c_suite": r"c-suite|c-level|\bCIO\b|\bCTO\b|\bCFO\b|\bCEO\b|\bCOO\b|executive (?:leadership|stakeholders?|sponsors?|team)|board of directors|senior executives|steering committee",
        "budget_portfolio": r"\bbudgets?\b|P&L|\bportfolio\b|investment (?:decisions|portfolio)|\bspend\b",
        "transformation": r"transformation|modernization|modernisation|migration",
        "ma": r"\bM&A\b|merger|acquisition|due diligence|post-merger|carve-?out|divestiture",
        "ma_integration": r"integration|\bTSA\b|transition services|separation|carve-?out|post-merger|\bPMI\b",
        "ea": r"enterprise architecture|architecture (?:governance|strategy|standards|roadmap)|target[- ]state architecture|reference architecture|architecture review board",
        "tech_strategy": r"(?:technology|IT|digital|cloud) strategy|technology roadmap|operating model",
        "advisory": r"\badvis(?:e|es|ing|ory|or|ors)\b|\bconsult(?:ing|ant|ants)\b|\bclients?\b|client-facing|\bengagements?\b",
        "practice": r"practice (?:lead|leader|building|development|growth)|(?:build|grow|scale)(?:ing)? (?:the|a|our) (?:\w+ )?practice|\bpractice\b",
        "cloud": r"\b(?:AWS|Azure|GCP|Google Cloud)\b|cloud (?:strategy|transformation|migration|adoption)",
        "ai": r"\bAI\b|artificial intelligence|generative",
        "rationalization": r"rationali[sz]ation|portfolio assessment|application portfolio|decommission|consolidat",
        "cost_opt": r"cost optimi[sz]ation|IT cost|cost reduction|FinOps|savings",
        "healthcare": r"health ?care|hospital|payer|clinical|diagnostic|laborator",
        "life_sciences": r"life sciences?|pharma|biotech|medical device",
        "financial_services": r"financial services|banking|\bbank\b|insurance|capital markets|wealth management|fintech",
        "manufacturing": r"manufactur|packaging|industrial",
        "logistics": r"logistics|supply chain|transportation",
    }.items()
}
CORE_TOPICS = ("ea", "ma", "tech_strategy", "transformation", "cloud", "rationalization", "cost_opt", "advisory", "practice")
INDUSTRIES = ("healthcare", "life_sciences", "financial_services", "manufacturing", "logistics")


@dataclass
class Signals:
    hits: dict[str, list[str]] = field(default_factory=dict)

    def has(self, cat: str) -> bool:
        return bool(self.hits.get(cat))

    def count(self, cat: str) -> int:
        return len(self.hits.get(cat, []))

    def evidence(self, cat: str, n: int = 2) -> list[str]:
        return self.hits.get(cat, [])[:n]


def compute_signals(description: str) -> Signals:
    sig = Signals()
    for s in sentences(description):
        for cat, rx in PATTERNS.items():
            if rx.search(s):
                sig.hits.setdefault(cat, []).append(excerpt(s))
        if _OWN_VERB.search(s) and _STRAT_OBJ.search(s):
            sig.hits.setdefault("strategy_ownership", []).append(excerpt(s))
    return sig
