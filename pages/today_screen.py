from __future__ import annotations

from datetime import date, timedelta

from core.dependencies import _log_app_error, require_db
from core.runtime import st, traceback, init_runtime

init_runtime()

from cache import bust_cache
from pages.common import load_goal_status_history
from services.supervisor_execution_service import build_today_screen_payload

ACTION_TYPES = [
    "coaching_followup",
    "process_retraining",
    "workstation_check",
    "escalate",
    "development_touchpoint",
]
OUTCOME_OPTIONS = ["improved", "no_change", "worse", "blocked"]


def _db():
    import database

    return database


def _load_actions(tenant_id: str) -> list[dict]:
    try:
        return _db().list_supervisor_actions(tenant_id=tenant_id)
    except Exception as error:
        _log_app_error("today_screen", f"Load actions failed: {error}", detail=traceback.format_exc())
        return []


def _load_action_payload(tenant_id: str) -> tuple[list[dict], list[dict], dict]:
    gs, history = load_goal_status_history("Loading today screen…")
    if gs is None:
        return [], [], {}
    actions = _load_actions(tenant_id)
    payload = build_today_screen_payload(gs or [], history or [], actions)
    return gs or [], history or [], payload


def _create_action_from_queue_item(item: dict, user_name: str) -> None:
    issue_type = item.get("issue_type") or "followup"
    action_type = st.session_state.get(f"create_action_type_{item['emp_id']}", ACTION_TYPES[0])
    due_date = st.session_state.get(f"create_due_date_{item['emp_id']}", date.today())
    success_metric = st.session_state.get(f"create_success_metric_{item['emp_id']}", item.get("success_metric") or "")
    note = st.session_state.get(f"create_note_{item['emp_id']}", "")
    try:
        _db().create_supervisor_action(
            emp_id=item["emp_id"],
            employee_name=item.get("employee_name", ""),
            department=item.get("department", ""),
            issue_type=issue_type,
            reason=item.get("reason", ""),
            action_type=action_type,
            success_metric=success_metric,
            due_date=str(due_date),
            note=note,
            created_by=user_name,
            baseline_uph=item.get("baseline_uph") or 0,
            latest_uph=item.get("latest_uph") or 0,
        )
        st.toast("Action started", icon="✅")
        bust_cache()
        st.rerun()
    except Exception as error:
        _log_app_error("today_screen", f"Create action failed: {error}", detail=traceback.format_exc())
        st.error("Could not start this action.")


def _save_existing_action(action_id: str) -> None:
    due_date = st.session_state.get(f"edit_due_date_{action_id}", date.today())
    action_type = st.session_state.get(f"edit_action_type_{action_id}", ACTION_TYPES[0])
    success_metric = st.session_state.get(f"edit_success_metric_{action_id}", "")
    note = st.session_state.get(f"edit_note_{action_id}", "")
    status = st.session_state.get(f"edit_status_{action_id}", "in_progress")
    try:
        _db().update_supervisor_action(
            action_id=action_id,
            updates={
                "due_date": str(due_date),
                "action_type": action_type,
                "success_metric": success_metric,
                "note": note,
                "status": status,
            },
        )
        st.toast("Action updated", icon="✅")
        bust_cache()
        st.rerun()
    except Exception as error:
        _log_app_error("today_screen", f"Update action failed: {error}", detail=traceback.format_exc())
        st.error("Could not update this action.")


def _resolve_action(action: dict, latest_uph_lookup: dict[str, float]) -> None:
    action_id = str(action.get("id") or "")
    outcome = st.session_state.get(f"resolve_outcome_{action_id}", OUTCOME_OPTIONS[0])
    outcome_note = st.session_state.get(f"resolve_note_{action_id}", "")
    latest_uph = float(latest_uph_lookup.get(str(action.get("emp_id") or ""), 0.0) or 0.0)
    baseline = float(action.get("baseline_uph") or 0.0)
    delta = round(latest_uph - baseline, 2)
    try:
        _db().update_supervisor_action(
            action_id=action_id,
            updates={
                "status": "closed",
                "outcome": outcome,
                "outcome_note": outcome_note,
                "latest_uph": latest_uph,
                "improvement_delta": delta,
            },
        )
        if outcome_note.strip():
            try:
                _db().add_coaching_note(str(action.get("emp_id") or ""), f"Action outcome: {outcome.replace('_', ' ')}. {outcome_note.strip()}")
            except Exception:
                pass
        st.toast("Outcome recorded", icon="✅")
        bust_cache()
        st.rerun()
    except Exception as error:
        _log_app_error("today_screen", f"Resolve action failed: {error}", detail=traceback.format_exc())
        st.error("Could not record this outcome.")


