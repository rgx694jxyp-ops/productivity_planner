"""One-time migration for legacy dpd_goals JSON files into tenant_goals.

Usage:
  python scripts/migrate_goals_json_to_db.py
  python scripts/migrate_goals_json_to_db.py --shared-tenant-id <tenant_uuid>

This script migrates:
  - dpd_goals_<tenant_id>.json  -> tenant_goals for that tenant
  - dpd_goals.json              -> tenant_goals for --shared-tenant-id (optional)

It does not delete any files. Review the output, verify tenant_goals in Supabase,
then remove the legacy JSON files manually.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from database import save_goals_db  # noqa: E402


def _normalize_payload(data: dict | None) -> dict:
    data = data or {}
    dept_targets = data.get("dept_targets") or {}
    flagged_employees = data.get("flagged_employees") or {}
    if not isinstance(dept_targets, dict):
        dept_targets = {}
    if not isinstance(flagged_employees, dict):
        flagged_employees = {}
    return {
        "dept_targets": dict(dept_targets),
        "flagged_employees": dict(flagged_employees),
    }


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return _normalize_payload(json.load(fh))


def _migrate_file(path: Path, tenant_id: str) -> bool:
    payload = _load_json(path)
    save_goals_db(payload, tenant_id=tenant_id)
    print(
        f"Migrated {path.name} -> tenant {tenant_id} "
        f"(departments={len(payload['dept_targets'])}, flags={len(payload['flagged_employees'])})"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy goal JSON files into tenant_goals")
    parser.add_argument(
        "--shared-tenant-id",
        default="",
        help="Tenant ID to receive the shared dpd_goals.json payload, if that file exists.",
    )
    args = parser.parse_args()

    migrated = 0
    skipped = 0

    tenant_files = sorted(REPO_ROOT.glob("dpd_goals_*.json"))
    for path in tenant_files:
        tenant_id = path.stem.replace("dpd_goals_", "", 1).strip()
        if not tenant_id:
            print(f"Skipping {path.name}: could not derive tenant ID from filename")
            skipped += 1
            continue
        _migrate_file(path, tenant_id)
        migrated += 1

    shared_path = REPO_ROOT / "dpd_goals.json"
    if shared_path.exists():
        if args.shared_tenant_id.strip():
            _migrate_file(shared_path, args.shared_tenant_id.strip())
            migrated += 1
        else:
            print(
                "Skipping dpd_goals.json: pass --shared-tenant-id <tenant_uuid> "
                "if you want to import the shared legacy file."
            )
            skipped += 1

    print(f"Done. Migrated={migrated} Skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())