"""
services/import_service.py
--------------------------
Data helpers, DB orchestration, and calculation logic for the import pipeline.
Contains everything that is NOT layout / form rendering / button handling.

Extracted from pages/import_page.py (Step 8 page split).
"""

import hashlib
import json
import math
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

_SUSPICIOUS_NAME_RE = re.compile(
    r"(<\s*/?\s*script\b|drop\s+table|;--|javascript:)", re.IGNORECASE
)


def _db_exec_with_retry(query_builder, retries: int = 6, delay_s: float = 0.5):
    """Execute DB operation with small retry window for transient disconnects."""
    last_err = None
    for attempt in range(max(1, retries)):
        try:
            return query_builder()
        except Exception as exc:
            last_err = exc
            msg = str(exc).lower()
            transient = (
                "server disconnected" in msg
                or "connection reset" in msg
                or "timed out" in msg
                or "timeout" in msg
            )
            if (not transient) or attempt >= retries - 1:
                raise
            time.sleep(delay_s * (attempt + 1))
    if last_err:
        raise last_err


def _normalize_label_text_local(value, max_len: int = 64) -> str:
    """Fallback normaliser — prefer pages.common._normalize_label_text."""
    s = str(value or "").replace("\x00", " ").strip()
    s = " ".join(s.split())
    s = s.replace("|", " ").replace("<", " ").replace(">", " ")
    s = s.strip(" '\"")
    if len(s) > max_len:
        s = s[: max_len - 3].rstrip() + "..."
    return s or "Unknown"


_normalize_label_text = _normalize_label_text_local


# ── Name sanitization ─────────────────────────────────────────────────────────

def _sanitize_employee_name(raw_name, emp_id: str = "") -> tuple[str, bool]:
    """Return a cleaned display name and suspicious-input flag."""
    raw = str(raw_name or "")
    suspicious = bool(_SUSPICIOUS_NAME_RE.search(raw))
    cleaned = _normalize_label_text(raw, max_len=64)
    if suspicious:
        fallback = f"Employee {emp_id}".strip() if emp_id else "Employee"
        return _normalize_label_text(fallback, max_len=64), True
    return cleaned, False


# ── JSON helpers ──────────────────────────────────────────────────────────────

def _decode_jsonish(raw_val):
    if isinstance(raw_val, dict):
        return raw_val
    if isinstance(raw_val, str) and raw_val.strip():
        try:
            return json.loads(raw_val)
        except Exception:
            return {}
    return {}


# ── Employee code maps ────────────────────────────────────────────────────────

def _build_emp_code_maps() -> tuple[dict, dict, dict]:
    """
    Return employee ID maps from a fresh DB read.

    Returns:
      code_to_primary_rowid: {emp_code: preferred_rowid_str}
      code_to_all_rowids:    {emp_code: set(rowid_str, ...)}
      rowid_to_code:         {rowid_str: emp_code}
    """
    try:
        from repositories.employees_repo import get_employees as _db_get_employees

        _rows = _db_get_employees() or []
        _code_to_all = {}
        _rowid_to_code = {}
        for _e in _rows:
            _code = str(_e.get("emp_id", "") or "").strip()
            _rid_raw = _e.get("id")
            if not _code or _rid_raw is None:
                continue
            _rid = str(_rid_raw).strip()
            if not _rid:
                continue
            _rowid_to_code[_rid] = _code
            if _code not in _code_to_all:
                _code_to_all[_code] = set()
            _code_to_all[_code].add(_rid)

        _code_to_primary = {}
        for _code, _rid_set in _code_to_all.items():
            try:
                _code_to_primary[_code] = str(min(int(_x) for _x in _rid_set))
            except Exception:
                _code_to_primary[_code] = sorted(_rid_set)[0]

        return _code_to_primary, _code_to_all, _rowid_to_code
    except Exception:
        return {}, {}, {}


# ── Rollback / undo ───────────────────────────────────────────────────────────

