"""Today Screen execution logic and queue-building helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from domain.actions import (
    IssueType,
    NO_IMPROVEMENT_OUTCOMES,
    OPEN_STATUSES,
    can_transition_status,
    determine_priority,
    runtime_status,
    status_label,
    urgency_score,
)

HIGH_PERFORMER_LOOKBACK_DAYS = 21
OPEN_ACTION_STATUSES = OPEN_STATUSES


# ──────────────────────────────────────────────────────────────────────────────
# Public Orchestration API
# Use these functions from pages/ and domain logic that needs to modify actions.
# ──────────────────────────────────────────────────────────────────────────────


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
) -> dict:
    """Create a new action and log creation event. Raises no exceptions — returns {} on failure."""
    try:
        import database
        result = database.create_action(
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
        print(f"[Error] create_action failed: {e}")
        return {}


def get_open_actions(
    tenant_id: str = "",
    employee_id: str = "",
    today: date | None = None,
) -> list[dict]:
    """Return all open actions (not resolved/deprioritized), enriched with runtime status."""
    today = today or date.today()
    try:
        import database
        actions = database.list_actions(
            tenant_id=tenant_id,
            statuses=list(OPEN_STATUSES),
            employee_id=employee_id,
        )
        for action in actions:
            action["_runtime_status"] = runtime_status(
                str(action.get("status") or "new"),
                action.get("follow_up_due_at"),
                today=today,
            )
        return actions
    except Exception as e:
        print(f"[Error] get_open_actions failed: {e}")
        return []


def get_overdue_actions(tenant_id: str = "", today: date | None = None) -> list[dict]:
    """Return all actions with follow_up_due_at in the past."""
    today = today or date.today()
    try:
        open_actions = get_open_actions(tenant_id=tenant_id, today=today)
        return [a for a in open_actions if a.get("_runtime_status") == "overdue"]
    except Exception as e:
        print(f"[Error] get_overdue_actions failed: {e}")
        return []


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
        import database
        result = database.update_action(
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
        return result
    except Exception as e:
        print(f"[Error] mark_action_resolved failed: {e}")
        return {}


def mark_action_deprioritized(
    action_id: str,
    reason: str = "",
    tenant_id: str = "",
) -> dict:
    """Mark action as deprioritized. Always logs event."""
    try:
        import database
        result = database.update_action(
            action_id=action_id,
            updates={
                "status": "deprioritized",
                "note": reason,
            },
            tenant_id=tenant_id,
        )
        return result
    except Exception as e:
        print(f"[Error] mark_action_deprioritized failed: {e}")
        return {}


def mark_action_escalated(
    action_id: str,
    reason: str = "",
    tenant_id: str = "",
) -> dict:
    """Mark action as escalated."""
    try:
        import database
        result = database.update_action(
            action_id=action_id,
            updates={
                "status": "escalated",
                "note": reason,
            },
            tenant_id=tenant_id,
        )
        return result
    except Exception as e:
        print(f"[Error] mark_action_escalated failed: {e}")
        return {}


def mark_action_transferred(
    action_id: str,
    reason: str = "",
    tenant_id: str = "",
) -> dict:
    """Mark action as transferred."""
    try:
        import database
        result = database.update_action(
            action_id=action_id,
            updates={
                "status": "transferred",
                "note": reason,
            },
            tenant_id=tenant_id,
        )
        return result
    except Exception as e:
        print(f"[Error] mark_action_transferred failed: {e}")
        return {}


def mark_action_in_progress(
    action_id: str,
    tenant_id: str = "",
) -> dict:
    """Move action to in_progress status. Always logs event."""
    try:
        import database
        result = database.update_action(
            action_id=action_id,
            updates={"status": "in_progress"},
            tenant_id=tenant_id,
        )
        return result
    except Exception as e:
        print(f"[Error] mark_action_in_progress failed: {e}")
        return {}


def reopen_action(
    action_id: str,
    reason: str = "Reopened by supervisor",
    tenant_id: str = "",
) -> dict:
    """Reopen a resolved/deprioritized action. Returns {} if transition not allowed."""
    try:
        import database
        actions = database.list_actions(tenant_id=tenant_id, employee_id="")
        current = next((a for a in actions if str(a.get("id")) == str(action_id)), None)
        if not current:
            print(f"[Warning] Action {action_id} not found")
            return {}
        current_status = str(current.get("status") or "new")
        if not can_transition_status(current_status, "in_progress"):
            print(f"[Warning] Cannot reopen from status {current_status}")
            return {}
        result = database.update_action(
            action_id=action_id,
            updates={"status": "in_progress", "note": reason},
            tenant_id=tenant_id,
        )
        return result
    except Exception as e:
        print(f"[Error] reopen_action failed: {e}")
        return {}


def refresh_action_statuses(tenant_id: str = "", today: date | None = None) -> int:
    """Scan open actions, persist derived runtime status updates, and return update count."""
    today = today or date.today()
    try:
        import database

        actions = database.list_actions(
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
            result = database.update_action(
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
        print(f"[Error] refresh_action_statuses failed: {e}")
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
        import database
        result = database.log_action_event(
            action_id=action_id,
            event_type=event_type,
            employee_id=employee_id,
            performed_by=performed_by,
            notes=notes,
            outcome=outcome,
            next_follow_up_at=next_follow_up_at,
            tenant_id=tenant_id,
        )
        return result
    except Exception as e:
        print(f"[Error] log_action_event failed: {e}")
        return {}


def get_action_history(
    action_id: str,
    tenant_id: str = "",
) -> list[dict]:
    """Return timeline events for one action, oldest first."""
    try:
        import database
        events = database.list_action_events(
            action_id=action_id,
            tenant_id=tenant_id,
        )
        return events or []
    except Exception as e:
        print(f"[Error] get_action_history failed: {e}")
        return []


def get_employee_actions(
    employee_id: str,
    tenant_id: str = "",
    today: date | None = None,
) -> list[dict]:
    """Return all actions for one employee, enriched with runtime status."""
    today = today or date.today()
    try:
        import database
        actions = database.list_actions(
            tenant_id=tenant_id,
            employee_id=employee_id,
        )
        for action in actions:
            action["_runtime_status"] = runtime_status(
                str(action.get("status") or "new"),
                action.get("follow_up_due_at"),
                today=today,
            )
        return actions
    except Exception as e:
        print(f"[Error] get_employee_actions failed: {e}")
        return []


def get_employee_action_timeline(
    employee_id: str,
    tenant_id: str = "",
) -> list[dict]:
    """Return flattened timeline across all actions for one employee, newest first."""
    try:
        import database
        actions = database.list_actions(
            tenant_id=tenant_id,
            employee_id=employee_id,
        )
        by_action_id = {str(a.get("id") or ""): a for a in (actions or [])}
        timeline: list[dict] = []
        for action in actions or []:
            action_id = str(action.get("id") or "")
            events = database.list_action_events(
                action_id=action_id,
                tenant_id=tenant_id,
            )
            for ev in events or []:
                timeline.append(
                    {
                        "action_id": action_id,
                        "event_type": ev.get("event_type"),
                        "event_at": ev.get("event_at"),
                        "performed_by": ev.get("performed_by"),
                        "notes": ev.get("notes"),
                        "outcome": ev.get("outcome"),
                        "next_follow_up_at": ev.get("next_follow_up_at"),
                        "status": action.get("status"),
                        "issue_type": action.get("issue_type"),
                        "action_type": action.get("action_type"),
                        "trigger_summary": action.get("trigger_summary"),
                    }
                )
        timeline.sort(key=lambda item: str(item.get("event_at") or ""), reverse=True)
        return timeline
    except Exception as e:
        print(f"[Error] get_employee_action_timeline failed: {e}")
        return []


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
) -> dict:
    """Log coaching as a tracked lifecycle event.

    Uses an existing open action when available, otherwise creates a new action
    and logs the first coaching event.
    """
    try:
        import database

        target_action: dict = {}
        if existing_action_id:
            candidate = database.list_actions(
                tenant_id=tenant_id,
                employee_id=employee_id,
            )
            target_action = next((a for a in candidate if str(a.get("id")) == str(existing_action_id)), {})

        if not target_action:
            open_actions = database.list_actions(
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
            )
            created_new = bool(target_action)

        action_id = str(target_action.get("id") or "")
        if not action_id:
            return {}

        status_update = database.update_action(
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
        print(f"[Error] log_coaching_lifecycle_entry failed: {e}")
        return {}


def get_repeat_offenders(
    tenant_id: str = "",
    today: date | None = None,
    open_actions: list[dict] | None = None,
    min_coached_cycles: int = 2,
    stale_days_threshold: int = 14,
) -> list[dict]:
    """Identify employees with repeated management patterns that suggest a different approach.

    Scans open actions (or accepts pre-loaded list) and loads lifecycle events to detect:
      - Coached 2+ times without sustained improvement
      - Unresolved 14+ days
      - Multiple no-improvement outcomes

    Returns one dict per qualifying employee, sorted by severity descending.
    Each dict keys: employee_id, employee_name, department, open_action_count,
    coached_cycle_count, no_improvement_count, max_days_open, recommendation,
    signals, actions.
    Recommendation values: "escalate" | "deprioritize" | "change_approach"
    """
    today = today or date.today()
    try:
        import database

        actions = open_actions
        if actions is None:
            actions = database.list_actions(
                tenant_id=tenant_id,
                statuses=list(OPEN_STATUSES),
            )

        # Group open actions by employee
        by_employee: dict[str, list[dict]] = {}
        for action in actions or []:
            emp_id = str(action.get("employee_id") or "")
            if not emp_id:
                continue
            by_employee.setdefault(emp_id, []).append(action)

        results: list[dict] = []

        for emp_id, emp_actions in by_employee.items():
            # Days open for each action
            days_open_list: list[int] = []
            for action in emp_actions:
                created_raw = str(action.get("created_at") or action.get("last_event_at") or "")
                if created_raw:
                    try:
                        created_date = date.fromisoformat(created_raw[:10])
                        days_open_list.append((today - created_date).days)
                    except Exception:
                        days_open_list.append(0)
                else:
                    days_open_list.append(0)

            max_days_open = max(days_open_list) if days_open_list else 0

            # Initial screen: skip employees who are neither repeat nor stale
            if len(emp_actions) < 2 and max_days_open < stale_days_threshold:
                continue

            # Load events across all actions for this employee
            coached_total = 0
            no_improvement_total = 0
            for action in emp_actions:
                action_id = str(action.get("id") or "")
                if not action_id:
                    continue
                events = database.list_action_events(
                    action_id=action_id,
                    tenant_id=tenant_id,
                )
                for ev in events or []:
                    ev_type = str(ev.get("event_type") or "")
                    ev_outcome = str(ev.get("outcome") or "")
                    if ev_type == "coached":
                        coached_total += 1
                    if ev_outcome in NO_IMPROVEMENT_OUTCOMES:
                        no_improvement_total += 1

            # Must have at least min coached cycles OR be stale to surface
            if coached_total < min_coached_cycles and max_days_open < stale_days_threshold:
                continue

            # Build human-readable signal list
            signals: list[str] = []
            if coached_total > 0:
                signals.append(f"coached {coached_total}×")
            if no_improvement_total > 0:
                signals.append(f"{no_improvement_total}× no improvement")
            if len(emp_actions) >= 2:
                signals.append(f"{len(emp_actions)} open actions")
            if max_days_open >= stale_days_threshold:
                signals.append(f"unresolved {max_days_open} days")

            # Recommendation
            if (coached_total >= 3 and no_improvement_total >= 2) or max_days_open >= 21:
                recommendation = "escalate"
            elif no_improvement_total >= 2 or coached_total >= 3:
                recommendation = "deprioritize"
            else:
                recommendation = "change_approach"

            emp_name = str(emp_actions[0].get("employee_name") or emp_id)
            dept = str(emp_actions[0].get("department") or "")
            severity = (
                coached_total * 3
                + no_improvement_total * 5
                + max(0, max_days_open - stale_days_threshold)
                + len(emp_actions) * 2
            )

            results.append({
                "employee_id": emp_id,
                "employee_name": emp_name,
                "department": dept,
                "open_action_count": len(emp_actions),
                "coached_cycle_count": coached_total,
                "no_improvement_count": no_improvement_total,
                "max_days_open": max_days_open,
                "recommendation": recommendation,
                "signals": signals,
                "actions": emp_actions,
                "_severity_score": severity,
            })

        results.sort(key=lambda r: -r["_severity_score"])
        return results
    except Exception as e:
        print(f"[Error] get_repeat_offenders failed: {e}")
        return []


_RECOGNITION_ISSUE_TYPES: set[str] = {
    "recognition",
    IssueType.HIGH_PERFORMER_IGNORED,
}


def get_ignored_high_performers(
    tenant_id: str = "",
    today: date | None = None,
    open_actions: list[dict] | None = None,
) -> list[dict]:
    """Surface top performers with an open recognition action where no recognition event was logged.

    An employee is "ignored" when:
      - There is an open action with issue_type in {"recognition", "high_performer_ignored"}
      - No "recognized" event has ever been logged against that action

    Returns one dict per qualifying employee, sorted by days_waiting descending.
    Keys: employee_id, employee_name, department, days_waiting, trigger_summary,
          action_id, action, signals.
    """
    today = today or date.today()
    try:
        import database

        actions = open_actions
        if actions is None:
            actions = database.list_actions(
                tenant_id=tenant_id,
                statuses=list(OPEN_STATUSES),
            )

        recognition_actions = [
            a for a in (actions or [])
            if str(a.get("issue_type") or "") in _RECOGNITION_ISSUE_TYPES
        ]

        results: list[dict] = []

        for action in recognition_actions:
            action_id = str(action.get("id") or "")
            if not action_id:
                continue

            events = database.list_action_events(
                action_id=action_id,
                tenant_id=tenant_id,
            )
            has_recognized_event = any(
                str(ev.get("event_type") or "") == "recognized"
                for ev in (events or [])
            )
            if has_recognized_event:
                continue  # already acknowledged — not ignored

            # Days since this action was created
            created_raw = str(action.get("created_at") or action.get("last_event_at") or "")
            days_waiting = 0
            if created_raw:
                try:
                    days_waiting = (today - date.fromisoformat(created_raw[:10])).days
                except Exception:
                    pass

            trigger_summary = str(action.get("trigger_summary") or "")
            signals: list[str] = []
            if trigger_summary:
                signals.append(trigger_summary)
            signals.append(f"waiting {days_waiting} day{'s' if days_waiting != 1 else ''}")
            signals.append("no recognition logged")

            # How many coaching/follow-up cycles have passed since flagged
            touchpoint_count = sum(
                1 for ev in (events or [])
                if str(ev.get("event_type") or "") in {"coached", "follow_up_logged"}
            )
            if touchpoint_count:
                signals.append(f"{touchpoint_count}× touched but not recognized")

            results.append({
                "employee_id": str(action.get("employee_id") or ""),
                "employee_name": str(action.get("employee_name") or action.get("employee_id") or ""),
                "department": str(action.get("department") or ""),
                "days_waiting": days_waiting,
                "trigger_summary": trigger_summary,
                "action_id": action_id,
                "action": action,
                "signals": signals,
                "touchpoint_count": touchpoint_count,
            })

        results.sort(key=lambda r: -r["days_waiting"])
        return results
    except Exception as e:
        print(f"[Error] get_ignored_high_performers failed: {e}")
        return []


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
        import database
        database.update_action(
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
        print(f"[Error] log_recognition_event failed: {e}")
        return {}


def get_manager_outcome_stats(
    tenant_id: str = "",
    lookback_days: int = 7,
    today: date | None = None,
) -> dict:
    """Compute manager-level outcome stats for this week (or N days back).

    Scans action_events with event_type in {coached, follow_up_logged, recognized}
    and outcome not null. Returns counts by outcome + breakdown by issue_type.

    Returns dict with:
      - "total_events": int
      - "outcomes": {"improved": int, "no_change": int, "worse": int, "pending": int}
      - "by_issue_type": {issue_type: {"improved": int, "no_change": int, ...}}
      - "outcome_percentages": {"improved": float, ...}
    """
    today = today or date.today()
    try:
        import database

        cutoff = (today - timedelta(days=lookback_days)).isoformat()

        # Load all events in the lookback window with outcomes
        all_actions = database.list_actions(tenant_id=tenant_id)
        total_events = 0
        outcomes_count: dict[str, int] = {
            "improved": 0,
            "no_change": 0,
            "worse": 0,
            "pending": 0,
            "not_applicable": 0,
        }
        by_issue_type: dict[str, dict[str, int]] = {}

        for action in all_actions or []:
            action_id = str(action.get("id") or "")
            issue_type = str(action.get("issue_type") or "unknown")
            if issue_type not in by_issue_type:
                by_issue_type[issue_type] = {
                    "improved": 0,
                    "no_change": 0,
                    "worse": 0,
                    "pending": 0,
                    "not_applicable": 0,
                }

            events = database.list_action_events(
                action_id=action_id,
                tenant_id=tenant_id,
            )
            for ev in events or []:
                ev_at = str(ev.get("event_at") or "")
                if ev_at < cutoff:
                    continue  # before lookback window
                ev_type = str(ev.get("event_type") or "")
                ev_outcome = str(ev.get("outcome") or "")

                # Only count when there's an explicit outcome
                if ev_type in {"coached", "follow_up_logged", "recognized"} and ev_outcome:
                    total_events += 1
                    outcomes_count[ev_outcome] = outcomes_count.get(ev_outcome, 0) + 1
                    by_issue_type[issue_type][ev_outcome] = (
                        by_issue_type[issue_type].get(ev_outcome, 0) + 1
                    )

        # Compute percentages
        outcome_percentages: dict[str, float] = {}
        if total_events > 0:
            for outcome, count in outcomes_count.items():
                outcome_percentages[outcome] = round(100.0 * count / total_events, 1)

        return {
            "total_events": total_events,
            "outcomes": outcomes_count,
            "by_issue_type": by_issue_type,
            "outcome_percentages": outcome_percentages,
            "lookback_days": lookback_days,
        }
    except Exception as e:
        print(f"[Error] get_manager_outcome_stats failed: {e}")
        return {
            "total_events": 0,
            "outcomes": {},
            "by_issue_type": {},
            "outcome_percentages": {},
            "lookback_days": lookback_days,
        }


def get_action_recommendation(
    action: dict,
    tenant_id: str = "",
    today: date | None = None,
) -> dict:
    """Return a single recommended next action based on action state and history.

    Rules (in priority order):
      1. Overdue → "follow up now"
      2. Due today → "follow up now"
      3. Recognition type with no recognized event → "recognize"
      4. Coached 2+ times with 2+ no-improvement outcomes → "escalate"
      5. 2+ no-improvement outcomes → "deprioritize"
      6. New action (≤1 day old) → "coach today"
      7. In progress but never coached → "coach today"
      8. Default → "follow up"

    Returns dict with: recommendation, reason, urgency.
    """
    today = today or date.today()
    try:
        import database

        action_id = str(action.get("id") or "")
        issue_type = str(action.get("issue_type") or "")
        status = str(action.get("status") or "new")
        created_at = action.get("created_at") or action.get("last_event_at")

        # Rule 1 & 2: Runtime status — overdue or due today
        runtime_status = action.get("_runtime_status") or ""
        if runtime_status in {"overdue", "due_today"}:
            return {
                "recommendation": "follow up now",
                "reason": "Follow-up is " + ("overdue" if runtime_status == "overdue" else "due today"),
                "urgency": "high",
            }

        # Rule 3: Recognition issue awaiting logged recognition
        if issue_type in {"recognition", "high_performer_ignored"}:
            if action_id:
                events = database.list_action_events(action_id, tenant_id)
                has_recognized = any(
                    str(e.get("event_type") or "") == "recognized"
                    for e in (events or [])
                )
                if not has_recognized:
                    return {
                        "recommendation": "recognize",
                        "reason": "High performer awaiting recognition",
                        "urgency": "medium",
                    }

        # Load events for cycle analysis
        coached_count = 0
        no_improvement_count = 0
        if action_id:
            events = database.list_action_events(action_id, tenant_id)
            coached_count = sum(
                1 for e in (events or [])
                if str(e.get("event_type") or "") == "coached"
            )
            no_improvement_count = sum(
                1 for e in (events or [])
                if str(e.get("outcome") or "") in NO_IMPROVEMENT_OUTCOMES
            )

        # Rule 4: Multiple coaching cycles with no improvement
        if coached_count >= 2 and no_improvement_count >= 2:
            return {
                "recommendation": "escalate",
                "reason": f"Coached {coached_count}× with no improvement",
                "urgency": "high",
            }

        # Rule 5: Multiple no-improvement outcomes
        if no_improvement_count >= 2:
            return {
                "recommendation": "deprioritize",
                "reason": f"{no_improvement_count} outcomes show no improvement",
                "urgency": "medium",
            }

        # Rule 6: New action (created recently)
        days_since_created = 0
        if created_at:
            try:
                created_date = date.fromisoformat(str(created_at)[:10])
                days_since_created = (today - created_date).days
            except Exception:
                pass

        if status == "new" and days_since_created <= 1:
            return {
                "recommendation": "coach today",
                "reason": "New action, ready to engage",
                "urgency": "medium",
            }

        # Rule 7: In progress but never coached
        if status == "in_progress" and coached_count == 0:
            return {
                "recommendation": "coach today",
                "reason": "Ready for initial coaching",
                "urgency": "medium",
            }

        # Default: continue tracking
        return {
            "recommendation": "follow up",
            "reason": "Continue tracking progress",
            "urgency": "low",
        }
    except Exception as e:
        print(f"[Error] get_action_recommendation failed: {e}")
        return {
            "recommendation": "continue",
            "reason": "See action card for details",
            "urgency": "low",
        }


def get_product_success_metrics(
    tenant_id: str = "",
    today: date | None = None,
) -> dict:
    """Compute product success metrics to track whether the new action-focused UX is working.

    Metrics returned (all as percentages or counts):
      - follow_up_logged_pct: % of actions with at least one follow-up event
      - overdue_count: Number of currently overdue actions
      - avg_days_to_first_followup: Average days from creation to first follow-up
      - resolved_pct: % of actions with status="resolved"
      - outcome_captured_pct: % of actions with at least one event having an outcome
      - repeat_unresolved_per_employee: Avg unresolved action count for employees with 2+ unresolved
      - repeat_unresolved_employee_count: Number of employees with 2+ unresolved actions
      - total_actions: Total action count (denominator for percentages)

    End goal: Track whether managers are actually using the system, following up, and closing out actions.
    """
    today = today or date.today()
    try:
        import database

        all_actions = database.list_actions(tenant_id=tenant_id)
        if not all_actions:
            return {
                "follow_up_logged_pct": 0.0,
                "overdue_count": 0,
                "avg_days_to_first_followup": 0.0,
                "resolved_pct": 0.0,
                "outcome_captured_pct": 0.0,
                "repeat_unresolved_per_employee": 0.0,
                "repeat_unresolved_employee_count": 0,
                "total_actions": 0,
                "lookback_period": "all-time",
            }

        total_count = len(all_actions)
        follow_up_count = 0
        overdue_count = 0
        resolved_count = 0
        outcome_captured_count = 0
        days_to_followup_list: list[int] = []

        # Group unresolved actions by employee for repeat analysis
        unresolved_by_emp: dict[str, int] = {}

        for action in all_actions:
            action_id = str(action.get("id") or "")
            status = str(action.get("status") or "new")
            created_at = action.get("created_at")
            emp_id = str(action.get("employee_id") or "")

            # Metric 4: % resolved
            if status == "resolved":
                resolved_count += 1

            # Metric 2: Overdue count
            runtime_st = runtime_status(
                status,
                action.get("follow_up_due_at"),
                today=today,
            )
            if runtime_st == "overdue":
                overdue_count += 1

            # Metrics based on events
            if action_id:
                events = database.list_action_events(action_id, tenant_id)
                
                # Metric 1: % with follow-up logged
                has_followup = any(
                    str(ev.get("event_type") or "") in {"follow_up_logged", "coached"}
                    for ev in (events or [])
                )
                if has_followup:
                    follow_up_count += 1
                    
                    # Metric 3: Avg days to first follow-up
                    if created_at:
                        try:
                            created_date = date.fromisoformat(str(created_at)[:10])
                            first_followup_event = next(
                                (ev for ev in sorted(events or [], key=lambda e: str(e.get("event_at") or ""))
                                 if str(ev.get("event_type") or "") in {"follow_up_logged", "coached"}),
                                None
                            )
                            if first_followup_event:
                                followup_at = str(first_followup_event.get("event_at") or "")
                                followup_date = date.fromisoformat(followup_at[:10])
                                days_diff = (followup_date - created_date).days
                                if days_diff >= 0:
                                    days_to_followup_list.append(days_diff)
                        except Exception:
                            pass

                # Metric 5: % with outcome captured
                has_outcome = any(
                    bool(ev.get("outcome"))
                    for ev in (events or [])
                )
                if has_outcome:
                    outcome_captured_count += 1

            # Metric 6: Repeat unresolved issues per employee
            if status in OPEN_STATUSES:
                unresolved_by_emp[emp_id] = unresolved_by_emp.get(emp_id, 0) + 1

        # Compute percentages
        follow_up_pct = round(100.0 * follow_up_count / total_count, 1) if total_count > 0 else 0.0
        resolved_pct = round(100.0 * resolved_count / total_count, 1) if total_count > 0 else 0.0
        outcome_pct = round(100.0 * outcome_captured_count / total_count, 1) if total_count > 0 else 0.0

        avg_days_to_followup = round(
            sum(days_to_followup_list) / len(days_to_followup_list), 1
        ) if days_to_followup_list else 0.0

        repeat_unresolved_emps = {
            emp_id: count for emp_id, count in unresolved_by_emp.items()
            if count >= 2
        }
        repeat_unresolved_count = len(repeat_unresolved_emps)
        avg_repeat_unresolved = round(
            sum(repeat_unresolved_emps.values()) / len(repeat_unresolved_emps), 2
        ) if repeat_unresolved_emps else 0.0

        return {
            "follow_up_logged_pct": follow_up_pct,
            "overdue_count": overdue_count,
            "avg_days_to_first_followup": avg_days_to_followup,
            "resolved_pct": resolved_pct,
            "outcome_captured_pct": outcome_pct,
            "repeat_unresolved_per_employee": avg_repeat_unresolved,
            "repeat_unresolved_employee_count": repeat_unresolved_count,
            "total_actions": total_count,
            "lookback_period": "all-time",
        }
    except Exception as e:
        print(f"[Error] get_product_success_metrics failed: {e}")
        return {
            "follow_up_logged_pct": 0.0,
            "overdue_count": 0,
            "avg_days_to_first_followup": 0.0,
            "resolved_pct": 0.0,
            "outcome_captured_pct": 0.0,
            "repeat_unresolved_per_employee": 0.0,
            "repeat_unresolved_employee_count": 0,
            "total_actions": 0,
            "lookback_period": "all-time",
        }


# ──────────────────────────────────────────────────────────────────────────────
# Automatic Action Triggers
# Run after import, on Today Screen load, or by daily refresh job.
# Return summary dict with counts of created/updated actions.
# ──────────────────────────────────────────────────────────────────────────────


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
        import database
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
                )
                if action:
                    result["created"] += 1
                else:
                    result["errors"] += 1
    except Exception as e:
        print(f"[Error] trigger_repeated_low_performance failed: {e}")
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
        print(f"[Error] trigger_follow_up_due failed: {e}")
    
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
        import database
        all_actions = database.list_actions(tenant_id=tenant_id, employee_id="")
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
        print(f"[Error] trigger_repeat_no_improvement failed: {e}")
    
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
        import database
        
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
                )
                if action:
                    result["created"] += 1
    except Exception as e:
        print(f"[Error] trigger_ignored_high_performer failed: {e}")
    
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
        
        print(f"[Info] All triggers completed: {summary}")
    except Exception as e:
        print(f"[Error] run_all_triggers failed: {e}")
        summary["error"] = str(e)
    
    return summary


def normalize_emp_id(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.endswith(".0") and raw[:-2].isdigit():
        return raw[:-2]
    return raw


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        try:
            return date.fromisoformat(text[:10])
        except Exception:
            return None


def _extract_row_emp_id(row: dict) -> str:
    return normalize_emp_id(
        row.get("EmployeeID")
        or row.get("emp_id")
        or row.get("Employee Name")
        or row.get("Employee")
        or ""
    )


def _extract_row_name(row: dict) -> str:
    return str(row.get("Employee Name") or row.get("Employee") or row.get("name") or "Unknown")


def _extract_row_dept(row: dict) -> str:
    return str(row.get("Department") or row.get("department") or "")


def _extract_row_uph(row: dict) -> float:
    if "UPH" in row:
        return _safe_float(row.get("UPH"), 0.0)
    if "uph" in row:
        return _safe_float(row.get("uph"), 0.0)
    return _safe_float(row.get("Average UPH"), 0.0)


def _history_by_emp(history: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in history or []:
        emp_id = _extract_row_emp_id(row)
        if not emp_id:
            continue
        grouped.setdefault(emp_id, []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda item: (_parse_date(item.get("Date") or item.get("work_date") or item.get("Week")) or date.min))
    return grouped


def _recent_average_uph(history_rows: list[dict], trailing_days: int = 7) -> float:
    if not history_rows:
        return 0.0
    cutoff = date.today() - timedelta(days=trailing_days)
    values = []
    for row in history_rows:
        row_date = _parse_date(row.get("Date") or row.get("work_date"))
        if row_date and row_date >= cutoff:
            uph = _extract_row_uph(row)
            if uph > 0:
                values.append(uph)
    if not values:
        values = [_extract_row_uph(row) for row in history_rows[-trailing_days:] if _extract_row_uph(row) > 0]
    return round(sum(values) / len(values), 2) if values else 0.0


def _below_goal_streak(row: dict, history_rows: list[dict]) -> int:
    target = _safe_float(row.get("Target UPH"), 0.0)
    if target <= 0 or not history_rows:
        return 0
    streak = 0
    for item in reversed(history_rows):
        uph = _extract_row_uph(item)
        if uph <= 0:
            continue
        if uph < target:
            streak += 1
        else:
            break
    return streak


def _queue_state(action: dict, today: date) -> str:
    return status_label(str(action.get("status") or "new"), action.get("follow_up_due_at"), today=today)


def _build_next_step(action_type: str, fallback: str) -> str:
    cleaned = str(action_type or "").strip().replace("_", " ")
    if cleaned:
        return cleaned.title()
    return fallback


def _open_actions_by_emp(actions: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for action in sorted(actions or [], key=lambda item: str(item.get("created_at") or ""), reverse=True):
        status = str(action.get("status") or "new").lower()
        if status not in OPEN_ACTION_STATUSES:
            continue
        emp_id = normalize_emp_id(action.get("employee_id"))
        if emp_id and emp_id not in latest:
            latest[emp_id] = action
    return latest


def build_today_screen_payload(
    gs: list[dict],
    history: list[dict],
    actions: list[dict],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    history_map = _history_by_emp(history)
    open_actions = _open_actions_by_emp(actions)
    queue: list[dict] = []

    for action in actions or []:
        if str(action.get("status") or "").lower() == "resolved":
            continue
        emp_id = normalize_emp_id(action.get("employee_id"))
        state = _queue_state(action, today)
        failed_cycles = int(action.get("failed_cycles") or 0)
        urgency = urgency_score(
            status=str(action.get("status") or "new"),
            due_date=action.get("follow_up_due_at"),
            issue_type=str(action.get("issue_type") or ""),
            failed_cycles=failed_cycles,
            today=today,
        )
        queue.append({
            "source": "action",
            "id": action.get("id"),
            "employee_id": emp_id,
            "employee_name": action.get("employee_name") or emp_id,
            "department": action.get("department") or "",
            "issue_type": action.get("issue_type") or "",
            "trigger_summary": action.get("trigger_summary") or "Open follow-up requires attention",
            "status": state,
            "follow_up_due_at": action.get("follow_up_due_at"),
            "action_type": action.get("action_type") or "",
            "success_metric": action.get("success_metric") or "",
            "baseline_uph": _safe_float(action.get("baseline_uph"), 0.0),
            "latest_uph": _safe_float(action.get("latest_uph"), 0.0),
            "next_step": _build_next_step(action.get("action_type"), "Complete follow-up"),
            "priority": determine_priority(
                issue_type=str(action.get("issue_type") or ""),
                status=str(action.get("status") or "new"),
                follow_up_due_at=action.get("follow_up_due_at"),
                failed_cycles=failed_cycles,
                today=today,
            ),
            "urgency": urgency,
        })

    for row in gs or []:
        emp_id = _extract_row_emp_id(row)
        if not emp_id or emp_id in open_actions:
            continue
        if str(row.get("goal_status") or "") != "below_goal":
            continue
        streak = _below_goal_streak(row, history_map.get(emp_id, []))
        if streak < 3:
            continue
        avg_uph = _safe_float(row.get("Average UPH"), 0.0)
        target = _safe_float(row.get("Target UPH"), 0.0)
        queue.append({
            "source": "generated",
            "id": None,
            "employee_id": emp_id,
            "employee_name": _extract_row_name(row),
            "department": _extract_row_dept(row),
            "issue_type": IssueType.LOW_PERFORMANCE_UNADDRESSED,
            "trigger_summary": f"Below goal for {streak} shifts with no action logged",
            "status": "New",
            "follow_up_due_at": today.isoformat(),
            "action_type": "",
            "success_metric": f"Return to {target:.1f} UPH target" if target > 0 else "Return to baseline",
            "baseline_uph": avg_uph,
            "latest_uph": avg_uph,
            "next_step": "Start follow-up cycle",
            "priority": determine_priority(
                issue_type=IssueType.LOW_PERFORMANCE_UNADDRESSED,
                status="new",
                follow_up_due_at=today.isoformat(),
                failed_cycles=streak,
                today=today,
            ),
            "urgency": 80 + streak,
        })

    queue.sort(key=lambda item: (-int(item.get("urgency") or 0), str(item.get("employee_name") or "")))

    closed_actions = [a for a in actions or [] if str(a.get("status") or "").lower() == "resolved"]
    repeat_offenders = build_repeat_offenders(closed_actions, gs)
    ignored_high_performers = build_ignored_high_performers(gs, actions, today=today)
    recent_outcomes = build_recent_outcomes(closed_actions, today=today)

    summary = {
        "open_actions": sum(1 for item in queue if item.get("status") not in {"Resolved"}),
        "overdue": sum(1 for item in queue if item.get("status") == "Overdue"),
        "repeat_offenders": len(repeat_offenders),
        "ignored_high_performers": len(ignored_high_performers),
    }

    return {
        "summary": summary,
        "action_queue": queue,
        "repeat_offenders": repeat_offenders,
        "ignored_high_performers": ignored_high_performers,
        "recent_outcomes": recent_outcomes,
    }


def build_repeat_offenders(closed_actions: list[dict], gs: list[dict]) -> list[dict]:
    current_by_emp = {_extract_row_emp_id(row): row for row in gs or []}
    grouped: dict[str, list[dict]] = {}
    for action in closed_actions or []:
        if str(action.get("resolution_type") or "").lower() not in NO_IMPROVEMENT_OUTCOMES:
            continue
        emp_id = normalize_emp_id(action.get("employee_id"))
        if emp_id:
            grouped.setdefault(emp_id, []).append(action)

    offenders = []
    for emp_id, items in grouped.items():
        if len(items) < 2:
            continue
        current = current_by_emp.get(emp_id, {})
        offenders.append({
            "employee_id": emp_id,
            "employee_name": items[0].get("employee_name") or _extract_row_name(current),
            "department": items[0].get("department") or _extract_row_dept(current),
            "failed_cycles": len(items),
            "current_uph": _safe_float(current.get("Average UPH"), 0.0),
            "target_uph": _safe_float(current.get("Target UPH"), 0.0),
            "recommendation": "Change approach or escalate; prior coaching cycles did not improve performance.",
        })

    offenders.sort(key=lambda item: (-int(item.get("failed_cycles") or 0), str(item.get("employee_name") or "")))
    return offenders


def build_ignored_high_performers(gs: list[dict], actions: list[dict], *, today: date | None = None) -> list[dict]:
    today = today or date.today()
    recent_cutoff = today - timedelta(days=HIGH_PERFORMER_LOOKBACK_DAYS)
    recent_dev_emp_ids = set()
    for action in actions or []:
        if str(action.get("issue_type") or "") != IssueType.HIGH_PERFORMER_IGNORED:
            continue
        created = _parse_date(action.get("created_at"))
        if created and created >= recent_cutoff:
            recent_dev_emp_ids.add(normalize_emp_id(action.get("employee_id")))

    high_performers = []
    for row in gs or []:
        emp_id = _extract_row_emp_id(row)
        if not emp_id or emp_id in recent_dev_emp_ids:
            continue
        avg_uph = _safe_float(row.get("Average UPH"), 0.0)
        target = _safe_float(row.get("Target UPH"), 0.0)
        if target <= 0 or avg_uph < (target * 1.10):
            continue
        if str(row.get("goal_status") or "") == "below_goal":
            continue
        high_performers.append({
            "employee_id": emp_id,
            "employee_name": _extract_row_name(row),
            "department": _extract_row_dept(row),
            "avg_uph": avg_uph,
            "target_uph": target,
            "recommendation": "Assign a development touchpoint so strong performers are not ignored.",
        })

    high_performers.sort(key=lambda item: (-float(item.get("avg_uph") or 0.0), str(item.get("employee_name") or "")))
    return high_performers[:5]


def build_recent_outcomes(closed_actions: list[dict], *, today: date | None = None) -> list[dict]:
    today = today or date.today()
    cutoff = today - timedelta(days=14)
    recent = []
    for action in closed_actions or []:
        completed = _parse_date(action.get("resolved_at") or action.get("last_event_at"))
        if completed and completed >= cutoff:
            recent.append({
                "employee_name": action.get("employee_name") or normalize_emp_id(action.get("employee_id")),
                "department": action.get("department") or "",
                "outcome": str(action.get("resolution_type") or "").replace("_", " ").title(),
                "delta": round(_safe_float(action.get("improvement_delta"), 0.0), 2),
                "completed_at": completed.isoformat(),
            })
    recent.sort(key=lambda item: item.get("completed_at", ""), reverse=True)
    return recent[:10]


def _recent_action_outcomes(lookback_days: int = 1, tenant_id: str = "") -> list[dict]:
    """Get recently resolved actions for the 'What Changed' section.
    
    Returns list of resolved actions from the past lookback_days sorted by resolution date.
    """
    try:
        import database
        today = date.today()
        cutoff = today - timedelta(days=lookback_days)
        
        # Query all resolved actions (not open)
        all_actions = database.list_actions(
            tenant_id=tenant_id,
            statuses=["resolved", "deprioritized"],
        )
        
        recent = []
        for action in all_actions or []:
            resolved_date = _parse_date(action.get("resolved_at"))
            if resolved_date and resolved_date >= cutoff:
                recent.append({
                    "employee_name": action.get("employee_name") or normalize_emp_id(action.get("employee_id")),
                    "department": action.get("department") or "",
                    "outcome": str(action.get("resolution_type") or "unknown").replace("_", " ").title(),
                    "delta": round(_safe_float(action.get("improvement_delta"), 0.0), 2),
                    "completed_at": (resolved_date.isoformat() if resolved_date else ""),
                    "id": action.get("id"),
                })
        
        recent.sort(key=lambda item: item.get("completed_at", ""), reverse=True)
        return recent
    except Exception as e:
        print(f"[Error] _recent_action_outcomes failed: {e}")
        return []
