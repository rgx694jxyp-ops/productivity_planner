"""Service-layer observability helpers without Streamlit/runtime coupling."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def tenant_log_path(base_name: str, tenant_id: str = "") -> str:
    root = _repo_root()
    tid = str(tenant_id or "").strip()
    filename = f"{base_name}_{tid}.log" if tid else f"{base_name}.log"
    return str(root / filename)


def log_app_error(
    category: str,
    message: str,
    *,
    detail: str = "",
    severity: str = "error",
    user_email: str = "",
    tenant_id: str = "",
) -> None:
    """Persist app errors when DB is available; otherwise emit a stderr-safe fallback."""
    try:
        from database import log_error

        log_error(
            category=category,
            message=message,
            detail=detail,
            user_email=str(user_email or ""),
            severity=severity,
            tenant_id=str(tenant_id or ""),
        )
    except Exception:
        print(f"[APP_ERROR] [{severity}] [{category}] {message}")


def log_operational_event(
    event_type: str,
    *,
    status: str = "info",
    detail: str = "",
    context: dict | None = None,
    tenant_id: str = "",
    user_email: str = "",
) -> None:
    """Write JSONL operational events without relying on session state."""
    payload = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event_type": str(event_type or "unknown"),
        "status": str(status or "info"),
        "detail": str(detail or ""),
        "tenant_id": str(tenant_id or ""),
        "user_email": str(user_email or ""),
        "context": context or {},
    }

    try:
        path = tenant_log_path("dpd_ops", tenant_id=str(tenant_id or ""))
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    except Exception:
        pass