def _restore_uph_snapshot(
    tenant_id: str,
    new_row_ids: list,
    previous_rows: list,
    touched_keys: list | None = None,
) -> tuple[int, int, int]:
    """
    Rollback helper — delete newly inserted rows by PK and restore any overwritten rows.

    Returns (restored_rows, attempted_deletes, verified_deleted).
    verified_deleted is confirmed by a follow-up SELECT — if it equals attempted_deletes
    the rollback is fully confirmed. If it's lower, some rows were already gone (not an error).

    touched_keys is a backwards-compatible fallback for uploads that predate
    new_row_ids. Each key is [emp_id, work_date, department].
    """
    from repositories._common import get_client as _db_get_client

    _sb = _db_get_client()
    _tn = str(tenant_id or "")

    attempted_deletes = 0
    verified_deleted = 0
    if new_row_ids:
        _ids = []
        for _x in new_row_ids:
            try:
                _ids.append(int(_x))
            except (TypeError, ValueError):
                pass
        if _ids:
            attempted_deletes = len(_ids)
            _db_exec_with_retry(
                lambda: _sb.table("uph_history").delete().in_("id", _ids).eq("tenant_id", _tn).execute()
            )
            try:
                _check = _db_exec_with_retry(
                    lambda: _sb.table("uph_history").select("id").in_("id", _ids).eq("tenant_id", _tn).execute()
                )
                _still_present = len(_check.data or [])
                verified_deleted = attempted_deletes - _still_present
            except Exception:
                verified_deleted = attempted_deletes

    if touched_keys:
        _prev_key_set = {
            (
                str(_r.get("emp_id", "") or ""),
                str(_r.get("work_date", "") or ""),
                str(_r.get("department", "") or ""),
            )
            for _r in (previous_rows or [])
        }
        for _k in touched_keys:
            if not (isinstance(_k, (list, tuple)) and len(_k) == 3):
                continue
            _emp_id = str(_k[0] or "")
            _work_date = str(_k[1] or "")
            _dept = str(_k[2] or "")
            if (_emp_id, _work_date, _dept) in _prev_key_set:
                continue
            _pre_chk = _db_exec_with_retry(
                lambda: _sb.table("uph_history").select("id").eq("tenant_id", _tn).eq("emp_id", _emp_id).eq(
                    "work_date", _work_date
                ).eq("department", _dept).limit(1).execute()
            )
            if not (_pre_chk.data or []):
                continue
            attempted_deletes += 1
            _db_exec_with_retry(
                lambda: _sb.table("uph_history").delete().eq("tenant_id", _tn).eq("emp_id", _emp_id).eq(
                    "work_date", _work_date
                ).eq("department", _dept).execute()
            )
            _chk = _db_exec_with_retry(
                lambda: _sb.table("uph_history").select("id").eq("tenant_id", _tn).eq("emp_id", _emp_id).eq(
                    "work_date", _work_date
                ).eq("department", _dept).limit(1).execute()
            )
            if not (_chk.data or []):
                verified_deleted += 1

    restored_rows = 0
    if previous_rows:
        _prev = []
        for _r in previous_rows:
            _prev.append({
                "emp_id": _r.get("emp_id"),
                "work_date": _r.get("work_date"),
                "uph": float(_r.get("uph") or 0),
                "units": float(_r.get("units") or 0),
                "hours_worked": float(_r.get("hours_worked") or 0),
                "department": _r.get("department", ""),
                "tenant_id": _tn,
            })
        _db_exec_with_retry(
            lambda: _sb.table("uph_history").upsert(
                _prev, on_conflict="tenant_id,emp_id,work_date,department"
            ).execute()
        )
        restored_rows = len(_prev)

    return restored_rows, attempted_deletes, verified_deleted


# ── Upload log helpers ────────────────────────────────────────────────────────

