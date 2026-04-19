from __future__ import annotations

from datetime import date
from typing import Any


def is_demo_upload_row(upload_row: dict[str, Any]) -> bool:
    if not bool(upload_row.get("is_active")):
        return False

    try:
        from services.import_service import _decode_jsonish

        meta = _decode_jsonish(upload_row.get("header_mapping"))
    except Exception:
        meta = {}

    if not isinstance(meta, dict):
        meta = {}

    stats = dict(meta.get("stats") or {})
    source_mode = str(meta.get("source_mode") or stats.get("source_mode") or "").strip().lower()
    if source_mode != "demo":
        return False

    if bool(meta.get("undo_applied_at")):
        return False

    return True


def reset_demo_uploads(*, tenant_id: str) -> dict[str, int]:
    from services.import_service import _decode_jsonish, _deactivate_upload, _list_recent_uploads, _restore_uph_snapshot

    summary = {
        "demo_uploads_found": 0,
        "demo_uploads_reset": 0,
        "restored_rows": 0,
        "verified_deleted_rows": 0,
        "skipped_without_snapshot": 0,
    }

    uploads = list(_list_recent_uploads(tenant_id=tenant_id, days=90) or [])
    for upload in uploads:
        if not is_demo_upload_row(upload):
            continue

        summary["demo_uploads_found"] += 1
        meta = _decode_jsonish(upload.get("header_mapping"))
        if not isinstance(meta, dict):
            meta = {}

        undo = meta.get("undo", {}) if isinstance(meta, dict) else {}
        new_row_ids = list(undo.get("new_row_ids", []) or [])
        previous_rows = list(undo.get("previous_rows", []) or [])
        touched_keys = list(undo.get("touched_keys", []) or [])

        if not new_row_ids and not previous_rows and not touched_keys:
            summary["skipped_without_snapshot"] += 1
            continue

        restored_rows, _attempted_deletes, verified_deleted = _restore_uph_snapshot(
            tenant_id,
            new_row_ids,
            previous_rows,
            touched_keys,
        )
        summary["restored_rows"] += int(restored_rows)
        summary["verified_deleted_rows"] += int(verified_deleted)

        meta["undo_applied_at"] = date.today().isoformat()
        meta["undo_result"] = {
            "source": "demo_reset",
            "restored_rows": int(restored_rows),
            "verified_deleted": int(verified_deleted),
        }
        _deactivate_upload(tenant_id, upload.get("id"), meta)
        summary["demo_uploads_reset"] += 1

    return summary