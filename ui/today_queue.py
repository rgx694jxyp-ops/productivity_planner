"""Reusable Today page queue components."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from domain.actions import parse_action_date
from services.action_lifecycle_service import (
    log_action_event,
    log_recognition_event,
    mark_action_deprioritized,
    mark_action_escalated,
    save_action_touchpoint,
)
from services.plain_language_service import (
    action_label,
    outcome_code,
    outcome_label,
    signal_wording,
)
from services.today_queue_service import (
    build_action_queue as build_action_queue_service,
    partition_action_queue_items,
)

MAX_VISIBLE_QUEUE_ITEMS = 7
OUTCOME_CODES = ["improved", "no_change", "worse", "blocked", "not_applicable"]
OUTCOME_OPTIONS = [outcome_label(code) for code in OUTCOME_CODES]
ACTION_CODES = ["log_check_in", "log_follow_up", "log_recognition", "mark_for_review", "lower_urgency"]
ACTION_OPTIONS = [action_label(code) for code in ACTION_CODES]
_AMBIGUOUS_FACTOR_PHRASES = {"", "unknown", "status", "needs review", "worth review", "limited data available"}


def _escape_html(value: object) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_queue_styles() -> None:
    if st.session_state.get("_today_queue_styles_rendered"):
        return
    st.session_state["_today_queue_styles_rendered"] = True
    st.markdown(
        """
        <style>
        .today-card-shell {
            border-radius: 16px;
            padding: 4px 2px 2px 2px;
        }
        .today-card-header {
            display: flex;
            justify-content: space-between;
            gap: 16px;
            align-items: flex-start;
            margin-bottom: 8px;
        }
        .today-card-name {
            font-size: 1.18rem;
            font-weight: 800;
            color: #0f2d52;
            line-height: 1.1;
        }
        .today-card-subtext {
            margin-top: 4px;
            color: #5d7693;
            font-size: 0.84rem;
        }
        .today-card-next {
            min-width: 120px;
            text-align: right;
        }
        .today-card-next-label {
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #5d7693;
        }
        .today-card-next-value {
            margin-top: 4px;
            font-size: 0.95rem;
            font-weight: 800;
            color: #0f2d52;
        }
        .today-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 8px;
        }
        .today-chip {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 4px 9px;
            font-size: 0.73rem;
            font-weight: 700;
            line-height: 1;
        }
        .today-chip-neutral {
            background: #eef3fa;
            color: #36506d;
        }
        .today-chip-danger {
            background: #fdeceb;
            color: #9d2d20;
        }
        .today-chip-warning {
            background: #fff3e4;
            color: #9a5b00;
        }
        .today-chip-success {
            background: #e8f5e9;
            color: #20603a;
        }
        .today-card-copy {
            display: grid;
            gap: 10px;
            margin: 12px 0 10px 0;
        }
        .today-copy-block {
            background: #f7fafd;
            border: 1px solid #dbe6f2;
            border-radius: 12px;
            padding: 10px 12px;
        }
        .today-copy-label {
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #5d7693;
            margin-bottom: 4px;
        }
        .today-copy-value {
            font-size: 0.95rem;
            color: #182b40;
            line-height: 1.4;
        }
        .today-card-signals {
            margin: 8px 0 10px 0;
            color: #5d7693;
            font-size: 0.84rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _queue_status(action: dict, today: date) -> str:
    due_date = parse_action_date(action.get("follow_up_due_at"))
    if due_date and due_date < today:
        return "overdue"
    if due_date and due_date == today:
        return "due_today"
    return "pending"


def _short_reason(action: dict) -> str:
    trigger_summary = str(action.get("trigger_summary") or "").strip()
    if trigger_summary:
        return trigger_summary

    issue_type = str(action.get("issue_type") or "issue").replace("_", " ").strip()
    return issue_type.title() or "Needs attention"


def _good_looks_like(action: dict) -> str:
    success_metric = str(action.get("success_metric") or "").strip()
    if success_metric:
        lower = success_metric.lower()
        if any(token in lower for token in ("escalate", "move role", "role reset", "support plan")):
            return "Track whether performance stabilizes versus baseline over the next review window."
        return success_metric

    baseline_uph = float(action.get("baseline_uph") or 0.0)
    if baseline_uph > 0:
        return f"Previous baseline context: {baseline_uph:.0f} UPH."

    return "Follow-up context is available in this item's timeline."


def _build_repeat_lookup(repeat_offenders: list[dict]) -> dict[str, dict]:
    return {str(item.get("employee_id") or ""): item for item in repeat_offenders}


def _build_recognition_lookup(recognition_opportunities: list[dict]) -> dict[str, dict]:
    return {str(item.get("action_id") or ""): item for item in recognition_opportunities}


def _why_this_is_here(action: dict, queue_status: str) -> str:
    if queue_status == "overdue":
        return "This follow-up date already passed, so it stays at the top until someone closes the loop."
    if queue_status == "due_today":
        return "This item is due today, so it belongs in the active queue for this shift."
    if action.get("_is_repeat_issue"):
        return "This employee has a repeated open pattern, so it stays visible for closer follow-through."
    if action.get("_is_recognition_opportunity"):
        return "This person is doing well and no recognition touchpoint has been logged yet."
    return "This item is still open and needs a supervisor decision to keep work moving."


def _surfaced_factors(action: dict) -> list[str]:
    factors: list[str] = []
    queue_status = str(action.get("_queue_status") or "pending")
    if queue_status in {"overdue", "due_today"}:
        factors.append("Follow-up overdue")
    if bool(action.get("_is_repeat_issue")):
        factors.append("Seen multiple times")

    issue_type = str(action.get("issue_type") or "").strip().lower()
    trigger_summary = str(action.get("trigger_summary") or "").strip().lower()
    if issue_type in {"low_performance", "low_performance_unaddressed", "repeated_low_performance"}:
        factors.append("Lower than recent pace")
    elif "below" in trigger_summary or "lower" in trigger_summary or "declin" in trigger_summary:
        factors.append("Lower than recent pace")

    if not factors:
        factors.append("Lower than recent pace")

    unique: list[str] = []
    seen: set[str] = set()
    for factor in factors:
        key = factor.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(factor)
    return unique


def _is_queue_item_display_eligible(action: dict) -> bool:
    if bool(action.get("_system_artifact")):
        return False
    factors = [str(f or "").strip() for f in list(action.get("_surfaced_factors") or [])]
    factors = [f for f in factors if f]
    if not factors:
        return False
    for factor in factors:
        lowered = factor.lower()
        if lowered in _AMBIGUOUS_FACTOR_PHRASES:
            return False
        if "system" in lowered or "artifact" in lowered:
            return False
    return True


def _display_bucket(action: dict) -> str:
    if not _is_queue_item_display_eligible(action):
        return "suppressed"
    confidence = str(action.get("confidence") or action.get("confidence_label") or "").strip().lower()
    if confidence == "low":
        return "secondary"
    return "primary"


def _sort_key(action: dict) -> tuple:
    queue_status = str(action.get("_queue_status") or "pending")
    status_rank = {"overdue": 0, "due_today": 1, "pending": 2}.get(queue_status, 3)
    priority_rank = {"high": 0, "medium": 1, "low": 2}.get(str(action.get("priority") or "medium"), 1)
    repeat_rank = 0 if action.get("_is_repeat_issue") else 1
    follow_up_rank = 0 if queue_status in {"overdue", "due_today"} else 1
    pace_rank = 0 if "Lower than recent pace" in list(action.get("_surfaced_factors") or []) else 1
    recognition_rank = 1 if action.get("_is_recognition_opportunity") else 0
    due_date = parse_action_date(action.get("follow_up_due_at")) or date.max
    return (status_rank, follow_up_rank, repeat_rank, pace_rank, priority_rank, recognition_rank, due_date, str(action.get("employee_name") or ""))


def build_action_queue(
    *,
    open_actions: list[dict],
    repeat_offenders: list[dict],
    recognition_opportunities: list[dict],
    tenant_id: str,
    today: date,
) -> list[dict]:
    return build_action_queue_service(
        open_actions=open_actions,
        repeat_offenders=repeat_offenders,
        recognition_opportunities=recognition_opportunities,
        tenant_id=tenant_id,
        today=today,
    )


def _render_action_context(action: dict) -> None:
    meta_bits = []
    department = str(action.get("department") or "").strip()
    if department:
        meta_bits.append(department)

    queue_status = str(action.get("_queue_status") or "pending")
    if queue_status == "overdue":
        meta_bits.append("Overdue")
    elif queue_status == "due_today":
        meta_bits.append("Due today")

    if action.get("_is_repeat_issue"):
        meta_bits.append("Repeat issue")
    if action.get("_is_recognition_opportunity"):
        meta_bits.append("Recognition")

    if meta_bits:
        st.caption(" | ".join(meta_bits))


def _build_status_chips(action: dict) -> str:
    chips: list[str] = []
    queue_status = str(action.get("_queue_status") or "pending")
    if queue_status == "overdue":
        chips.append('<span class="today-chip today-chip-danger">Overdue</span>')
    elif queue_status == "due_today":
        chips.append('<span class="today-chip today-chip-warning">Due today</span>')

    if action.get("_is_repeat_issue"):
        chips.append('<span class="today-chip today-chip-warning">Repeat issue</span>')
    if action.get("_is_recognition_opportunity"):
        chips.append('<span class="today-chip today-chip-success">Recognition</span>')

    priority = str(action.get("priority") or "medium").title()
    chips.append(f'<span class="today-chip today-chip-neutral">{_escape_html(priority)} priority</span>')
    return "".join(chips)


def _action_code_from_label(label: str) -> str:
    normalized = str(label or "").strip().lower()
    for code in ACTION_CODES:
        if action_label(code).lower() == normalized:
            return code
    return ""


def _action_form_key(action_id: str) -> str:
    return f"today_queue_form_open_{action_id}"


def _set_flash_and_refresh(message: str, action_id: str) -> None:
    st.session_state["today_flash_message"] = message
    st.session_state[_action_form_key(action_id)] = False
    st.rerun()


def _follow_up_signal(action: dict) -> str:
    factors = list(action.get("_surfaced_factors") or [])
    if factors:
        return factors[0]
    return signal_wording("lower_than_recent_pace")


def _follow_up_context_line(action: dict) -> str:
    failed_cycles = int(action.get("failed_cycles") or 0)
    if failed_cycles >= 2:
        return f"{failed_cycles} follow-ups logged with no improvement"
    if bool(action.get("_is_repeat_issue")):
        return "Seen again after coaching"
    trigger_summary = str(action.get("trigger_summary") or "").strip()
    if trigger_summary:
        return trigger_summary[:120]
    return ""


def _follow_up_timing_line(action: dict, *, today: date) -> str:
    due_date = parse_action_date(action.get("follow_up_due_at"))
    if due_date is None:
        return ""
    day_delta = (due_date - today).days
    if day_delta < 0:
        return "Overdue"
    if day_delta == 0:
        return "Due today"
    return ""


def _submit_primary_action(
    action: dict,
    selected_action_code: str,
    outcome: str,
    note: str,
    next_follow_up_at: str,
    tenant_id: str,
    performed_by: str,
) -> bool:
    action_id = str(action.get("id") or "")
    employee_id = str(action.get("employee_id") or "")
    primary_action_code = str(selected_action_code or "").strip().lower()
    if primary_action_code not in ACTION_CODES:
        return False
    note_text = str(note or "").strip()
    submitted = False

    if primary_action_code == "log_recognition":
        note_payload = note_text
        if outcome and outcome != "not_applicable":
            note_payload = f"outcome={outcome}\n{note_text}".strip()
        result = log_recognition_event(
            action_id=action_id,
            employee_id=employee_id,
            performed_by=performed_by,
            notes=note_payload,
            next_follow_up_at=next_follow_up_at,
            tenant_id=tenant_id,
        )
        submitted = bool(result)
    elif primary_action_code == "mark_for_review":
        reason = f"outcome={outcome}\nnote={note_text}".strip()
        result = mark_action_escalated(action_id=action_id, reason=reason, tenant_id=tenant_id)
        if result:
            log_action_event(
                action_id=action_id,
                event_type="escalated",
                employee_id=employee_id,
                performed_by=performed_by,
                notes=note_text,
                outcome=outcome,
                next_follow_up_at=next_follow_up_at,
                tenant_id=tenant_id,
            )
        submitted = bool(result)
    elif primary_action_code == "lower_urgency":
        reason = f"outcome={outcome}\nnote={note_text}".strip()
        result = mark_action_deprioritized(action_id=action_id, reason=reason, tenant_id=tenant_id)
        if result:
            log_action_event(
                action_id=action_id,
                event_type="deprioritized",
                employee_id=employee_id,
                performed_by=performed_by,
                notes=note_text,
                outcome=outcome,
                next_follow_up_at=next_follow_up_at,
                tenant_id=tenant_id,
            )
        submitted = bool(result)
    else:
        event_type = "coached" if primary_action_code == "log_check_in" else "follow_up_logged"
        result = save_action_touchpoint(
            action_id=action_id,
            event_type=event_type,
            performed_by=performed_by,
            outcome=outcome,
            notes=note_text,
            next_follow_up_at=next_follow_up_at,
            tenant_id=tenant_id,
        )
        submitted = bool(result)

    return submitted


def render_action_card(action: dict, *, tenant_id: str, performed_by: str, today: date) -> None:
    _render_queue_styles()
    action_id = str(action.get("id") or "")
    employee_name = str(action.get("employee_name") or action.get("employee_id") or "Unknown")
    primary_cta = "Choose action"
    form_key = _action_form_key(action_id)
    department = str(action.get("department") or "").strip()
    line_1 = f"{employee_name} · {department}" if department else employee_name
    line_2 = _follow_up_signal(action)
    line_3 = _follow_up_context_line(action)
    line_4 = _follow_up_timing_line(action, today=today)

    with st.container(border=True):
        st.markdown(
            f"""
            <div class="today-card-shell">
                <div class="today-card-header">
                    <div>
                        <div class="today-card-name">{_escape_html(line_1)}</div>
                    </div>
                </div>
                <div class="today-card-copy">
                    <div class="today-copy-block">
                        <div class="today-copy-value">{_escape_html(line_2)}</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if line_3:
            st.caption(line_3)
        if line_4:
            st.caption(line_4)

        if st.button(primary_cta, key=f"today_primary_cta_{action_id}", type="primary", use_container_width=True):
            st.session_state[form_key] = not bool(st.session_state.get(form_key, False))
            st.rerun()

        if st.session_state.get(form_key, False):
            with st.form(key=f"today_action_form_{action_id}", clear_on_submit=False):
                selected_action_label = st.selectbox(
                    "Action",
                    options=["Select action"] + ACTION_OPTIONS,
                    index=0,
                    key=f"today_action_choice_{action_id}",
                )
                outcome_display = st.selectbox(
                    "Outcome",
                    options=OUTCOME_OPTIONS,
                    index=0,
                    key=f"today_outcome_{action_id}",
                )
                outcome = outcome_code(outcome_display)
                note = st.text_area(
                    "Note (optional)",
                    value="",
                    placeholder="Add a short note if it helps the next follow-up.",
                    height=80,
                    key=f"today_note_{action_id}",
                )
                schedule_next = st.checkbox(
                    "Set next follow-up date",
                    value=False,
                    key=f"today_schedule_toggle_{action_id}",
                )
                next_follow_up_at = ""
                if schedule_next:
                    next_follow_up_date = st.date_input(
                        "Next follow-up date",
                        value=today + timedelta(days=7),
                        key=f"today_follow_up_date_{action_id}",
                    )
                    next_follow_up_at = next_follow_up_date.isoformat()

                submit_col, cancel_col = st.columns(2)
                submit = submit_col.form_submit_button("Save action", type="primary", use_container_width=True)
                cancel = cancel_col.form_submit_button("Cancel", use_container_width=True)

            if cancel:
                st.session_state[form_key] = False
                st.rerun()

            if submit:
                selected_action_code = _action_code_from_label(selected_action_label)
                if not selected_action_code:
                    st.error("Choose an action before saving.")
                    return
                success = _submit_primary_action(
                    action=action,
                    selected_action_code=selected_action_code,
                    outcome=outcome,
                    note=note,
                    next_follow_up_at=next_follow_up_at,
                    tenant_id=tenant_id,
                    performed_by=performed_by,
                )
                if success:
                    _set_flash_and_refresh(f"{employee_name}: update logged.", action_id)
                st.error("Action could not be saved. Please try again.")


def render_action_queue(queue_items: list[dict], *, tenant_id: str, performed_by: str, today: date) -> None:
    primary_items, secondary_items = partition_action_queue_items(queue_items)

    visible_items = primary_items[:MAX_VISIBLE_QUEUE_ITEMS]
    overflow_items = primary_items[MAX_VISIBLE_QUEUE_ITEMS:]

    for action in visible_items:
        render_action_card(action, tenant_id=tenant_id, performed_by=performed_by, today=today)

    if overflow_items:
        with st.expander(f"Show {len(overflow_items)} more queue item{'s' if len(overflow_items) != 1 else ''}"):
            for action in overflow_items:
                render_action_card(action, tenant_id=tenant_id, performed_by=performed_by, today=today)

    if secondary_items:
        with st.expander(f"Other items (low confidence) ({len(secondary_items)})", expanded=False):
            for action in secondary_items[:MAX_VISIBLE_QUEUE_ITEMS]:
                render_action_card(action, tenant_id=tenant_id, performed_by=performed_by, today=today)