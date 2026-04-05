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
    # ── Post-import confidence summary (shown once after pipeline completes) ──
    if st.session_state.get("_import_complete_summary"):
        _sm = st.session_state["_import_complete_summary"]
        _ic_emp   = _sm.get("emp_count", 0)
        _ic_days  = _sm.get("days", 1)
        _ic_below = _sm.get("below", 0)
        _ic_risks = _sm.get("risks", 0)
        _ic_rank  = _sm.get("ranked", 0)
        _ic_below_line = (
            f'<div class="dpd-import-row"><span class="dpd-import-warn">⚠</span>&nbsp;'
            f'<strong>{_ic_below}</strong> employees below goal &nbsp;·&nbsp; {_ic_risks} high-priority risks</div>'
            if _ic_below > 0 else
            f'<div class="dpd-import-row"><span class="dpd-import-ok">✔</span>&nbsp;All employees on target</div>'
        )
        st.markdown(
            f'<div class="dpd-import-done">'
            f'<div class="dpd-import-done-title">✔ Import complete — you\'re ready</div>'
            f'<div class="dpd-import-row"><span class="dpd-import-ok">✔</span>&nbsp;'
            f'<strong>{_ic_emp}</strong> employees loaded &nbsp;·&nbsp; {_ic_rank} ranked</div>'
            f'<div class="dpd-import-row"><span class="dpd-import-ok">✔</span>&nbsp;'
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

    if st.button("▶  Run pipeline now", type="primary", use_container_width=True):
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
                batch_upsert_employees(list(seen_emps.values()))
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
            try:
                _tenant_id = st.session_state.get("tenant_id", "")
                _dates = sorted({r.get("work_date") for r in uph_batch if r.get("work_date")})
                _date_min = _dates[0] if _dates else ""
                _date_max = _dates[-1] if _dates else ""
                _emp_ids = sorted({r.get("emp_id") for r in uph_batch if r.get("emp_id")})
                _existing_keys = set()
                if _tenant_id and _date_min and _date_max and _emp_ids:
                    _sb = _get_db_client()
                    _res = (
                        _sb.table("uph_history")
                        .select("emp_id, work_date, uph, units, hours_worked")
                        .eq("tenant_id", _tenant_id)
                        .gte("work_date", _date_min)
                        .lte("work_date", _date_max)
                        .in_("emp_id", _emp_ids)
                        .execute()
                    )
                    for _er in (_res.data or []):
                        _existing_keys.add((
                            str(_er.get("emp_id", "")),
                            str(_er.get("work_date", "")),
                            round(float(_er.get("uph") or 0), 4),
                            round(float(_er.get("units") or 0), 4),
                            round(float(_er.get("hours_worked") or 0), 4),
                        ))

                _filtered_batch = []
                for _r in uph_batch:
                    _key = (
                        str(_r.get("emp_id", "")),
                        str(_r.get("work_date", "")),
                        round(float(_r.get("uph") or 0), 4),
                        round(float(_r.get("units") or 0), 4),
                        round(float(_r.get("hours_worked") or 0), 4),
                    )
                    if _key in _existing_keys:
                        _dup_skipped += 1
                        continue
                    _filtered_batch.append(_r)
                uph_batch = _filtered_batch
            except Exception:
                pass

            # Store UPH history synchronously so data is in DB before pipeline completes
            try:
                _bg_tid = st.session_state.get("tenant_id", "")
                if _bg_tid:
                    uph_batch = [{**r, "tenant_id": _bg_tid} for r in uph_batch]
                batch_store_uph_history(uph_batch)
                if _dup_skipped:
                    st.info(f"Skipped {_dup_skipped} duplicate UPH row(s) already in history.")
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