def _latest_uph_lookup(gs: list[dict]) -> dict[str, float]:
    out = {}
    for row in gs or []:
        emp_id = str(row.get("EmployeeID") or row.get("Employee Name") or "")
        if not emp_id:
            continue
        try:
            out[emp_id] = float(row.get("Average UPH") or 0.0)
        except Exception:
            out[emp_id] = 0.0
    return out


def _render_summary(summary: dict) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Open actions", int(summary.get("open_actions") or 0))
    col2.metric("Overdue", int(summary.get("overdue") or 0))
    col3.metric("Repeat offenders", int(summary.get("repeat_offenders") or 0))
    col4.metric("Ignored high performers", int(summary.get("ignored_high_performers") or 0))


def _render_generated_item(item: dict, user_name: str) -> None:
    expander_title = f"{item['status']} · {item['employee_name']} · {item['reason']}"
    with st.expander(expander_title, expanded=item.get("urgency", 0) >= 90):
        st.caption(f"{item.get('department', '')} · Next step: {item.get('next_step', '')}")
        st.selectbox(
            "Action type",
            ACTION_TYPES,
            key=f"create_action_type_{item['emp_id']}",
        )
        st.date_input(
            "Follow-up due",
            value=date.today() + timedelta(days=1),
            key=f"create_due_date_{item['emp_id']}",
        )
        st.text_input(
            "Success metric",
            value=item.get("success_metric") or "Return to target UPH",
            key=f"create_success_metric_{item['emp_id']}",
        )
        st.text_area(
            "Action note",
            key=f"create_note_{item['emp_id']}",
            placeholder="What will you do and how will you know it worked?",
        )
        if st.button("Start action", key=f"start_action_{item['emp_id']}", type="primary"):
            _create_action_from_queue_item(item, user_name)


def _render_existing_action(item: dict, latest_uph_lookup: dict[str, float]) -> None:
    action_id = str(item.get("id") or "")
    expander_title = f"{item['status']} · {item['employee_name']} · {item['reason']}"
    with st.expander(expander_title, expanded=item.get("status") in {"Overdue", "Due Today"}):
        st.caption(f"{item.get('department', '')} · Next step: {item.get('next_step', '')}")
        st.selectbox(
            "Action type",
            ACTION_TYPES,
            index=ACTION_TYPES.index(item.get("action_type")) if item.get("action_type") in ACTION_TYPES else 0,
            key=f"edit_action_type_{action_id}",
        )
        default_due = date.today() + timedelta(days=1)
        try:
            if item.get("due_date"):
                default_due = date.fromisoformat(str(item.get("due_date"))[:10])
        except Exception:
            pass
        st.date_input("Follow-up due", value=default_due, key=f"edit_due_date_{action_id}")
        st.selectbox(
            "Status",
            ["new", "in_progress", "escalated"],
            index=["new", "in_progress", "escalated"].index("in_progress" if item.get("status") in {"Due Today", "Overdue"} else str(item.get("status") or "new").lower()) if ("in_progress" if item.get("status") in {"Due Today", "Overdue"} else str(item.get("status") or "new").lower()) in ["new", "in_progress", "escalated"] else 0,
            key=f"edit_status_{action_id}",
        )
        st.text_input("Success metric", value=item.get("success_metric") or "", key=f"edit_success_metric_{action_id}")
        st.text_area("Action note", value="", key=f"edit_note_{action_id}", placeholder="Update plan or add context")
        c1, c2 = st.columns(2)
        if c1.button("Save plan", key=f"save_action_{action_id}"):
            _save_existing_action(action_id)
        c2.markdown(f"Current UPH: **{latest_uph_lookup.get(str(item.get('emp_id') or ''), 0.0):.1f}**")
        st.divider()
        st.selectbox("Outcome", OUTCOME_OPTIONS, key=f"resolve_outcome_{action_id}")
        st.text_area("Outcome note", key=f"resolve_note_{action_id}", placeholder="What happened after the action?")
        if st.button("Resolve action", key=f"resolve_action_{action_id}", type="primary"):
            _resolve_action(item, latest_uph_lookup)


