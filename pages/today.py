"""Today Screen — execution focus for supervisor workflow.

This is the main/default page. Shows:
1. Right now — summary cards (overdue, due today, new issues, ignored performers)
2. Action Queue — main list of action cards for execution
3. What changed since yesterday — quick outcomes summary
4. Secondary insights — supporting context

NOT a dashboard or analytics view. Optimized for: What do I need to do TODAY?
"""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from domain.actions import (
    OPEN_STATUSES,
    IssueType,
    determine_priority,
    runtime_status,
    status_label,
    urgency_score,
)
from services.action_service import (
    get_action_history,
    get_action_recommendation,
    get_ignored_high_performers,
    get_manager_outcome_stats,
    get_open_actions,
    get_overdue_actions,
    get_repeat_offenders,
    log_action_event,
    log_recognition_event,
    mark_action_deprioritized,
    mark_action_escalated,
    mark_action_in_progress,
    mark_action_resolved,
    mark_action_transferred,
    run_all_triggers,
    _recent_action_outcomes,
)


st.set_page_config(
    page_title="Today — DPD Supervisor",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ──────────────────────────────────────────────────────────────────────────────
# Session State & Setup
# ──────────────────────────────────────────────────────────────────────────────

if "tenant_id" not in st.session_state:
    st.session_state.tenant_id = ""

if "auto_triggers_run" not in st.session_state:
    st.session_state.auto_triggers_run = False

# Filter state
if "filter_status" not in st.session_state:
    st.session_state.filter_status = []

if "filter_issue_type" not in st.session_state:
    st.session_state.filter_issue_type = []

if "filter_department" not in st.session_state:
    st.session_state.filter_department = []

if "filter_priority" not in st.session_state:
    st.session_state.filter_priority = []

if "quick_filter" not in st.session_state:
    st.session_state.quick_filter = None  # "overdue" | "due_today" | "repeat" | "performers" | None


# ──────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────────────────────────────────────


def _apply_filters(actions: list[dict]) -> list[dict]:
    """Apply all active filters and quick filters to action list."""
    filtered = actions[:]
    
    # Quick filters override other filters
    if st.session_state.quick_filter == "overdue":
        filtered = [a for a in filtered if a.get("_runtime_status") == "overdue"]
    elif st.session_state.quick_filter == "due_today":
        filtered = [a for a in filtered if a.get("_runtime_status") == "due_today"]
    elif st.session_state.quick_filter == "repeat":
        # Use repeat offender employee IDs stored in session state after compute
        repeat_emp_ids = st.session_state.get("_repeat_offender_emp_ids", set())
        if not repeat_emp_ids:
            # Fallback: employees with 2+ open actions
            emp_action_counts: dict[str, int] = {}
            for a in actions:
                emp_id = str(a.get("employee_id") or "")
                emp_action_counts[emp_id] = emp_action_counts.get(emp_id, 0) + 1
            repeat_emp_ids = {emp_id for emp_id, count in emp_action_counts.items() if count >= 2}
        filtered = [a for a in filtered if str(a.get("employee_id")) in repeat_emp_ids]
    elif st.session_state.quick_filter == "performers":
        # Use ignored performer action IDs stored in session state
        performer_action_ids = st.session_state.get("_ignored_performer_action_ids", set())
        if performer_action_ids:
            filtered = [a for a in filtered if str(a.get("id") or "") in performer_action_ids]
        else:
            # Fallback: any recognition issue type
            filtered = [a for a in filtered if str(a.get("issue_type") or "") in {"recognition", "high_performer_ignored"}]
    else:
        # Apply individual filters
        if st.session_state.filter_status:
            filtered = [a for a in filtered if a.get("status") in st.session_state.filter_status]
        
        if st.session_state.filter_issue_type:
            filtered = [a for a in filtered if a.get("issue_type") in st.session_state.filter_issue_type]
        
        if st.session_state.filter_department:
            filtered = [a for a in filtered if a.get("department") in st.session_state.filter_department]
        
        if st.session_state.filter_priority:
            filtered = [a for a in filtered if a.get("priority") in st.session_state.filter_priority]
    
    return filtered


# ──────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────────────────────────────────────


def action_card(action: dict, col_width: float = 1.0) -> None:
    """Render a single action card with full details and CTAs."""
    emp_id = action.get("employee_id") or ""
    emp_name = action.get("employee_name") or emp_id
    dept = action.get("department") or "—"
    issue_type = action.get("issue_type") or "unknown"
    status = action.get("status") or "new"
    priority = action.get("priority") or "medium"
    action_type = action.get("action_type") or "coaching"
    trigger_summary = action.get("trigger_summary") or ""
    success_metric = action.get("success_metric") or ""
    follow_up_due = action.get("follow_up_due_at")
    runtime_st = action.get("_runtime_status") or ""
    baseline = round(float(action.get("baseline_uph") or 0.0), 2)
    latest = round(float(action.get("latest_uph") or 0.0), 2)
    action_id = action.get("id") or ""
    created_at = action.get("created_at")
    note = action.get("note") or ""

    # Get recommendation for this action
    _rec = get_action_recommendation(
        action=action,
        tenant_id=st.session_state.tenant_id,
        today=date.today(),
    )
    rec_type = _rec.get("recommendation", "continue")
    rec_reason = _rec.get("reason", "")
    rec_urgency = _rec.get("urgency", "low")

    with st.container(border=True):
        # Header row: Employee name + Priority badge + Status + Runtime status
        col1, col2, col3, col4 = st.columns([2, 0.8, 1, 1])
        
        with col1:
            st.markdown(f"### {emp_name}")
            st.caption(f"ID: {emp_id} · {dept}")
        
        with col2:
            priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(priority, "⚪")
            st.markdown(f"**{priority_icon}**")
            st.caption(priority.title())
        
        with col3:
            st.markdown(f"_{status_label(status)}_")
        
        with col4:
            if runtime_st == "overdue":
                st.markdown("**⚠️ OVERDUE**")
            elif runtime_st == "due_today":
                st.markdown("**📅 DUE TODAY**")
            elif runtime_st == "pending":
                st.caption("Pending")

        # Repeat offender badge — shown when this employee has pattern flags
        _ro_emp_ids: set = st.session_state.get("_repeat_offender_emp_ids", set())
        if str(emp_id) in _ro_emp_ids:
            _ro_data = next(
                (r for r in st.session_state.get("_repeat_offenders_data", []) if r["employee_id"] == str(emp_id)),
                None,
            )
            if _ro_data:
                _badge_rec = _ro_data["recommendation"]
                _badge_rec_label = {"escalate": "Escalate", "deprioritize": "Deprioritize", "change_approach": "Change Approach"}.get(_badge_rec, _badge_rec)
                _badge_sigs = " · ".join(_ro_data["signals"])
                st.warning(f"🔁 **Pattern detected:** {_badge_sigs}  \n**Recommendation:** {_badge_rec_label}", icon=None)
            else:
                st.caption("🔁 Repeat pattern")

        st.divider()

        # Issue details grid
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"**Issue Type:** {issue_type.title()}")
            if trigger_summary:
                st.markdown(f"**Trigger:** {trigger_summary}")
        
        with col2:
            st.markdown(f"**Action Type:** {action_type.replace('_', ' ').title()}")
            if created_at:
                st.caption(f"Created: {created_at[:10]}")

        # Success metric / UPH tracking
        if success_metric:
            st.markdown(f"**Success Metric:** {success_metric}")
        
        if baseline > 0 or latest > 0:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Latest UPH", f"{latest:.0f}")
            with col2:
                st.metric("Baseline", f"{baseline:.0f}")
            with col3:
                delta = latest - baseline
                delta_color = "🟢" if delta >= 0 else "🔴"
                st.metric("Delta", f"{delta_color} {delta:+.0f}")

        # Follow-up due date
        if follow_up_due:
            try:
                due_date = date.fromisoformat(follow_up_due[:10])
                days_until = (due_date - date.today()).days
                if days_until < 0:
                    due_label = f"⚠️ **{abs(days_until)} days overdue**"
                elif days_until == 0:
                    due_label = f"📅 **Due today**"
                elif days_until == 1:
                    due_label = f"📅 **Due tomorrow**"
                else:
                    due_label = f"📌 **Due in {days_until} days**"
                st.write(due_label)
            except Exception:
                st.caption(f"Due: {follow_up_due[:10]}")

        # Action note (if any)
        if note:
            with st.expander("💬 Notes"):
                st.write(note)

        st.divider()

        # Recommendation section — one clear next step
        rec_icon = {"follow up now": "📝", "coach today": "🧭", "recognize": "⭐", "escalate": "📈", "deprioritize": "⏸️", "follow up": "📌", "continue": "•"}.get(rec_type, "•")
        rec_color = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(rec_urgency, "⚪")
        st.markdown(f"**{rec_color} Recommended: {rec_icon} {rec_type.title()}**")
        if rec_reason:
            st.caption(rec_reason)

        st.divider()

        # Action buttons
        st.write("**Actions:**")
        
        button_cols = st.columns(6)
        
        with button_cols[0]:
            is_rec = rec_type in {"follow up now", "follow up"}
            if st.button("📝 Log Follow-Up", key=f"followup_{action_id}", use_container_width=True, type="primary" if is_rec else "secondary"):
                st.session_state[f"show_followup_{action_id}"] = True
                st.rerun()

        with button_cols[1]:
            if st.button("✅ Mark Resolved", key=f"resolve_{action_id}", use_container_width=True, type="secondary"):
                st.session_state[f"show_close_{action_id}"] = True
                st.session_state[f"close_type_{action_id}"] = "resolved"
                st.rerun()

        with button_cols[2]:
            is_rec = rec_type == "escalate"
            if st.button("📈 Escalate", key=f"escalate_{action_id}", use_container_width=True, type="primary" if is_rec else "secondary"):
                st.session_state[f"show_close_{action_id}"] = True
                st.session_state[f"close_type_{action_id}"] = "escalated"
                st.rerun()

        with button_cols[3]:
            is_rec = rec_type == "deprioritize"
            if st.button("⏸️ Deprioritize", key=f"deprioritize_{action_id}", use_container_width=True, type="primary" if is_rec else "secondary"):
                st.session_state[f"show_close_{action_id}"] = True
                st.session_state[f"close_type_{action_id}"] = "deprioritized"
                st.rerun()

        with button_cols[4]:
            if st.button("↪️ Transfer", key=f"transfer_{action_id}", use_container_width=True, type="secondary"):
                st.session_state[f"show_close_{action_id}"] = True
                st.session_state[f"close_type_{action_id}"] = "transferred"
                st.rerun()

        with button_cols[5]:
            if st.button("📋 History", key=f"history_{action_id}", use_container_width=True, type="secondary"):
                st.session_state[f"show_history_{action_id}"] = True
                st.rerun()

        # Follow-up dialog
        if st.session_state.get(f"show_followup_{action_id}"):
            with st.expander("📝 Log Follow-Up", expanded=True):
                with st.form(key=f"followup_form_{action_id}", clear_on_submit=False):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        followup_date = st.date_input(
                            "Follow-up date",
                            value=date.today(),
                            key=f"followup_date_{action_id}",
                        )
                    with col_b:
                        next_due = st.date_input(
                            "Next follow-up due",
                            value=date.today() + timedelta(days=7),
                            key=f"followup_due_{action_id}",
                        )

                    outcome = st.selectbox(
                        "Outcome",
                        ["pending", "improved", "no_change", "worse", "not_applicable"],
                        key=f"followup_outcome_{action_id}",
                    )

                    action_taken = st.text_input(
                        "Action taken (optional)",
                        key=f"followup_action_taken_{action_id}",
                        placeholder="e.g., station reset + 1:1 coaching",
                    )

                    followup_note = st.text_area(
                        "Follow-up note",
                        key=f"followup_note_{action_id}",
                        placeholder="What happened in this follow-up?",
                        height=90,
                    )

                    col_submit, col_cancel = st.columns(2)
                    submit_followup = col_submit.form_submit_button(
                        "Save Follow-Up",
                        use_container_width=True,
                        type="primary",
                    )
                    cancel_followup = col_cancel.form_submit_button(
                        "Cancel",
                        use_container_width=True,
                    )

                if cancel_followup:
                    st.session_state[f"show_followup_{action_id}"] = False
                    st.rerun()

                if submit_followup:
                    structured_note = (
                        f"follow_up_date={followup_date.isoformat()}\n"
                        f"action_taken={action_taken.strip()}\n"
                        f"note={followup_note.strip()}"
                    )
                    result = log_action_event(
                        action_id=str(action_id),
                        event_type="follow_up_logged",
                        performed_by=st.session_state.get("user_email", "supervisor"),
                        notes=structured_note,
                        outcome=outcome,
                        next_follow_up_at=next_due.isoformat(),
                        tenant_id=st.session_state.tenant_id,
                    )
                    if result:
                        st.success("Follow-up logged!")
                        st.session_state[f"show_followup_{action_id}"] = False
                        st.rerun()

        # Close action dialog (resolved / deprioritized / escalated / transferred)
        if st.session_state.get(f"show_close_{action_id}"):
            close_type = str(st.session_state.get(f"close_type_{action_id}") or "resolved")
            title_map = {
                "resolved": "✅ Mark Resolved",
                "deprioritized": "⏸️ Deprioritize Action",
                "escalated": "📈 Escalate Action",
                "transferred": "↪️ Transfer Action",
            }
            with st.expander(title_map.get(close_type, "Close Action"), expanded=True):
                reason_options = {
                    "improved": "improved",
                    "no improvement, not worth time": "no_improvement_not_worth_time",
                    "referred to HR / leadership": "referred_to_hr_leadership",
                    "issue no longer relevant": "issue_no_longer_relevant",
                }
                reason_label = st.selectbox(
                    "Reason",
                    list(reason_options.keys()),
                    key=f"close_reason_{action_id}",
                )
                reason_code = reason_options[reason_label]

                close_note = st.text_area(
                    "Note",
                    key=f"close_note_{action_id}",
                    placeholder="Add context for this decision...",
                    height=80,
                )

                latest_uph_close = st.number_input(
                    "Latest UPH (optional)",
                    value=latest,
                    key=f"latest_uph_close_{action_id}",
                )

                c1, c2 = st.columns(2)
                submit_close = c1.button(
                    "Save Decision",
                    key=f"submit_close_{action_id}",
                    type="primary",
                    use_container_width=True,
                )
                cancel_close = c2.button(
                    "Cancel",
                    key=f"cancel_close_{action_id}",
                    use_container_width=True,
                )

                if cancel_close:
                    st.session_state[f"show_close_{action_id}"] = False
                    st.rerun()

                if submit_close:
                    note_payload = f"reason={reason_label}\nnote={close_note.strip()}"
                    result = {}
                    if close_type == "resolved":
                        result = mark_action_resolved(
                            action_id=str(action_id),
                            resolution_type=reason_code,
                            resolution_note=close_note,
                            latest_uph=float(latest_uph_close),
                            improvement_delta=round(float(latest_uph_close) - float(baseline), 2),
                            tenant_id=st.session_state.tenant_id,
                        )
                    elif close_type == "deprioritized":
                        result = mark_action_deprioritized(
                            action_id=str(action_id),
                            reason=note_payload,
                            tenant_id=st.session_state.tenant_id,
                        )
                    elif close_type == "escalated":
                        result = mark_action_escalated(
                            action_id=str(action_id),
                            reason=note_payload,
                            tenant_id=st.session_state.tenant_id,
                        )
                    elif close_type == "transferred":
                        result = mark_action_transferred(
                            action_id=str(action_id),
                            reason=note_payload,
                            tenant_id=st.session_state.tenant_id,
                        )

                    if result:
                        log_action_event(
                            action_id=str(action_id),
                            event_type=close_type,
                            performed_by=st.session_state.get("user_email", "supervisor"),
                            outcome=reason_code,
                            notes=note_payload,
                            tenant_id=st.session_state.tenant_id,
                        )
                        st.success(f"Action {close_type}.")
                        st.session_state[f"show_close_{action_id}"] = False
                        st.rerun()

        # History dialog
        if st.session_state.get(f"show_history_{action_id}"):
            with st.expander("📋 Action History", expanded=True):
                st.caption(
                    f"Action ID: {action_id} | Created: {created_at[:10] if created_at else '—'} | "
                    f"Status: {status_label(status)}"
                )
                events = get_action_history(
                    action_id=str(action_id),
                    tenant_id=st.session_state.tenant_id,
                )

                if not events:
                    st.caption("No timeline events yet.")
                else:
                    event_icon = {
                        "created": "🟢",
                        "coached": "🧭",
                        "follow_up_logged": "📝",
                        "resolved": "✅",
                        "deprioritized": "⏸️",
                        "escalated": "📈",
                        "transferred": "↪️",
                        "reopened": "🔄",
                    }

                    for ev in events:
                        ev_type = str(ev.get("event_type") or "").strip()
                        ev_at = str(ev.get("event_at") or "")
                        ev_outcome = str(ev.get("outcome") or "").strip()
                        ev_notes = str(ev.get("notes") or "").strip()
                        ev_by = str(ev.get("performed_by") or "").strip()
                        ev_next_due = str(ev.get("next_follow_up_at") or "").strip()

                        label = ev_type.replace("_", " ").title() if ev_type else "Event"
                        ts = ev_at[:16].replace("T", " ") if ev_at else "Unknown time"
                        icon = event_icon.get(ev_type, "•")

                        st.markdown(f"{icon} **{label}** · {ts}")
                        meta_bits = []
                        if ev_by:
                            meta_bits.append(f"by {ev_by}")
                        if ev_outcome:
                            meta_bits.append(f"outcome: {ev_outcome}")
                        if ev_next_due:
                            meta_bits.append(f"next due: {ev_next_due[:10]}")
                        if meta_bits:
                            st.caption(" | ".join(meta_bits))
                        if ev_notes:
                            st.caption(ev_notes)
                        st.divider()


