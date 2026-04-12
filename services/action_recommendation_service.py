"""Action signal service.

Surfaces neutral factors for open action review without prescribing decisions.
"""

from __future__ import annotations

from datetime import date, timedelta

from domain.actions import IssueType, NO_IMPROVEMENT_OUTCOMES, OPEN_STATUSES
from repositories import action_events_repo, actions_repo

_REPEAT_ISSUE_TYPES: frozenset[str] = frozenset({
    IssueType.REPEAT_NO_IMPROVEMENT,
})

def get_repeat_offenders(
    tenant_id: str = "",
    today: date | None = None,
    open_actions: list[dict] | None = None,
    min_coached_cycles: int = 2,
    stale_days_threshold: int = 14,
) -> list[dict]:
    """Identify employees with repeated management patterns that need closer review.

    Scans open actions (or accepts pre-loaded list) and loads lifecycle events to detect:
      - Coached 2+ times without sustained improvement
      - Unresolved 14+ days
      - Multiple no-improvement outcomes

    Returns one dict per qualifying employee, sorted by severity descending.
    Each dict keys: employee_id, employee_name, department, open_action_count,
    coached_cycle_count, no_improvement_count, max_days_open, signals, actions.
    """
    today = today or date.today()
    try:
        actions = open_actions
        if actions is None:
            actions = actions_repo.list_actions(
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
            has_repeat_type = any(
                str(a.get("issue_type") or "") in _REPEAT_ISSUE_TYPES
                for a in emp_actions
            )
            if len(emp_actions) < 2 and max_days_open < stale_days_threshold and not has_repeat_type:
                continue

            # Load events across all actions for this employee
            coached_total = 0
            no_improvement_total = 0
            for action in emp_actions:
                action_id = str(action.get("id") or "")
                if not action_id:
                    continue
                events = action_events_repo.list_action_events(
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
        actions = open_actions
        if actions is None:
            actions = actions_repo.list_actions(
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

            events = action_events_repo.list_action_events(
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



def get_action_factors(
    action: dict,
    tenant_id: str = "",
    today: date | None = None,
) -> dict:
    """Return neutral surfaced factors for an open action.

    Returns dict with: factors (list[str]), reason, urgency.
    """
    today = today or date.today()
    try:
        action_id = str(action.get("id") or "")
        issue_type = str(action.get("issue_type") or "")
        status = str(action.get("status") or "new")
        created_at = action.get("created_at") or action.get("last_event_at")

        factors: list[str] = []

        # Runtime status: overdue or due today
        runtime_status = action.get("_runtime_status") or ""
        if runtime_status in {"overdue", "due_today"}:
            factors.append("Follow-up overdue")

        # Recognition issue awaiting logged recognition
        if issue_type in {"recognition", "high_performer_ignored"}:
            if action_id:
                events = action_events_repo.list_action_events(action_id, tenant_id)
                has_recognized = any(
                    str(e.get("event_type") or "") == "recognized"
                    for e in (events or [])
                )
                if not has_recognized:
                    factors.append("Seen multiple times")

        # Load events for cycle analysis
        coached_count = 0
        no_improvement_count = 0
        if action_id:
            events = action_events_repo.list_action_events(action_id, tenant_id)
            coached_count = sum(
                1 for e in (events or [])
                if str(e.get("event_type") or "") == "coached"
            )
            no_improvement_count = sum(
                1 for e in (events or [])
                if str(e.get("outcome") or "") in NO_IMPROVEMENT_OUTCOMES
            )

        # Multiple coaching cycles with no improvement
        if coached_count >= 2 and no_improvement_count >= 2:
            factors.append("Seen multiple times")

        # Multiple no-improvement outcomes
        if no_improvement_count >= 2:
            factors.append("Lower than recent pace")

        # Rule 6: New action (created recently)
        days_since_created = 0
        if created_at:
            try:
                created_date = date.fromisoformat(str(created_at)[:10])
                days_since_created = (today - created_date).days
            except Exception:
                pass

        if status in {"new", "in_progress"} and days_since_created <= 1:
            factors.append("Lower than recent pace")

        if not factors:
            factors.append("Lower than recent pace")

        unique_factors: list[str] = []
        seen: set[str] = set()
        for factor in factors:
            key = str(factor).strip().lower()
            if key in seen:
                continue
            seen.add(key)
            unique_factors.append(str(factor).strip())

        return {
            "factors": unique_factors,
            "reason": "Signals are surfaced for supervisor review.",
            "urgency": "high" if "Follow-up overdue" in unique_factors else "medium",
        }
    except Exception as e:
        print(f"[Error] get_action_factors failed: {e}")
        return {
            "factors": ["Lower than recent pace"],
            "reason": "See action card for details",
            "urgency": "low",
        }


def get_action_recommendation(
    action: dict,
    tenant_id: str = "",
    today: date | None = None,
) -> dict:
    """Backward-compatible alias that now returns neutral factors.

    This function no longer returns recommendation fields.
    """
    return get_action_factors(action=action, tenant_id=tenant_id, today=today)


