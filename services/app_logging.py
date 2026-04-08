"""Lightweight structured application logging for service and auth workflows."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_SENSITIVE_KEY_PARTS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "key",
    "password",
    "refresh_token",
    "secret",
    "session",
    "token",
}

_TEXT_REDACTIONS = [
    (
        re.compile(r"(?i)(access_token|refresh_token|password|secret|api[_-]?key|authorization)\s*[:=]\s*([^\s,;]+)"),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(r"(?i)bearer\s+[A-Za-z0-9\-\._~\+/=]+"),
        "Bearer [REDACTED]",
    ),
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _log_file_path() -> Path:
    path = _repo_root() / "logs" / "dpd_app.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_text(value: Any, *, max_length: int = 500) -> str:
    text = str(value or "").strip()
    for pattern, replacement in _TEXT_REDACTIONS:
        text = pattern.sub(replacement, text)
    if len(text) > max_length:
        return text[: max_length - 3].rstrip() + "..."
    return text


def _should_redact(key: str) -> bool:
    lowered = str(key or "").strip().lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _sanitize_value(value: Any, *, key: str = "") -> Any:
    if key and _should_redact(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _sanitize_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, (str, bytes)):
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        return sanitize_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return sanitize_text(repr(value))


def sanitize_context(context: dict[str, Any] | None) -> dict[str, Any]:
    return _sanitize_value(context or {})


def _write_log(
    level: str,
    event: str,
    message: str,
    *,
    tenant_id: str = "",
    user_email: str = "",
    context: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> None:
    payload = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "level": str(level or "info"),
        "event": str(event or "app"),
        "message": sanitize_text(message),
        "tenant_id": sanitize_text(tenant_id),
        "user_email": sanitize_text(user_email),
        "context": sanitize_context(context),
    }
    if error is not None:
        payload["error_type"] = type(error).__name__
        payload["error"] = sanitize_text(error)

    try:
        with _log_file_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    except Exception:
        try:
            print(f"[{payload['level'].upper()}] [{payload['event']}] {payload['message']}")
        except Exception:
            pass


def log_info(
    event: str,
    message: str,
    *,
    tenant_id: str = "",
    user_email: str = "",
    context: dict[str, Any] | None = None,
) -> None:
    _write_log("info", event, message, tenant_id=tenant_id, user_email=user_email, context=context)


def log_warn(
    event: str,
    message: str,
    *,
    tenant_id: str = "",
    user_email: str = "",
    context: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> None:
    _write_log("warn", event, message, tenant_id=tenant_id, user_email=user_email, context=context, error=error)


def log_error(
    event: str,
    message: str,
    *,
    tenant_id: str = "",
    user_email: str = "",
    context: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> None:
    _write_log("error", event, message, tenant_id=tenant_id, user_email=user_email, context=context, error=error)