def _list_recent_uploads(tenant_id: str, days: int = 7) -> list[dict]:
    try:
        from repositories._common import get_client as _db_get_client, tenant_query as _db_tq
        from services.settings_service import get_tenant_local_now

        _tenant_id = str(tenant_id or "").strip()
        if not _tenant_id:
            return []

        _sb = _db_get_client()
        _since = (get_tenant_local_now(_tenant_id) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        _res = _db_tq(
            _sb.table("uploaded_files")
            .select("id, filename, row_count, header_mapping, is_active, created_at")
            .eq("tenant_id", _tenant_id)
            .gte("created_at", _since)
            .order("created_at", desc=True)
        ).execute()
        return _res.data or []
    except Exception:
        return []


def _record_upload_event(tenant_id: str, filename: str, row_count: int, payload: dict):
    try:
        from repositories._common import get_client as _db_get_client

        _tenant_id = str(tenant_id or "").strip()
        if not _tenant_id:
            return None

        _sb = _db_get_client()
        _res = _sb.table("uploaded_files").insert({
            "filename": filename,
            "row_count": int(row_count),
            "header_mapping": payload,
            "is_active": True,
            "tenant_id": _tenant_id,
        }).execute()
        _data = _res.data or []
        return (_data[0].get("id") if _data else None)
    except Exception:
        return None


def _deactivate_upload(tenant_id: str, upload_id, payload: dict | None = None) -> None:
    try:
        from repositories._common import get_client as _db_get_client, tenant_query as _db_tq

        _tenant_id = str(tenant_id or "").strip()
        if not _tenant_id:
            return
        _sb = _db_get_client()
        _update_data = {"is_active": False}
        if isinstance(payload, dict):
            _update_data["header_mapping"] = payload
        _db_tq(_sb.table("uploaded_files").update(_update_data).eq("id", upload_id).eq("tenant_id", _tenant_id)).execute()
    except Exception:
        pass


def _get_upload_by_id(tenant_id: str, upload_id):
    try:
        from repositories._common import get_client as _db_get_client, tenant_query as _db_tq

        _tenant_id = str(tenant_id or "").strip()
        if not _tenant_id or not upload_id:
            return None
        _sb = _db_get_client()
        _res = _db_tq(
            _sb.table("uploaded_files")
            .select("id, filename, row_count, header_mapping, is_active, created_at")
            .eq("id", upload_id)
            .eq("tenant_id", _tenant_id)
            .limit(1)
        ).execute()
        _rows = _res.data or []
        return _rows[0] if _rows else None
    except Exception:
        return None


# ── New employee estimation ───────────────────────────────────────────────────

def _estimate_new_employees_for_sessions(sessions: list[dict]) -> tuple[list[str], dict[str, str]]:
    """Return (new_employee_ids, id_to_name) inferred from uploaded sessions."""
    from repositories.employees_repo import get_employee_ids as _get_employee_ids
    from data_loader import auto_detect as _auto_detect

    _existing_ids = set(_get_employee_ids() or [])
    _new_ids = set()
    _name_map = {}

    for _s in (sessions or []):
        _rows = _s.get("rows") or []
        _headers = _s.get("headers") or []
        _mapping = _s.get("mapping") or {}
        _auto = _auto_detect(_headers) if _headers else {}

        _id_col = _mapping.get("EmployeeID") or _auto.get("EmployeeID") or "EmployeeID"
        _name_col = _mapping.get("EmployeeName") or _auto.get("EmployeeName") or "EmployeeName"

        for _r in _rows:
            _eid = str(_r.get(_id_col, "") or "").strip()
            if not _eid or _eid in _existing_ids:
                continue
            _new_ids.add(_eid)
            _nm = str(_r.get(_name_col, "") or "").strip()
            if _nm and _eid not in _name_map:
                _name_map[_eid] = _nm

    return sorted(_new_ids), _name_map


# ── Fingerprinting ────────────────────────────────────────────────────────────

def _build_import_fingerprint(rows: list[dict]) -> str:
    """Create a stable fingerprint for derived UPH rows.

    Catches repeat imports of the same dataset even when legacy employee-id
    mappings make DB duplicate checks noisy.
    """
    try:
        _canon = []
        for _r in (rows or []):
            try:
                _uph = round(float(_r.get("uph") or 0), 4)
            except Exception:
                _uph = 0.0
            try:
                _units = round(float(_r.get("units") or 0), 4)
            except Exception:
                _units = 0.0
            try:
                _hours = round(float(_r.get("hours_worked") or 0), 4)
            except Exception:
                _hours = 0.0
            _canon.append([
                str(_r.get("emp_id", "") or "").strip(),
                str(_r.get("work_date", "") or "").strip()[:10],
                _normalize_label_text(_r.get("department", "") or "", max_len=40).strip().lower(),
                _uph,
                _units,
                _hours,
            ])
        _canon.sort()
        _raw = json.dumps(_canon, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(_raw.encode("utf-8")).hexdigest()
    except Exception:
        return ""


def _find_matching_upload_by_fingerprint(tenant_id: str, fingerprint: str, days: int = 3650):
    if not fingerprint:
        return None
    _uploads = _list_recent_uploads(tenant_id=tenant_id, days=days)
    for _u in _uploads:
        _meta = _decode_jsonish(_u.get("header_mapping"))
        if not isinstance(_meta, dict):
            continue
        if _meta.get("undo_applied_at"):
            continue
        _fp = str(_meta.get("data_fingerprint") or _meta.get("fingerprint") or "").strip()
        if _fp and _fp == fingerprint:
            return _u
    return None


# ── UPH row aggregation ───────────────────────────────────────────────────────

def _build_candidate_uph_rows(sessions: list[dict], fallback_date) -> list[dict]:
    """
    Aggregate per-session CSV rows into per-(emp_id, work_date, department) UPH
    records, used for pre-import duplicate detection and preview.
    """
    _agg = defaultdict(lambda: {"units": 0.0, "hours": 0.0, "uphs": [], "files": set()})
    _max_uph = 500.0

    for _sess in sessions:
        _m = _sess.get("mapping") or {}
        _rows = _sess.get("rows") or []
        _filename = str(_sess.get("filename", "") or "").strip()
        _id_col = _m.get("EmployeeID", "EmployeeID")
        _dept_col = _m.get("Department", "Department")
        _date_col = _m.get("Date", "")
        _u_col = _m.get("Units", "Units")
        _h_col = _m.get("HoursWorked", "HoursWorked")
        _uph_col = _m.get("UPH", "UPH")

        for _row in _rows:
            _eid = str(_row.get(_id_col, "") or "").strip()
            if not _eid:
                continue
            _dept = _normalize_label_text(_row.get(_dept_col, ""), max_len=40)
            _row_date = fallback_date.isoformat()
            if _date_col and _row.get(_date_col):
                _raw_d = str(_row.get(_date_col, "") or "").strip()[:10]
                try:
                    datetime.strptime(_raw_d, "%Y-%m-%d")
                    _row_date = _raw_d
                except Exception:
                    pass

            try:
                _units = float(_row.get(_u_col, 0) or 0)
            except Exception:
                _units = 0.0
            try:
                _hours = float(_row.get(_h_col, 0) or 0)
            except Exception:
                _hours = 0.0
            if not math.isfinite(_units) or _units < 0:
                _units = 0.0
            if not math.isfinite(_hours) or _hours < 0:
                _hours = 0.0

            _valid_uph = None
            _raw_uph = _row.get(_uph_col, None)
            if str(_raw_uph or "").strip() != "":
                try:
                    _uph = float(_raw_uph)
                    if math.isfinite(_uph) and 0 <= _uph <= _max_uph:
                        _valid_uph = _uph
                except Exception:
                    pass

            _k = (_eid, _row_date, _dept)
            _agg[_k]["units"] += _units
            _agg[_k]["hours"] += _hours
            if _filename:
                _agg[_k]["files"].add(_filename)
            if _valid_uph is not None:
                _agg[_k]["uphs"].append(_valid_uph)

    _out = []
    for (_eid, _row_date, _dept), _vals in _agg.items():
        if _vals["uphs"]:
            _uph = round(sum(_vals["uphs"]) / len(_vals["uphs"]), 2)
        elif _vals["hours"] > 0:
            _uph = round(_vals["units"] / _vals["hours"], 2)
        else:
            _uph = 0.0
        _out.append({
            "emp_id": _eid,
            "work_date": _row_date,
            "department": _dept,
            "uph": _uph,
            "units": round(_vals["units"]),
            "hours_worked": round(_vals["hours"], 2),
            "source_files": ", ".join(sorted(_vals["files"])),
        })
    return _out
