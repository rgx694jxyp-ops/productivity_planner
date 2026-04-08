"""Service-layer observability helpers without Streamlit/runtime coupling."""

from __future__ import annotations

from pathlib import Path

from services.app_logging import log_error as _log_error
from services.app_logging import log_info as _log_info


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
    """Persist app errors while keeping a file-based fallback for service failures."""
    _log_error(
        category,
        message,
        tenant_id=tenant_id,
        user_email=user_email,
        context={"severity": severity, "detail": detail},
    )
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
        pass


def log_operational_event(
    event_type: str,
    *,
    status: str = "info",
    detail: str = "",
    context: dict | None = None,
    tenant_id: str = "",
    user_email: str = "",
) -> None:
    """Write operational events through the shared structured logger."""
    _log_info(
        event_type,
        detail or event_type,
        tenant_id=tenant_id,
        user_email=user_email,
        context={"status": status, "context": context or {}},
    )
