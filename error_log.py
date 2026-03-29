"""
error_log.py
------------
Writes pipeline issues to 'dpd_error_log.csv' in the output directory.
Each pipeline run appends to the same file — never overwrites old runs.
"""

import csv
import os
from datetime import datetime


# ── Issue categories (mirrors the VBA colour-coding logic) ──────────────────
CATEGORY_COLOURS = {
    "skipped":            "⚠",
    "invalid date":       "⚠",
    "invalid uph":        "⚠",
    "zero hours":         "⚠",
    "export error":       "✗",
    "send error":         "✗",
    "duplicate":          "~",
    "merged":             "ℹ",
    "missing column":     "✗",
    "mapping":            "✗",
    "info":               "ℹ",
}


def _tenant_suffix() -> str:
    try:
        import streamlit as st
        tid = st.session_state.get("tenant_id", "")
        if tid:
            return f"_{tid}"
    except Exception:
        pass
    return ""


class ErrorLog:
    """Collects issues during a pipeline run and writes them to CSV at the end."""

    def __init__(self, output_dir: str):
        self._records: list[dict] = []
        _sfx = _tenant_suffix()
        self._log_path = os.path.join(output_dir, f"dpd_error_log{_sfx}.csv")

    # ── Public API ──────────────────────────────────────────────────────────

    def log(self, step: str, row_num: int, issue_type: str, detail: str, raw_value: str = ""):
        """Record one issue.  row_num=0 means it's not row-specific."""
        self._records.append({
            "Timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Step":       step,
            "Row #":      row_num if row_num > 0 else "",
            "Issue Type": issue_type,
            "Detail":     detail,
            "Raw Value":  raw_value,
        })

    def count(self) -> int:
        return len(self._records)

    def flush_to_csv(self):
        """Append all buffered records to the log file, then clear the buffer."""
        if not self._records:
            return
        file_exists = os.path.exists(self._log_path)
        try:
            with open(self._log_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["Timestamp", "Step", "Row #", "Issue Type", "Detail", "Raw Value"],
                )
                if not file_exists:
                    writer.writeheader()
                writer.writerows(self._records)
        except IOError as e:
            print(f"[Warning] Could not write error log: {e}")
        finally:
            self._records.clear()

    def print_summary(self):
        """Print a one-line summary after the pipeline finishes."""
        if not self._records:
            return
        total = len(self._records)
        print(f"\n  ⚠  {total} issue(s) logged → {self._log_path}")

    def reset(self):
        """Start fresh for a new pipeline run."""
        self._records.clear()