def summary_card(title: str, value: int | str, subtitle: str = "", icon: str = "") -> None:
    """Render a summary metric card with title, count, and explanation."""
    with st.container(border=True):
        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown(f"# {value}")
        with col2:
            st.markdown(f"**{icon} {title}**")
            if subtitle:
                st.caption(subtitle)


# ──────────────────────────────────────────────────────────────────────────────
# Main Page
# ──────────────────────────────────────────────────────────────────────────────

st.title("📋 Today")
st.caption("What needs your attention right now?")

# Auto-run triggers on page load
if not st.session_state.auto_triggers_run:
    with st.spinner("Loading actions..."):
        trigger_summary = run_all_triggers(tenant_id=st.session_state.tenant_id)
    st.session_state.auto_triggers_run = True

st.write("")

# ──────────────────────────────────────────────────────────────────────────────
# Section 1: Right Now
# ──────────────────────────────────────────────────────────────────────────────

st.subheader("🔴 Right Now")

# Get data for summary cards
overdue_actions = get_overdue_actions(tenant_id=st.session_state.tenant_id)
open_actions = get_open_actions(tenant_id=st.session_state.tenant_id)

due_today = [
    a for a in open_actions
    if a.get("_runtime_status") == "due_today"
]

new_issues = [
    a for a in open_actions
    if a.get("status") == "new"
]

