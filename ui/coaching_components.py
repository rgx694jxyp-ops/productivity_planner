"""Coaching-specific UI components and action rails."""

import streamlit as st
from datetime import datetime, date
import html as _html_mod

from services.recommendation_service import _render_adaptive_action_suggestion
from services.coaching_service import _get_primary_recommendation
from domain.risk_scoring import _compute_priority_summary


def _render_priority_strip(gs: list[dict], history: list[dict]):
    """Top-of-page signal strip summarizing where priority patterns are surfacing."""
    p = _compute_priority_summary(gs, history)
    c1, c2, c3 = st.columns(3)
    c1.metric("⚠️ Below Goal", p["below"])
    c2.metric("🔥 Critical Risk", p["critical"])
    c3.metric("📈 Quick Wins", p["quick_wins"])

    a1, a2 = st.columns(2)
    if a1.button("View Priority List", use_container_width=True, key="pri_strip_priority"):
        st.session_state["goto_page"] = "productivity"
        st.session_state["prod_view"] = "📋 Priority List"
        st.rerun()
    if a2.button("Open Journal", use_container_width=True, key="pri_strip_coaching"):
        st.session_state["goto_page"] = "employees"
        st.session_state["emp_view"] = "Performance Journal"
        st.rerun()


def _render_primary_action_rail(gs: list[dict], history: list[dict], key_prefix: str):
    """Dominant command-bar panel — visually anchors every key page with one clear action."""
    rec = _get_primary_recommendation(gs, history)
    remaining = [r for r in gs if r.get("goal_status") == "below_goal"]

    if not rec:
        st.markdown(
            '<div class="dpd-rail">'
            '<div class="dpd-rail-label">▶ Primary Signal</div>'
            '<div class="dpd-rail-ok">✓ All employees on track — no priority signal surfaced</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        return

    last_coached_id = st.session_state.get("_last_coached_emp_id", None)
    adaptive = _render_adaptive_action_suggestion(
        gs,
        history,
        last_coached_id,
        coached_today=int(st.session_state.get("_coached_today", 0)),
    )

    _name_raw = adaptive["name"] if adaptive else rec.get("name", "")
    _dept_raw = rec.get("department", "")
    _context_raw = adaptive["context"] if adaptive and "context" in adaptive else rec.get("why", "")
    _name = _html_mod.escape(str(_name_raw) if _name_raw is not None else "")
    _dept = _html_mod.escape(str(_dept_raw) if _dept_raw is not None else "")
    _context = _html_mod.escape(str(_context_raw) if _context_raw is not None else "")
    _dept_str = f" · {_dept}" if _dept else ""
    _n_remaining = len(remaining)

    rail_style = "color: #FFFFFF;"
    if adaptive and adaptive.get("priority") == "critical":
        rail_style = "background: linear-gradient(90deg, #8B0000 0%, #DC143C 100%); color: #FFFFFF;"
    elif adaptive and adaptive.get("priority") == "high":
        rail_style = "background: linear-gradient(90deg, #FF6347 0%, #FF7F50 100%); color: #FFFFFF;"

    _remaining_note = (
        f"<div class='dpd-rail-label' style='color:#FFFFFF !important;'>⬇ {_n_remaining - 1} more below goal</div>"
        if _n_remaining > 1
        else ""
    )

    st.markdown(
        f'<div class="dpd-rail" style="{rail_style}">'
        f'<div class="dpd-rail-label" style="color:#FFFFFF !important;">▶ Primary Signal</div>'
        f'<div class="dpd-rail-name">{_name}{_dept_str}</div>'
        f'<div class="dpd-rail-why">{_context}</div>'
        f"{_remaining_note}"
        "</div>",
        unsafe_allow_html=True,
    )

    if adaptive and "emphasis" in adaptive:
        st.caption(f"💡 {adaptive['emphasis']}")

    col1, col2 = st.columns(2)
    action_label = adaptive.get("action", "Open Journal") if adaptive else "Open Journal"
    if col1.button(f"▶ {action_label}", key=f"{key_prefix}_start_coach", type="primary", use_container_width=True):
        st.session_state["goto_page"] = "employees"
        st.session_state["emp_view"] = "Performance Journal"
        st.session_state["cn_selected_emp"] = rec["emp_id"]
        st.rerun()
    if col2.button("View Context →", key=f"{key_prefix}_view_context", use_container_width=True):
        st.session_state["goto_page"] = "dashboard"
        st.rerun()
    if _n_remaining > 1:
        st.caption(f"{_n_remaining} employee(s) below goal · sorted by highest risk")


def _render_soft_action_buttons(emp_id: str, emp_name: str, risk_level: str, context_tags: list[str] | None = None):
    """Render soft action buttons for medium-risk employees."""
    if not risk_level.startswith("🟡"):
        return

    st.markdown("**💡 Quick Actions — No coaching needed**")

    col1, col2, col3 = st.columns(3)

    if col1.button(
        "⏰ Schedule Check-In",
        key=f"soft_checkin_{emp_id}",
        help="Brief conversation to prevent decline (not formal coaching)",
        use_container_width=True,
    ):
        from database import add_coaching_note

        add_coaching_note(
            emp_id,
            "[SCHEDULED] Brief check-in queued — quick conversation to identify trends before they worsen.",
            "System",
        )
        st.success(f"✓ Check-in scheduled for {emp_name}")
        st.rerun()

    if col2.button(
        "📝 Add Note",
        key=f"soft_note_{emp_id}",
        help="Log observation without full coaching",
        use_container_width=True,
    ):
        st.session_state["soft_note_emp_id"] = emp_id
        st.session_state["show_soft_note_input"] = True

    if col3.button(
        "▶ Full Coaching",
        key=f"soft_escalate_{emp_id}",
        help="Move to formal coaching session",
        use_container_width=True,
        type="secondary",
    ):
        st.session_state["goto_page"] = "employees"
        st.session_state["emp_view"] = "Performance Journal"
        st.session_state["cn_selected_emp"] = emp_id
        st.rerun()

    st.caption("📌 **Add context** if applicable:")
    context_tags = context_tags or []

    CONTEXT_OPTIONS = ["Equipment issues", "New employee", "Cross-training", "Shift change", "Short staffed"]

    c1, c2, c3 = st.columns(3)
    cols = [c1, c2, c3]

    for i, ctx_opt in enumerate(CONTEXT_OPTIONS[:3]):
        col_idx = i % 3
        is_selected = ctx_opt in context_tags
        if cols[col_idx].button(
            f"{'✓' if is_selected else '○'} {ctx_opt}",
            key=f"soft_ctx_{emp_id}_{ctx_opt}",
            use_container_width=True,
            type="secondary" if is_selected else "primary",
        ):
            if ctx_opt in context_tags:
                context_tags.remove(ctx_opt)
            else:
                context_tags.append(ctx_opt)

            try:
                from goals import get_active_flags, load_goals, save_goals
                tenant_id = str(st.session_state.get("tenant_id", "") or "")

                flags = get_active_flags(tenant_id)
                if emp_id in flags:
                    goals_data = load_goals(tenant_id)
                    if emp_id in goals_data.get("flagged_employees", {}):
                        goals_data["flagged_employees"][emp_id]["context_tags"] = context_tags
                        save_goals(goals_data, tenant_id)
            except Exception:
                pass
            st.rerun()
