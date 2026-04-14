from __future__ import annotations

from typing import Any, MutableMapping

from services.observability import log_operational_event


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def build_upgrade_event_payload(
    *,
    prompt_location: str = "",
    prompt_type: str = "",
    current_plan: str = "starter",
    employee_count: Any = 0,
    employee_limit: Any = 0,
    feature_context: str = "",
    tenant_id: str = "",
    user_id: str = "",
) -> dict[str, Any]:
    return {
        "prompt_location": _normalize_text(prompt_location).lower(),
        "prompt_type": _normalize_text(prompt_type).lower(),
        "current_plan": _normalize_text(current_plan).lower() or "starter",
        "employee_count": _coerce_int(employee_count, default=0),
        "employee_limit": _coerce_int(employee_limit, default=0),
        "feature_context": _normalize_text(feature_context) or None,
        "tenant_id": _normalize_text(tenant_id) or None,
        "user_id": _normalize_text(user_id) or None,
    }


def log_upgrade_event(
    event_type: str,
    *,
    prompt_location: str = "",
    prompt_type: str = "",
    current_plan: str = "starter",
    employee_count: Any = 0,
    employee_limit: Any = 0,
    feature_context: str = "",
    tenant_id: str = "",
    user_id: str = "",
    user_email: str = "",
) -> dict[str, Any]:
    payload = build_upgrade_event_payload(
        prompt_location=prompt_location,
        prompt_type=prompt_type,
        current_plan=current_plan,
        employee_count=employee_count,
        employee_limit=employee_limit,
        feature_context=feature_context,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    detail_parts = [
        payload.get("prompt_location") or "",
        payload.get("prompt_type") or "",
        payload.get("feature_context") or "",
    ]
    detail = " / ".join(part for part in detail_parts if part) or str(event_type or "upgrade_event")
    log_operational_event(
        str(event_type or "upgrade_event"),
        status="info",
        detail=detail,
        context=payload,
        tenant_id=_normalize_text(tenant_id),
        user_email=_normalize_text(user_email),
    )
    return payload


def log_upgrade_event_once(
    session_state: MutableMapping[str, Any],
    event_type: str,
    *,
    event_key: str | None = None,
    prompt_location: str = "",
    prompt_type: str = "",
    current_plan: str = "starter",
    employee_count: Any = 0,
    employee_limit: Any = 0,
    feature_context: str = "",
    tenant_id: str = "",
    user_id: str = "",
    user_email: str = "",
) -> bool:
    payload = build_upgrade_event_payload(
        prompt_location=prompt_location,
        prompt_type=prompt_type,
        current_plan=current_plan,
        employee_count=employee_count,
        employee_limit=employee_limit,
        feature_context=feature_context,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    cache = session_state.get("_upgrade_telemetry_once")
    if not isinstance(cache, dict):
        cache = {}
    once_key = event_key or "|".join(
        [
            str(event_type or "upgrade_event"),
            str(payload.get("prompt_location") or ""),
            str(payload.get("prompt_type") or ""),
            str(payload.get("current_plan") or ""),
            str(payload.get("employee_count") or 0),
            str(payload.get("employee_limit") or 0),
            str(payload.get("feature_context") or ""),
        ]
    )
    if cache.get(once_key):
        return False
    cache[once_key] = True
    session_state["_upgrade_telemetry_once"] = cache
    log_upgrade_event(
        event_type,
        prompt_location=prompt_location,
        prompt_type=prompt_type,
        current_plan=current_plan,
        employee_count=employee_count,
        employee_limit=employee_limit,
        feature_context=feature_context,
        tenant_id=tenant_id,
        user_id=user_id,
        user_email=user_email,
    )
    return True


def log_upgrade_prompt_impression_once(
    session_state: MutableMapping[str, Any],
    *,
    event_key: str | None = None,
    prompt_location: str = "",
    prompt_type: str = "",
    current_plan: str = "starter",
    employee_count: Any = 0,
    employee_limit: Any = 0,
    feature_context: str = "",
    tenant_id: str = "",
    user_id: str = "",
    user_email: str = "",
) -> bool:
    return log_upgrade_event_once(
        session_state,
        "upgrade_prompt_impression",
        event_key=event_key,
        prompt_location=prompt_location,
        prompt_type=prompt_type,
        current_plan=current_plan,
        employee_count=employee_count,
        employee_limit=employee_limit,
        feature_context=feature_context,
        tenant_id=tenant_id,
        user_id=user_id,
        user_email=user_email,
    )