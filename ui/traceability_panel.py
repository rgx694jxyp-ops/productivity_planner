"""UI helpers to render drill-down traceability context."""

from __future__ import annotations

import streamlit as st


def render_traceability_panel(context: dict, *, heading: str = "Signal traceability") -> None:
    if not context:
        return

    with st.expander(heading, expanded=False):
        st.caption(f"Insight: {context.get('insight_title', '')}")
        st.write(f"Date range used: {context.get('date_range_used', 'Not specified')}")
        st.write(f"Baseline/target used: {context.get('baseline_or_target_used', 'Not specified')}")
        linked_scope = str(context.get("linked_scope", "") or "").title() or "Linked context"
        linked_label = str(context.get("linked_entity_label", "") or context.get("linked_entity_id", "") or "Not specified")
        st.write(f"{linked_scope}: {linked_label}")

        import_job = str(context.get("related_import_job_id", "") or "")
        import_file = str(context.get("related_import_file", "") or "")
        if import_job or import_file:
            st.write(f"Related import job/file: {import_job or 'n/a'} / {import_file or 'n/a'}")
        else:
            st.write("Related import job/file: Not available")

        included = context.get("included_rows")
        excluded = context.get("excluded_rows")
        if included is not None or excluded is not None:
            st.write(f"Included rows: {included if included is not None else 'n/a'}")
            st.write(f"Excluded rows: {excluded if excluded is not None else 'n/a'}")

        warnings = [str(w) for w in (context.get("warnings") or []) if str(w).strip()]
        if warnings:
            st.markdown("**Warnings / caveats**")
            for warning in warnings[:10]:
                st.caption(f"- {warning}")

        source_summary = str(context.get("source_summary", "") or "")
        if source_summary:
            st.caption(f"Sources: {source_summary}")