recent_improved = [
    o for o in _recent_action_outcomes(lookback_days=1, tenant_id=st.session_state.tenant_id)
    if o.get("outcome") == "Improved"
]

# Display summary cards in columns
col1, col2, col3, col4 = st.columns(4)

with col1:
    summary_card(
        title="Overdue",
        value=len(overdue_actions),
        subtitle="Actions past follow-up date",
        icon="⚠️",
    )

with col2:
    summary_card(
        title="Due Today",
        value=len(due_today),
        subtitle="Follow-up actions due now",
        icon="📅",
    )

with col3:
    summary_card(
        title="New Issues",
        value=len(new_issues),
        subtitle="Not yet started",
        icon="🆕",
    )

with col4:
    summary_card(
        title="Improvements",
        value=len(recent_improved),
        subtitle="Resolved this shift",
        icon="✅",
    )

st.write("")

# ──────────────────────────────────────────────────────────────────────────────
# Section 1b: Repeat Offenders — Management Pattern Alerts
# ──────────────────────────────────────────────────────────────────────────────

_repeat_offenders = get_repeat_offenders(
    tenant_id=st.session_state.tenant_id,
    today=date.today(),
    open_actions=open_actions,
)
st.session_state["_repeat_offender_emp_ids"] = {r["employee_id"] for r in _repeat_offenders}
st.session_state["_repeat_offenders_data"] = _repeat_offenders

