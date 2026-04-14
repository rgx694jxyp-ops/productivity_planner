"""Service-layer queue construction for Today action flows.

This module contains non-UI queue logic so services and pages do not depend on
UI modules.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

from domain.actions import parse_action_date
from services.plain_language_service import signal_wording


_AMBIGUOUS_FACTOR_PHRASES = {"", "unknown", "status", "needs review", "worth review", "limited data available"}


@dataclass(frozen=True)
class ActionQueueItemModel:
    payload: dict
    queue_status: str
    short_reason: str
    good_looks_like: str
    is_repeat_issue: bool
    is_recognition_opportunity: bool
    why_this_is_here: str
    surfaced_factors: list[str]
    repeat_signals: list[str]
    recognition_signals: list[str]
    display_bucket: str

    def to_dict(self) -> dict:
        row = dict(self.payload)
        row["_queue_status"] = self.queue_status
        row["_short_reason"] = self.short_reason
        row["_good_looks_like"] = self.good_looks_like
        row["_is_repeat_issue"] = self.is_repeat_issue
        row["_is_recognition_opportunity"] = self.is_recognition_opportunity
        row["_why_this_is_here"] = self.why_this_is_here
        row["_surfaced_factors"] = list(self.surfaced_factors)
        row["_repeat_signals"] = list(self.repeat_signals)
        row["_recognition_signals"] = list(self.recognition_signals)
        row["_display_bucket"] = self.display_bucket
        return row


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
        factors.append(signal_wording("follow_up_not_completed"))
    if bool(action.get("_is_repeat_issue")):
        factors.append("Seen multiple times")

    issue_type = str(action.get("issue_type") or "").strip().lower()
    trigger_summary = str(action.get("trigger_summary") or "").strip().lower()
    if issue_type in {"low_performance", "low_performance_unaddressed", "repeated_low_performance"}:
        factors.append(signal_wording("lower_than_recent_pace"))
    elif "below" in trigger_summary or "lower" in trigger_summary or "declin" in trigger_summary:
        factors.append(signal_wording("lower_than_recent_pace"))

    if not factors:
        factors.append(signal_wording("lower_than_recent_pace"))

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
    pace_rank = 0 if signal_wording("lower_than_recent_pace") in list(action.get("_surfaced_factors") or []) else 1
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
    """Canonical Today action-queue builder.

    This is the single source of truth for queue-item generation from open
    actions. daily_signals_service uses it when building the precomputed Today
    payload, and any legacy UI wrapper must delegate here instead of copying
    ranking or display-bucket logic.
    """
    _ = tenant_id
    repeat_lookup = _build_repeat_lookup(repeat_offenders)
    recognition_lookup = _build_recognition_lookup(recognition_opportunities)
    queue_models: list[ActionQueueItemModel] = []

    for action in open_actions:
        enriched = dict(action)
        action_id = str(action.get("id") or "")
        employee_id = str(action.get("employee_id") or "")
        queue_status = _queue_status(action, today)
        repeat_item = repeat_lookup.get(employee_id)
        recognition_item = recognition_lookup.get(action_id)

        enriched["_queue_status"] = queue_status
        enriched["_is_repeat_issue"] = bool(repeat_item)
        enriched["_is_recognition_opportunity"] = bool(recognition_item)
        enriched["_surfaced_factors"] = _surfaced_factors(enriched)

        model = ActionQueueItemModel(
            payload=dict(action),
            queue_status=queue_status,
            short_reason=_short_reason(action),
            good_looks_like=_good_looks_like(action),
            is_repeat_issue=bool(repeat_item),
            is_recognition_opportunity=bool(recognition_item),
            why_this_is_here=_why_this_is_here(enriched, queue_status),
            surfaced_factors=list(enriched.get("_surfaced_factors") or []),
            repeat_signals=list((repeat_item or {}).get("signals") or []),
            recognition_signals=list((recognition_item or {}).get("signals") or []),
            display_bucket=_display_bucket(enriched),
        )
        queue_models.append(model)

    queue_items = [model.to_dict() for model in queue_models if model.display_bucket != "suppressed"]
    queue_items.sort(key=_sort_key)
    return queue_items


def partition_action_queue_items(queue_items: list[dict]) -> tuple[list[dict], list[dict]]:
    primary_items: list[dict] = []
    secondary_items: list[dict] = []
    for item in list(queue_items or []):
        bucket = str(item.get("_display_bucket") or _display_bucket(item))
        if bucket == "secondary":
            secondary_items.append(item)
        elif bucket == "primary":
            primary_items.append(item)
    return primary_items, secondary_items
