"""Commit validated import rows and persist upload metadata."""

from __future__ import annotations

from datetime import datetime

from repositories.import_repo import batch_store_uph_history
from repositories._common import get_client


def persist_import_rows(candidate_rows: list[dict], tenant_id: str) -> int:
    if not candidate_rows:
        return 0
    payload_rows = [{**row, "tenant_id": tenant_id} for row in candidate_rows]
    batch_store_uph_history(payload_rows)
    return len(payload_rows)


def record_upload_event(*, tenant_id: str, filename: str, row_count: int, payload: dict) -> str | None:
    """Write uploaded_files event row; returns upload id if available."""
    if not tenant_id:
        return None

    sb = get_client()
    result = sb.table("uploaded_files").insert(
        {
            "filename": filename,
            "row_count": int(row_count),
            "header_mapping": payload,
            "is_active": True,
            "tenant_id": tenant_id,
        }
    ).execute()
    rows = result.data or []
    return str(rows[0].get("id")) if rows else None


def build_upload_payload(*, fingerprint: str, summary: dict, mapping: dict, source_files: list[str]) -> dict:
    return {
        "data_fingerprint": fingerprint,
        "files": source_files,
        "mapping": mapping,
        "stats": summary,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