if _repeat_offenders:
    _rec_icon = {"escalate": "📈", "deprioritize": "⏸️", "change_approach": "🔀"}
    _rec_label = {"escalate": "Escalate", "deprioritize": "Deprioritize", "change_approach": "Change Approach"}
    _rec_color = {"escalate": "🔴", "deprioritize": "🟡", "change_approach": "🟠"}

    with st.expander(
        f"🔁 Needs a Different Approach — {len(_repeat_offenders)} employee{'s' if len(_repeat_offenders) != 1 else ''}",
        expanded=True,
    ):
        st.caption("Employees with repeated coaching cycles or no-improvement patterns. The queue alone won't fix these.")

        for _ro in _repeat_offenders:
            _ro_emp_name = _ro["employee_name"]
            _ro_dept = _ro["department"]
            _ro_rec = _ro["recommendation"]
            _ro_signals = _ro["signals"]
            _ro_actions = _ro["actions"]
            _ro_emp_id = _ro["employee_id"]

            # Pick the most urgent open action as the primary action target
            _ro_primary = sorted(
                _ro_actions,
                key=lambda a: (
                    0 if a.get("_runtime_status") == "overdue" else
                    1 if a.get("_runtime_status") == "due_today" else 2,
                    a.get("priority") == "high" and -1 or 0,
                ),
            )[0]
            _ro_primary_id = _ro_primary.get("id") or ""

            with st.container(border=True):
                _hcol1, _hcol2, _hcol3 = st.columns([2.5, 2, 1.2])

                with _hcol1:
                    st.markdown(f"**{_ro_emp_name}**")
                    st.caption(_ro_dept or "—")

                with _hcol2:
                    for _sig in _ro_signals:
                        st.caption(f"• {_sig}")

                with _hcol3:
                    st.markdown(
                        f"{_rec_color[_ro_rec]} **{_rec_label[_ro_rec]}**"
                    )

                _bcol1, _bcol2, _bcol3 = st.columns(3)
                with _bcol1:
                    if st.button(
                        "📈 Escalate",
                        key=f"ro_escalate_{_ro_emp_id}",
                        use_container_width=True,
                    ):
                        st.session_state[f"show_close_{_ro_primary_id}"] = True
                        st.session_state[f"close_type_{_ro_primary_id}"] = "escalated"
                        st.rerun()
                with _bcol2:
                    if st.button(
                        "⏸️ Deprioritize",
                        key=f"ro_deprioritize_{_ro_emp_id}",
                        use_container_width=True,
                    ):
                        st.session_state[f"show_close_{_ro_primary_id}"] = True
                        st.session_state[f"close_type_{_ro_primary_id}"] = "deprioritized"
                        st.rerun()
                with _bcol3:
                    if st.button(
                        "📝 Log Follow-Up",
                        key=f"ro_followup_{_ro_emp_id}",
                        use_container_width=True,
                    ):
                        st.session_state[f"show_followup_{_ro_primary_id}"] = True
                        st.rerun()

