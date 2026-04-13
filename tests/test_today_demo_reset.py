from pages.today import _is_demo_upload_row, _reset_demo_uploads


def test_is_demo_upload_row_requires_active_and_demo_mode(monkeypatch):
    monkeypatch.setattr(
        "services.import_service._decode_jsonish",
        lambda raw: raw if isinstance(raw, dict) else {},
    )

    assert _is_demo_upload_row({"is_active": True, "header_mapping": {"source_mode": "demo"}})
    assert not _is_demo_upload_row({"is_active": False, "header_mapping": {"source_mode": "demo"}})
    assert not _is_demo_upload_row({"is_active": True, "header_mapping": {"source_mode": "real"}})
    assert not _is_demo_upload_row(
        {
            "is_active": True,
            "header_mapping": {
                "source_mode": "demo",
                "undo_applied_at": "2026-04-12",
            },
        }
    )


def test_reset_demo_uploads_rolls_back_only_demo_uploads(monkeypatch):
    uploads = [
        {
            "id": 11,
            "is_active": True,
            "header_mapping": {
                "source_mode": "demo",
                "undo": {
                    "new_row_ids": [101, 102],
                    "previous_rows": [],
                    "touched_keys": [],
                },
            },
        },
        {
            "id": 12,
            "is_active": True,
            "header_mapping": {
                "source_mode": "real",
                "undo": {
                    "new_row_ids": [201],
                    "previous_rows": [],
                    "touched_keys": [],
                },
            },
        },
    ]

    calls = {"deactivate": [], "restore": []}

    monkeypatch.setattr("services.import_service._list_recent_uploads", lambda tenant_id, days=3650: uploads)
    monkeypatch.setattr(
        "services.import_service._decode_jsonish",
        lambda raw: raw if isinstance(raw, dict) else {},
    )

    def _fake_restore(tenant_id, new_row_ids, previous_rows, touched_keys):
        calls["restore"].append((tenant_id, list(new_row_ids), list(previous_rows), list(touched_keys)))
        return 0, len(new_row_ids), len(new_row_ids)

    def _fake_deactivate(tenant_id, upload_id, payload):
        calls["deactivate"].append((tenant_id, upload_id, payload))

    monkeypatch.setattr("services.import_service._restore_uph_snapshot", _fake_restore)
    monkeypatch.setattr("services.import_service._deactivate_upload", _fake_deactivate)

    out = _reset_demo_uploads(tenant_id="tenant-1")

    assert out["demo_uploads_found"] == 1
    assert out["demo_uploads_reset"] == 1
    assert out["verified_deleted_rows"] == 2
    assert out["skipped_without_snapshot"] == 0
    assert len(calls["restore"]) == 1
    assert len(calls["deactivate"]) == 1
    assert calls["deactivate"][0][1] == 11


def test_reset_demo_uploads_skips_demo_without_snapshot(monkeypatch):
    uploads = [
        {
            "id": 41,
            "is_active": True,
            "header_mapping": {
                "source_mode": "demo",
                "undo": {
                    "new_row_ids": [],
                    "previous_rows": [],
                    "touched_keys": [],
                },
            },
        }
    ]

    monkeypatch.setattr("services.import_service._list_recent_uploads", lambda tenant_id, days=3650: uploads)
    monkeypatch.setattr(
        "services.import_service._decode_jsonish",
        lambda raw: raw if isinstance(raw, dict) else {},
    )
    monkeypatch.setattr(
        "services.import_service._restore_uph_snapshot",
        lambda tenant_id, new_row_ids, previous_rows, touched_keys: (_ for _ in ()).throw(AssertionError("should not restore")),
    )
    monkeypatch.setattr(
        "services.import_service._deactivate_upload",
        lambda tenant_id, upload_id, payload: (_ for _ in ()).throw(AssertionError("should not deactivate")),
    )

    out = _reset_demo_uploads(tenant_id="tenant-1")

    assert out["demo_uploads_found"] == 1
    assert out["demo_uploads_reset"] == 0
    assert out["skipped_without_snapshot"] == 1
