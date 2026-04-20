"""Normalized action-state read model and safe scheduling adapter.

This service exposes one four-state interpretation over the existing
`actions`, `action_events`, and `coaching_followups` storage layers so UI
surfaces can read a single action-state contract without requiring a risky
storage rewrite.
"""

from __future__ import annotations

import os
import time
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from domain.actions import parse_action_date, runtime_status
from followup_manager import add_followup, get_followups_for_employee, get_followups_for_employees
from repositories import action_events_repo, actions_repo
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
from services.perf_profile import profile_block


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


_ACTION_STATE_LOOKUP_VALIDATION_ENABLED = str(os.environ.get("DPD_ACTION_STATE_LOOKUP_VALIDATION", "")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
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

    return _build_employee_action_state_summary_from_inputs(
        employee_id=employee_id,
        actions=actions,
        timeline=timeline,
        followups=followups,
        today=today,
    )


def _build_employee_action_state_summary_from_inputs(
    *,
    employee_id: str,
    actions: list[dict[str, Any]] | None,
    timeline: list[dict[str, Any]] | None,
    followups: list[dict[str, Any]] | None,
    today: date,
) -> dict[str, Any]:
    actions = list(actions or [])
    timeline = list(timeline or [])
    followups = list(followups or [])

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


def _build_employee_action_timeline_rows(
    *,
    actions: list[dict[str, Any]] | None,
    action_events: list[dict[str, Any]] | None,
    generic_events: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    by_action_id = {str(action.get("id") or ""): action for action in list(actions or [])}
    timeline: list[dict[str, Any]] = []

    for ev in list(action_events or []):
        action_id = str(ev.get("action_id") or "")
        action = by_action_id.get(action_id, {})
        timeline.append(
            {
                "action_id": action_id,
                "linked_exception_id": ev.get("linked_exception_id"),
                "event_type": ev.get("event_type"),
                "event_at": ev.get("event_at"),
                "performed_by": ev.get("owner") or ev.get("performed_by"),
                "notes": ev.get("details") or ev.get("notes"),
                "outcome": ev.get("outcome"),
                "next_follow_up_at": ev.get("due_date") or ev.get("next_follow_up_at"),
                "status": ev.get("status") or action.get("status"),
                "issue_type": action.get("issue_type"),
                "action_type": action.get("action_type"),
                "trigger_summary": action.get("trigger_summary"),
            }
        )

    for ev in list(generic_events or []):
        if str(ev.get("action_id") or "").strip():
            continue
        timeline.append(
            {
                "action_id": "",
                "linked_exception_id": ev.get("linked_exception_id"),
                "event_type": ev.get("event_type"),
                "event_at": ev.get("event_at"),
                "performed_by": ev.get("owner") or ev.get("performed_by"),
                "notes": ev.get("details") or ev.get("notes"),
                "outcome": ev.get("outcome"),
                "next_follow_up_at": ev.get("due_date") or ev.get("next_follow_up_at"),
                "status": ev.get("status") or "logged",
                "issue_type": "",
                "action_type": "",
                "trigger_summary": "Lightweight follow-through log",
            }
        )

    timeline.sort(key=lambda item: str(item.get("event_at") or ""), reverse=True)
    return timeline


def _build_employee_action_state_lookup_batched(
    *,
    employee_ids: tuple[str, ...],
    tenant_id: str = "",
    today: date,
) -> dict[str, dict[str, Any]]:
    with profile_block(
        "action_state.lookup_batched",
        tenant_id=str(tenant_id or ""),
        context={
            "today_iso": today.isoformat(),
            "employee_ids": len(employee_ids or ()),
        },
    ) as profile:
        def _finalize_lookup_payload(*, query_count_value: int = 0, visible_db_rows_value: int = 0) -> None:
            # Keep the authoritative runtime payload shape stable across all branches.
            profile.set("service_work_ms", int(max(0.0, (time.perf_counter() - profile.started_at) * 1000)))
            profile.set("actions_rows", int(profile.metrics.get("actions_rows", 0) or 0))
            profile.set("generic_employee_event_rows", int(profile.metrics.get("generic_employee_event_rows", 0) or 0))
            profile.set("followup_rows", int(profile.metrics.get("followup_rows", 0) or 0))
            profile.set(
                "actions_query_ms",
                int(profile.metrics.get("actions_query_ms", profile.metrics.get("stage_batched_actions_read_ms", 0)) or 0),
            )
            profile.set(
                "generic_employee_events_probe_ms",
                int(
                    profile.metrics.get(
                        "generic_employee_events_probe_ms",
                        profile.metrics.get("stage_batched_generic_employee_events_probe_ms", 0),
                    )
                    or 0
                ),
            )
            profile.set(
                "followups_probe_ms",
                int(
                    profile.metrics.get(
                        "followups_probe_ms",
                        profile.metrics.get("stage_shared_followup_probe_ms", 0),
                    )
                    or 0
                ),
            )
            profile.set("actions_query_skipped", bool(profile.metrics.get("actions_query_skipped", False)))
            profile.set("generic_employee_events_query_skipped", bool(profile.metrics.get("generic_employee_events_query_skipped", False)))
            profile.set("followups_query_skipped", bool(profile.metrics.get("followups_query_skipped", False)))
            profile.set("query_count", int(profile.metrics.get("query_count", query_count_value) or 0))
            # Preserve legacy db_rows_visible while guaranteeing the new field.
            profile.set("visible_db_rows", int(profile.metrics.get("visible_db_rows", visible_db_rows_value) or 0))

        # Keep payload schema consistent across all branches, including early returns.
        profile.set("actions_rows", 0)
        profile.set("generic_employee_event_rows", 0)
        profile.set("followup_rows", 0)
        profile.set("actions_query_skipped", False)
        profile.set("generic_employee_events_query_skipped", False)
        profile.set("followups_query_skipped", False)
        profile.set("actions_query_ms", 0)
        profile.set("generic_employee_events_query_ms", 0)
        profile.set("followups_query_ms", 0)
        profile.set("generic_employee_events_probe_ms", 0)
        profile.set("followups_probe_ms", 0)
        profile.set("service_work_ms", 0)
        profile.set("query_count", 0)
        profile.set("visible_db_rows", 0)
        profile.set("needs_generic_employee_events_probe", False)
        profile.set("needs_followups_probe", False)

        if not employee_ids:
            _finalize_lookup_payload(query_count_value=0, visible_db_rows_value=0)
            profile.set("lookup_rows", 0)
            return {}

        employee_id_set = {str(employee_id or "").strip() for employee_id in employee_ids if str(employee_id or "").strip()}
        profile.set("employee_ids", len(employee_id_set or set()))
        if not employee_id_set:
            _finalize_lookup_payload(query_count_value=0, visible_db_rows_value=0)
            profile.set("lookup_rows", 0)
            return {}

        query_count = 0
        visible_db_rows = 0

        with profile.stage("batched_actions_read"):
            actions = list(
                actions_repo.list_actions_for_employee_ids(
                    employee_ids=employee_ids,
                    tenant_id=tenant_id,
                    columns="id, employee_id, employee_name, department, status, follow_up_due_at, trigger_summary, note, issue_type, action_type, last_event_at",
                )
                or []
            )
            for action in actions:
                action["_runtime_status"] = runtime_status(
                    str(action.get("status") or "new"),
                    action.get("follow_up_due_at"),
                    today=today,
                )
        query_count += 1
        visible_db_rows += len(actions or [])
        profile.query(rows=len(actions or []), count=1)
        profile.set("actions_rows", len(actions or []))
        profile.set("actions_query_ms", int(profile.metrics.get("stage_batched_actions_read_ms", 0) or 0))
        profile.set("actions_query_skipped", False)

        tenant_scope_text = str(tenant_id or "").strip()
        tenant_scope_is_valid_uuid = False
        if tenant_scope_text:
            try:
                UUID(tenant_scope_text)
                tenant_scope_is_valid_uuid = True
            except (TypeError, ValueError, AttributeError):
                tenant_scope_is_valid_uuid = False

        # Safe short-circuit branch 1: malformed tenant scope is treated as non-queryable for
        # tenant-scoped standalone sources.
        skip_standalone_reads = bool((not actions) and tenant_scope_text and not tenant_scope_is_valid_uuid)
        standalone_probe_ran = False
        generic_probe_rows: list[dict[str, Any]] = []
        followup_probe_rows: list[dict[str, Any]] = []
        standalone_probe_generic_rows = 0
        standalone_probe_followup_rows = 0
        needs_generic_employee_events_probe = False
        needs_followups_probe = False

        # Safe short-circuit branch 2: for valid-tenant, zero-action lookups, run cheap
        # existence probes first and skip full standalone reads only when both probes are empty.
        should_probe_standalone = bool((not actions) and tenant_scope_text and tenant_scope_is_valid_uuid)
        probe_employee_ids = tuple(sorted(employee_id_set))
        needs_followups_probe = bool(should_probe_standalone)
        needs_generic_employee_events_probe = bool(should_probe_standalone)
        if should_probe_standalone:
            standalone_probe_ran = True
            # Follow-ups can independently create visible non-action state.
            # Probe follow-ups first so singleton pages can skip generic probing/reads
            # when follow-up state is already present.
            if needs_followups_probe:
                profile.set("followups_probe_mode", "exists_only_emp_date_ordered")
                with profile.stage("shared_followup_probe"):
                    followup_probe_rows = list(
                        get_followups_for_employees(
                            employee_ids=probe_employee_ids,
                            from_date=(today - timedelta(days=90)).isoformat(),
                            to_date=(today + timedelta(days=365)).isoformat(),
                            tenant_id=tenant_id,
                            limit=1,
                            exists_only=bool(len(employee_id_set) > 1),
                        )
                        or []
                    )
                query_count += 1
                standalone_probe_followup_rows = len(followup_probe_rows or [])
                visible_db_rows += standalone_probe_followup_rows
                profile.query(rows=standalone_probe_followup_rows, count=1)

            # For a singleton visible employee, any follow-up row guarantees visible
            # non-action state from follow-ups, so standalone generic events cannot
            # alter the final surfaced state.
            skip_generic_for_singleton_followup = bool(
                len(employee_id_set) == 1 and standalone_probe_followup_rows > 0
            )
            needs_generic_employee_events_probe = bool(
                needs_generic_employee_events_probe and not skip_generic_for_singleton_followup
            )
            if needs_generic_employee_events_probe:
                profile.set("generic_probe_mode", "exists_only_emp_date")
                with profile.stage("batched_generic_employee_events_probe"):
                    generic_probe_rows = list(
                        action_events_repo.list_action_events_for_employee_ids(
                            employee_ids=employee_ids,
                            tenant_id=tenant_id,
                            newest_first=True,
                            limit=1,
                            columns="action_id, employee_id, event_type, event_at, details, notes, due_date, next_follow_up_at, status",
                            exists_only=bool(len(employee_id_set) > 1),
                            from_date=(today - timedelta(days=90)).isoformat(),
                            to_date=(today + timedelta(days=365)).isoformat(),
                        )
                        or []
                    )
                query_count += 1
                standalone_probe_generic_rows = len(generic_probe_rows or [])
                visible_db_rows += standalone_probe_generic_rows
                profile.query(rows=standalone_probe_generic_rows, count=1)
            else:
                standalone_probe_generic_rows = 0

            if standalone_probe_generic_rows == 0 and standalone_probe_followup_rows == 0:
                skip_standalone_reads = True

        can_reuse_singleton_generic_probe = bool(
            standalone_probe_ran
            and len(employee_id_set) == 1
            and standalone_probe_followup_rows == 0
            and standalone_probe_generic_rows > 0
            and not str((generic_probe_rows[0] if generic_probe_rows else {}).get("action_id") or "").strip()
        )
        can_reuse_singleton_followup_probe = bool(
            standalone_probe_ran
            and len(employee_id_set) == 1
            and standalone_probe_generic_rows == 0
            and standalone_probe_followup_rows > 0
            and str((followup_probe_rows[0] if followup_probe_rows else {}).get("followup_date") or "").strip()
        )
        probe_proves_no_standalone_state = bool(
            standalone_probe_ran
            and standalone_probe_generic_rows == 0
            and standalone_probe_followup_rows == 0
        )
        # Safe because probes already establish that additional standalone reads cannot change visible Today state.
        safe_singleton_probe_short_circuit = bool(
            can_reuse_singleton_generic_probe or can_reuse_singleton_followup_probe
        )
        skip_standalone_reads = bool(
            skip_standalone_reads
            or probe_proves_no_standalone_state
            or safe_singleton_probe_short_circuit
        )

        profile.set("standalone_probe_ran", bool(standalone_probe_ran))
        profile.set("standalone_probe_generic_rows", int(standalone_probe_generic_rows))
        profile.set("standalone_probe_followup_rows", int(standalone_probe_followup_rows))
        profile.set("needs_generic_employee_events_probe", bool(needs_generic_employee_events_probe))
        profile.set("needs_followups_probe", bool(needs_followups_probe))

        actions_by_employee: dict[str, list[dict[str, Any]]] = {employee_id: [] for employee_id in employee_id_set}
        action_ids: list[str] = []
        action_ids_by_employee: dict[str, set[str]] = {employee_id: set() for employee_id in employee_id_set}
        grouping_merge_started = time.perf_counter()
        try:
            for action in actions:
                employee_id = str(action.get("employee_id") or "").strip()
                if employee_id not in employee_id_set:
                    continue
                actions_by_employee.setdefault(employee_id, []).append(action)
                action_id = str(action.get("id") or "").strip()
                if action_id:
                    action_ids.append(action_id)
                    action_ids_by_employee.setdefault(employee_id, set()).add(action_id)
        finally:
            grouping_merge_ms = int((time.perf_counter() - grouping_merge_started) * 1000)
        profile.set("action_ids_count", len(action_ids or []))

        with profile.stage("batched_action_events_read"):
            batched_action_events = list(
                action_events_repo.list_action_events_for_action_ids(
                    action_ids=action_ids,
                    tenant_id=tenant_id,
                    newest_first=True,
                    limit=max(500, len(action_ids) * 30),
                    columns="action_id, linked_exception_id, event_type, event_at, owner, performed_by, details, notes, outcome, due_date, next_follow_up_at, status",
                )
                or []
            )
        profile.query(rows=len(batched_action_events or []), count=(1 if action_ids else 0))
        profile.set("batched_action_event_rows", len(batched_action_events or []))

        if skip_standalone_reads:
            generic_employee_events = list(generic_probe_rows[:1]) if can_reuse_singleton_generic_probe else []
            followups = list(followup_probe_rows[:1]) if can_reuse_singleton_followup_probe else []
            profile.set("stage_batched_generic_employee_events_read_ms", 0)
            profile.set("stage_shared_followup_read_ms", 0)
            profile.set("generic_employee_event_rows", len(generic_employee_events or []))
            profile.set("followup_rows", len(followups or []))
            profile.set("generic_employee_events_query_ms", 0)
            profile.set("followups_query_ms", 0)
            profile.set("generic_employee_events_query_skipped", True)
            profile.set("generic_employee_events_scope", "employee_scoped")
            profile.set("followups_query_skipped", True)
            profile.set("followups_scope", "employee_scoped")
        else:
            # Run full standalone reads only when probe outcomes show they can still
            # alter the surfaced non-action state for Today.
            needs_generic_employee_events_read = bool(
                not (
                    (standalone_probe_ran and standalone_probe_generic_rows == 0)
                    or (standalone_probe_ran and not needs_generic_employee_events_probe)
                    or can_reuse_singleton_generic_probe
                )
            )
            if not needs_generic_employee_events_read:
                generic_employee_events = list(generic_probe_rows[:1]) if can_reuse_singleton_generic_probe else []
                profile.set("stage_batched_generic_employee_events_read_ms", 0)
                profile.set("generic_employee_event_rows", len(generic_employee_events or []))
                profile.set("generic_employee_events_query_ms", 0)
                profile.set("generic_employee_events_query_skipped", True)
            else:
                with profile.stage("batched_generic_employee_events_read"):
                    generic_employee_events = list(
                        action_events_repo.list_action_events_for_employee_ids(
                            employee_ids=employee_ids,
                            tenant_id=tenant_id,
                            newest_first=True,
                            limit=max(120, len(employee_ids) * 120),
                            columns="action_id, employee_id, event_type, event_at, details, notes, due_date, next_follow_up_at, status",
                            from_date=(today - timedelta(days=90)).isoformat(),
                            to_date=(today + timedelta(days=365)).isoformat(),
                        )
                        or []
                    )
                query_count += 1
                visible_db_rows += len(generic_employee_events or [])
                profile.query(rows=len(generic_employee_events or []), count=1)
                profile.set("generic_employee_event_rows", len(generic_employee_events or []))
                profile.set("generic_employee_events_query_ms", int(profile.metrics.get("stage_batched_generic_employee_events_read_ms", 0) or 0))
                profile.set("generic_employee_events_query_skipped", False)
            profile.set("generic_employee_events_scope", "employee_scoped")

            needs_followups_read = bool(
                not (
                    (standalone_probe_ran and standalone_probe_followup_rows == 0)
                    or can_reuse_singleton_followup_probe
                )
            )
            if not needs_followups_read:
                followups = list(followup_probe_rows[:1]) if can_reuse_singleton_followup_probe else []
                profile.set("stage_shared_followup_read_ms", 0)
                profile.set("followup_rows", len(followups or []))
                profile.set("followups_query_ms", 0)
                profile.set("followups_query_skipped", True)
            else:
                with profile.stage("shared_followup_read"):
                    followups = list(
                        get_followups_for_employees(
                            employee_ids=probe_employee_ids,
                            from_date=(today - timedelta(days=90)).isoformat(),
                            to_date=(today + timedelta(days=365)).isoformat(),
                            tenant_id=tenant_id,
                        )
                        or []
                    )
                query_count += 1
                visible_db_rows += len(followups or [])
                profile.query(rows=len(followups or []), count=1)
                profile.set("followup_rows", len(followups or []))
                profile.set("followups_query_ms", int(profile.metrics.get("stage_shared_followup_read_ms", 0) or 0))
                profile.set("followups_query_skipped", False)
            profile.set("followups_scope", "employee_scoped")
        profile.set("query_count", int(query_count))
        profile.set("visible_db_rows", int(visible_db_rows))

        action_events_by_employee: dict[str, list[dict[str, Any]]] = {employee_id: [] for employee_id in employee_id_set}
        generic_events_by_employee: dict[str, list[dict[str, Any]]] = {employee_id: [] for employee_id in employee_id_set}
        followups_by_employee: dict[str, list[dict[str, Any]]] = {employee_id: [] for employee_id in employee_id_set}

        grouping_merge_started = time.perf_counter()
        try:
            action_owner_by_id: dict[str, str] = {}
            for employee_id, employee_action_ids in action_ids_by_employee.items():
                for action_id in employee_action_ids:
                    action_owner_by_id[action_id] = employee_id

            for event in batched_action_events:
                action_id = str(event.get("action_id") or "").strip()
                owner_employee_id = action_owner_by_id.get(action_id, "")
                if owner_employee_id:
                    action_events_by_employee.setdefault(owner_employee_id, []).append(event)

            for event in generic_employee_events:
                employee_id = str(event.get("employee_id") or "").strip()
                if employee_id in employee_id_set:
                    generic_events_by_employee.setdefault(employee_id, []).append(event)

            for followup in followups:
                employee_id = str(followup.get("emp_id") or "").strip()
                if employee_id in employee_id_set:
                    followups_by_employee.setdefault(employee_id, []).append(followup)
        finally:
            grouping_merge_ms += int((time.perf_counter() - grouping_merge_started) * 1000)
        profile.set("stage_grouping_merge_ms", int(grouping_merge_ms))

        lookup: dict[str, dict[str, Any]] = {}
        with profile.stage("summary_assembly"):
            for employee_id in employee_ids:
                clean_employee_id = str(employee_id or "").strip()
                if not clean_employee_id:
                    continue
                timeline = _build_employee_action_timeline_rows(
                    actions=actions_by_employee.get(clean_employee_id, []),
                    action_events=action_events_by_employee.get(clean_employee_id, []),
                    generic_events=generic_events_by_employee.get(clean_employee_id, []),
                )
                summary = _build_employee_action_state_summary_from_inputs(
                    employee_id=clean_employee_id,
                    actions=actions_by_employee.get(clean_employee_id, []),
                    timeline=timeline,
                    followups=followups_by_employee.get(clean_employee_id, []),
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

        if _ACTION_STATE_LOOKUP_VALIDATION_ENABLED:
            legacy_lookup = _build_employee_action_state_lookup_legacy(
                employee_ids=employee_ids,
                tenant_id=tenant_id,
                today=today,
            )
            normalized_optimized = _normalize_lookup_for_validation(lookup)
            normalized_legacy = _normalize_lookup_for_validation(legacy_lookup)
            mismatch_count = _lookup_validation_mismatch_count(normalized_optimized, normalized_legacy)
            profile.set("validation_ran", True)
            profile.set("validation_matched", bool(mismatch_count == 0))
            profile.set("mismatch_count", int(mismatch_count))
        else:
            profile.set("validation_ran", False)
            profile.set("validation_matched", True)
            profile.set("mismatch_count", 0)

        _finalize_lookup_payload(query_count_value=query_count, visible_db_rows_value=visible_db_rows)
        profile.set("lookup_rows", len(lookup or {}))
        return lookup


def _build_employee_action_state_lookup_legacy(
    *,
    employee_ids: tuple[str, ...],
    tenant_id: str,
    today: date,
) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for employee_id in employee_ids:
        clean_employee_id = str(employee_id or "").strip()
        if not clean_employee_id:
            continue
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


def _normalize_lookup_for_validation(lookup: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for employee_id in sorted(lookup.keys()):
        payload = dict(lookup.get(employee_id) or {})
        normalized[str(employee_id)] = {
            "state": str(payload.get("state") or "").strip(),
            "state_detail": str(payload.get("state_detail") or "").strip(),
            "title": str(payload.get("title") or "").strip(),
            "is_open": bool(payload.get("is_open")),
            "source_type": str(payload.get("source_type") or "").strip(),
        }
    return normalized


def _lookup_validation_mismatch_count(
    optimized: dict[str, dict[str, Any]],
    legacy: dict[str, dict[str, Any]],
) -> int:
    all_employee_ids = set(optimized.keys()) | set(legacy.keys())
    mismatches = 0
    for employee_id in all_employee_ids:
        if dict(optimized.get(employee_id) or {}) != dict(legacy.get(employee_id) or {}):
            mismatches += 1
    return mismatches


def build_employee_action_state_lookup(
    employee_ids: list[str] | tuple[str, ...],
    *,
    tenant_id: str = "",
    today: date | None = None,
) -> dict[str, dict[str, Any]]:
    """Return the primary normalized action state for each employee."""
    today = today or date.today()
    seen: set[str] = set()
    normalized_employee_ids: list[str] = []

    for employee_id in list(employee_ids or []):
        clean_employee_id = str(employee_id or "").strip()
        if not clean_employee_id or clean_employee_id in seen:
            continue
        seen.add(clean_employee_id)
        normalized_employee_ids.append(clean_employee_id)

    return _build_employee_action_state_lookup_batched(
        employee_ids=tuple(normalized_employee_ids),
        tenant_id=tenant_id,
        today=today,
    )


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