st.write("")

# ──────────────────────────────────────────────────────────────────────────────
# Section 1c: Ignored High Performers — Recognition / Development Gaps
# ──────────────────────────────────────────────────────────────────────────────

_ignored_performers = get_ignored_high_performers(
    tenant_id=st.session_state.tenant_id,
    today=date.today(),
    open_actions=open_actions,
)
st.session_state["_ignored_performer_action_ids"] = {r["action_id"] for r in _ignored_performers}

if _ignored_performers:
    with st.expander(
        f"⭐ High Performers Awaiting Recognition — {len(_ignored_performers)} employee{'s' if len(_ignored_performers) != 1 else ''}",
        expanded=False,
    ):
        st.caption("Top performers flagged by the system with no recognition or development touchpoint logged yet.")

        for _hp in _ignored_performers:
            _hp_emp_name = _hp["employee_name"]
            _hp_dept = _hp["department"]
            _hp_action_id = _hp["action_id"]
            _hp_emp_id = _hp["employee_id"]
            _hp_signals = _hp["signals"]
            _hp_days = _hp["days_waiting"]

            with st.container(border=True):
                _hpcol1, _hpcol2, _hpcol3 = st.columns([2.5, 2.5, 1.2])

                with _hpcol1:
                    st.markdown(f"**{_hp_emp_name}**")
                    st.caption(_hp_dept or "—")

                with _hpcol2:
                    for _sig in _hp_signals:
                        st.caption(f"• {_sig}")

                with _hpcol3:
                    urgency_label = "🔴 Long wait" if _hp_days >= 14 else ("🟡 Pending" if _hp_days >= 7 else "🟢 Recent")
                    st.markdown(f"**{urgency_label}**")

                _hpb1, _hpb2, _hpb3 = st.columns(3)

                with _hpb1:
                    if st.button(
                        "⭐ Log Recognition",
                        key=f"hp_recognize_{_hp_emp_id}",
                        use_container_width=True,
                    ):
                        st.session_state[f"show_recognize_{_hp_action_id}"] = True
                        st.rerun()

                with _hpb2:
                    if st.button(
                        "📈 Development Touchpoint",
                        key=f"hp_develop_{_hp_emp_id}",
                        use_container_width=True,
                    ):
                        st.session_state[f"show_followup_{_hp_action_id}"] = True
                        st.rerun()

                with _hpb3:
                    if st.button(
                        "✅ Mark Done",
                        key=f"hp_done_{_hp_emp_id}",
                        use_container_width=True,
                    ):
                        st.session_state[f"show_close_{_hp_action_id}"] = True
                        st.session_state[f"close_type_{_hp_action_id}"] = "resolved"
                        st.rerun()

                # Recognition form
                if st.session_state.get(f"show_recognize_{_hp_action_id}"):
                    with st.form(key=f"recognize_form_{_hp_action_id}", clear_on_submit=True):
                        st.markdown("**⭐ Log Recognition**")
                        rec_note = st.text_area(
                            "Recognition note",
                            placeholder="What achievement / behaviour are you recognising?",
                            height=80,
                            key=f"rec_note_{_hp_action_id}",
                        )
                        rec_next_due = st.date_input(
                            "Next development check-in (optional)",
                            value=date.today() + timedelta(days=30),
                            key=f"rec_next_due_{_hp_action_id}",
                        )
                        _rc1, _rc2 = st.columns(2)
                        _save_rec = _rc1.form_submit_button("Save", type="primary", use_container_width=True)
                        _cancel_rec = _rc2.form_submit_button("Cancel", use_container_width=True)

                    if _cancel_rec:
                        st.session_state[f"show_recognize_{_hp_action_id}"] = False
                        st.rerun()

                    if _save_rec:
                        _rec_result = log_recognition_event(
                            action_id=_hp_action_id,
                            employee_id=_hp_emp_id,
                            performed_by=st.session_state.get("user_email", "supervisor"),
                            notes=rec_note.strip(),
                            next_follow_up_at=rec_next_due.isoformat(),
                            tenant_id=st.session_state.tenant_id,
                        )
                        if _rec_result:
                            st.success(f"Recognition logged for {_hp_emp_name}!")
                        st.session_state[f"show_recognize_{_hp_action_id}"] = False
                        st.rerun()

