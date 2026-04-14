"""Normalized action-state read model and safe scheduling adapter.

This service exposes one four-state interpretation over the existing
`actions`, `action_events`, and `coaching_followups` storage layers so UI
surfaces can read a single action-state contract without requiring a risky
storage rewrite.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from domain.actions import parse_action_date, runtime_status
from followup_manager import add_followup, get_followups_for_employee
from repositories import actions_repo
from services.action_lifecycle_service import (
    log_action_event as _log_action_event,
    log_coaching_lifecycle_entry as _log_coaching_lifecycle_entry,
    log_recognition_event as _log_recognition_event,
    mark_action_resolved as _mark_action_resolved,
    save_action_touchpoint as _save_action_touchpoint,
)
from services.action_query_service import get_employee_action_timeline, get_employee_actions
from services.app_logging import log_error
from services.follow_through_service import log_follow_through_event as _log_follow_through_event


class NormalizedActionState:
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    FOLLOW_UP_SCHEDULED = "Follow-up Scheduled"
    RESOLVED = "Resolved"


OPEN_NORMALIZED_ACTION_STATES: set[str] = {
    NormalizedActionState.OPEN,
    NormalizedActionState.IN_PROGRESS,
    NormalizedActionState.FOLLOW_UP_SCHEDULED,
}


def interpret_normalized_action_state(
    status: str,
    follow_up_due_at: Any = None,
    *,
    today: date | None = None,
) -> str:
    today = today or date.today()
    normalized_runtime = runtime_status(status, follow_up_due_at, today=today)
    legacy_status = str(status or "").strip().lower()
    due_date = parse_action_date(follow_up_due_at)

    if legacy_status in {"resolved", "deprioritized", "transferred"} or normalized_runtime == "resolved":
        return NormalizedActionState.RESOLVED
    if legacy_status == "new":
        return NormalizedActionState.OPEN
    if due_date is not None:
        return NormalizedActionState.FOLLOW_UP_SCHEDULED
    return NormalizedActionState.IN_PROGRESS


def interpret_follow_through_state(
    status: str,
    due_date: Any = None,
    *,
    today: date | None = None,
) -> str:
    del today
    normalized = str(status or "").strip().lower()
    if normalized == "done":
        return NormalizedActionState.RESOLVED
    if parse_action_date(due_date) is not None:
        return NormalizedActionState.FOLLOW_UP_SCHEDULED
    if normalized in {"logged", "pending", "blocked"}:
        return NormalizedActionState.IN_PROGRESS
    return NormalizedActionState.OPEN


def schedule_follow_up_for_employee(
    *,
    employee_id: str,
    employee_name: str,
    department: str,
    follow_up_date: str,
    note_preview: str = "",
    tenant_id: str = "",
    action_id: str = "",
) -> dict[str, Any]:
    """Safely schedule a follow-up while preserving the legacy scheduler mirror."""
    cleaned_date = str(follow_up_date or "").strip()[:10]
    if not cleaned_date or not str(employee_id or "").strip():
        return {}

    try:
        target_action_id = str(action_id or "").strip()
        if not target_action_id:
            open_actions = [
                action
                for action in get_employee_actions(employee_id, tenant_id=tenant_id)
                if interpret_normalized_action_state(
                    str(action.get("_runtime_status") or action.get("status") or ""),
                    action.get("follow_up_due_at"),
                )
                in OPEN_NORMALIZED_ACTION_STATES
            ]
            if open_actions:
                target_action_id = str(open_actions[0].get("id") or "")

        if target_action_id:
            updated = actions_repo.update_action(
                action_id=target_action_id,
                updates={
                    "status": "follow_up_due",
                    "follow_up_due_at": cleaned_date,
                    **({"note": str(note_preview or "")[:2000]} if str(note_preview or "").strip() else {}),
                },
                tenant_id=tenant_id,
            )
            return {
                "mode": "action_update",
                "action_id": target_action_id,
                "follow_up_date": cleaned_date,
                "action": updated,
            }

        add_followup(
            employee_id,
            employee_name,
            department,
            cleaned_date,
            note_preview,
            tenant_id=tenant_id,
        )
        return {
            "mode": "scheduler_only",
            "action_id": "",
            "follow_up_date": cleaned_date,
        }
    except Exception as error:
        log_error(
            "action_state_schedule_follow_up_failed",
            "Normalized follow-up scheduling failed.",
            tenant_id=tenant_id,
            context={
                "employee_id": str(employee_id or ""),
                "action_id": str(action_id or ""),
                "follow_up_date": cleaned_date,
            },
            error=error,
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
) -> dict[str, Any]:
    """Bridge coaching lifecycle writes through the normalized action-state API."""
    return _log_coaching_lifecycle_entry(
        employee_id=employee_id,
        employee_name=employee_name,
        department=department,
        reason=reason,
        action_taken=action_taken,
        expected_follow_up_date=expected_follow_up_date,
        performed_by=performed_by,
        later_outcome=later_outcome,
        existing_action_id=existing_action_id,
        tenant_id=tenant_id,
        user_role=user_role,
    )


def log_follow_through_event(
    *,
    employee_id: str = "",
    action_id: str = "",
    linked_exception_id: str = "",
    owner: str = "",
    status: str = "logged",
    due_date: str = "",
    details: str,
    outcome: str = "",
    tenant_id: str = "",
) -> dict[str, Any]:
    """Bridge follow-through logging through the normalized action-state API."""
    return _log_follow_through_event(
        employee_id=employee_id,
        action_id=action_id,
        linked_exception_id=linked_exception_id,
        owner=owner,
        status=status,
        due_date=due_date,
        details=details,
        outcome=outcome,
        tenant_id=tenant_id,
    )


def save_action_touchpoint(
    action_id: str,
    event_type: str,
    performed_by: str = "",
    outcome: str | None = None,
    notes: str = "",
    next_follow_up_at: str = "",
    tenant_id: str = "",
) -> dict[str, Any]:
    """Bridge touchpoint writes through the normalized action-state API."""
    return _save_action_touchpoint(
        action_id=action_id,
        event_type=event_type,
        performed_by=performed_by,
        outcome=outcome,
        notes=notes,
        next_follow_up_at=next_follow_up_at,
        tenant_id=tenant_id,
    )


def log_recognition_event(
    action_id: str,
    employee_id: str = "",
    performed_by: str = "",
    notes: str = "",
    next_follow_up_at: str = "",
    tenant_id: str = "",
) -> dict[str, Any]:
    """Bridge recognition writes through the normalized action-state API."""
    return _log_recognition_event(
        action_id=action_id,
        employee_id=employee_id,
        performed_by=performed_by,
        notes=notes,
        next_follow_up_at=next_follow_up_at,
        tenant_id=tenant_id,
    )


def mark_action_resolved(
    action_id: str,
    resolution_type: str,
    resolution_note: str = "",
    latest_uph: float = 0.0,
    improvement_delta: float = 0.0,
    tenant_id: str = "",
) -> dict[str, Any]:
    """Bridge action resolution writes through the normalized action-state API."""
    return _mark_action_resolved(
        action_id=action_id,
        resolution_type=resolution_type,
        resolution_note=resolution_note,
        latest_uph=latest_uph,
        improvement_delta=improvement_delta,
        tenant_id=tenant_id,
    )


def log_action_event(
    action_id: str,
    event_type: str,
    employee_id: str = "",
    performed_by: str = "",
    notes: str = "",
    outcome: str | None = None,
    next_follow_up_at: str = "",
    tenant_id: str = "",
) -> dict[str, Any]:
    """Bridge action event writes through the normalized action-state API."""
    return _log_action_event(
        action_id=action_id,
        event_type=event_type,
        employee_id=employee_id,
        performed_by=performed_by,
        notes=notes,
        outcome=outcome,
        next_follow_up_at=next_follow_up_at,
        tenant_id=tenant_id,
    )


def build_employee_action_state_summary(
    employee_id: str,
    *,
    tenant_id: str = "",
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    actions = list(get_employee_actions(employee_id, tenant_id=tenant_id, today=today) or [])
    timeline = list(get_employee_action_timeline(employee_id, tenant_id=tenant_id) or [])
    followups = list(
        get_followups_for_employee(
            employee_id,
            from_date=(today - timedelta(days=90)).isoformat(),
            to_date=(today + timedelta(days=365)).isoformat(),
            tenant_id=tenant_id,
        )
        or []
    )

    latest_event_by_action: dict[str, dict[str, Any]] = {}
    standalone_events: list[dict[str, Any]] = []
    for event in timeline:
        action_id = str(event.get("action_id") or "").strip()
        if action_id:
            latest_event_by_action.setdefault(action_id, event)
        else:
            standalone_events.append(event)

    states: list[dict[str, Any]] = []
    action_followup_keys: set[tuple[str, str]] = set()

    for action in actions:
        action_id = str(action.get("id") or "").strip()
        due_text = str(action.get("follow_up_due_at") or "").strip()[:10]
        if due_text:
            action_followup_keys.add((str(employee_id or "").strip(), due_text))
        latest_event = latest_event_by_action.get(action_id, {})
        runtime_value = str(action.get("_runtime_status") or action.get("status") or "")
        state_value = interpret_normalized_action_state(runtime_value, action.get("follow_up_due_at"), today=today)
        states.append(
            _build_action_state_row(
                source_type="action",
                source_label="Lifecycle action",
                employee_id=employee_id,
                employee_name=str(action.get("employee_name") or employee_id),
                department=str(action.get("department") or ""),
                action_id=action_id,
                title=str(action.get("trigger_summary") or "Open action"),
                note_preview=str(action.get("note") or ""),
                normalized_state=state_value,
                legacy_status=runtime_value,
                follow_up_due_at=due_text,
                latest_event=latest_event,
                today=today,
            )
        )

    for followup in followups:
        due_text = str(followup.get("followup_date") or "").strip()[:10]
        key = (str(followup.get("emp_id") or employee_id).strip(), due_text)
        if not due_text or key in action_followup_keys:
            continue
        states.append(
            _build_action_state_row(
                source_type="scheduled_only",
                source_label="Legacy follow-up schedule",
                employee_id=employee_id,
                employee_name=str(followup.get("name") or employee_id),
                department=str(followup.get("dept") or ""),
                action_id="",
                title=str(followup.get("note_preview") or "Scheduled follow-up"),
                note_preview=str(followup.get("note_preview") or ""),
                normalized_state=NormalizedActionState.FOLLOW_UP_SCHEDULED,
                legacy_status="scheduled_only",
                follow_up_due_at=due_text,
                latest_event={},
                today=today,
            )
        )

    if not states and standalone_events:
        latest_standalone = standalone_events[0]
        standalone_due = str(latest_standalone.get("next_follow_up_at") or "").strip()[:10]
        states.append(
            _build_action_state_row(
                source_type="standalone_follow_through",
                source_label="Standalone follow-through",
                employee_id=employee_id,
                employee_name=str(employee_id or ""),
                department="",
                action_id="",
                title=str(latest_standalone.get("notes") or latest_standalone.get("trigger_summary") or "Follow-through log"),
                note_preview=str(latest_standalone.get("notes") or ""),
                normalized_state=interpret_follow_through_state(
                    str(latest_standalone.get("status") or "logged"),
                    latest_standalone.get("next_follow_up_at"),
                    today=today,
                ),
                legacy_status=str(latest_standalone.get("status") or "logged"),
                follow_up_due_at=standalone_due,
                latest_event=latest_standalone,
                today=today,
            )
        )

    states.sort(key=_state_sort_key)
    summary = {
        "total_count": len(states),
        "open_count": sum(1 for item in states if item.get("is_open")),
        "scheduled_count": sum(1 for item in states if item.get("state") == NormalizedActionState.FOLLOW_UP_SCHEDULED),
        "resolved_count": sum(1 for item in states if item.get("state") == NormalizedActionState.RESOLVED),
        "in_progress_count": sum(1 for item in states if item.get("state") == NormalizedActionState.IN_PROGRESS),
    }
    primary = states[0] if states else {}
    return {
        "employee_id": str(employee_id or ""),
        "states": states,
        "summary": summary,
        "primary_state": str(primary.get("state") or ""),
        "primary": primary,
    }


def build_employee_action_state_lookup(
    employee_ids: list[str] | tuple[str, ...],
    *,
    tenant_id: str = "",
    today: date | None = None,
) -> dict[str, dict[str, Any]]:
    """Return the primary normalized action state for each employee."""
    today = today or date.today()
    lookup: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()

    for employee_id in list(employee_ids or []):
        clean_employee_id = str(employee_id or "").strip()
        if not clean_employee_id or clean_employee_id in seen:
            continue
        seen.add(clean_employee_id)

        summary = build_employee_action_state_summary(
            clean_employee_id,
            tenant_id=tenant_id,
            today=today,
        )
        primary = dict(summary.get("primary") or {})
        state = str(summary.get("primary_state") or "").strip()
        if not state:
            continue

        lookup[clean_employee_id] = {
            "state": state,
            "state_detail": str(primary.get("state_detail") or "").strip(),
            "title": str(primary.get("title") or "").strip(),
            "is_open": bool(primary.get("is_open")),
            "source_type": str(primary.get("source_type") or "").strip(),
        }

    return lookup


def _build_action_state_row(
    *,
    source_type: str,
    source_label: str,
    employee_id: str,
    employee_name: str,
    department: str,
    action_id: str,
    title: str,
    note_preview: str,
    normalized_state: str,
    legacy_status: str,
    follow_up_due_at: str,
    latest_event: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    timing_status = _timing_status(follow_up_due_at, today=today)
    latest_event_type = str(latest_event.get("event_type") or "").replace("_", " ").title()
    return {
        "source_type": source_type,
        "source_label": source_label,
        "employee_id": str(employee_id or ""),
        "employee_name": str(employee_name or employee_id or ""),
        "department": str(department or ""),
        "action_id": str(action_id or ""),
        "title": str(title or "").strip() or "Open action",
        "note_preview": str(note_preview or "").strip(),
        "state": normalized_state,
        "legacy_status": str(legacy_status or "").strip(),
        "state_detail": _build_state_detail(
            normalized_state=normalized_state,
            legacy_status=legacy_status,
            follow_up_due_at=follow_up_due_at,
            today=today,
        ),
        "follow_up_due_at": follow_up_due_at,
        "timing_status": timing_status,
        "latest_event_at": str(latest_event.get("event_at") or ""),
        "latest_event_type": latest_event_type,
        "latest_event_notes": str(latest_event.get("notes") or "").strip(),
        "is_open": normalized_state in OPEN_NORMALIZED_ACTION_STATES,
    }


def _build_state_detail(*, normalized_state: str, legacy_status: str, follow_up_due_at: str, today: date) -> str:
    detail_parts: list[str] = []
    timing_status = _timing_status(follow_up_due_at, today=today)
    if timing_status == "overdue":
        detail_parts.append("Overdue")
    elif timing_status == "due_today":
        detail_parts.append("Due today")
    elif follow_up_due_at:
        detail_parts.append(f"Due {follow_up_due_at}")

    legacy = str(legacy_status or "").strip().replace("_", " ").title()
    if legacy and legacy not in {normalized_state, "Scheduled Only"}:
        detail_parts.append(f"Underlying: {legacy}")
    return " | ".join(detail_parts)


def _timing_status(follow_up_due_at: str, *, today: date) -> str:
    due = parse_action_date(follow_up_due_at)
    if due is None:
        return ""
    delta = (due - today).days
    if delta < 0:
        return "overdue"
    if delta == 0:
        return "due_today"
    return "scheduled"


def _state_sort_key(item: dict[str, Any]) -> tuple[int, int, str, str]:
    timing_rank = {"overdue": 0, "due_today": 1, "scheduled": 2, "": 3}
    state_rank = {
        NormalizedActionState.FOLLOW_UP_SCHEDULED: 0,
        NormalizedActionState.IN_PROGRESS: 1,
        NormalizedActionState.OPEN: 2,
        NormalizedActionState.RESOLVED: 3,
    }
    latest_value = str(item.get("latest_event_at") or "")
    if latest_value:
        latest_value = f"~{latest_value}"
    return (
        state_rank.get(str(item.get("state") or ""), 9),
        timing_rank.get(str(item.get("timing_status") or ""), 9),
        latest_value,
        str(item.get("follow_up_due_at") or ""),
    )