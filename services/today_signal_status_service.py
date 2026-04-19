"""User-set signal status tracking for Today queue cards.

This is intentionally lightweight: each status change is appended as an immutable
row in action_events. The system never auto-sets status values.
"""

from __future__ import annotations

import json
from typing import Any

from repositories import action_events_repo
from repositories._common import get_client, get_tenant_id


SIGNAL_STATUS_LOOKED_AT = "looked_at"
SIGNAL_STATUS_NEEDS_FOLLOW_UP = "needs_follow_up"
SIGNAL_STATUSES: tuple[str, str] = (
    SIGNAL_STATUS_LOOKED_AT,
    SIGNAL_STATUS_NEEDS_FOLLOW_UP,
)

_SIGNAL_STATUS_EVENT_TYPE = "today_signal_status_set"
_SIGNAL_STATUS_SCOPE = "today_queue_signal_status"


def normalize_signal_status(value: str) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return normalized if normalized in SIGNAL_STATUSES else ""


def _action_event_status_for_signal_status(signal_status: str) -> str:
    return "done" if signal_status == SIGNAL_STATUS_LOOKED_AT else "pending"


def _status_payload(*, signal_key: str, signal_status: str) -> str:
    payload = {
        "scope": _SIGNAL_STATUS_SCOPE,
        "signal_key": str(signal_key or ""),
        "signal_status": str(signal_status or ""),
    }
    return json.dumps(payload, separators=(",", ":"))


def _parse_status_payload(details: Any) -> tuple[str, str]:
    raw = str(details or "").strip()
    if not raw:
        return "", ""
    try:
        payload = json.loads(raw)
    except Exception:
        return "", ""
    if not isinstance(payload, dict):
        return "", ""
    if str(payload.get("scope") or "") != _SIGNAL_STATUS_SCOPE:
        return "", ""
    signal_key = str(payload.get("signal_key") or "").strip()
    signal_status = normalize_signal_status(str(payload.get("signal_status") or ""))
    if not signal_key or not signal_status:
        return "", ""
    return signal_key, signal_status


def set_signal_status(
    *,
    signal_key: str,
    employee_id: str,
    signal_status: str,
    owner: str = "",
    tenant_id: str = "",
) -> dict:
    normalized = normalize_signal_status(signal_status)
    clean_key = str(signal_key or "").strip()
    clean_employee = str(employee_id or "").strip()
    if not clean_key or not clean_employee or not normalized:
        return {}

    notes = (
        "Marked as looked at from Today queue."
        if normalized == SIGNAL_STATUS_LOOKED_AT
        else "Marked as needs follow-up from Today queue."
    )

    return action_events_repo.log_action_event(
        action_id="",
        event_type=_SIGNAL_STATUS_EVENT_TYPE,
        employee_id=clean_employee,
        performed_by=owner,
        notes=notes,
        owner=owner,
        status=_action_event_status_for_signal_status(normalized),
        details=_status_payload(signal_key=clean_key, signal_status=normalized),
        tenant_id=tenant_id,
    )


def list_latest_signal_statuses(*, signal_keys: set[str], tenant_id: str = "") -> dict[str, dict[str, str]]:
    wanted = {str(key or "").strip() for key in (signal_keys or set()) if str(key or "").strip()}
    if not wanted:
        return {}

    tid = str(tenant_id or get_tenant_id() or "").strip()
    if not tid:
        return {}

    page_size = max(200, min(1000, len(wanted) * 5))
    offset = 0

    by_signal: dict[str, dict[str, str]] = {}
    while len(by_signal) < len(wanted):
        upper = offset + page_size - 1
        result = (
            get_client()
            .table("action_events")
            .select("event_type, details, owner, performed_by, event_at")
            .eq("tenant_id", tid)
            .eq("event_type", _SIGNAL_STATUS_EVENT_TYPE)
            .order("event_at", desc=True)
            .range(offset, upper)
            .execute()
        )
        rows = result.data or []
        if not rows:
            break

        for row in rows:
            signal_key, signal_status = _parse_status_payload(row.get("details"))
            if not signal_key or signal_key not in wanted or signal_key in by_signal:
                continue
            by_signal[signal_key] = {
                "status": signal_status,
                "owner": str(row.get("owner") or row.get("performed_by") or "").strip(),
                "event_at": str(row.get("event_at") or "").strip(),
            }
            if len(by_signal) >= len(wanted):
                break

        if len(rows) < page_size:
            break
        offset += page_size

    return by_signal