st.write("")

# ──────────────────────────────────────────────────────────────────────────────
# Section 2: Action Queue
# ──────────────────────────────────────────────────────────────────────────────

st.subheader("📌 Action Queue")

# Sort by urgency: overdue > due_today > pending
def _sort_key(action):
    runtime_st = action.get("_runtime_status") or ""
    status = action.get("status") or "new"
    priority = action.get("priority") or "medium"
    urgency = urgency_score(
        status=status,
        runtime_status=runtime_st,
        priority=priority,
    )
    return -urgency  # Higher urgency first

sorted_open = sorted(open_actions, key=_sort_key)

# Quick filter buttons
st.write("**Quick Filters:**")
quick_cols = st.columns(5)

with quick_cols[0]:
    if st.button(
        "🔄 Clear Filters",
        key="clear_filters",
        use_container_width=True,
    ):
        st.session_state.quick_filter = None
        st.session_state.filter_status = []
        st.session_state.filter_issue_type = []
        st.session_state.filter_department = []
        st.session_state.filter_priority = []
        st.rerun()

with quick_cols[1]:
    if st.button(
        f"⚠️ Overdue ({len(overdue_actions)})",
        key="filter_overdue",
        use_container_width=True,
    ):
        st.session_state.quick_filter = "overdue"
        st.rerun()

