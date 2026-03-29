"""
history_manager.py
------------------
The memory of the system: a CSV file that accumulates every imported record.

Mirrors the VBA UpdateHistory sub plus the archive logic:
  - Deduplicates by (Department + EmployeeID + EmployeeName + Date)
  - Smart-merges blank fields in existing records when a duplicate appears
  - Archives oldest rows to a separate CSV when the row limit is reached
"""

import os
import csv
import shutil
from datetime import datetime

from settings  import Settings
from error_log import ErrorLog


# ── File names ───────────────────────────────────────────────────────────────

def _tenant_suffix() -> str:
    """Return tenant_id suffix for file isolation."""
    try:
        import streamlit as st
        tid = st.session_state.get("tenant_id", "")
        if tid:
            return f"_{tid}"
    except Exception:
        pass
    return ""


class HistoryManager:

    def __init__(self, output_dir: str, settings: Settings, error_log: ErrorLog):
        self._dir      = output_dir
        self._settings = settings
        self._log      = error_log
        _sfx = _tenant_suffix()
        self._hist_path = os.path.join(output_dir, f"dpd_historical_data{_sfx}.csv")
        self._arch_path = os.path.join(output_dir, f"dpd_historical_archive{_sfx}.csv")

    # ── Public API ───────────────────────────────────────────────────────────

    def update(
        self,
        new_rows: list[dict],
        mapping:  dict[str, str],
    ) -> tuple[int, int]:
        """
        Merges new_rows into the history file.
        Returns (duplicates_removed, new_records_added).
        """
        existing = self._load()
        existing_by_key = self._build_index(existing, mapping)

        added      = 0
        duplicates = 0
        merged     = 0

        final_rows = list(existing)   # start with everything we already had

        for row in new_rows:
            key = self._row_key(row, mapping)

            if key and key in existing_by_key:
                duplicates += 1
                hist_row = existing_by_key[key]
                if self._settings.get("smart_merge"):
                    m = self._smart_merge(hist_row, row)
                    if m:
                        merged += m
                        self._log.log("UpdateHistory", 0, "merged",
                                      f"{m} blank field(s) filled from new import.", key)
            else:
                final_rows.append(row)
                if key:
                    existing_by_key[key] = row
                added += 1

        self._save(final_rows)

        if merged:
            print(f"  ℹ  {merged} blank field(s) filled via smart merge")
        print(f"  ~  {duplicates} duplicate(s) skipped")
        print(f"  ✓  {added} new record(s) added to history")
        print(f"  ℹ  History total: {len(final_rows)} row(s)")

        # Archive if over limit
        self._maybe_archive(final_rows)

        return duplicates, added

    def load_all(self) -> list[dict]:
        """Return every row in the history file as a list of dicts."""
        return self._load()

    def row_count(self) -> int:
        rows = self._load()
        return len(rows)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _load(self) -> list[dict]:
        if not os.path.exists(self._hist_path):
            return []
        try:
            with open(self._hist_path, newline="", encoding="utf-8-sig") as f:
                return list(csv.DictReader(f))
        except (IOError, csv.Error) as e:
            print(f"  [Warning] Could not read history file: {e}")
            return []

    def _save(self, rows: list[dict]):
        if not rows:
            return
        fieldnames = list(rows[0].keys()) if rows else []
        # Make sure Month and Week are always present
        for col in ("Month", "Week"):
            if col not in fieldnames:
                fieldnames.append(col)

        try:
            with open(self._hist_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
        except IOError as e:
            print(f"  [Warning] Could not save history: {e}")

    def _build_index(self, rows: list[dict], mapping: dict[str, str]) -> dict[str, dict]:
        return {
            key: row
            for row in rows
            if (key := self._row_key(row, mapping))
        }

    def _row_key(self, row: dict, mapping: dict[str, str]) -> str:
        """Composite dedup key: dept | employee_id | employee_name | date."""
        parts = [
            str(row.get(mapping.get(f, f), "") or "").strip()
            for f in ("Department", "EmployeeID", "EmployeeName", "Date")
        ]
        key = "|".join(parts)
        return key if any(parts) else ""

    def _smart_merge(self, existing: dict, incoming: dict) -> int:
        """Fill blank cells in existing from incoming.  Returns count of fills."""
        filled = 0
        for col, incoming_val in incoming.items():
            if incoming_val and not existing.get(col):
                existing[col] = incoming_val
                filled += 1
        return filled

    def _maybe_archive(self, rows: list[dict]):
        """Move oldest rows to the archive file if the history exceeds max_history_rows."""
        max_rows = int(self._settings.get("max_history_rows") or 0)
        if max_rows <= 0 or len(rows) <= max_rows:
            return

        to_archive = len(rows) - max_rows
        archive_rows = rows[:to_archive]
        keep_rows    = rows[to_archive:]

        # Append to archive
        archive_exists = os.path.exists(self._arch_path)
        try:
            with open(self._arch_path, "a", newline="", encoding="utf-8") as f:
                if archive_rows:
                    writer = csv.DictWriter(f, fieldnames=list(archive_rows[0].keys()))
                    if not archive_exists:
                        writer.writeheader()
                    writer.writerows(archive_rows)
        except IOError as e:
            print(f"  [Warning] Could not write archive: {e}")
            return

        # Rewrite history with only the kept rows
        self._save(keep_rows)
        self._log.log("ArchiveHistory", 0, "info",
                      f"{to_archive} old row(s) archived to '{self._arch_path}'.", "")
        print(f"  ℹ  {to_archive} old row(s) archived to {ARCHIVE_FILE}")