def _render_action_queue(queue: list[dict], user_name: str, latest_uph_lookup: dict[str, float]) -> None:
    st.subheader("Open Actions")
    if not queue:
        st.success("No unhandled actions right now.")
        return
    for item in queue:
        if item.get("source") == "generated":
            _render_generated_item(item, user_name)
        else:
            _render_existing_action(item, latest_uph_lookup)


def _render_repeat_offenders(items: list[dict]) -> None:
    st.subheader("Repeat Offenders")
    if not items:
        st.caption("No repeat no-improvement cycles detected.")
        return
    for item in items:
        st.markdown(
            f"- **{item['employee_name']}** ({item['department']}) · {item['failed_cycles']} failed cycles · {item['recommendation']}"
        )


def _render_ignored_high_performers(items: list[dict], user_name: str) -> None:
    st.subheader("Ignored High Performers")
    if not items:
        st.caption("No high performers missing development touchpoints.")
        return
    for item in items:
        with st.expander(f"{item['employee_name']} · {item['avg_uph']:.1f} UPH vs {item['target_uph']:.1f} target", expanded=False):
            st.caption(item["recommendation"])
            st.text_input(
                "Success metric",
                value="Document stretch assignment or recognition follow-up",
                key=f"create_success_metric_{item['emp_id']}",
            )
            st.text_area(
                "Development note",
                key=f"create_note_{item['emp_id']}",
                placeholder="What development action will you take?",
            )
            st.date_input(
                "Follow-up due",
                value=date.today() + timedelta(days=7),
                key=f"create_due_date_{item['emp_id']}",
            )
            st.selectbox(
                "Action type",
                ACTION_TYPES,
                index=ACTION_TYPES.index("development_touchpoint"),
                key=f"create_action_type_{item['emp_id']}",
            )
            if st.button("Start development action", key=f"start_dev_{item['emp_id']}"):
                _create_action_from_queue_item(
                    {
                        "emp_id": item["emp_id"],
                        "employee_name": item["employee_name"],
                        "department": item["department"],
                        "issue_type": "high_performer_development",
                        "reason": "High performer has no recent development action logged",
                        "success_metric": "Document stretch assignment or recognition follow-up",
                        "baseline_uph": item.get("avg_uph", 0.0),
                        "latest_uph": item.get("avg_uph", 0.0),
                    },
                    user_name,
                )


def _render_recent_outcomes(items: list[dict]) -> None:
    st.subheader("Did It Work?")
    if not items:
        st.caption("No recent closed actions yet.")
        return
    for item in items:
        delta_label = f"{item['delta']:+.1f} UPH" if item.get("delta") else "0.0 UPH"
        st.markdown(f"- **{item['employee_name']}** ({item['department']}) · {item['outcome']} · {delta_label} · {item['completed_at']}")


def page_supervisor() -> None:
    st.title("Today")
    st.caption("Act on what has not been handled yet, track outcomes, and keep follow-up discipline tight.")
    if not require_db():
        return

    tenant_id = str(st.session_state.get("tenant_id", "") or "")
    user_name = str(st.session_state.get("user_name", "") or st.session_state.get("user_email", "") or "Manager")

    try:
        gs, _history, payload = _load_action_payload(tenant_id)
    except Exception as error:
        _log_app_error("today_screen", f"Today screen load failed: {error}", detail=traceback.format_exc())
        st.error("Could not load the Today screen.")
        return

    if not payload:
        return

    latest_lookup = _latest_uph_lookup(gs)
    _render_summary(payload.get("summary") or {})
    st.divider()
    _render_action_queue(payload.get("action_queue") or [], user_name, latest_lookup)
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        _render_repeat_offenders(payload.get("repeat_offenders") or [])
    with col2:
        _render_ignored_high_performers(payload.get("ignored_high_performers") or [], user_name)
    st.divider()
    _render_recent_outcomes(payload.get("recent_outcomes") or [])
