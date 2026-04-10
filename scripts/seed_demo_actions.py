"""Push demo actions + action_events into Supabase for one tenant.

Usage
-----
    python scripts/seed_demo_actions.py --tenant-id <uuid>

The script uses SUPABASE_SERVICE_KEY (service role) to bypass RLS so the
inserts reach the database without needing a live user session.  Falls back to
SUPABASE_KEY (anon/configured key) with a warning if the service key is absent.

Set credentials in .streamlit/secrets.toml or as environment variables before
running:

    SUPABASE_URL        = "https://xxx.supabase.co"
    SUPABASE_SERVICE_KEY = "eyJ..."   # service_role key from Supabase settings

Optional flags:
    --dry-run    Print what would be inserted without writing anything
    --clear      Delete existing demo-seeded rows for the tenant first
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIONS_FILE = ROOT / "demo_data" / "demo_actions_seed.json"
EVENTS_FILE = ROOT / "demo_data" / "demo_action_events_seed.json"

# Tag inserted rows so --clear knows which rows to remove
DEMO_SEED_TAG = "demo_seed"


def _get_config(key: str) -> str:
    val = os.environ.get(key, "").strip().strip('"').strip("'")
    if val:
        return val
    # Try reading from .streamlit/secrets.toml (simple key = "value" parse)
    secrets_path = ROOT / ".streamlit" / "secrets.toml"
    if secrets_path.exists():
        for line in secrets_path.read_text().splitlines():
            if line.strip().startswith(key):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    return parts[1].strip().strip('"').strip("'")
    return ""


def _get_client():
    url = _get_config("SUPABASE_URL")
    key = _get_config("SUPABASE_SERVICE_KEY") or _get_config("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.", file=sys.stderr)
        print("  Add them to .streamlit/secrets.toml or export as env vars.", file=sys.stderr)
        sys.exit(1)
    if not _get_config("SUPABASE_SERVICE_KEY"):
        print(
            "WARNING: SUPABASE_SERVICE_KEY not found — falling back to SUPABASE_KEY.\n"
            "         RLS will block inserts unless you are seeding your own tenant.\n"
            "         Use the service_role key from Supabase > Settings > API for demos.",
            file=sys.stderr,
        )
    from supabase import create_client
    return create_client(url, key)


def _load_json(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _clear_existing(sb, tenant_id: str) -> None:
    """Remove previously seeded demo rows for this tenant."""
    print(f"  Clearing existing demo rows for tenant {tenant_id}...")
    # Delete action_events first (FK dependency)
    sb.table("action_events").delete().eq("tenant_id", tenant_id).eq(
        "performed_by", "demo.supervisor@example.com"
    ).execute()
    # Delete actions seeded by the demo user
    sb.table("actions").delete().eq("tenant_id", tenant_id).eq(
        "created_by", "demo.supervisor@example.com"
    ).execute()
    print("  Cleared.")


def _strip_id(row: dict) -> dict:
    """Remove the seed-file id so Supabase can auto-generate the PK."""
    return {k: v for k, v in row.items() if k != "id"}


def seed(tenant_id: str, dry_run: bool = False, clear: bool = False) -> None:
    actions_raw = _load_json(ACTIONS_FILE)
    events_raw = _load_json(EVENTS_FILE)

    sb = None if dry_run else _get_client()

    if not dry_run and clear:
        _clear_existing(sb, tenant_id)

    # ── Phase 1: insert actions ─────────────────────────────────────────────
    # Remap every action's tenant_id to the real tenant and remove the
    # hardcoded seed id so Supabase auto-assigns a real PK.
    seed_id_to_db_id: dict[int, str] = {}

    print(f"\nInserting {len(actions_raw)} actions for tenant {tenant_id}...")
    for action in actions_raw:
        seed_id = action["id"]
        payload = {**_strip_id(action), "tenant_id": tenant_id}
        # Null out empty strings for nullable timestamp fields
        for ts_field in ("resolved_at", "escalated_at"):
            if payload.get(ts_field) in (None, "", "null"):
                payload[ts_field] = None

        if dry_run:
            print(f"  [DRY RUN] Would insert action: seed_id={seed_id} employee={payload.get('employee_id')} status={payload.get('status')}")
            seed_id_to_db_id[seed_id] = f"(dry-run-{seed_id})"
            continue

        result = sb.table("actions").insert(payload).execute()
        if not result.data:
            print(f"  ERROR: insert failed for action seed_id={seed_id}", file=sys.stderr)
            continue
        db_id = str(result.data[0]["id"])
        seed_id_to_db_id[seed_id] = db_id
        print(f"  ✓ action seed_id={seed_id} → db_id={db_id}  ({payload.get('employee_id')} | {payload.get('status')})")

    # ── Phase 2: insert action_events ──────────────────────────────────────
    # Remap both tenant_id and action_id to the real values assigned above.
    print(f"\nInserting {len(events_raw)} action events...")
    skipped = 0
    for event in events_raw:
        seed_action_id = event["action_id"]
        db_action_id = seed_id_to_db_id.get(seed_action_id)
        if not db_action_id:
            print(f"  SKIP: event {event['id']} references unknown action seed_id={seed_action_id}")
            skipped += 1
            continue

        payload = {
            **_strip_id(event),
            "tenant_id": tenant_id,
            "action_id": db_action_id,
        }
        if payload.get("next_follow_up_at") in (None, "", "null"):
            payload["next_follow_up_at"] = None

        if dry_run:
            print(f"  [DRY RUN] Would insert event: type={payload.get('event_type')} action_db_id={db_action_id}")
            continue

        result = sb.table("action_events").insert(payload).execute()
        if not result.data:
            print(f"  ERROR: insert failed for event seed_id={event['id']}", file=sys.stderr)
            continue
        print(f"  ✓ event seed_id={event['id']} → db_id={result.data[0]['id']}  ({payload.get('event_type')})")

    if skipped:
        print(f"\n  {skipped} event(s) skipped due to unmatched action IDs.")

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done. {len(seed_id_to_db_id)} action(s) seeded.")
    if not dry_run:
        print("\nNext steps:")
        print("  1. Open the Import page and upload demo_data/demo_supervisor_history.csv")
        print("  2. Open the Today page — you should see 8 queue items")
        print("  3. Filters: 2 overdue, 2 due today, 2 recognition, 2 repeat no-improvement, 1 resolved")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo actions into Supabase.")
    parser.add_argument("--tenant-id", required=True, help="UUID of the target tenant.")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without writing.")
    parser.add_argument("--clear", action="store_true", help="Delete existing demo rows first.")
    args = parser.parse_args()
    seed(tenant_id=args.tenant_id, dry_run=args.dry_run, clear=args.clear)


if __name__ == "__main__":
    main()
