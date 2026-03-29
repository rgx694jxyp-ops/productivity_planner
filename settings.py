"""
settings.py
-----------
All user-configurable values.
Storage: Supabase tenant_settings table (DB-backed), with local JSON file as fallback.
"""

import json
import os


# ── The file that stores everything the user can tweak ──────────────────────
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _settings_file() -> str:
    """Return a tenant-specific settings path, falling back to the shared file."""
    try:
        import streamlit as st
        tid = st.session_state.get("tenant_id", "")
        if tid:
            return os.path.join(_BASE_DIR, f"dpd_settings_{tid}.json")
    except Exception:
        pass
    return os.path.join(_BASE_DIR, "dpd_settings.json")

DEFAULTS = {
    # Column mapping: field name -> CSV header the user selected
    "mapping": {
        "Date":         "",
        "Department":   "",
        "EmployeeID":   "",
        "EmployeeName": "",
        "Shift":        "",
        "UPH":          "",
        "Units":        "",
        "HoursWorked":  "",
    },

    # ── Highlighting thresholds ────────────────────────────────────────────
    "primary_kpi":      "UPH",      # UPH | Units | Efficiency
    "target_uph":       0,          # 0 = disabled; set per-dept with "target_uph:DeptName"
    "top_pct":          10,         # top N% highlighted green
    "bot_pct":          10,         # bottom N% highlighted red

    # ── Rolling window ─────────────────────────────────────────────────────
    "chart_months":     12,         # 0 = show all history

    # ── Export toggles ─────────────────────────────────────────────────────
    "export_pdf":       False,
    "export_excel":     True,

    # ── Smart merge ───────────────────────────────────────────────────────
    "smart_merge":      True,       # fill blank history cells from new imports

    # ── Archive ───────────────────────────────────────────────────────────
    "timezone":         "",         # IANA name e.g. "America/Chicago"; "" = server local time
    "max_history_rows": 50000,      # 0 = never archive

    # ── Paths ─────────────────────────────────────────────────────────────
    "default_csv_path": "",         # pre-populate the file picker dialog
    "output_dir":       "",         # where exports are saved; "" = same folder as this file
}


class Settings:
    """Thin wrapper around DB-backed config.  Get/set any key with dot-like access."""

    def __init__(self, tenant_id: str = ""):
        self._tenant_id = tenant_id
        self._data = self._load()

    # ── Public API ──────────────────────────────────────────────────────────

    def get(self, key: str, default=None):
        """Supports 'key' and 'key:subkey' notation (e.g. 'target_uph:Shipping')."""
        if ":" in key:
            base, sub = key.split(":", 1)
            return self._data.get(f"{base}:{sub}", self._data.get(base, default))
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value
        self._save()

    def get_mapping(self, field: str) -> str:
        """Returns the CSV column header mapped to a canonical field name."""
        return self._data.get("mapping", {}).get(field, "")

    def set_mapping(self, field: str, csv_header: str):
        if "mapping" not in self._data:
            self._data["mapping"] = {}
        self._data["mapping"][field] = csv_header
        self._save()

    def get_dept_target_uph(self, dept_name: str) -> float:
        """Per-department target first, then global fallback."""
        dept_key = f"target_uph:{dept_name}"
        if dept_key in self._data:
            try:
                return float(self._data[dept_key])
            except (ValueError, TypeError):
                pass
        try:
            return float(self._data.get("target_uph", 0))
        except (ValueError, TypeError):
            return 0.0

    def get_output_dir(self) -> str:
        """Returns the output directory, defaulting to the project folder."""
        od = self._data.get("output_dir", "")
        return od if od else os.path.dirname(os.path.abspath(__file__))

    def all_mappings(self) -> dict:
        return dict(self._data.get("mapping", {}))

    def show(self):
        """Pretty-print current settings to the terminal."""
        print("\n── Current Settings ─────────────────────────────────────")
        for key, val in self._data.items():
            if key == "mapping":
                print("  mapping:")
                for field, header in val.items():
                    status = f"→ {header}" if header else "(not mapped)"
                    print(f"    {field:20s} {status}")
            else:
                print(f"  {key:30s} {val}")
        print()

    # ── Internal helpers ────────────────────────────────────────────────────

    def _load(self) -> dict:
        # Try database first
        try:
            from database import load_settings_db
            stored = load_settings_db(self._tenant_id)
            if stored:
                merged = dict(DEFAULTS)
                merged.update(stored)
                if "mapping" in DEFAULTS and "mapping" in stored:
                    merged["mapping"] = dict(DEFAULTS["mapping"])
                    merged["mapping"].update(stored.get("mapping", {}))
                return merged
        except Exception:
            pass
        # Fallback to file
        sf = _settings_file()
        if not os.path.exists(sf):
            return dict(DEFAULTS)
        try:
            with open(sf, "r", encoding="utf-8") as f:
                stored = json.load(f)
            merged = dict(DEFAULTS)
            merged.update(stored)
            if "mapping" in DEFAULTS and "mapping" in stored:
                merged["mapping"] = dict(DEFAULTS["mapping"])
                merged["mapping"].update(stored.get("mapping", {}))
            return merged
        except (json.JSONDecodeError, IOError):
            print("[Warning] Settings file is corrupted — using defaults.")
            return dict(DEFAULTS)

    def _save(self):
        # Save to database
        try:
            from database import save_settings_db
            save_settings_db(self._data, self._tenant_id)
        except Exception:
            pass
        # Also save to file as backup
        try:
            with open(_settings_file(), "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except IOError:
            pass
