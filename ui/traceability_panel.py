"""UI helpers to render drill-down traceability context."""

from __future__ import annotations

import streamlit as st


def _maturity_label_from_context(context: dict) -> str:
    explicit = str(context.get("signal_maturity_label") or "").strip().lower()
    if explicit in {"stable signal", "early signal", "limited-data prompt"}:
        return explicit

    included = context.get("included_rows")
    sample = context.get("confidence_sample_size")
    try:
        if included is not None and int(included) > 0 and int(included) < 3:
            return "limited-data prompt"
    except Exception:
        pass
    try:
        if sample is not None and int(sample) > 0 and int(sample) < 3:
            return "limited-data prompt"
    except Exception:
        pass

    confidence = str(context.get("confidence_level") or "").strip().lower()
    if confidence == "low":
        return "early signal"
    return "stable signal"


def _confidence_explanation(context: dict) -> str:
    level = str(context.get("confidence_level") or "").strip().lower()
    basis = str(context.get("confidence_basis") or "").strip()
    caveat = str(context.get("confidence_caveat") or "").strip()
    sample = context.get("confidence_sample_size")
    min_points = context.get("confidence_minimum_points")

    if level == "low":
        if basis:
            return f"Confidence is low because {basis[0].lower() + basis[1:] if len(basis) > 1 else basis.lower()}"
        if sample is not None and min_points is not None:
            try:
                return f"Confidence is low because only {int(sample)} usable points are available (stable trend typically needs {int(min_points)}+)"
            except Exception:
                pass
        if caveat:
            return f"Confidence is low because {caveat[0].lower() + caveat[1:] if len(caveat) > 1 else caveat.lower()}"
        return "Confidence is low because evidence coverage is limited in the current snapshot"

    if level == "medium":
        if basis:
            return f"Confidence is medium because {basis[0].lower() + basis[1:] if len(basis) > 1 else basis.lower()}"
        return "Confidence is medium because evidence coverage is partial"

    if level == "high":
        if basis:
            return f"Confidence is high because {basis[0].lower() + basis[1:] if len(basis) > 1 else basis.lower()}"
        return "Confidence is high because evidence coverage is strong"

    return "Confidence is not fully specified in this context"


def _data_basis_statement(context: dict) -> str:
    included = context.get("included_rows")
    sample = context.get("confidence_sample_size")
    source_summary = str(context.get("source_summary") or "").strip()
    if included is not None:
        try:
            value = int(included)
            if value >= 1:
                base = f"Based on {value} usable records"
                return f"{base} from {source_summary}" if source_summary else base
        except Exception:
            pass
    if sample is not None:
        try:
            value = int(sample)
            if value >= 1:
                base = f"Based on {value} recent records"
                return f"{base} from {source_summary}" if source_summary else base
        except Exception:
            pass
    return "Latest snapshot only"


def _comparison_statement(context: dict) -> str:
    comparison = str(context.get("comparison_statement") or context.get("baseline_or_target_used") or "").strip()
    if comparison:
        lowered = comparison.lower()
        if lowered.startswith("compared with"):
            return comparison
        if lowered.startswith("compared to"):
            return comparison.replace("Compared to", "Compared with", 1)
        return f"Compared with {comparison}"
    return "Compared with available snapshot context only; baseline comparison is limited or missing"


def _freshness_statement(context: dict) -> str:
    freshness = str(context.get("freshness_statement") or "").strip()
    if freshness:
        return freshness
    observed = str(context.get("date_range_used") or context.get("observed_window_label") or "").strip()
    if observed:
        return f"Freshness: {observed}"
    return "Freshness: Latest snapshot"


def render_traceability_panel(context: dict, *, heading: str = "Signal traceability") -> None:
    if not context:
        return

    signal_summary = str(context.get("signal_summary") or context.get("insight_title") or "Signal detail").strip()
    surfaced_because = str(context.get("surfaced_because") or "").strip()
    if not surfaced_because:
        surfaced_because = "Surfaced because this signal met display thresholds in the latest data window"
    elif not surfaced_because.lower().startswith("surfaced because"):
        surfaced_because = f"Surfaced because {surfaced_because[0].lower() + surfaced_because[1:] if len(surfaced_because) > 1 else surfaced_because.lower()}"

    maturity = _maturity_label_from_context(context)
    maturity_reason = str(context.get("signal_maturity_reason") or "").strip()
    maturity_line = f"{maturity.title()}"
    if maturity_reason:
        maturity_line = f"{maturity.title()}: {maturity_reason}"
    elif maturity == "early signal":
        maturity_line = "Early signal: this reflects an early signal and may stabilize as more data arrives"
    elif maturity == "limited-data prompt":
        maturity_line = "Limited-data prompt: fewer than 3 usable points are available"
    else:
        maturity_line = "Stable signal: evidence and comparison context are sufficiently established"

    with st.container(border=True):
        st.markdown(f"**{heading}**")
        st.markdown(f"### {signal_summary}")
        st.write(surfaced_because)
        st.write(_confidence_explanation(context))
        st.write(_data_basis_statement(context))
        st.write(_comparison_statement(context))
        st.write(_freshness_statement(context))
        st.write(maturity_line)

        linked_scope = str(context.get("linked_scope", "") or "").title() or "Linked context"
        linked_label = str(context.get("linked_entity_label", "") or context.get("linked_entity_id", "") or "Not specified")
        st.caption(f"{linked_scope}: {linked_label}")

        warnings = [str(w) for w in (context.get("warnings") or []) if str(w).strip()]
        if warnings:
            st.caption("Data notes: " + " | ".join(warnings[:3]))