with quick_cols[2]:
    if st.button(
        f"📅 Due Today ({len(due_today)})",
        key="filter_due_today",
        use_container_width=True,
    ):
        st.session_state.quick_filter = "due_today"
        st.rerun()

with quick_cols[3]:
    repeat_count = len(_repeat_offenders)
    if st.button(
        f"🔁 Repeat Issues ({repeat_count})",
        key="filter_repeat",
        use_container_width=True,
    ):
        st.session_state.quick_filter = "repeat"
        st.rerun()

with quick_cols[4]:
    performers_count = len(_ignored_performers)
    if st.button(
        f"⭐ High Performers ({performers_count})",
        key="filter_performers",
        use_container_width=True,
    ):
        st.session_state.quick_filter = "performers"
        st.rerun()

st.divider()

# Advanced filter controls
with st.expander("🔧 Advanced Filters", expanded=False):
    filter_cols = st.columns(4)
    
    # Get unique values for filters
    unique_statuses = sorted(set(a.get("status") or "new" for a in open_actions))
    unique_issue_types = sorted(set(a.get("issue_type") or "unknown" for a in open_actions))
    unique_departments = sorted(set(a.get("department") or "—" for a in open_actions if a.get("department")))
    unique_priorities = ["high", "medium", "low"]
    
    with filter_cols[0]:
        st.session_state.filter_status = st.multiselect(
            "Status",
            options=unique_statuses,
            default=st.session_state.filter_status,
            key="status_filter",
        )
    
    with filter_cols[1]:
        st.session_state.filter_issue_type = st.multiselect(
            "Issue Type",
            options=unique_issue_types,
            default=st.session_state.filter_issue_type,
            key="issue_type_filter",
        )
    
    with filter_cols[2]:
        st.session_state.filter_department = st.multiselect(
            "Department",
            options=unique_departments,
            default=st.session_state.filter_department,
            key="department_filter",
        )
    
    with filter_cols[3]:
        st.session_state.filter_priority = st.multiselect(
            "Priority",
            options=unique_priorities,
            default=st.session_state.filter_priority,
            key="priority_filter",
        )

st.write("")

# Apply filters to action queue
filtered_actions = _apply_filters(sorted_open)

# Display filter status
if st.session_state.quick_filter:
    st.caption(f"📊 Showing {len(filtered_actions)} of {len(sorted_open)} actions ({st.session_state.quick_filter})")
elif any([st.session_state.filter_status, st.session_state.filter_issue_type, st.session_state.filter_department, st.session_state.filter_priority]):
    st.caption(f"📊 Showing {len(filtered_actions)} of {len(sorted_open)} actions (filtered)")
else:
    st.caption(f"📊 Showing all {len(filtered_actions)} actions")

st.write("")

# Display filtered action queue
if not filtered_actions:
    if st.session_state.quick_filter or any([st.session_state.filter_status, st.session_state.filter_issue_type, st.session_state.filter_department, st.session_state.filter_priority]):
        st.info("✅ No actions match your filter criteria.")
    else:
        st.info("✅ No open actions. Great work!")
else:
    # Display actions
    for action in filtered_actions:
        action_card(action)

st.write("")

# ──────────────────────────────────────────────────────────────────────────────
# Section 3: What Changed Since Yesterday
# ──────────────────────────────────────────────────────────────────────────────

st.subheader("📊 What Changed Since Yesterday")

recent_outcomes = _recent_action_outcomes(
    lookback_days=1,
    tenant_id=st.session_state.tenant_id,
)

new_overdue_items = sum(1 for a in open_actions if a.get("_runtime_status") == "overdue")

if not recent_outcomes:
    st.caption("No outcomes logged yesterday.")
else:
    improved_count = sum(1 for o in recent_outcomes if o.get("outcome") == "Improved")
    no_change_count = sum(1 for o in recent_outcomes if o.get("outcome") == "No Change")
    worse_count = sum(1 for o in recent_outcomes if o.get("outcome") == "Worse")
    resolved_count = len(recent_outcomes)

    strip_cols = st.columns(5)
    with strip_cols[0]:
        st.metric("🟢 Improved", improved_count)
    with strip_cols[1]:
        st.metric("🟡 No Change", no_change_count)
    with strip_cols[2]:
        st.metric("🔴 Worsened", worse_count)
    with strip_cols[3]:
        st.metric("✅ Resolved", resolved_count)
    with strip_cols[4]:
        st.metric("⚠️ New Overdue", new_overdue_items)

    with st.expander("View yesterday outcomes", expanded=False):
        for outcome in recent_outcomes[:15]:
            st.write(
                f"**{outcome.get('employee_name', 'Unknown')}** "
                f"({outcome.get('department', '')}) · "
                f"{outcome.get('outcome', 'Unknown')} · "
                f"Δ UPH: {outcome.get('delta', 0):+.1f}"
            )

