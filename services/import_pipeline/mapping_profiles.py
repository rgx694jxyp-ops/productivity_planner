"""Lightweight reusable mapping profile support for import sessions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from repositories._common import get_client, tenant_query


def _headers_fingerprint(headers: list[str]) -> str:
    canonical = [str(h or "").strip().lower() for h in (headers or []) if str(h or "").strip()]
    canonical.sort()
    raw = json.dumps(canonical, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_recent_mapping_profile(*, tenant_id: str, headers: list[str], days: int = 30) -> dict[str, str]:
    if not tenant_id or not headers:
        return {}

    try:
        fp = _headers_fingerprint(headers)
        sb = get_client()
        result = tenant_query(
            sb.table("uploaded_files")
            .select("header_mapping, created_at")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(50)
        ).execute()

        for row in (result.data or []):
            meta = row.get("header_mapping")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            if not isinstance(meta, dict):
                continue
            profile = meta.get("mapping_profile") or {}
            profile_fp = str(profile.get("headers_fingerprint") or "")
            mapping = profile.get("mapping") if isinstance(profile, dict) else {}
            if profile_fp == fp and isinstance(mapping, dict):
                # Keep only non-empty mapped fields.
                return {k: str(v) for k, v in mapping.items() if str(v or "").strip()}
    except Exception:
        return {}

    return {}


def build_mapping_profile_payload(*, headers: list[str], mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        "headers_fingerprint": _headers_fingerprint(headers),
        "headers": [str(h or "") for h in (headers or [])],
        "mapping": {k: str(v) for k, v in (mapping or {}).items() if str(v or "").strip()},
    }
