from app import (
    _bust_cache,
    _cached_employees,
    _cached_targets,
    _get_current_plan,
    _html_mod,
    _log_app_error,
    date,
    datetime,
    diagnose_upload,
    io,
    math,
    pd,
    require_db,
    show_diagnosis,
    show_manual_entry_form,
    st,
    tempfile,
    time,
    traceback,
)
import re
from data_loader import auto_detect as _auto_detect, parse_csv_bytes as _parse_csv
try:
    from pages.common import _normalize_label_text
except Exception:
    def _normalize_label_text(value, max_len: int = 64) -> str:
        s = str(value or "").replace("\x00", " ").strip()
        s = " ".join(s.split())
        s = s.replace("|", " ").replace("<", " ").replace(">", " ")
        s = s.strip(" '\"")
        if len(s) > max_len:
            s = s[: max_len - 3].rstrip() + "..."
        return s or "Unknown"
from pages.employees import _build_archived_productivity


_SUSPICIOUS_NAME_RE = re.compile(r"(<\s*/?\s*script\b|drop\s+table|;--|javascript:)", re.IGNORECASE)


def _sanitize_employee_name(raw_name, emp_id: str = "") -> tuple[str, bool]:
    """Return a cleaned display name and suspicious-input flag."""
    raw = str(raw_name or "")
    suspicious = bool(_SUSPICIOUS_NAME_RE.search(raw))
    cleaned = _normalize_label_text(raw, max_len=64)
    if suspicious:
        fallback = f"Employee {emp_id}".strip() if emp_id else "Employee"
        return _normalize_label_text(fallback, max_len=64), True
    return cleaned, False


def _decode_jsonish(raw_val):
    if isinstance(raw_val, dict):
        return raw_val
    if isinstance(raw_val, str) and raw_val.strip():
        try:
            return json.loads(raw_val)
        except Exception:
            return {}
    return {}


def _restore_uph_snapshot(tenant_id: str, touched_keys: list, previous_rows: list) -> tuple[int, int]:
    """Restore uph_history rows to a previous snapshot for a set of touched keys."""
    from database import get_client as _db_get_client, _tq as _db_tq

    _sb = _db_get_client()
    _tenant_id = str(tenant_id or "")

    _prev_map = {}
    for _r in (previous_rows or []):
        _k = (
            str(_r.get("emp_id", "") or ""),
            str(_r.get("work_date", "") or ""),
            str(_r.get("department", "") or ""),
        )
        _prev_map[_k] = {
            "emp_id": _r.get("emp_id"),
            "work_date": _r.get("work_date"),
            "uph": float(_r.get("uph") or 0),
            "units": float(_r.get("units") or 0),
            "hours_worked": float(_r.get("hours_worked") or 0),
            "department": _r.get("department", ""),
            "tenant_id": _tenant_id,
        }

    restored_rows = 0
    if _prev_map:
        _sb.table("uph_history").upsert(
            list(_prev_map.values()),
            on_conflict="tenant_id,emp_id,work_date,department",
        ).execute()
        restored_rows = len(_prev_map)

    _delete_keys = []
    for _k in (touched_keys or []):
        if isinstance(_k, (list, tuple)) and len(_k) == 3:
            _tk = (str(_k[0]), str(_k[1]), str(_k[2]))
            if _tk not in _prev_map:
                _delete_keys.append(_tk)

    deleted_rows = 0
    for _emp_id, _work_date, _dept in _delete_keys:
        _q = _db_tq(
            _sb.table("uph_history")
            .delete()
            .eq("emp_id", _emp_id)
            .eq("work_date", _work_date)
            .eq("department", _dept)
        )
        if _tenant_id:
            _q = _q.eq("tenant_id", _tenant_id)
        _q.execute()
        deleted_rows += 1

    return restored_rows, deleted_rows