st.write("")

# ──────────────────────────────────────────────────────────────────────────────
# Section 3b: Manager Performance — Intervention Outcomes This Week
# ──────────────────────────────────────────────────────────────────────────────

st.subheader("🎯 Manager Performance — This Week")

_manager_stats = get_manager_outcome_stats(
    tenant_id=st.session_state.tenant_id,
    lookback_days=7,
    today=date.today(),
)

_total = _manager_stats.get("total_events", 0)
_outcomes = _manager_stats.get("outcomes", {})
_percentages = _manager_stats.get("outcome_percentages", {})

if _total == 0:
    st.caption("No outcomes logged this week yet.")
else:
    # Compact metric strip — outcomes with counts and %
    perf_cols = st.columns(4)
    
    with perf_cols[0]:
        _improved = _outcomes.get("improved", 0)
        _improved_pct = _percentages.get("improved", 0)
        st.metric("🟢 Improved", f"{_improved} ({_improved_pct:.0f}%)")
    
    with perf_cols[1]:
        _unchanged = _outcomes.get("no_change", 0)
        _unchanged_pct = _percentages.get("no_change", 0)
        st.metric("🟡 Unchanged", f"{_unchanged} ({_unchanged_pct:.0f}%)")
    
    with perf_cols[2]:
        _worse = _outcomes.get("worse", 0)
        _worse_pct = _percentages.get("worse", 0)
        st.metric("🔴 Worsened", f"{_worse} ({_worse_pct:.0f}%)")
    
    with perf_cols[3]:
        _pending = _outcomes.get("pending", 0)
        _pending_pct = _percentages.get("pending", 0)
        st.metric("⏳ Pending", f"{_pending} ({_pending_pct:.0f}%)")

    st.caption(f"**{_total} follow-ups logged this week** — Tracking coaching approach effectiveness")

    # Expandable: by-issue-type breakdown
    _by_type = _manager_stats.get("by_issue_type", {})
    if _by_type and any(sum(counts.values()) > 0 for counts in _by_type.values()):
        with st.expander("Success rate by issue type", expanded=False):
            for issue_type in sorted(_by_type.keys()):
                counts = _by_type[issue_type]
                type_total = sum(counts.values())
                if type_total == 0:
                    continue
                
                improved_in_type = counts.get("improved", 0)
                success_pct = round(100.0 * improved_in_type / type_total, 1) if type_total > 0 else 0
                
                col_a, col_b, col_c = st.columns([2, 1, 1.5])
                with col_a:
                    st.caption(f"**{issue_type.replace('_', ' ').title()}**")
                with col_b:
                    st.caption(f"{type_total} events")
                with col_c:
                    st.metric("Success", f"{success_pct:.0f}%", label_visibility="collapsed")

st.write("")

# ──────────────────────────────────────────────────────────────────────────────
# Section 4: Secondary Insights
# ──────────────────────────────────────────────────────────────────────────────

st.subheader("💡 Secondary Insights")

insight_col1, insight_col2, insight_col3 = st.columns(3)

with insight_col1:
    with st.container(border=True):
        st.write("**Actions by Type**")
        if open_actions:
            type_counts = {}
            for action in open_actions:
                atype = action.get("action_type") or "unknown"
                type_counts[atype] = type_counts.get(atype, 0) + 1
            for atype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
                st.caption(f"{atype.title()}: {count}")
        else:
            st.caption("—")

with insight_col2:
    with st.container(border=True):
        st.write("**Actions by Status**")
        if open_actions:
            status_counts = {}
            for action in open_actions:
                status = action.get("status") or "new"
                status_counts[status] = status_counts.get(status, 0) + 1
            for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
                st.caption(f"{status_label(status)}: {count}")
        else:
            st.caption("—")

with insight_col3:
    with st.container(border=True):
        st.write("**Actions by Priority**")
        if open_actions:
            priority_counts = {}
            for action in open_actions:
                priority = action.get("priority") or "medium"
                priority_counts[priority] = priority_counts.get(priority, 0) + 1
            for priority in ["high", "medium", "low"]:
                if priority in priority_counts:
                    st.caption(f"{priority.title()}: {priority_counts[priority]}")
        else:
            st.caption("—")

st.write("")

# Footer
st.caption("Last refresh: " + date.today().isoformat())

