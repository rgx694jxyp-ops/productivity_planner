"""Action lifecycle service.

Responsible for action create/update/advance/close/reopen and trigger orchestration.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from domain.actions import (
    IssueType,
    OPEN_STATUSES,
    can_transition_status,
    determine_priority,
    runtime_status,
)
from repositories import action_events_repo, actions_repo
from services.access_control_service import require_write
from services.app_logging import log_error, log_info, log_warn
from services.observability import log_operational_event
from services.action_query_service import (
    _extract_row_dept,
    _extract_row_name,
    _extract_row_uph,
    _history_by_emp,
    _parse_date,
    get_open_actions,
)


def _action_log_context(
    *,
    action_id: str = "",
    employee_id: str = "",
    event_type: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {}
    if action_id:
        context["action_id"] = str(action_id)
    if employee_id:
        context["employee_id"] = str(employee_id)
    if event_type:
        context["event_type"] = str(event_type)
    if extra:
        context.update(extra)
    return context

def create_action(
    employee_id: str,
    employee_name: str,
    department: str,
    issue_type: str,
    trigger_summary: str,
    action_type: str,
    success_metric: str,
    follow_up_due_at: str,
    note: str = "",
    created_by: str = "",
    baseline_uph: float = 0.0,
    latest_uph: float = 0.0,
    priority: str = "medium",
    tenant_id: str = "",
    user_role: str = "",
) -> dict:
    """Create a new action and log creation event. Raises no exceptions — returns {} on failure."""
    try:
        require_write(user_role)
        result = actions_repo.create_action(
            employee_id=employee_id,
            employee_name=employee_name,
            department=department,
            issue_type=issue_type,
            trigger_summary=trigger_summary,
            action_type=action_type,
            success_metric=success_metric,
            follow_up_due_at=follow_up_due_at,
            note=note,
            created_by=created_by,
            baseline_uph=baseline_uph,
            latest_uph=latest_uph,
            priority=priority,
            tenant_id=tenant_id,
        )
        return result
    except Exception as e:
        log_error(
            "action_create_failed",
            "Action creation failed.",
            tenant_id=tenant_id,
            context=_action_log_context(
                employee_id=employee_id,
                extra={"issue_type": issue_type, "action_type": action_type},
            ),
            error=e,
        )
        return {}



def mark_action_resolved(
    action_id: str,
    resolution_type: str,
    resolution_note: str = "",
    latest_uph: float = 0.0,
    improvement_delta: float = 0.0,
    tenant_id: str = "",
) -> dict:
    """Mark action as resolved with outcome. Always logs event."""
    try:
        result = actions_repo.update_action(
            action_id=action_id,
            updates={
                "status": "resolved",
                "resolution_type": resolution_type,
                "resolution_note": resolution_note,
                "latest_uph": latest_uph,
                "improvement_delta": improvement_delta,
            },
            tenant_id=tenant_id,
        )
        if result:
            log_operational_event(
                "action_completed",
                status="completed",
                tenant_id=tenant_id,
                context={
                    "action_id": str(action_id or ""),
                    "resolution_type": str(resolution_type or ""),
                },
            )
        return result
    except Exception as e:
        log_error(
            "action_resolve_failed",
            "Action resolution failed.",
            tenant_id=tenant_id,
            context=_action_log_context(action_id=action_id, extra={"resolution_type": resolution_type}),
            error=e,
        )
        return {}


def mark_action_deprioritized(
    action_id: str,
    reason: str = "",
    tenant_id: str = "",
) -> dict:
    """Mark action as deprioritized. Always logs event."""
    try:
        result = actions_repo.update_action(
            action_id=action_id,
            updates={
                "status": "deprioritized",
                "note": reason,
            },
            tenant_id=tenant_id,
        )
        return result
    except Exception as e:
        log_error(
            "action_deprioritize_failed",
            "Action deprioritization failed.",
            tenant_id=tenant_id,
            context=_action_log_context(action_id=action_id),
            error=e,
        )
        return {}


def mark_action_escalated(
    action_id: str,
    reason: str = "",
    tenant_id: str = "",
) -> dict:
    """Mark action as escalated."""
    try:
        result = actions_repo.update_action(
            action_id=action_id,
            updates={
                "status": "escalated",
                "note": reason,
            },
            tenant_id=tenant_id,
        )
        return result
    except Exception as e:
        log_error(
            "action_escalate_failed",
            "Action escalation failed.",
            tenant_id=tenant_id,
            context=_action_log_context(action_id=action_id),
            error=e,
        )
        return {}


def mark_action_transferred(
    action_id: str,
    reason: str = "",
    tenant_id: str = "",
) -> dict:
    """Mark action as transferred."""
    try:
        result = actions_repo.update_action(
            action_id=action_id,
            updates={
                "status": "transferred",
                "note": reason,
            },
            tenant_id=tenant_id,
        )
        return result
    except Exception as e:
        log_error(
            "action_transfer_failed",
            "Action transfer failed.",
            tenant_id=tenant_id,
            context=_action_log_context(action_id=action_id),
            error=e,
        )
        return {}


def mark_action_in_progress(
    action_id: str,
    tenant_id: str = "",
) -> dict:
    """Move action to in_progress status. Always logs event."""
    try:
        result = actions_repo.update_action(
            action_id=action_id,
            updates={"status": "in_progress"},
            tenant_id=tenant_id,
        )
        return result
    except Exception as e:
        log_error(
            "action_start_failed",
            "Action transition to in-progress failed.",
            tenant_id=tenant_id,
            context=_action_log_context(action_id=action_id),
            error=e,
        )
        return {}


def reopen_action(
    action_id: str,
    reason: str = "Reopened by supervisor",
    tenant_id: str = "",
) -> dict:
    """Reopen a resolved/deprioritized action. Returns {} if transition not allowed."""
    try:
        actions = actions_repo.list_actions(tenant_id=tenant_id, employee_id="")
        current = next((a for a in actions if str(a.get("id")) == str(action_id)), None)
        if not current:
            log_warn(
                "action_reopen_missing",
                "Action reopen skipped because the action was not found.",
                tenant_id=tenant_id,
                context=_action_log_context(action_id=action_id),
            )
            return {}
        current_status = str(current.get("status") or "new")
        if not can_transition_status(current_status, "in_progress"):
            log_warn(
                "action_reopen_blocked",
                "Action reopen skipped because the transition is not allowed.",
                tenant_id=tenant_id,
                context=_action_log_context(action_id=action_id, extra={"current_status": current_status}),
            )
            return {}
        result = actions_repo.update_action(
            action_id=action_id,
            updates={"status": "in_progress", "note": reason},
            tenant_id=tenant_id,
        )
        return result
    except Exception as e:
        log_error(
            "action_reopen_failed",
            "Action reopen failed.",
            tenant_id=tenant_id,
            context=_action_log_context(action_id=action_id),
            error=e,
        )
        return {}


def refresh_action_statuses(tenant_id: str = "", today: date | None = None) -> int:
    """Scan open actions, persist derived runtime status updates, and return update count."""
    today = today or date.today()
    try:
        actions = actions_repo.list_actions(
            tenant_id=tenant_id,
            statuses=list(OPEN_STATUSES),
        )
        updated = 0
        for action in actions or []:
            current_status = str(action.get("status") or "new")
            derived_status = runtime_status(
                current_status,
                action.get("follow_up_due_at"),
                today=today,
            )
            if derived_status == current_status:
                continue
            if not can_transition_status(current_status, derived_status):
                continue
            priority = determine_priority(
                issue_type=str(action.get("issue_type") or ""),
                status=derived_status,
                failed_cycles=int(action.get("failed_cycles") or 0),
                follow_up_due_at=action.get("follow_up_due_at"),
                today=today,
            )
            result = actions_repo.update_action(
                action_id=str(action.get("id") or ""),
                updates={
                    "status": derived_status,
                    "priority": priority,
                },
                tenant_id=tenant_id,
            )
            if result:
                updated += 1
        return updated
    except Exception as e:
        log_error(
            "action_refresh_statuses_failed",
            "Action status refresh failed.",
            tenant_id=tenant_id,
            context={"today": today.isoformat()},
            error=e,
        )
        return 0


def log_action_event(
    action_id: str,
    event_type: str,
    employee_id: str = "",
    performed_by: str = "",
    notes: str = "",
    outcome: str | None = None,
    next_follow_up_at: str = "",
    tenant_id: str = "",
) -> dict:
    """Log an immutable lifecycle event for an action. Returns created event or {} on failure."""
    try:
        result = action_events_repo.log_action_event(
            action_id=action_id,
            event_type=event_type,
            employee_id=employee_id,
            performed_by=performed_by,
            notes=notes,
            outcome=outcome,
            next_follow_up_at=next_follow_up_at,
            tenant_id=tenant_id,
        )
        if result:
            log_operational_event(
                "action_event_created",
                status="completed",
                tenant_id=tenant_id,
                context={
                    "action_id": str(action_id or ""),
                    "event_type": str(event_type or ""),
                    "event_id": str(result.get("id") or ""),
                },
            )
        return result
    except Exception as e:
        log_error(
            "action_event_log_failed",
            "Action event logging failed.",
            tenant_id=tenant_id,
            context=_action_log_context(action_id=action_id, employee_id=employee_id, event_type=event_type),
            error=e,
        )
        return {}



def save_action_touchpoint(
    action_id: str,
    event_type: str,
    performed_by: str = "",
    outcome: str | None = None,
    notes: str = "",
    next_follow_up_at: str = "",
    tenant_id: str = "",
) -> dict:
    """Save a quick coaching or follow-up touchpoint and refresh the parent action."""
    try:
        result = actions_repo.update_action(
            action_id=action_id,
            updates={
                "status": "in_progress",
                "note": notes,
                **({"follow_up_due_at": next_follow_up_at} if next_follow_up_at else {}),
            },
            tenant_id=tenant_id,
        )
        event = log_action_event(
            action_id=action_id,
            event_type=event_type,
            employee_id=str(result.get("employee_id") or ""),
            performed_by=performed_by,
            notes=notes,
            outcome=outcome,
            next_follow_up_at=next_follow_up_at,
            tenant_id=tenant_id,
        )
        return result or event
    except Exception as e:
        log_error(
            "action_touchpoint_save_failed",
            "Action touchpoint save failed.",
            tenant_id=tenant_id,
            context=_action_log_context(action_id=action_id, event_type=event_type),
            error=e,
        )
        return {}


def log_coaching_lifecycle_entry(
    *,
    employee_id: str,
    employee_name: str,
    department: str,
    reason: str,
    action_taken: str,
    expected_follow_up_date: str,
    performed_by: str = "",
    later_outcome: str = "pending",
    existing_action_id: str = "",
    tenant_id: str = "",
    user_role: str = "",
) -> dict:
    """Log coaching as a tracked lifecycle event.

    Uses an existing open action when available, otherwise creates a new action
    and logs the first coaching event.
    """
    try:
        target_action: dict = {}
        if existing_action_id:
            candidate = actions_repo.list_actions(
                tenant_id=tenant_id,
                employee_id=employee_id,
            )
            target_action = next((a for a in candidate if str(a.get("id")) == str(existing_action_id)), {})

        if not target_action:
            open_actions = actions_repo.list_actions(
                tenant_id=tenant_id,
                statuses=list(OPEN_STATUSES),
                employee_id=employee_id,
            )
            target_action = (open_actions or [{}])[0] if open_actions else {}

        created_new = False
        if not target_action:
            trigger_summary = f"Coaching initiated: {reason}".strip()
            action_note = f"reason={reason}\naction_taken={action_taken}".strip()
            target_action = create_action(
                employee_id=employee_id,
                employee_name=employee_name,
                department=department,
                issue_type=IssueType.LOW_PERFORMANCE_UNADDRESSED,
                trigger_summary=trigger_summary,
                action_type="coaching_followup",
                success_metric="Sustain measurable improvement after coaching",
                follow_up_due_at=expected_follow_up_date,
                note=action_note,
                created_by=performed_by,
                tenant_id=tenant_id,
                user_role=user_role,
            )
            created_new = bool(target_action)

        action_id = str(target_action.get("id") or "")
        if not action_id:
            return {}

        status_update = actions_repo.update_action(
            action_id=action_id,
            updates={
                "status": "in_progress",
                "follow_up_due_at": expected_follow_up_date,
                "note": f"reason={reason}\naction_taken={action_taken}",
            },
            tenant_id=tenant_id,
        )

        event = log_action_event(
            action_id=action_id,
            event_type="coached",
            employee_id=employee_id,
            performed_by=performed_by,
            notes=f"reason={reason}\naction_taken={action_taken}",
            outcome=later_outcome or "pending",
            next_follow_up_at=expected_follow_up_date,
            tenant_id=tenant_id,
        )

        return {
            "action_id": action_id,
            "created_new_action": created_new,
            "action": status_update or target_action,
            "event": event,
        }
    except Exception as e:
        log_error(
            "coaching_lifecycle_log_failed",
            "Coaching lifecycle logging failed.",
            tenant_id=tenant_id,
            context=_action_log_context(employee_id=employee_id, extra={"existing_action_id": existing_action_id}),
            error=e,
        )
        return {}



def log_recognition_event(
    action_id: str,
    employee_id: str = "",
    performed_by: str = "",
    notes: str = "",
    next_follow_up_at: str = "",
    tenant_id: str = "",
) -> dict:
    """Log a 'recognized' event and update action status to resolved."""
    try:
        actions_repo.update_action(
            action_id=action_id,
            updates={"status": "resolved", "resolution_type": "improved"},
            tenant_id=tenant_id,
        )
        event = log_action_event(
            action_id=action_id,
            event_type="recognized",
            employee_id=employee_id,
            performed_by=performed_by,
            notes=notes,
            outcome="not_applicable",
            next_follow_up_at=next_follow_up_at,
            tenant_id=tenant_id,
        )
        return event
    except Exception as e:
        log_error(
            "recognition_event_failed",
            "Recognition event logging failed.",
            tenant_id=tenant_id,
            context=_action_log_context(action_id=action_id, employee_id=employee_id),
            error=e,
        )
        return {}



def trigger_repeated_low_performance(
    history: list[dict],
    baseline_mapping: dict[str, float],
    low_count_threshold: int = 3,
    lookback_shifts: int = 7,
    tenant_id: str = "",
) -> dict:
    """Trigger 1: Create action for employees with repeated low performance.
    
    If employee is below baseline for low_count_threshold of last lookback_shifts
    and no active action exists, create action.
    
    Returns: {"created": int, "skipped": int, "errors": int}
    """
    result = {"created": 0, "skipped": 0, "errors": 0}
    try:
        history_by_emp = _history_by_emp(history)
        existing_actions = get_open_actions(tenant_id=tenant_id)
        active_emp_ids = {str(a.get("employee_id")) for a in existing_actions}
        
        for emp_id, rows in history_by_emp.items():
            if emp_id in active_emp_ids:
                result["skipped"] += 1
                continue
            
            # Check last lookback_shifts for performance below baseline
            baseline = baseline_mapping.get(emp_id, 100.0)
            recent = rows[-lookback_shifts:] if rows else []
            low_count = sum(1 for r in recent if _extract_row_uph(r) < baseline)
            
            if low_count >= low_count_threshold:
                emp_name = _extract_row_name(recent[-1]) if recent else emp_id
                dept = _extract_row_dept(recent[-1]) if recent else ""
                latest_uph = _extract_row_uph(recent[-1]) if recent else 0.0
                
                action = create_action(
                    employee_id=emp_id,
                    employee_name=emp_name,
                    department=dept,
                    issue_type="performance",
                    trigger_summary=f"Below baseline {low_count}/{lookback_shifts} shifts",
                    action_type="coaching",
                    success_metric=f"Reach {baseline:.0f}+ UPH consistently",
                    follow_up_due_at=(date.today() + timedelta(days=7)).isoformat(),
                    baseline_uph=baseline,
                    latest_uph=latest_uph,
                    tenant_id=tenant_id,
                    user_role="admin",
                )
                if action:
                    result["created"] += 1
                else:
                    result["errors"] += 1
    except Exception as e:
        log_error(
            "action_trigger_low_performance_failed",
            "Repeated low-performance trigger failed.",
            tenant_id=tenant_id,
            context={"history_rows": len(history or [])},
            error=e,
        )
        result["errors"] += 1
    
    return result


def trigger_follow_up_due(
    tenant_id: str = "",
    today: date | None = None,
) -> dict:
    """Trigger 2: Mark actions as overdue if follow_up_due_at is in past.
    
    Scans open actions and counts those with follow_up_due_at before today.
    (Actual status persistence can be handled by daily batch job.)
    
    Returns: {"overdue_count": int, "at_risk_count": int}
    """
    today = today or date.today()
    result = {"overdue_count": 0, "at_risk_count": 0}
    try:
        open_actions = get_open_actions(tenant_id=tenant_id, today=today)
        for action in open_actions:
            due_str = action.get("follow_up_due_at")
            if not due_str:
                continue
            due_date = _parse_date(due_str)
            if not due_date:
                continue
            
            days_until = (due_date - today).days
            if days_until < 0:
                result["overdue_count"] += 1
            elif days_until <= 2:
                result["at_risk_count"] += 1
    except Exception as e:
        log_error(
            "action_trigger_follow_up_due_failed",
            "Follow-up due trigger failed.",
            tenant_id=tenant_id,
            context={"today": today.isoformat()},
            error=e,
        )
    
    return result


def trigger_repeat_no_improvement(
    tenant_id: str = "",
) -> dict:
    """Trigger 3: Flag actions with multiple no_improvement outcomes.
    
    Scans all actions and identifies employees with 2+ events showing
    no_change or worse outcomes. Recommendation: deprioritize or escalate.
    
    Returns: {"flagged_count": int, "escalated_count": int}
    """
    result = {"flagged_count": 0, "escalated_count": 0}
    try:
        all_actions = actions_repo.list_actions(tenant_id=tenant_id, employee_id="")
        actions_by_emp = {}
        for action in all_actions:
            emp_id = str(action.get("employee_id") or "")
            if not emp_id:
                continue
            actions_by_emp.setdefault(emp_id, []).append(action)
        
        for emp_id, actions in actions_by_emp.items():
            no_improvement_count = 0
            for action in actions:
                last_outcome = action.get("last_outcome")
                if last_outcome in NO_IMPROVEMENT_OUTCOMES:
                    no_improvement_count += 1
            
            if no_improvement_count >= 2:
                result["flagged_count"] += 1
                # For true escalation, set priority to "high" or add note
                # This is a signal for supervisor review
    except Exception as e:
        log_error(
            "action_trigger_repeat_no_improvement_failed",
            "Repeat no-improvement trigger failed.",
            tenant_id=tenant_id,
            error=e,
        )
    
    return result


def trigger_ignored_high_performer(
    history: list[dict],
    top_percentile_threshold: float = 0.80,
    lookback_days: int = 21,
    tenant_id: str = "",
) -> dict:
    """Trigger 4: Create recognition/development action for consistent high performers.
    
    If employee is in top percentile (by UPH) for last lookback_days
    and no recognition action exists, create one.
    
    Returns: {"created": int, "skipped": int}
    """
    result = {"created": 0, "skipped": 0}
    try:
        
        # Calculate top performer threshold
        all_uphs = [_extract_row_uph(r) for r in history if _extract_row_uph(r) > 0]
        if not all_uphs:
            return result
        
        all_uphs.sort()
        threshold = all_uphs[int(len(all_uphs) * top_percentile_threshold)]
        
        # Group by employee and check recent performance
        history_by_emp = _history_by_emp(history)
        cutoff = date.today() - timedelta(days=lookback_days)
        existing_actions = get_open_actions(tenant_id=tenant_id)
        active_emp_ids = {str(a.get("employee_id")) for a in existing_actions}
        
        for emp_id, rows in history_by_emp.items():
            if emp_id in active_emp_ids:
                result["skipped"] += 1
                continue
            
            # Check if consistently in top percentile
            recent_rows = [r for r in rows if _parse_date(r.get("Date") or r.get("work_date")) and _parse_date(r.get("Date") or r.get("work_date")) >= cutoff]
            if not recent_rows:
                continue
            
            avg_recent = round(sum(_extract_row_uph(r) for r in recent_rows) / len(recent_rows), 2)
            if avg_recent >= threshold:
                emp_name = _extract_row_name(recent_rows[-1]) if recent_rows else emp_id
                dept = _extract_row_dept(recent_rows[-1]) if recent_rows else ""
                
                action = create_action(
                    employee_id=emp_id,
                    employee_name=emp_name,
                    department=dept,
                    issue_type="recognition",
                    trigger_summary=f"Top {int((1-top_percentile_threshold)*100)}% performer ({avg_recent:.0f} avg UPH)",
                    action_type="recognition",
                    success_metric="Recognize achievement and explore development opportunities",
                    follow_up_due_at=(date.today() + timedelta(days=14)).isoformat(),
                    baseline_uph=threshold,
                    latest_uph=avg_recent,
                    tenant_id=tenant_id,
                    user_role="admin",
                )
                if action:
                    result["created"] += 1
    except Exception as e:
        log_error(
            "action_trigger_high_performer_failed",
            "High-performer trigger failed.",
            tenant_id=tenant_id,
            context={"history_rows": len(history or [])},
            error=e,
        )
    
    return result


def run_all_triggers(
    history: list[dict] = None,
    baseline_mapping: dict[str, float] = None,
    tenant_id: str = "",
) -> dict:
    """Run all triggers and return combined summary.
    
    Call this on Today Screen load or by daily refresh job.
    Loads history and baselines if not provided.
    
    Returns: {"trigger_1": {...}, "trigger_2": {...}, ...}
    """
    summary = {}
    try:
        if history is None:
            import data_loader
            history = data_loader.load_performance_history() or []
        if baseline_mapping is None:
            import data_loader
            baseline_mapping = data_loader.load_baseline_performance() or {}
        
        summary["trigger_1_low_performance"] = trigger_repeated_low_performance(
            history=history,
            baseline_mapping=baseline_mapping,
            tenant_id=tenant_id,
        )
        summary["trigger_2_follow_up_due"] = trigger_follow_up_due(tenant_id=tenant_id)
        summary["trigger_3_repeat_no_improvement"] = trigger_repeat_no_improvement(tenant_id=tenant_id)
        summary["trigger_4_high_performer"] = trigger_ignored_high_performer(
            history=history,
            tenant_id=tenant_id,
        )
        
        log_info(
            "action_triggers_completed",
            "Action triggers completed.",
            tenant_id=tenant_id,
            context=summary,
        )
    except Exception as e:
        log_error(
            "action_triggers_failed",
            "Running action triggers failed.",
            tenant_id=tenant_id,
            context={"has_history": history is not None, "has_baseline_mapping": baseline_mapping is not None},
            error=e,
        )
        summary["error"] = "Action trigger run failed."
    
    return summary