def _list_recent_uploads(days: int = 7) -> list[dict]:
    try:
        from database import get_client as _db_get_client, _tq as _db_tq
        from datetime import timedelta as _td

        _tenant_id = st.session_state.get("tenant_id", "")
        if not _tenant_id:
            return []

        _sb = _db_get_client()
        _since = (datetime.now() - _td(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
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


def _record_upload_event(filename: str, row_count: int, payload: dict):
    try:
        from database import get_client as _db_get_client

        _tenant_id = st.session_state.get("tenant_id", "")
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


def _deactivate_upload(upload_id, payload: dict | None = None) -> None:
    try:
        from database import get_client as _db_get_client, _tq as _db_tq

        _tenant_id = st.session_state.get("tenant_id", "")
        if not _tenant_id:
            return
        _sb = _db_get_client()
        _update_data = {"is_active": False}
        if isinstance(payload, dict):
            _update_data["header_mapping"] = payload
        _db_tq(_sb.table("uploaded_files").update(_update_data).eq("id", upload_id).eq("tenant_id", _tenant_id)).execute()
    except Exception:
        pass

def page_import():
    st.title("📁 Import Data")

    if not require_db(): return

    step = st.session_state.import_step

    # ── Reset button — shown whenever something is in progress ───────────────
    if (step > 1 or st.session_state.get("uploaded_sessions") or
            st.session_state.get("alloc_rows") or st.session_state.pipeline_done):
        if st.button("↺ Start over", key="import_reset", type="secondary"):
            keys_to_clear = [
                "uploaded_sessions", "import_step", "alloc_rows",
                "pipeline_done", "top_performers", "goal_status", "dept_report",
                "dept_trends", "weekly_summary", "history", "mapping",
                "_archived_loaded",
            ]
            for k in keys_to_clear:
                st.session_state.pop(k, None)
            # Clear all au_ / ao_ / snap_ widget keys
            for k in list(st.session_state.keys()):
                if k.startswith(("au_", "ao_", "snap_", "alloc_sel_")):
                    del st.session_state[k]
            st.session_state.import_step = 1
            _bust_cache()
            st.rerun()

    # ── Step indicator ────────────────────────────────────────────────────────
    s1c = "#0F2D52" if step >= 1 else "#C5D4E8"
    s2c = "#2E7D32" if step >= 3 else ("#0F2D52" if step >= 2 else "#C5D4E8")
    st.markdown(f"""
<div style="display:flex;gap:8px;align-items:center;margin-bottom:1.5rem;">
  <div style="background:{s1c};color:#fff;border-radius:50%;width:28px;height:28px;
              display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;">1</div>
  <span style="color:{s1c};font-size:13px;font-weight:500;">Upload</span>
  <span style="color:#C5D4E8;margin:0 4px;">──────</span>
  <div style="background:{s2c};color:#fff;border-radius:50%;width:28px;height:28px;
              display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;">2</div>
  <span style="color:{s2c};font-size:13px;font-weight:500;">Process</span>
</div>""", unsafe_allow_html=True)

    if step == 1:
        _import_step1()
    elif step == 2:
        _import_step2()
    elif step == 3:
        _import_step3()


def _import_step1():
    """Step 1 — upload files or enter lightweight production data manually."""
    st.subheader("Bring in whatever you have")
    st.caption("Upload a CSV or Excel export, or type a few rows in manually. We will help make it usable.")

    _recent_uploads = _list_recent_uploads(days=7)
    with st.expander("This week's uploads", expanded=bool(_recent_uploads)):
        if not _recent_uploads:
            st.caption("No uploads logged in the last 7 days.")
        else:
            for _u in _recent_uploads:
                _uid = _u.get("id")
                _meta = _decode_jsonish(_u.get("header_mapping"))
                _stats = _meta.get("stats", {}) if isinstance(_meta, dict) else {}
                _undo_applied = bool(_meta.get("undo_applied_at")) if isinstance(_meta, dict) else False
                _is_active = bool(_u.get("is_active"))
                _dup = int(_stats.get("duplicate_rows", 0) or 0)
                _ins = int(_stats.get("inserted_rows", 0) or 0)
                _cand = int(_stats.get("candidate_rows", _u.get("row_count", 0)) or 0)
                _exact_dup = bool(_stats.get("exact_duplicate_import"))
                _status = "Undone" if _undo_applied else ("Active" if _is_active else "Inactive")

                st.markdown(
                    f"**{_u.get('filename', 'Upload')}**  "
                    f"({(_u.get('created_at') or '')[:16].replace('T', ' ')})"
                )
                st.caption(
                    f"Status: {_status} · Candidate rows: {_cand} · Inserted: {_ins} · "
                    f"Duplicates: {_dup}{' · Exact duplicate import' if _exact_dup else ''}"
                )

                if _is_active:
                    if st.button("Remove upload and rollback data", key=f"remove_upload_{_uid}"):
                        try:
                            _undo = _meta.get("undo", {}) if isinstance(_meta, dict) else {}
                            _tenant_id = st.session_state.get("tenant_id", "")
                            _restored = 0
                            _deleted = 0
                            if _tenant_id and _undo.get("touched_keys") is not None:
                                _restored, _deleted = _restore_uph_snapshot(
                                    _tenant_id,
                                    _undo.get("touched_keys", []),
                                    _undo.get("previous_rows", []),
                                )

                            if not isinstance(_meta, dict):
                                _meta = {}
                            _meta["undo_applied_at"] = datetime.now().isoformat(timespec="seconds")
                            _meta["undo_result"] = {
                                "restored_rows": int(_restored),
                                "deleted_rows": int(_deleted),
                            }
                            _deactivate_upload(_uid, _meta)

                            _bust_cache()
                            _build_archived_productivity(force=True)
                            st.success("Upload removed and productivity data refreshed.")
                            st.rerun()
                        except Exception as _rm_err:
                            st.error(f"Could not remove upload: {_rm_err}")
                            _log_app_error("import", f"Remove upload failed: {_rm_err}", detail=traceback.format_exc(), severity="error")
                st.divider()

    mode = st.radio(
        "Choose a starting point",
        ["Upload file", "Manual entry"],
        horizontal=True,
        key="import_entry_mode",
    )

    if mode == "Manual entry":
        manual_rows = show_manual_entry_form()
        st.info("Manual entry works even if you only have today's numbers.")
        if manual_rows:
            st.session_state.uploaded_sessions = [{
                "filename": "Manual Entry",
                "rows": manual_rows,
                "headers": ["Date", "EmployeeID", "EmployeeName", "Department", "Units", "HoursWorked"],
                "row_count": len(manual_rows),
                "mapping": {
                    "Date": "Date",
                    "EmployeeID": "EmployeeID",
                    "EmployeeName": "EmployeeName",
                    "Department": "Department",
                    "Shift": "",
                    "UPH": "",
                    "Units": "Units",
                    "HoursWorked": "HoursWorked",
                },
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }]
            st.session_state.submission_plan = None
            st.session_state.split_overrides = {}
            st.session_state.import_step = 3
            st.rerun()
        return

    files = st.file_uploader(
        "Drop your export here or click Browse",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
        key="import_uploader",
    )

    if not files:
        st.info("Upload anything you have. Even partial data is enough to start.")
        return

    _MAX_FILE_MB = 50
    pending = []
    for f in files:
        # ── File size guard ───────────────────────────────────────────
        f.seek(0, 2)
        size_mb = f.tell() / (1024 * 1024)
        f.seek(0)
        if size_mb > _MAX_FILE_MB:
            st.error(f"**{f.name}** is {size_mb:.1f} MB — max allowed is {_MAX_FILE_MB} MB. Split into smaller files.")
            continue

        try:
            raw_bytes = f.read()
        except Exception as _read_err:
            st.error(f"Could not read **{f.name}**: {_read_err}")
            _log_app_error("import", f"File read error ({f.name}): {_read_err}")
            continue

        if f.name.lower().endswith((".xlsx", ".xls")):
            try:
                _df = pd.read_excel(io.BytesIO(raw_bytes))
                _df.columns = [str(c).strip() for c in _df.columns]
                _df = _df.dropna(how="all")
                rows = _df.fillna("").to_dict("records")
                headers = list(_df.columns)
            except Exception as _xlsx_err:
                st.error(f"Could not read **{f.name}** as an Excel file: {_xlsx_err}")
                continue
        else:
            headers, rows = _parse_csv(raw_bytes)
        if not headers:
            st.error(
                f"**{f.name}** could not be parsed as a valid CSV header row. "
                "Make sure row 1 contains column names (e.g., EmployeeID, EmployeeName, Department, UPH/Units/HoursWorked) "
                "and that the file is comma-separated."
            )
            continue
        if not rows:
            st.error(
                f"**{f.name}** has headers but no usable data rows. "
                "Add at least one employee row beneath the header and remove blank trailing lines."
            )
            continue
        pending.append({
            "filename":  f.name,
            "rows":      rows,
            "headers":   headers,
            "row_count": len(rows),
        })
        st.success(f"✓ **{f.name}** — {len(rows):,} rows, {len(headers)} columns")

    if pending:
        diagnosis = diagnose_upload(pending)
        show_diagnosis(diagnosis)
        if diagnosis.get("days_of_data", 0) <= 1:
            st.info("Using today's performance only. No trend pattern yet, but we can still show who needs attention.")
        elif diagnosis.get("days_of_data", 0) < 3:
            st.info("Limited trend confidence. Recommendations will lean more on recent performance than longer patterns.")

        if st.button("Continue →", type="primary", use_container_width=True):
            sessions = [
                {**p, "mapping": {}, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")}
                for p in pending
            ]
            # Auto-detect columns for each file
            all_auto = True
            for s in sessions:
                headers = s.get("headers", list(s.get("rows",[{}])[0].keys()) if s.get("rows") else [])
                auto = _auto_detect(headers)
                has_id   = bool(auto.get("EmployeeID"))
                has_name = bool(auto.get("EmployeeName"))
                has_uph  = bool(auto.get("UPH")) or (bool(auto.get("Units")) and bool(auto.get("HoursWorked")))
                if has_id and has_name and has_uph:
                    s["mapping"] = {
                        "Date":        auto.get("Date", ""),
                        "EmployeeID":  auto.get("EmployeeID", ""),
                        "EmployeeName":auto.get("EmployeeName", ""),
                        "Department":  auto.get("Department", ""),
                        "Shift":       auto.get("Shift", ""),
                        "UPH":         auto.get("UPH", ""),
                        "Units":       auto.get("Units", ""),
                        "HoursWorked": auto.get("HoursWorked", ""),
                    }
                else:
                    all_auto = False

            st.session_state.uploaded_sessions = sessions
            st.session_state.submission_plan  = None
            st.session_state.split_overrides  = {}
            if all_auto:
                # Skip mapping — go straight to pipeline
                st.session_state.import_step = 3
            else:
                st.session_state.import_step = 2
            st.rerun()


def _import_step2():
    """Step 2 — map columns for each file."""
    sessions = st.session_state.uploaded_sessions
    if not sessions:
        st.session_state.import_step = 1
        st.rerun()
        return

    st.subheader("Map your columns")
    st.caption("We've auto-detected the best match for each field. Check them and adjust anything that looks wrong.")

    all_mapped = True

    for idx, s in enumerate(sessions):
        headers = s.get("headers", list(s.get("rows",[{}])[0].keys()) if s.get("rows") else [])
        auto    = _auto_detect(headers)
        options = ["— not in this file —"] + headers

        with st.container():
            _safe_fn = _html_mod.escape(s["filename"])
            st.markdown(
                f'<div style="background:#F0F5FB;border-radius:8px;padding:14px 16px;margin-bottom:8px;">'
                f'<span style="font-size:14px;font-weight:600;color:#0F2D52;">{_safe_fn}</span>'
                f'<span style="font-size:12px;color:#5A7A9C;margin-left:12px;">{s["row_count"]:,} rows</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # ── UPH Source Selection (OUTSIDE form for immediate rerun) ──
            m = s.get("mapping") or {}
            _map_has_uph = bool(m.get("UPH"))
            _map_has_calc = bool(m.get("Units") and m.get("HoursWorked"))
            uph_src_key = f"uph_src_{idx}"
            _default_src = "Already have UPH column" if (_map_has_uph and not _map_has_calc) else "Calculate: Units ÷ Hours"
            saved_src   = st.session_state.get(uph_src_key, _default_src)
            
            # Clear stale values when source changes
            _prev_key = f"uph_src_prev_{idx}"
            _prev_src = st.session_state.get(_prev_key, saved_src)
            if _prev_src != saved_src:
                if "Already" in saved_src:
                    st.session_state.pop(f"fm_{idx}_Units_un", None)
                    st.session_state.pop(f"fm_{idx}_HoursWorked_h", None)
                else:
                    st.session_state.pop(f"fm_{idx}_UPH_u", None)
            st.session_state[_prev_key] = saved_src
            
            uph_src = st.radio(
                "UPH source",
                ["Calculate: Units ÷ Hours", "Already have UPH column"],
                index=1 if "Already" in saved_src else 0,
                key=uph_src_key,
                horizontal=True,
            )

            ca, cb = st.columns(2)

            def _sel(label, field, req, col, extra=""):
                cur = m.get(field) or auto.get(field, "")
                idx2 = options.index(cur) if cur in options else 0
                dot  = "🔴" if req else "⚪"
                v    = col.selectbox(f"{dot} {label}", options, index=idx2,
                                     key=f"fm_{idx}_{field}_{extra}")
                return "" if v.startswith("—") else v

            with ca:
                d_date = _sel("Date (optional — use work date picker if absent)",
                              "Date",         False, ca)
                d_eid  = _sel("Employee ID",  "EmployeeID",   True,  ca)
                d_name = _sel("Employee Name","EmployeeName", True,  ca)
                d_dept = _sel("Department",   "Department",   False, ca)

            with cb:
                d_shift = _sel("Shift",                    "Shift",       False, cb)

                if "Already" in uph_src:
                    st.caption("Using your existing UPH column.")
                    d_uph   = _sel("UPH column",   "UPH",         True,  cb, "u")
                    d_units = ""
                    d_hrs   = ""
                else:
                    st.caption("UPH will be calculated from Units ÷ Hours Worked.")
                    d_uph   = ""
                    d_units = _sel("Units",        "Units",       True,  cb, "un")
                    d_hrs   = _sel("Hours Worked", "HoursWorked", True,  cb, "h")

                # Validation — Date is optional (falls back to work date picker)
                missing = [
                    f for f, v in [
                        ("Employee ID", d_eid),
                        ("Employee Name", d_name),
                    ] if not v
                ]

                if "Already" in uph_src:
                    uph_ok = bool(d_uph)
                    if not uph_ok:
                        uph_msg = "Select your UPH column above."
                    else:
                        uph_msg = ""
                else:
                    uph_ok = bool(d_units and d_hrs)
                    if not d_units and not d_hrs:
                        uph_msg = "Select both Units and Hours Worked columns."
                    elif not d_units:
                        uph_msg = "Select the Units column."
                    elif not d_hrs:
                        uph_msg = "Select the Hours Worked column."
                    else:
                        uph_msg = ""

                can_confirm = not missing and uph_ok

                if missing:
                    st.warning(f"Still needed: {', '.join(missing)}")
                if uph_msg:
                    st.warning(uph_msg)
                # Auto-confirm if all fields detected with no conflicts
                _auto_confirmed = (can_confirm and
                                   not s.get("mapping") and
                                   all(auto.get(f) for f in ["EmployeeID","EmployeeName","Units"]) and
                                   len([v for v in auto.values() if v]) >= 4)
                if _auto_confirmed:
                    sessions[idx]["mapping"] = {
                        "Date": d_date, "EmployeeID": d_eid, "EmployeeName": d_name,
                        "Department": d_dept, "Shift": d_shift,
                        "UPH": d_uph, "Units": d_units, "HoursWorked": d_hrs,
                    }
                    st.session_state.uploaded_sessions = sessions
                    st.success(f"✓ Auto-confirmed: {s['filename']}")
                    st.rerun()

                if can_confirm and not _auto_confirmed:
                    st.info("✓ All fields mapped — ready to confirm.")

                confirmed = st.button(
                    f"Confirm mapping for {s['filename']}",
                    type="primary",
                    use_container_width=True,
                    disabled=_auto_confirmed,
                    key=f"confirm_mapping_{idx}",
                )

                if confirmed:
                    if not can_confirm:
                        st.warning("Fix the issues above before confirming.")
                    else:
                        sessions[idx]["mapping"] = {
                            "Date":        d_date,
                            "EmployeeID":  d_eid,
                            "EmployeeName":d_name,
                            "Department":  d_dept,
                            "Shift":       d_shift,
                            "UPH":         d_uph,
                            "Units":       d_units,
                            "HoursWorked": d_hrs,
                        }
                        st.session_state.uploaded_sessions = sessions
                        st.rerun()

            # Show confirmation tick if mapping saved
            if s.get("mapping") and s["mapping"].get("EmployeeID"):
                st.success(f"✓ Mapping confirmed for {s['filename']}")
            else:
                all_mapped = False

    st.divider()
    col1, col2 = st.columns(2)

    if col1.button("← Back to upload", use_container_width=True):
        st.session_state.import_step = 1
        st.rerun()

    if all_mapped:
        if col2.button("Continue to pipeline →", type="primary", use_container_width=True):
            st.session_state.import_step = 3
            st.rerun()
    else:
        col2.info("Confirm all file mappings above to continue.")


def _import_step3():
    """Step 3 — run the pipeline. Registers employees, calculates UPH, stores history."""
    def _undo_last_import() -> bool:
        _undo = st.session_state.get("_last_import_undo") or {}
        if not _undo:
            st.warning("No import snapshot available to undo.")
            return False

        try:
            _tenant_id = str(_undo.get("tenant_id", "") or "")
            _restore_uph_snapshot(
                _tenant_id,
                _undo.get("touched_keys", []) or [],
                _undo.get("previous_rows", []) or [],
            )

            _upload_id = _undo.get("upload_id")
            if _upload_id:
                _payload = _decode_jsonish(_undo.get("upload_payload") or {})
                if not isinstance(_payload, dict):
                    _payload = {}
                _payload["undo_applied_at"] = datetime.now().isoformat(timespec="seconds")
                _payload["undo_result"] = {"source": "last_import_button"}
                _deactivate_upload(_upload_id, _payload)

            _bust_cache()
            _build_archived_productivity(force=True)
            st.session_state.pop("_last_import_undo", None)
            st.success("Last import was rolled back. UPH history and productivity views were restored.")
            return True
        except Exception as _undo_err:
            st.error(f"Undo failed: {_undo_err}")
            _log_app_error("pipeline", f"Undo import failed: {_undo_err}", detail=traceback.format_exc(), severity="error")
            return False

    # ── Post-import confidence summary (shown once after pipeline completes) ──
    if st.session_state.get("_import_complete_summary"):
        _sm = st.session_state["_import_complete_summary"]
        _ic_emp   = _sm.get("emp_count", 0)
        _ic_days  = _sm.get("days", 1)
        _ic_below = _sm.get("below", 0)
        _ic_risks = _sm.get("risks", 0)
        _ic_rank  = _sm.get("ranked", 0)
        _ic_below_line = (
            f'<div class="dpd-import-row" style="color:#000000;font-size:16px;line-height:1.5;"><span class="dpd-import-warn" style="color:#8a5a00;">⚠</span>&nbsp;'
            f'<strong>{_ic_below}</strong> employees below goal &nbsp;·&nbsp; {_ic_risks} high-priority risks</div>'
            if _ic_below > 0 else
            f'<div class="dpd-import-row" style="color:#000000;font-size:16px;line-height:1.5;"><span class="dpd-import-ok" style="color:#1f6f2a;">✔</span>&nbsp;All employees on target</div>'
        )
        st.markdown(
            f'<div class="dpd-import-done" style="background:#ffffff;border:1px solid #d9e2ef;border-radius:10px;padding:14px 16px;">'
            f'<div class="dpd-import-done-title" style="color:#000000;font-size:20px;font-weight:800;line-height:1.3;">✔ Import complete — you\'re ready</div>'
            f'<div class="dpd-import-row" style="color:#000000;font-size:16px;line-height:1.5;"><span class="dpd-import-ok" style="color:#1f6f2a;">✔</span>&nbsp;'
            f'<strong>{_ic_emp}</strong> employees loaded &nbsp;·&nbsp; {_ic_rank} ranked</div>'
            f'<div class="dpd-import-row" style="color:#000000;font-size:16px;line-height:1.5;"><span class="dpd-import-ok" style="color:#1f6f2a;">✔</span>&nbsp;'
            f'<strong>{_ic_days}</strong> {"day" if _ic_days == 1 else "days"} of data</div>'
            f'{_ic_below_line}'
            f'</div>',
            unsafe_allow_html=True,
        )
        _ic_c1, _ic_c2 = st.columns(2)
        if _ic_c1.button("→ Start your day", type="primary", use_container_width=True, key="ic_start_day"):
            del st.session_state["_import_complete_summary"]
            st.session_state["goto_page"] = "supervisor"
            st.rerun()
        if _ic_c2.button("↺ Import more data", use_container_width=True, key="ic_import_more"):
            del st.session_state["_import_complete_summary"]
            st.session_state.import_step = 1
            st.session_state.uploaded_sessions = []
            st.rerun()
        if st.session_state.get("_last_import_undo"):
            if st.button("↩ Undo last import", type="secondary", use_container_width=True, key="ic_undo_last_import"):
                if _undo_last_import():
                    st.session_state.pop("_import_complete_summary", None)
                    st.rerun()
        return

    sessions = st.session_state.uploaded_sessions
    if not sessions:
        st.session_state.import_step = 1
        st.rerun()
        return

    st.subheader("Run the pipeline")

    # Summary of what's loaded
    total_rows = sum(s["row_count"] for s in sessions)
    st.markdown(
        f'<div style="background:#E8F0F9;border-radius:8px;padding:14px 16px;margin-bottom:1rem;">'
        f'<span style="color:#0F2D52;font-weight:600;">{len(sessions)} file(s) ready</span>'
        f'<span style="color:#5A7A9C;font-size:12px;margin-left:12px;">{total_rows:,} total rows</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    for s in sessions:
        m = s.get("mapping",{})
        st.caption(f"📄 **{s['filename']}** — {s['row_count']:,} rows · mapped to {sum(1 for v in m.values() if v)} fields")

    _mapped_date_fields = [s.get("mapping", {}).get("Date", "") for s in sessions]
    _has_date_col = any(_mapped_date_fields)
    _estimated_days = 0
    if _has_date_col:
        _all_dates = set()
        for s in sessions:
            _date_key = s.get("mapping", {}).get("Date", "")
            if not _date_key:
                continue
            for row in s.get("rows", []):
                _raw = str(row.get(_date_key, "") or "").strip()
                if _raw:
                    _all_dates.add(_raw[:10])
        _estimated_days = len(_all_dates)
    else:
        _estimated_days = 1

    if _estimated_days <= 1:
        st.info("Minimum viable data mode: we will use today's performance only and skip trend language until more days are loaded.")
    elif _estimated_days < 3:
        st.info("Limited trend confidence: enough to guide decisions, but long-run patterns will strengthen after a few more days.")

    st.divider()

    # Check if any session has a Date column mapped
    _has_date_col = any(s.get("mapping",{}).get("Date") for s in sessions)

    if _has_date_col:
        st.info("📅 Date column detected — work dates come from your CSV. No date picker needed.")
        work_date = date.today()   # placeholder only; rows use their own date
    else:
        st.markdown("**Work date for this import**")
        st.caption("Your CSV has no Date column mapped — all rows will be recorded under this date.")
        work_date = st.date_input("Work date", value=date.today(), label_visibility="collapsed")

    def _build_candidate_uph_rows(_sessions, _fallback_date):
        from collections import defaultdict as _dd

        _agg = _dd(lambda: {"units": 0.0, "hours": 0.0, "uphs": []})
        _max_uph = 500.0
        for _sess in _sessions:
            _m = _sess.get("mapping") or {}
            _rows = _sess.get("rows") or []
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
                _row_date = _fallback_date.isoformat()
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
            })
        return _out

    _candidate_preview_rows = _build_candidate_uph_rows(sessions, work_date)
    _preview_dup_count = 0
    _preview_exact_duplicate_import = False
    try:
        _tenant_id = st.session_state.get("tenant_id", "")
        if _tenant_id and _candidate_preview_rows:
            from database import get_client as _db_get_client, _tq as _db_tq
            _emp_rows = _cached_employees() or []
            _emp_code_to_rowid = {
                str(_e.get("emp_id", "")).strip(): str(_e.get("id"))
                for _e in _emp_rows
                if _e.get("id") is not None and str(_e.get("emp_id", "")).strip()
            }

            def _db_emp(_eid):
                _s = str(_eid or "").strip()
                return _emp_code_to_rowid.get(_s, _s)

            _dates = sorted({r.get("work_date") for r in _candidate_preview_rows if r.get("work_date")})
            _emp_ids = sorted({_db_emp(r.get("emp_id")) for r in _candidate_preview_rows if r.get("emp_id")})
            _dmin = _dates[0] if _dates else ""
            _dmax = _dates[-1] if _dates else ""
            _existing_exact = set()
            if _dmin and _dmax and _emp_ids:
                _sb = _db_get_client()
                _res = _db_tq(
                    _sb.table("uph_history")
                    .select("emp_id, work_date, uph, units, hours_worked, department")
                    .eq("tenant_id", _tenant_id)
                    .gte("work_date", _dmin)
                    .lte("work_date", _dmax)
                    .in_("emp_id", _emp_ids)
                ).execute()
                for _er in (_res.data or []):
                    _existing_exact.add((
                        str(_er.get("emp_id", "")),
                        str(_er.get("work_date", "")),
                        str(_er.get("department", "") or ""),
                        round(float(_er.get("uph") or 0), 4),
                        round(float(_er.get("units") or 0), 4),
                        round(float(_er.get("hours_worked") or 0), 4),
                    ))

            for _r in _candidate_preview_rows:
                _k = (
                    str(_db_emp(_r.get("emp_id", ""))),
                    str(_r.get("work_date", "")),
                    str(_r.get("department", "") or ""),
                    round(float(_r.get("uph") or 0), 4),
                    round(float(_r.get("units") or 0), 4),
                    round(float(_r.get("hours_worked") or 0), 4),
                )
                if _k in _existing_exact:
                    _preview_dup_count += 1

            _preview_exact_duplicate_import = (
                len(_candidate_preview_rows) > 0 and
                _preview_dup_count == len(_candidate_preview_rows)
            )
    except Exception:
        pass

    # Preview sample rows with selected mapping before writing to DB.
    _preview_rows = []
    _preview_emp_ids = set()
    _preview_dates = set()
    for _s in sessions:
        _m = _s.get("mapping", {})
        _id_col = _m.get("EmployeeID", "")
        _name_col = _m.get("EmployeeName", "")
        _dept_col = _m.get("Department", "")
        _date_col = _m.get("Date", "")
        _u_col = _m.get("Units", "")
        _h_col = _m.get("HoursWorked", "")
        _uph_col = _m.get("UPH", "")
        for _r in (_s.get("rows") or []):
            _eid = str(_r.get(_id_col, "") if _id_col else "").strip()
            _enm = str(_r.get(_name_col, "") if _name_col else "").strip()
            _dep = str(_r.get(_dept_col, "") if _dept_col else "").strip()
            _d = str(_r.get(_date_col, "") if _date_col else "").strip()
            if _eid:
                _preview_emp_ids.add(_eid)
            if _d:
                _preview_dates.add(_d[:10])
            if len(_preview_rows) < 25:
                _preview_rows.append({
                    "Date": _d[:10] if _d else work_date.isoformat(),
                    "Employee ID": _eid,
                    "Employee Name": _enm,
                    "Department": _dep,
                    "Units": str(_r.get(_u_col, "") if _u_col else "").strip(),
                    "Hours": str(_r.get(_h_col, "") if _h_col else "").strip(),
                    "UPH": str(_r.get(_uph_col, "") if _uph_col else "").strip(),
                })

    _preview_new_count = max(0, len(_candidate_preview_rows) - _preview_dup_count)
    with st.expander("👀 Preview parsed data before import", expanded=True):
        _preview_days = len(_preview_dates) if _preview_dates else 1
        st.caption(
            f"Sample preview of parsed rows. About {_preview_days} day(s) and "
            f"{len(_preview_emp_ids)} unique employee ID(s) detected."
        )
        if _candidate_preview_rows:
            st.markdown(
                f"**Duplicate summary**\n"
                f"File rows selected: **{total_rows:,}**  \n"
                f"History rows derived from file: **{len(_candidate_preview_rows):,}**  \n"
                f"Exact duplicates already in system: **{_preview_dup_count:,}**  \n"
                f"Rows that will be uploaded: **{_preview_new_count:,}**"
            )
            st.caption(
                f"Duplicate check (exact row match against history): "
                f"{_preview_dup_count}/{len(_candidate_preview_rows)} row(s) already exist."
            )
            if _preview_exact_duplicate_import:
                st.warning("All derived rows are duplicates. Nothing new will be uploaded.")
        if _preview_rows:
            st.dataframe(pd.DataFrame(_preview_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No preview rows available from mapped data.")

    _confirm_preview = st.checkbox(
        "I reviewed the preview and want to write this data to history",
        key="confirm_import_preview",
    )

    if st.button("▶  Run pipeline now", type="primary", use_container_width=True, disabled=not _confirm_preview):
        all_rows    = []
        all_mapping = {}
        for s in sessions:
            all_rows.extend(s["rows"])
            if not all_mapping and s.get("mapping"):
                all_mapping = s["mapping"]

        bar = st.progress(0, text="Registering employees…")

        # Register all employees — one batch upsert instead of N individual calls
        id_col    = all_mapping.get("EmployeeID","EmployeeID")
        name_col  = all_mapping.get("EmployeeName","EmployeeName")
        dept_col  = all_mapping.get("Department","Department")
        shift_col = all_mapping.get("Shift","Shift")
        seen_emps = {}
        name_fixed_count = 0
        uph_rejected_count = 0
        neg_value_fixed_count = 0
        max_reasonable_uph = 500.0
        for row in all_rows:
            eid = str(row.get(id_col,"")).strip()
            if eid and eid not in seen_emps:
                _safe_name, _name_flagged = _sanitize_employee_name(row.get(name_col, ""), eid)
                _safe_dept = _normalize_label_text(row.get(dept_col, ""), max_len=40)
                _safe_shift = _normalize_label_text(row.get(shift_col, ""), max_len=30)
                if _name_flagged or _safe_name != str(row.get(name_col, "")).strip():
                    name_fixed_count += 1
                seen_emps[eid] = {
                    "emp_id":     eid,
                    "name":       _safe_name,
                    "department": _safe_dept,
                    "shift":      _safe_shift,
                }
        if seen_emps:
            # Check employee limit before importing
            try:
                from database import can_add_employees, get_employee_count, get_employee_limit
                _el = get_employee_limit()
                if _el != -1:  # not unlimited
                    _existing = get_employee_count()
                    _existing_ids = {
                        str(e.get("emp_id", "")).strip()
                        for e in (_cached_employees() or [])
                        if str(e.get("emp_id", "")).strip()
                    }
                    _new_ids = [eid for eid in seen_emps.keys() if eid not in _existing_ids]
                    _new_unique = len(_new_ids)
                    if _existing + _new_unique > _el and _el > 0:
                        _plan = _get_current_plan()
                        st.error(
                            f"Employee limit reached. Your **{_plan.capitalize()}** plan allows "
                            f"**{_el}** employees and you have **{_existing}**. "
                            f"This import adds **{_new_unique}** new employee(s). "
                            f"Upgrade your plan in Settings → Subscription."
                        )
                        return
            except Exception:
                pass  # don't block import if limit check fails
            try:
                from database import batch_upsert_employees as _batch_upsert_employees
                _batch_upsert_employees(list(seen_emps.values()))
            except Exception as _e:
                st.warning(f"Employee sync warning: {_e} — allocation will continue.")
                _log_app_error("pipeline", f"Employee sync error: {_e}", detail=traceback.format_exc(), severity="warning")
            _bust_cache()

        bar.progress(25, text="Processing rows…")

        # Run productivity pipeline
        try:
            from data_processor import process_data
            from ranker         import rank_employees, build_department_report, calculate_employee_risk
            from trends         import calculate_department_trends, build_weekly_summary, calculate_employee_rolling_average
            from error_log      import ErrorLog
            from goals          import analyse_trends, build_goal_status

            class _PS:
                def get(self, k, d=None): return st.session_state.get(k, d)
                def get_output_dir(self): return tempfile.gettempdir()
                def get_dept_target_uph(self, d):
                    t = _cached_targets().get(d, 0)
                    return float(t) if t else float(st.session_state.get("target_uph",0) or 0)
                def all_mappings(self): return all_mapping

            ps  = _PS()
            log = ErrorLog(tempfile.gettempdir())

            processed = process_data(all_rows, all_mapping, ps, log)

            # User-friendly cleanup pass: normalize employee labels and discard
            # unrealistic/non-finite UPH values before ranking.
            _proc_name_col = all_mapping.get("EmployeeName") or "EmployeeName"
            _proc_id_col = all_mapping.get("EmployeeID") or "EmployeeID"
            _proc_dept_col = all_mapping.get("Department") or "Department"
            _proc_uph_col = all_mapping.get("UPH") or "UPH"
            for _row in processed:
                _eid = str(_row.get(_proc_id_col, "")).strip()
                _raw_name = _row.get(_proc_name_col, "")
                _safe_name, _flagged = _sanitize_employee_name(_raw_name, _eid)
                if _flagged or _safe_name != str(_raw_name).strip():
                    name_fixed_count += 1
                _row[_proc_name_col] = _safe_name
                _row[_proc_dept_col] = _normalize_label_text(_row.get(_proc_dept_col, ""), max_len=40)

                _raw_uph = _row.get(_proc_uph_col, "")
                if str(_raw_uph).strip() != "":
                    try:
                        _uph = float(_raw_uph)
                        if (not math.isfinite(_uph)) or _uph < 0 or _uph > max_reasonable_uph:
                            _row[_proc_uph_col] = ""
                            uph_rejected_count += 1
                        else:
                            _row[_proc_uph_col] = round(_uph, 4)
                    except (ValueError, TypeError):
                        _row[_proc_uph_col] = ""
                        uph_rejected_count += 1

            if name_fixed_count or uph_rejected_count:
                st.warning(
                    "Data cleanup applied for readability: "
                    f"{name_fixed_count} employee label(s) normalized, "
                    f"{uph_rejected_count} invalid UPH value(s) ignored."
                )

            bar.progress(40, text="Preparing import data…")

            existing = st.session_state.history
            existing.extend(processed)
            st.session_state.history = existing

            bar.progress(60, text="Storing UPH history…")

            # Aggregate per employee — handle multiple files with different column names
            # Aggregate per (emp_id, order_number, date) so that:
            # - employees who worked on multiple orders get pre-split rows
            # - employees who worked across multiple dates get per-date rows
            # - if no order/date columns are mapped we fall back to one row per emp
            from collections import defaultdict

            # key = (emp_id, order_number_or_"", date_str)
            combo_agg = defaultdict(lambda: {
                "units": 0.0, "hours": 0.0, "uphs": [], "dept": "", "name": ""
            })

            # Track per (employee, date) for UPH history — one record per day per employee
            emp_date_totals = defaultdict(lambda: {
                "units": 0.0, "hours": 0.0, "uphs": [], "dept": "", "name": ""
            })

            # Determine whether any session has a date column mapped
            has_date_col  = any(s.get("mapping",{}).get("Date")  for s in sessions)

            for sess in sessions:
                s_mapping  = sess.get("mapping") or all_mapping
                s_rows     = sess.get("rows", [])
                s_id_col   = s_mapping.get("EmployeeID",   "EmployeeID")
                s_name_col = s_mapping.get("EmployeeName", "EmployeeName")
                s_dept_col = s_mapping.get("Department",   "Department")
                s_date_col = s_mapping.get("Date",         "")
                s_u_col    = s_mapping.get("Units",        "Units")
                s_h_col    = s_mapping.get("HoursWorked",  "HoursWorked")
                s_uph_col  = s_mapping.get("UPH",          "UPH")

                for row in s_rows:
                    eid = str(row.get(s_id_col, "")).strip()
                    if not eid:
                        continue

                    try:
                        units_val = float(row.get(s_u_col, 0) or 0)
                        if not math.isfinite(units_val):
                            units_val = 0.0
                    except (ValueError, TypeError):
                        units_val = 0.0
                    try:
                        hours_val = float(row.get(s_h_col, 0) or 0)
                        if not math.isfinite(hours_val):
                            hours_val = 0.0
                    except (ValueError, TypeError):
                        hours_val = 0.0
                    if units_val < 0:
                        units_val = 0.0
                        neg_value_fixed_count += 1
                    if hours_val < 0:
                        hours_val = 0.0
                        neg_value_fixed_count += 1
                    raw_uph = row.get(s_uph_col, None)

                    # Date: use mapped column value, fall back to work_date picker
                    row_date = work_date.isoformat()
                    if s_date_col and row.get(s_date_col):
                        raw_d = str(row[s_date_col]).strip()[:10]
                        try:
                            datetime.strptime(raw_d, "%Y-%m-%d")
                            row_date = raw_d
                        except ValueError:
                            pass

                    key = (eid, "", row_date)
                    combo_agg[key]["units"] += units_val
                    combo_agg[key]["hours"] += hours_val
                    _valid_uph_val = None
                    if raw_uph:
                        try:
                            _uph_val = float(raw_uph)
                            if math.isfinite(_uph_val) and 0 <= _uph_val <= max_reasonable_uph:
                                _valid_uph_val = _uph_val
                            else:
                                uph_rejected_count += 1
                        except (ValueError, TypeError):
                            uph_rejected_count += 1
                    if _valid_uph_val is not None:
                        combo_agg[key]["uphs"].append(_valid_uph_val)

                    name_val, _name_flagged = _sanitize_employee_name(row.get(s_name_col, ""), eid)
                    if _name_flagged:
                        name_fixed_count += 1
                    dept_val = _normalize_label_text(row.get(s_dept_col, ""), max_len=40)
                    if name_val:
                        combo_agg[key]["name"]                    = name_val
                        emp_date_totals[(eid, row_date)]["name"]  = name_val
                    if dept_val:
                        combo_agg[key]["dept"]                    = dept_val
                        emp_date_totals[(eid, row_date)]["dept"]  = dept_val

                    emp_date_totals[(eid, row_date)]["units"] += units_val
                    emp_date_totals[(eid, row_date)]["hours"] += hours_val
                    if _valid_uph_val is not None:
                        emp_date_totals[(eid, row_date)]["uphs"].append(_valid_uph_val)

            if neg_value_fixed_count:
                st.warning(f"Adjusted {neg_value_fixed_count} negative unit/hour value(s) to 0.")

            # Build alloc_rows — one entry per (emp, date) combo
            alloc_rows = []
            for (eid, _unused, row_date), agg in combo_agg.items():
                if agg["uphs"]:
                    uph = round(sum(agg["uphs"]) / len(agg["uphs"]), 2)
                elif agg["hours"] > 0:
                    uph = round(agg["units"] / agg["hours"], 2)
                else:
                    uph = 0.0
                alloc_rows.append({
                    "emp_id":    eid,
                    "name":      agg["name"] or eid,
                    "dept":      agg["dept"],
                    "units":     float(round(agg["units"])),
                    "hours":     round(agg["hours"], 2),
                    "uph":       uph,
                    "date":      row_date,
                })
            alloc_rows.sort(key=lambda r: (r.get("dept",""), r.get("name",""), r.get("date","")))

            # Canonical date for the alloc page
            wd_str    = work_date.isoformat()
            csv_dates = sorted({r["date"] for r in alloc_rows if r["date"]})
            canon_date = csv_dates[0] if (has_date_col and csv_dates) else wd_str

            # Resolve any blank departments from the employees table
            _emp_dept_map = {e["emp_id"]: e.get("department","") for e in (_cached_employees() or [])}

            # Store UPH history in background thread so user doesn't wait
            uph_batch = []
            for (eid, uph_date), agg in emp_date_totals.items():
                if agg["uphs"]:
                    uph = round(sum(agg["uphs"]) / len(agg["uphs"]), 2)
                elif agg["hours"] > 0:
                    uph = round(min(agg["units"] / agg["hours"], 9999), 2)
                else:
                    uph = 0.0
                if not math.isfinite(uph):
                    uph = 0.0
                units_total = round(agg["units"])
                hours_total = round(agg["hours"], 2)
                if not math.isfinite(float(units_total)):
                    units_total = 0
                if not math.isfinite(float(hours_total)):
                    hours_total = 0.0
                dept = agg["dept"] or _emp_dept_map.get(eid, "")
                uph_batch.append({
                    "emp_id":       eid,
                    "work_date":    uph_date,
                    "uph":          uph,
                    "units":        units_total,
                    "hours_worked": hours_total,
                    "department":   dept,
                })
            # Avoid inserting exact duplicates when users import the same file again.
            _dup_skipped = 0
            _candidate_count = len(uph_batch)
            _exact_duplicate_import = False
            _undo_previous_rows = []
            _undo_touched_keys = []
            try:
                _tenant_id = st.session_state.get("tenant_id", "")
                _dates = sorted({r.get("work_date") for r in uph_batch if r.get("work_date")})
                _date_min = _dates[0] if _dates else ""
                _date_max = _dates[-1] if _dates else ""
                _emp_rows = _cached_employees() or []
                _emp_code_to_rowid = {
                    str(_e.get("emp_id", "")).strip(): str(_e.get("id"))
                    for _e in _emp_rows
                    if _e.get("id") is not None and str(_e.get("emp_id", "")).strip()
                }

                def _db_emp_key(_eid):
                    _s = str(_eid or "").strip()
                    return _emp_code_to_rowid.get(_s, _s)

                _emp_ids = sorted({_db_emp_key(r.get("emp_id")) for r in uph_batch if r.get("emp_id")})
                _touched = {
                    (
                        _db_emp_key(_r.get("emp_id")),
                        str(_r.get("work_date", "")),
                        str(_r.get("department", "") or ""),
                    )
                    for _r in uph_batch
                }
                _undo_touched_keys = [list(_k) for _k in sorted(_touched)]
                _existing_keys = set()
                if _tenant_id and _date_min and _date_max and _emp_ids:
                    from database import get_client as _db_get_client, _tq as _db_tq
                    _sb = _db_get_client()
                    _res = _db_tq(
                        _sb.table("uph_history")
                        .select("emp_id, work_date, uph, units, hours_worked, department")
                        .eq("tenant_id", _tenant_id)
                        .gte("work_date", _date_min)
                        .lte("work_date", _date_max)
                        .in_("emp_id", _emp_ids)
                    ).execute()
                    for _er in (_res.data or []):
                        _key3 = (
                            str(_er.get("emp_id", "")),
                            str(_er.get("work_date", "")),
                            str(_er.get("department", "") or ""),
                        )
                        if _key3 in _touched:
                            _undo_previous_rows.append({
                                "emp_id": _er.get("emp_id"),
                                "work_date": _er.get("work_date"),
                                "uph": _er.get("uph"),
                                "units": _er.get("units"),
                                "hours_worked": _er.get("hours_worked"),
                                "department": _er.get("department", ""),
                            })
                        _existing_keys.add((
                            str(_er.get("emp_id", "")),
                            str(_er.get("work_date", "")),
                            str(_er.get("department", "") or ""),
                            round(float(_er.get("uph") or 0), 4),
                            round(float(_er.get("units") or 0), 4),
                            round(float(_er.get("hours_worked") or 0), 4),
                        ))

                _filtered_batch = []
                for _r in uph_batch:
                    _key = (
                        str(_db_emp_key(_r.get("emp_id", ""))),
                        str(_r.get("work_date", "")),
                        str(_r.get("department", "") or ""),
                        round(float(_r.get("uph") or 0), 4),
                        round(float(_r.get("units") or 0), 4),
                        round(float(_r.get("hours_worked") or 0), 4),
                    )
                    if _key in _existing_keys:
                        _dup_skipped += 1
                        continue
                    _filtered_batch.append(_r)
                uph_batch = _filtered_batch
                _exact_duplicate_import = (_candidate_count > 0 and _dup_skipped == _candidate_count)
            except Exception:
                pass

            # Store UPH history synchronously so data is in DB before pipeline completes
            try:
                _bg_tid = st.session_state.get("tenant_id", "")
                if _bg_tid:
                    uph_batch = [{**r, "tenant_id": _bg_tid} for r in uph_batch]
                from database import batch_store_uph_history as _batch_store_uph_history
                _batch_store_uph_history(uph_batch)
                if _bg_tid and _undo_touched_keys:
                    _upload_payload = {
                        "files": [s.get("filename", "") for s in sessions],
                        "stats": {
                            "candidate_rows": int(_candidate_count),
                            "inserted_rows": int(len(uph_batch)),
                            "duplicate_rows": int(_dup_skipped),
                            "exact_duplicate_import": bool(_exact_duplicate_import),
                        },
                        "undo": {
                            "tenant_id": _bg_tid,
                            "touched_keys": _undo_touched_keys,
                            "previous_rows": _undo_previous_rows,
                        },
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                    }
                    _upload_filename = ", ".join([s.get("filename", "") for s in sessions if s.get("filename")]).strip() or "Import"
                    _upload_log_id = _record_upload_event(_upload_filename, _candidate_count, _upload_payload)
                    st.session_state["_last_import_undo"] = {
                        "tenant_id": _bg_tid,
                        "touched_keys": _undo_touched_keys,
                        "previous_rows": _undo_previous_rows,
                        "row_count": len(uph_batch),
                        "created_at": time.time(),
                        "upload_id": _upload_log_id,
                        "upload_payload": _upload_payload,
                    }
                if _dup_skipped:
                    _new_count = max(0, _candidate_count - _dup_skipped)
                    if _new_count == 0:
                        st.warning(
                            f"All {_candidate_count} derived row(s) were duplicates. "
                            "No new rows were uploaded."
                        )
                    else:
                        st.info(
                            f"Duplicate check complete: {_dup_skipped} duplicate row(s) skipped, "
                            f"{_new_count} row(s) uploaded."
                        )
            except Exception as _uph_err:
                st.warning(f"UPH history storage warning: {_uph_err}")
                _log_app_error("pipeline", f"UPH history storage failed: {_uph_err}",
                               detail=traceback.format_exc(), severity="warning")

            _bust_cache()

            # Rebuild productivity from full DB (includes all past imports)
            # so that a second import doesn't lose the first import's data.
            bar.progress(90, text="Rebuilding full productivity view…")
            _full_ok = _build_archived_productivity()
            _ranked_count = len(st.session_state.get("top_performers", []))
            if _full_ok:
                st.session_state["_archived_last_refresh_ts"] = time.time()
            if not _full_ok:
                # Fallback path: only compute heavy analytics when archived rebuild fails.
                ranked = rank_employees(existing, all_mapping, ps, log)
                targets = _cached_targets()
                trend_data = analyse_trends(existing, all_mapping, weeks=st.session_state.trend_weeks)
                goal_status = build_goal_status(ranked, targets, trend_data)
                dept_report = build_department_report(ranked, ps, log)
                dept_trends = calculate_department_trends(existing, all_mapping, ps, log)
                weekly = build_weekly_summary(existing, all_mapping, ps, log)
                rolling_avg = calculate_employee_rolling_average(existing, all_mapping, ps, log)
                risk_scores = calculate_employee_risk(existing, all_mapping, ps, log)
                _ranked_count = len(ranked)

                # Fallback: use only current import's data
                st.session_state.update({
                    "top_performers":    ranked,
                    "dept_report":       dept_report,
                    "dept_trends":       dept_trends,
                    "weekly_summary":    weekly,
                    "employee_rolling_avg": rolling_avg,
                    "employee_risk":     risk_scores,
                    "goal_status":       goal_status,
                    "trend_data":        trend_data,
                    "pipeline_done":     True,
                    "_archived_loaded":  False,
                })

            st.session_state.update({
                "mapping":           all_mapping,
                "alloc_rows":        alloc_rows,
                "alloc_date":        canon_date,
                "alloc_has_date":    has_date_col,
            })
            bar.progress(100, text="Done!")
            _unique_emp_count = len({r["emp_id"] for r in alloc_rows})
            _gs_final   = st.session_state.get("goal_status", [])
            _below_final = len([r for r in _gs_final if r.get("goal_status") == "below_goal"])
            _risks_final = len([r for r in _gs_final
                                 if r.get("goal_status") == "below_goal" and r.get("trend") == "down"])
            st.session_state["_import_complete_summary"] = {
                "emp_count": _unique_emp_count,
                "ranked":    _ranked_count,
                "below":     _below_final,
                "risks":     _risks_final,
                "days":      _estimated_days,
            }
            st.rerun()

        except Exception as _pipe_err:
            _tb = traceback.format_exc()
            st.error("Pipeline error:")
            st.code(_tb)
            _log_app_error("pipeline", str(_pipe_err), detail=_tb)

    st.divider()
    col1, col2 = st.columns(2)

    if col1.button("← Back to mapping", use_container_width=True):
        st.session_state.import_step = 2
        st.rerun()

    if st.session_state.pipeline_done and st.session_state.alloc_rows:
        _uc = len({r["emp_id"] for r in st.session_state.alloc_rows})
        _gs = st.session_state.get("goal_status", []) or []
        _below = len([r for r in _gs if r.get("goal_status") == "below_goal"])
        _risks = len([r for r in _gs if r.get("goal_status") == "below_goal" and r.get("trend") == "down"])
        col2.success(
            f"✓ {_uc} employees processed — {_below} below goal, {_risks} high-priority risks detected."
        )

    if st.button("↺ Start fresh import", use_container_width=True):
        st.session_state.uploaded_sessions = []
        st.session_state.import_step       = 1
        st.session_state.alloc_rows        = []
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: EMPLOYEES
# ══════════════════════════════════════════════════════════════════════════════

def _build_coaching_recommendations():
    """Generate smart coaching recommendations based on employee performance data."""
    gs = st.session_state.get("goal_status", [])
    if not gs:
        return []

    recommendations = []
    for r in gs:
        name = r.get("Employee", "")
        dept = r.get("Department", "")
        uph = r.get("Avg UPH")
        target = r.get("Target UPH")
        trend_dir = r.get("Trend", "")
        vs_target = r.get("vs Target")

        if not name:
            continue

        try:
            uph = float(uph) if uph and uph not in ("—", None, "") else None
        except (ValueError, TypeError):
            uph = None
        try:
            target = float(target) if target and target not in ("—", None, "", 0) else None
        except (ValueError, TypeError):
            target = None

        if uph is None:
            continue

        rec = {"name": name, "dept": dept, "uph": uph, "target": target,
               "priority": "low", "actions": [], "status": ""}

        # Determine gap
        gap_pct = 0
        if target and target > 0:
            gap_pct = round(((uph - target) / target) * 100, 1)

        # Rule-based coaching logic
        if target and gap_pct < -20:
            rec["priority"] = "high"
            rec["status"] = f"{gap_pct}% below target"
            rec["actions"].append(f"Schedule one-on-one coaching session — {name} is significantly below the {dept} target of {target} UPH.")
            rec["actions"].append("Review workstation setup and process efficiency for immediate improvements.")
            rec["actions"].append("Consider pairing with a top performer for peer mentoring.")
            if trend_dir and "declining" in str(trend_dir).lower():
                rec["actions"].append("URGENT: Performance is declining. Investigate potential issues (equipment, training, engagement).")
        elif target and gap_pct < -10:
            rec["priority"] = "medium"
            rec["status"] = f"{gap_pct}% below target"
            rec["actions"].append(f"Monitor closely — {name} is moderately below the {target} UPH target.")
            rec["actions"].append("Provide targeted training on efficiency techniques.")
            if trend_dir and "improving" in str(trend_dir).lower():
                rec["actions"].append("Positive sign: trend is improving. Continue current support.")
            else:
                rec["actions"].append("Set a 2-week improvement checkpoint to track progress.")
        elif target and gap_pct < 0:
            rec["priority"] = "low"
            rec["status"] = f"{gap_pct}% below target"
            rec["actions"].append(f"Slightly below target. Encourage {name} and recognize effort.")
            rec["actions"].append("Small adjustments to workflow may close the gap.")
        elif target and gap_pct >= 20:
            rec["priority"] = "star"
            rec["status"] = f"+{gap_pct}% above target"
            rec["actions"].append(f"Top performer! Consider {name} for peer mentor or team lead role.")
            rec["actions"].append("Recognize achievement publicly to boost team morale.")
        elif target and gap_pct >= 0:
            rec["priority"] = "low"
            rec["status"] = f"+{gap_pct}% above target"
            rec["actions"].append("Meeting or exceeding target. Keep up the good work!")
        else:
            rec["status"] = "No target set"
            rec["actions"].append(f"Set a department target for {dept} to enable performance tracking.")

        # Trend-based additions
        if trend_dir and "declining" in str(trend_dir).lower() and rec["priority"] != "high":
            rec["priority"] = "medium" if rec["priority"] == "low" else rec["priority"]
            rec["actions"].append("Note: Performance trend is declining — check in with employee.")

        recommendations.append(rec)

    # Sort: high first, then medium, then low, then star
    priority_order = {"high": 0, "medium": 1, "low": 2, "star": 3}
    recommendations.sort(key=lambda x: priority_order.get(x["priority"], 99))
    return recommendations


