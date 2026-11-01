"""Screening, remote eligibility and scoring behaviour, driven through the full pipeline on SYNTHETIC fixtures."""
from __future__ import annotations

import pytest

from helpers import ACTIVE_STATUS, QUALIFYING_VP, make_pipeline, row_by_title


@pytest.fixture()
def run(tmp_path):
    s, store, pipe, session = make_pipeline(tmp_path)
    summary = pipe.run("employer_direct")
    return s, store, pipe, summary


def test_executive_us_remote_role_qualifies_with_evidence(run):
    _, store, _, _ = run
    r = row_by_title(store, QUALIFYING_VP)
    assert r["state"] == "qualified"
    assert r["total_score"] >= 80
    assert r["work_arrangement"] == "remote"
    assert r["nc_eligibility"] in ("eligible", "not_restricted")
    assert r["active_status"] == ACTIVE_STATUS and r["verified_at"]
    assert r["score_source"] == "deterministic_provisional"  # LLM disabled -> provisional
    assert r["evidence"], "positive scoring must persist evidence excerpts"
    assert set(r["dimension_scores"]) == {
        "functional_alignment", "executive_scope", "ma_ea_transformation", "strategy_consulting",
        "industry_relevance", "compensation_progression",
    }
    assert r["salary_min"] == 280000 and r["salary_max"] == 340000  # only because the posting states it


def test_weighted_total_matches_specified_weights(run):
    _, store, _, _ = run
    d = row_by_title(store, QUALIFYING_VP)["dimension_scores"]
    expected = (d["functional_alignment"] * .30 + d["executive_scope"] * .20 + d["ma_ea_transformation"] * .20
                + d["strategy_consulting"] * .15 + d["industry_relevance"] * .10 + d["compensation_progression"] * .05)
    assert row_by_title(store, QUALIFYING_VP)["total_score"] == pytest.approx(expected, abs=0.11)


def test_principal_engineer_excluded_despite_principal_title(run):
    _, store, _, _ = run
    assert row_by_title(store, "Principal Software Engineer")["state"] == "excluded"
    assert row_by_title(store, "Principal Cloud Engineer")["state"] == "excluded"


def test_director_without_strategic_ownership_excluded(run):
    _, store, _, _ = run
    r = row_by_title(store, "Director, Digital Transformation")
    assert r["state"] == "excluded"
    assert r["total_score"] is None or r["total_score"] < 80


def test_consulting_practice_leader_with_business_development_is_not_excluded(run):
    _, store, _, _ = run
    r = row_by_title(store, "Partner, Technology Advisory & Cloud Practice Lead")
    assert r["state"] == "qualified"
    assert r["travel_requirements"] and "20%" in r["travel_requirements"]


def test_hybrid_roles_are_excluded_from_confirmed_us_remote(run):
    _, store, _, _ = run
    for title in ("Vice President, Enterprise Architecture", "Director, Enterprise Architecture"):
        r = row_by_title(store, title)
        assert r["state"] != "qualified"
        assert r["work_arrangement"] == "hybrid" or "hybrid" in (r["state_reason"] or "").lower()


def test_remote_canada_is_not_us_remote(run):
    _, store, _, _ = run
    r = row_by_title(store, "Director, Cloud Strategy")
    assert r["state"] != "qualified"


def test_state_restricted_remote_without_north_carolina_is_not_qualifying(run):
    _, store, _, _ = run
    r = row_by_title(store, "Senior Director, Technology Strategy")
    assert r["state"] != "qualified"
    assert r["nc_eligibility"] == "ineligible"
    assert {"CA", "WA", "TX"} <= set(r["eligible_states"] or [])


def test_remote_alone_is_not_proof_of_us_eligibility(run):
    _, store, _, _ = run
    r = row_by_title(store, "Managing Director, Technology Advisory")  # location is just "Remote"
    assert r["state"] != "qualified"
    assert "US" not in (r["eligible_countries"] or [])


def test_missing_salary_and_posting_date_are_not_invented(run):
    _, store, _, _ = run
    r = row_by_title(store, "Executive Director, IT Transformation")
    assert r["posted_at"] is None
    assert r["freshness"] == "unknown_date"
    assert r["salary_text"] is None and r["salary_min"] is None
    # updated_at / first_seen must never be promoted to the posting date
    assert r["updated_at"] is not None and r["first_seen_at"] is not None


def test_expired_posting_fails_active_verification(run):
    _, store, _, _ = run
    r = row_by_title(store, "Senior Vice President, Technology Strategy")
    assert r["state"] == "excluded"
    assert "expired" in r["state_reason"] or "inaccessible" in r["state_reason"]
    assert r["state"] != "qualified"


def test_insufficient_description_stays_pending_and_is_not_tracked(run, tmp_path):
    s, store, _, _ = run
    r = row_by_title(store, "VP, Enterprise Architecture")
    assert r["state"] == "pending_inspection"
    from executive_job_search.seen import SeenFile
    assert r["canonical_url"] not in SeenFile(s.seen_path).urls()


def test_all_inspected_roles_including_nonqualifying_are_tracked(run):
    s, store, _, _ = run
    from executive_job_search.seen import SeenFile
    seen = SeenFile(s.seen_path).urls()
    assert row_by_title(store, "Principal Software Engineer")["canonical_url"] in seen
    assert row_by_title(store, QUALIFYING_VP)["canonical_url"] in seen


def test_intents_are_recorded_as_local_matching_not_external_searches(run):
    _, _, _, summary = run
    ev = summary["search_intents_evaluated"]
    assert ev["external_searches_executed"] == 0
    assert "local matching" in ev["method"]
    assert len(ev["intents"]) == 14
    assert sum(ev["intents"].values()) > 0
