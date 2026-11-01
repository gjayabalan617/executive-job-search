"""Candidate profile. Contains ONLY facts supplied by the operator; nothing is inferred
(no degrees, certifications, deal counts, team sizes, budgets, P&L, citizenship, clearance or work authorisation)."""
from __future__ import annotations

PROFILE_VERSION = "2026-10-31.1"
SCORING_VERSION = "det-1.0"

CANDIDATE = {
    "name": "Gokulnath Jayabalan",
    "location": "Apex, North Carolina, United States",
    "experience": "23+ years",
    "positioning": [
        "Enterprise Technology Executive", "M&A Technology Advisory", "Enterprise Architecture",
        "Digital Transformation", "IT Strategy", "Cloud Strategy", "Technology Consulting",
    ],
    "experience_by_employer": {
        "Labcorp": "enterprise architecture, M&A technology due diligence and integration",
        "Graphic Packaging": "enterprise architecture, application rationalization, technology strategy",
        "RCG Global Services": "director-level consulting, cloud practice leadership, program management, technology advisory",
        "Syntel": "technology consulting, enterprise solutions, client leadership",
        "Citibank": "enterprise technology and financial services",
    },
    "competencies": [
        "Technology M&A due diligence and integration", "architecture governance", "digital transformation",
        "modernization", "technology operating models", "AWS/Azure/GCP strategy", "IT cost optimization",
        "application rationalization", "technology portfolio assessment", "TSA and separation planning",
        "C-suite advisory", "practice development", "strategic partnerships", "AI transformation advisory",
    ],
    "industries": [
        "healthcare", "life sciences", "banking", "financial services", "insurance", "manufacturing", "logistics",
    ],
}

# Snippets used to explain fit in the candidate's own terms.
FIT_MAP = {
    "ma": "Labcorp work on enterprise architecture and M&A technology due diligence and integration",
    "ma_integration": "Labcorp M&A technology integration, plus his TSA and separation planning competencies",
    "ea": "Labcorp and Graphic Packaging enterprise architecture experience",
    "rationalization": "Graphic Packaging application rationalization and technology strategy work",
    "tech_strategy": "Graphic Packaging technology strategy and his technology operating model experience",
    "practice": "RCG Global Services director-level consulting and cloud practice leadership",
    "advisory": "RCG Global Services technology advisory work and Syntel client leadership",
    "cloud": "his AWS/Azure/GCP strategy competencies and RCG cloud practice leadership",
    "financial_services": "his Citibank financial-services background",
    "healthcare": "his Labcorp healthcare and life-sciences background",
    "life_sciences": "his Labcorp healthcare and life-sciences background",
}
