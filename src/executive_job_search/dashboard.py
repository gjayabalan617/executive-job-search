"""Streamlit dashboard (read-only). Run bound to localhost:

    streamlit run src/executive_job_search/dashboard.py --server.address 127.0.0.1 --server.port 8501

NOTE: Streamlit could not be installed in the build sandbox, so this file was only syntax-checked there.
All data access lives in ui_data.py, which is covered by the test suite.
"""
from __future__ import annotations

import streamlit as st  # type: ignore[import-not-found]

from executive_job_search.config import load_settings
from executive_job_search.store import Store
from executive_job_search import ui_data

st.set_page_config(page_title="Executive Job Search", layout="wide")
settings = load_settings()
store = Store(settings.db_path)
data = ui_data.overview(store)

st.title("Executive technology roles")
st.caption("Candidate data is local. Bind this dashboard to localhost only; do not expose it publicly.")
last = data["last_run"]
if last:
    st.write(f"Last run: **{last['status']}** · mode `{last['mode']}` · {last['started_at']}")
    summary = last.get("summary") or {}
    if summary.get("label"):
        st.warning(summary["label"])
    if summary.get("source_failures"):
        st.error("Source failures: " + "; ".join(summary["source_failures"]))
else:
    st.info("No runs recorded yet.")

cols = st.columns(len(data["counts"]))
for col, (k, v) in zip(cols, data["counts"].items()):
    col.metric(k, v)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Newly posted", "Unknown date", "Pending retries", "Outbox", "Job detail"])
with tab1:
    st.dataframe(data["newly_posted"], use_container_width=True)
with tab2:
    st.caption("Discovered but NOT confirmed newly posted (no reliable source date).")
    st.dataframe(data["unknown_date"], use_container_width=True)
with tab3:
    st.dataframe(data["pending"], use_container_width=True)
with tab4:
    st.dataframe(data["outbox"], use_container_width=True)
with tab5:
    job_id = st.number_input("Job id", min_value=1, step=1)
    detail = ui_data.job_detail(store, int(job_id))
    if detail:
        st.subheader(f"{detail['title']} — {detail['company']}")
        st.write(detail.get("match_explanation"))
        st.json({k: detail.get(k) for k in ("state", "state_reason", "total_score", "dimension_scores", "remote_assessment", "potential_gaps", "evidence")})
        with st.expander("Full description"):
            st.text(detail.get("description") or "")
