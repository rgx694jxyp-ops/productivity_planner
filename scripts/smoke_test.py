#!/usr/bin/env python3
"""Lightweight production smoke tests for critical app invariants.

Run: python3 scripts/smoke_test.py
"""

from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PY = ROOT / "app.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_sidebar_key_routes() -> None:
    """Ensure key-based nav is present and routes are explicit."""
    src = _read(APP_PY)

    required_nav_keys = [
        '("supervisor",',
        '("dashboard",',
        '("import",',
        '("employees",',
        '("productivity",',
        '("email",',
        '("settings",',
    ]
    for token in required_nav_keys:
        assert token in src, f"Missing sidebar nav key token: {token}"

    assert "handlers = {" in src, "Missing route handlers map"
    required_handler_keys = [
        '"supervisor": page_supervisor',
        '"dashboard": page_dashboard',
        '"import": page_import',
        '"employees": page_employees',
        '"productivity": page_productivity',
        '"email": page_email',
        '"settings": page_settings',
    ]
    for token in required_handler_keys:
        assert token in src, f"Missing route handler: {token}"
    assert "handler = handlers.get(page, page_import)" in src, "Missing fallback handler"


def test_uph_batch_sanitization() -> None:
    """Ensure UPH batch writer sanitizes inf/nan before JSON serialization/upsert."""
    # Import with fallback placeholders so module-level config check passes in CI/local.
    os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
    os.environ.setdefault("SUPABASE_KEY", "placeholder-key")

    import importlib
    database = importlib.import_module("database")

    captured: dict[str, list[dict]] = {"rows": []}

    class _FakeTable:
        def upsert(self, rows, on_conflict=None):
            captured["rows"] = rows
            return self

        def execute(self):
            return type("_Resp", (), {"data": []})()

    class _FakeClient:
        def table(self, _name: str):
            return _FakeTable()

    original_get_client = database.get_client
    try:
        database.get_client = lambda: _FakeClient()
        bad_rows = [
            {
                "emp_id": "E1",
                "work_date": "2026-03-01",
                "uph": float("inf"),
                "units": float("nan"),
                "hours_worked": float("-inf"),
                "department": "Packaging",
                "tenant_id": "t1",
            }
        ]
        database.batch_store_uph_history(bad_rows)
    finally:
        database.get_client = original_get_client

    assert captured["rows"], "No rows captured from upsert call"
    row = captured["rows"][0]
    assert math.isfinite(float(row["uph"])), "uph is not finite after sanitization"
    assert math.isfinite(float(row["units"])), "units is not finite after sanitization"
    assert math.isfinite(float(row["hours_worked"])), "hours_worked is not finite after sanitization"


def test_no_replacement_chars_in_core() -> None:
    """Catch accidental encoding artifacts in core files."""
    for rel in ("app.py", "database.py"):
        txt = _read(ROOT / rel)
        assert "�" not in txt, f"Replacement character found in {rel}"


def main() -> None:
    tests = [
        test_sidebar_key_routes,
        test_uph_batch_sanitization,
        test_no_replacement_chars_in_core,
    ]
    for t in tests:
        t()
        print(f"PASS: {t.__name__}")


if __name__ == "__main__":
    main()
