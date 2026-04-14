"""Action metrics service.

Responsible for KPI/statistics rollups and outcome summaries.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from domain.actions import OPEN_STATUSES, runtime_status
from repositories import action_events_repo, actions_repo


_TODAY_SIGNAL_STATUS_EVENT_TYPE = "today_signal_status_set"
_TODAY_SIGNAL_STATUS_SCOPE = "today_queue_signal_status"
_TODAY_SIGNAL_STATUS_LOOKED_AT = "looked_at"


def _parse_today_signal_status(details: Any) -> tuple[str, str]:
    raw = str(details or "").strip()
    if not raw:
        return "", ""
    try:
        payload = json.loads(raw)
    except Exception:
        return "", ""
    if not isinstance(payload, dict):
        return "", ""
    if str(payload.get("scope") or "") != _TODAY_SIGNAL_STATUS_SCOPE:
        return "", ""
    signal_key = str(payload.get("signal_key") or "").strip()
    signal_status = str(payload.get("signal_status") or "").strip().lower()
    return signal_key, signal_status


def get_weekly_manager_activity_summary(
    tenant_id: str = "",
    lookback_days: int = 7,
    today: date | None = None,
) -> dict[str, int]:
    """Return lightweight weekly manager-activity counts for Today.

    Counts are intentionally conservative and derived from existing action/event
    sources only:
    - reviewed_issues: distinct Today signal keys marked looked-at this week
    - follow_up_touchpoints: coaching/follow-up events logged this week
    - closed_issues: resolved/deprioritized actions closed this week
    - improved_outcomes: explicit improved outcomes logged this week
    """
    today = today or date.today()
    cutoff = today - timedelta(days=lookback_days)

    try:
        reviewed_signal_keys: set[str] = set()
        follow_up_touchpoints = 0

        all_events = action_events_repo.list_action_events(
            action_id="",
            tenant_id=tenant_id,
            limit=5000,
            newest_first=True,
            columns="event_type, event_at, details",
        )
        for event in all_events or []:
            event_date = _parse_date(event.get("event_at"))
            if event_date is None or event_date < cutoff:
                continue

            event_type = str(event.get("event_type") or "").strip()
            if event_type == _TODAY_SIGNAL_STATUS_EVENT_TYPE:
                signal_key, signal_status = _parse_today_signal_status(event.get("details"))
                if signal_key and signal_status == _TODAY_SIGNAL_STATUS_LOOKED_AT:
                    reviewed_signal_keys.add(signal_key)
            elif event_type in {"coached", "follow_up_logged", "follow_through_logged"}:
                follow_up_touchpoints += 1

        manager_outcomes = get_manager_outcome_stats(
            tenant_id=tenant_id,
            lookback_days=lookback_days,
            today=today,
        )
        recent_closed = _recent_action_outcomes(lookback_days=lookback_days, tenant_id=tenant_id)

        return {
            "reviewed_issues": len(reviewed_signal_keys),
            "follow_up_touchpoints": int(follow_up_touchpoints),
            "closed_issues": len(list(recent_closed or [])),
            "improved_outcomes": int((manager_outcomes.get("outcomes") or {}).get("improved", 0) or 0),
        }
    except Exception as e:
        print(f"[Error] get_weekly_manager_activity_summary failed: {e}")
        return {
            "reviewed_issues": 0,
            "follow_up_touchpoints": 0,
            "closed_issues": 0,
            "improved_outcomes": 0,
        }

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
        cutoff = (today - timedelta(days=lookback_days)).isoformat()

        # Load all events in the lookback window with outcomes
        all_actions = actions_repo.list_actions(tenant_id=tenant_id)
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

            events = action_events_repo.list_action_events(
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
        all_actions = actions_repo.list_actions(tenant_id=tenant_id)
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
                events = action_events_repo.list_action_events(action_id, tenant_id)
                
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



def _recent_action_outcomes(lookback_days: int = 1, tenant_id: str = "") -> list[dict]:
    """Get recently resolved actions for the 'What Changed' section.
    
    Returns list of resolved actions from the past lookback_days sorted by resolution date.
    """
    try:
        today = date.today()
        cutoff = today - timedelta(days=lookback_days)
        
        # Query all resolved actions (not open)
        all_actions = actions_repo.list_actions(
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
