from core.dependencies import (
    _bust_cache,
    _cached_employees,
    _cached_targets,
    _log_app_error,
    _log_operational_event,
    _show_user_error,
    require_db,
)
from services.plan_service import evaluate_import_limit
from core.runtime import _html_mod, date, datetime, io, math, pd, st, tempfile, time, traceback, init_runtime

init_runtime()
from pages.common import get_user_timezone_now, _normalize_label_text
from ui.components import diagnose_upload, show_diagnosis, show_manual_entry_form
import json
from data_loader import auto_detect as _auto_detect, parse_csv_bytes as _parse_csv
from pages.employees import _build_archived_productivity
from services.import_service import (
    _sanitize_employee_name,
    _decode_jsonish,
    _build_emp_code_maps,
    _restore_uph_snapshot,
    _list_recent_uploads,
    _record_upload_event,
    _estimate_new_employees_for_sessions,
    _deactivate_upload,
    _get_upload_by_id,
    _build_import_fingerprint,
    _find_matching_upload_by_fingerprint,
    _build_candidate_uph_rows,
)
from services.import_pipeline.job_service import (
    complete_job as _complete_import_job,
    create_import_job as _create_import_job,
    mark_stage_completed as _mark_import_stage_completed,
    mark_stage_failed as _mark_import_stage_failed,
    mark_stage_in_progress as _mark_import_stage_in_progress,
    serialize_job as _serialize_import_job,
)
from services.import_pipeline.mapping_profiles import (
    build_mapping_profile_payload as _build_mapping_profile_payload,
    get_recent_mapping_profile as _get_recent_mapping_profile,
)
from services.import_trust_service import build_import_trust_summary
from jobs.entrypoints import run_import_postprocess_job, run_import_preview_job
from services.import_quality_service import (
    ISSUE_HANDLING_CHOICES,
    ISSUE_HANDLING_LABELS,
    build_issue_groups,
    build_latest_import_summary,
    trust_level_from_summary,
)
from ui.traceability_panel import render_traceability_panel
from models.import_quality_models import LatestImportSummary
from services.trend_classification_service import normalize_trend_state
from services.onboarding_service import build_first_import_insight


# ---------------------------------------------------------------------------
# Sample template
# ---------------------------------------------------------------------------

# Minimal realistic CSV that new users can fill in and upload immediately.
_SAMPLE_TEMPLATE_CSV = (
    "Date,EmployeeID,EmployeeName,Department,Units,HoursWorked\n"
    "2026-04-07,1001,Alex Chen,Picking,420,8.0\n"
    "2026-04-07,1002,Jamie Park,Picking,385,7.5\n"
    "2026-04-07,1003,Sam Rivera,Packing,290,8.0\n"
    "2026-04-07,1004,Taylor Moore,Receiving,210,6.0\n"
    "2026-04-07,1005,Jordan Lee,Picking,445,8.0\n"
)


# ---------------------------------------------------------------------------
# First-insight renderer (post-import completion screen)
# ---------------------------------------------------------------------------

def _render_first_import_insight(insight: dict) -> None:
    """Render the trust-first first-insight section on the completion screen."""
    conf_label = str(insight.get("confidence_label") or "Low")
    conf_score = int(insight.get("confidence_score") or 0)
    conf_colors = {"High": "#1f6f2a", "Medium": "#8a5a00", "Low": "#c0392b"}
    conf_color = conf_colors.get(conf_label, "#555")

    st.markdown(
        '<div style="margin-top:14px;margin-bottom:4px;font-size:0.75rem;font-weight:700;'
        'letter-spacing:0.08em;text-transform:uppercase;color:#5d7693;">'
        'Your first look</div>',
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.markdown(
            f'<div style="font-size:0.93rem;line-height:1.45;margin-bottom:6px;">'
            f'<strong>What happened:</strong> {insight["what_happened"]}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="font-size:0.93rem;line-height:1.45;margin-bottom:6px;">'
            f'<strong>Compared to what:</strong> {insight["compared_to_what"]}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="font-size:0.93rem;line-height:1.45;margin-bottom:6px;">'
            f'<strong>Confidence:</strong> '
            f'<span style="color:{conf_color};font-weight:700;">{conf_label}</span>'
            f' ({conf_score}/100) — {insight["confidence_basis"]}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="font-size:0.93rem;line-height:1.45;margin-bottom:6px;">'
            f'<strong>Why shown:</strong> {insight["why_shown"]}</div>',
            unsafe_allow_html=True,
        )
        if insight.get("confidence_note"):
            st.info(insight["confidence_note"])

        top_item = insight.get("top_item")
        if top_item is not None:
            st.divider()
            st.markdown(
                '<div style="font-size:0.83rem;font-weight:700;color:#5d7693;'
                'text-transform:uppercase;letter-spacing:0.06em;">'
                'Highest-priority signal</div>',
                unsafe_allow_html=True,
            )
            tier = str(getattr(top_item, "attention_tier", "") or "")
            tier_colors = {"high": "#c0392b", "medium": "#e67e22", "low": "#7f8c8d"}
            tier_color = tier_colors.get(tier, "#555")
            summary = str(getattr(top_item, "attention_summary", "") or "")
            reasons = list(getattr(top_item, "attention_reasons", []) or [])
            employee_id = str(getattr(top_item, "employee_id", "") or "")
            process_name = str(getattr(top_item, "process_name", "") or "")
            score = int(getattr(top_item, "attention_score", 0) or 0)
            process_label = f" ({process_name})" if process_name and process_name.lower() != "unassigned" else ""
            st.markdown(
                f'<div style="border-left:4px solid {tier_color};padding-left:10px;margin-top:6px;">'
                f'<span style="font-weight:700;">{employee_id}{process_label}</span> — '
                f'<span style="color:{tier_color};font-size:0.88rem;">'
                f'{tier.title()} priority · score {score}/100</span></div>',
                unsafe_allow_html=True,
            )
            if summary:
                st.markdown(
                    f'<div style="font-size:0.9rem;margin-top:4px;">{summary}</div>',
                    unsafe_allow_html=True,
                )
            if reasons:
                with st.expander("Why ranked first", expanded=False):
                    for reason in reasons:
                        st.markdown(f"- {reason}")
        elif insight.get("is_healthy"):
            st.divider()
            st.markdown(
                f'<div style="font-size:0.9rem;color:#1f6f2a;">{insight.get("healthy_message") or "No strong signals yet."}'
                f'</div>',
                unsafe_allow_html=True,
            )


_TRUST_STATUS_LABELS = {
    "valid": "Valid",
    "partial": "Partial",
    "low_confidence": "Low confidence",
    "invalid": "Invalid",
}


def _render_latest_import_summary(summary: LatestImportSummary, *, heading: str) -> None:
    processed = int(summary.rows_processed or 0)
    valid = int(summary.valid_rows or 0)
    warning_rows = int(summary.warning_rows or 0)
    rejected = int(summary.rejected_rows or 0)
    ignored = int(summary.ignored_or_excluded_rows or 0)

    st.markdown(f"**{heading}**")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Rows processed", f"{processed:,}")
    m2.metric("Valid rows", f"{valid:,}")
    m3.metric("Warning rows", f"{warning_rows:,}")
    m4.metric("Rejected rows", f"{rejected:,}")
    m5.metric("Ignored/excluded", f"{ignored:,}")


def _render_data_confidence_panel(trust: dict) -> None:
    level = trust_level_from_summary(trust)
    meanings = {
        "High": "Most rows are usable and today's comparisons are likely reliable.",
        "Moderate": "Some rows have quality issues, so comparisons are usable but should be treated with caution.",
        "Low": "Several issues were found; today's comparisons may change after data cleanup.",
    }
    st.markdown("**Data Confidence**")
    with st.container(border=True):
        st.markdown(f"**{level} confidence**")
        st.caption(meanings.get(level, "Confidence context is still being calculated."))
        st.caption("Data issues can reduce confidence in today’s interpretation, especially trend and comparison sections.")


def _render_import_ready_message(summary: dict) -> None:
    rows_ready = int(summary.get("valid_rows", 0) or summary.get("rows_processed", 0) or 0)
    employees = int(summary.get("emp_count", 0) or 0)
    row_label = "row" if rows_ready == 1 else "rows"
    employee_label = "employee" if employees == 1 else "employees"

    st.markdown(
        f'<div class="dpd-import-done" style="background:#ffffff;border:1px solid #d9e2ef;border-radius:10px;padding:14px 16px;">'
        f'<div class="dpd-import-done-title" style="color:#000000;font-size:20px;font-weight:800;line-height:1.3;">Your data is ready</div>'
        f'<div class="dpd-import-row" style="color:#000000;font-size:16px;line-height:1.5;margin-top:6px;"><strong>{rows_ready:,}</strong> {row_label} across <strong>{employees:,}</strong> {employee_label}</div>'
        f'<div class="dpd-import-row" style="color:#000000;font-size:15px;line-height:1.5;margin-top:8px;">Data looks good</div>'
        f'<div class="dpd-import-row" style="color:#5d7693;font-size:13px;line-height:1.4;margin-top:10px;">You can start reviewing performance now</div>'
        f'<div class="dpd-import-row" style="color:#5d7693;font-size:13px;line-height:1.4;margin-top:4px;">Comparisons will appear after more data is available</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_issue_group_handling(
    *,
    trust: dict,
    row_issues: list[dict],
    preview_rows: list[dict],
    excluded_rows: list[dict],
    state_key: str,
) -> None:
    groups = build_issue_groups(
        trust=trust,
        row_issues=row_issues,
        preview_rows=preview_rows,
        excluded_rows=excluded_rows,
    )
    if not groups:
        return

    st.markdown("**Issue Groups and Handling**")
    st.caption("Choose a lightweight handling path per issue group. This records intent for the current import flow without opening a spreadsheet editor.")

    if state_key not in st.session_state or not isinstance(st.session_state.get(state_key), dict):
        # TODO: Move handling-state persistence to a tenant-scoped repository once policy storage is added.
        st.session_state[state_key] = {}
    handling_state = st.session_state[state_key]

    for group in groups:
        group_key = str(group.key or "")
        selected_choice = str(handling_state.get(group_key) or group.default_choice or "review_details")
        if selected_choice not in ISSUE_HANDLING_CHOICES:
            selected_choice = "review_details"
        with st.container(border=True):
            st.markdown(f"**{group.label}** · {int(group.count or 0):,}")
            st.caption(str(group.effect or ""))
            selected_choice = st.selectbox(
                "Handling choice",
                ISSUE_HANDLING_CHOICES,
                index=ISSUE_HANDLING_CHOICES.index(selected_choice),
                format_func=lambda value: ISSUE_HANDLING_LABELS.get(value, value),
                key=f"{state_key}_{group_key}_choice",
            )
            handling_state[group_key] = selected_choice

            if selected_choice == "map_or_correct":
                st.text_input(
                    "Optional mapping/correction note",
                    value=str(handling_state.get(f"{group_key}_note") or ""),
                    key=f"{state_key}_{group_key}_note",
                    placeholder="Example: normalize process labels to 'Packing'.",
                )
                handling_state[f"{group_key}_note"] = str(st.session_state.get(f"{state_key}_{group_key}_note") or "")

            with st.expander("Review details", expanded=False):
                rows = group.rows or []
                if not rows:
                    st.caption("No row-level details are available for this issue group.")
                else:
                    st.dataframe(pd.DataFrame(rows[:120]), use_container_width=True, hide_index=True)

    with st.expander("View handling choices applied", expanded=False):
        choices = []
        for key, value in handling_state.items():
            if key.endswith("_note"):
                continue
            choices.append(
                {
                    "Issue Group": key.replace("_", " ").title(),
                    "Handling": ISSUE_HANDLING_LABELS.get(str(value), str(value)),
                    "Note": str(handling_state.get(f"{key}_note") or ""),
                }
            )
        if choices:
            st.dataframe(pd.DataFrame(choices), use_container_width=True, hide_index=True)
        else:
            st.caption("No handling choices have been selected yet.")


def _render_import_trust_summary(trust: dict, *, heading: str) -> None:
    _status = str(trust.get("status", "invalid") or "invalid")
    _score = int(trust.get("confidence_score", 0) or 0)
    _accepted = int(trust.get("accepted_rows", 0) or 0)
    _rejected = int(trust.get("rejected_rows", 0) or 0)
    _warnings = int(trust.get("warnings", 0) or 0)
    _duplicates = int(trust.get("duplicates", 0) or 0)
    _missing_required = int(trust.get("missing_required_fields", 0) or 0)
    _inconsistent = int(trust.get("inconsistent_names", 0) or 0)
    _suspicious = int(trust.get("suspicious_values", 0) or 0)

    st.markdown(f"**{heading}**")
    st.caption(
        f"Status: {_TRUST_STATUS_LABELS.get(_status, _status.title())} · "
        f"Confidence score: {_score}/100"
    )
    _m1, _m2, _m3, _m4 = st.columns(4)
    _m1.metric("Accepted rows", f"{_accepted:,}")
    _m2.metric("Rejected rows", f"{_rejected:,}")
    _m3.metric("Warnings", f"{_warnings:,}")
    _m4.metric("Duplicates", f"{_duplicates:,}")
    _d1, _d2, _d3 = st.columns(3)
    _d1.caption(f"Missing required fields: {_missing_required:,}")
    _d2.caption(f"Inconsistent names: {_inconsistent:,}")
    _d3.caption(f"Suspicious values: {_suspicious:,}")


def _render_row_error_summary(issues: list[dict]) -> None:
    if not issues:
        return

    error_rows = [issue for issue in issues if str(issue.get("severity", "error")) == "error"]
    warning_rows = [issue for issue in issues if str(issue.get("severity", "error")) == "warning"]

    st.markdown("**Row-level validation details**")
    c1, c2 = st.columns(2)
    c1.metric("Row errors", f"{len(error_rows):,}")
    c2.metric("Row warnings", f"{len(warning_rows):,}")

    preview = []
    for issue in issues[:80]:
        preview.append(
            {
                "Severity": str(issue.get("severity", "error") or "error").title(),
                "Row": int(issue.get("row_index", 0) or 0),
                "Field": str(issue.get("field", "") or ""),
                "Code": str(issue.get("code", "") or ""),
                "Message": str(issue.get("message", "") or ""),
                "Value": str(issue.get("value", "") or ""),
            }
        )
    if preview:
        st.dataframe(pd.DataFrame(preview), use_container_width=True, hide_index=True)



def page_import():
    st.title("📁 Import Data")
    tenant_id = str(st.session_state.get("tenant_id", "") or "")

    _trace_ctx = st.session_state.get("_drill_traceability_context") or {}
    if _trace_ctx and str(_trace_ctx.get("drill_down_screen", "")) == "import_data_trust":
        render_traceability_panel(_trace_ctx, heading="Signal source context")

    # Keep expander headings readable on themed backgrounds.
    st.markdown(
        """
        <style>
        /* Top-level expanders: black text when collapsed, white when expanded */
        div[data-testid="stExpander"] details:not([open]) > summary p,
        div[data-testid="stExpander"] details:not([open]) > summary span,
        div[data-testid="stExpander"] details:not([open]) > summary * {
            color: #000000 !important;
        }
        div[data-testid="stExpander"] details[open] > summary p,
        div[data-testid="stExpander"] details[open] > summary span,
        div[data-testid="stExpander"] details[open] > summary * {
            color: #ffffff !important;
        }
        div[data-testid="stExpander"] details[open] > summary svg {
            fill: #ffffff !important;
        }
        /* Nested upload-entry expanders: always black */
        div[data-testid="stExpander"] div[data-testid="stExpander"] details summary p,
        div[data-testid="stExpander"] div[data-testid="stExpander"] details summary * {
            color: #000000 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if not require_db(): return

    step = st.session_state.import_step

    # ── Reset button — shown whenever something is in progress ───────────────
    if (step > 1 or st.session_state.get("uploaded_sessions") or
            st.session_state.get("alloc_rows") or st.session_state.get("pipeline_done")):
        if st.button("↺ Start over", key="import_reset", type="secondary"):
            keys_to_clear = [
                "uploaded_sessions", "import_step", "alloc_rows",
                "pipeline_done", "top_performers", "goal_status", "dept_report",
                "dept_trends", "weekly_summary", "history", "mapping",
                "_archived_loaded", "confirm_import_preview",
                "_import_complete_summary", "submission_plan", "split_overrides",
            ]
            for k in keys_to_clear:
                st.session_state.pop(k, None)
            # Clear all au_ / ao_ / snap_ widget keys
            for k in list(st.session_state.keys()):
                if k.startswith(("au_", "ao_", "snap_", "alloc_sel_")):
                    del st.session_state[k]
            # Force a fresh uploader instance so previously selected files disappear.
            st.session_state["import_uploader_nonce"] = int(
                st.session_state.get("import_uploader_nonce", 0) or 0
            ) + 1
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
        _import_step1(tenant_id)
    elif step == 2:
        _import_step2(tenant_id)
    elif step == 3:
        _import_step3(tenant_id)


def _import_step1(tenant_id: str):
    """Step 1 — upload files or enter lightweight production data manually."""
    st.subheader("Bring in whatever you have")
    st.caption("Upload a CSV or Excel export, or type a few rows in manually. We will help make it usable.")

    def _render_recent_uploads_panel():
        _recent_uploads = _list_recent_uploads(st.session_state.get("tenant_id", ""), days=7)
        _recent_uploads_visible = []
        for _u in _recent_uploads:
            _meta = _decode_jsonish(_u.get("header_mapping"))
            _undo_applied = bool(_meta.get("undo_applied_at")) if isinstance(_meta, dict) else False
            if not _undo_applied:
                _recent_uploads_visible.append(_u)

        with st.expander("This week's uploads", expanded=False):
            if not _recent_uploads_visible:
                st.caption("No uploads logged in the last 7 days.")
            else:
                for _u in _recent_uploads_visible:
                    _uid = _u.get("id")
                    _meta = _decode_jsonish(_u.get("header_mapping"))
                    _stats = _meta.get("stats", {}) if isinstance(_meta, dict) else {}
                    _undo_applied = bool(_meta.get("undo_applied_at")) if isinstance(_meta, dict) else False
                    _is_active = bool(_u.get("is_active"))
                    _dup = int(_stats.get("duplicate_rows", 0) or 0)
                    _ins = int(_stats.get("inserted_rows", 0) or 0)
                    _cand = int(_stats.get("candidate_rows", _u.get("row_count", 0)) or 0)
                    _exact_dup = bool(_stats.get("exact_duplicate_import"))
                    _trust_status = str(_stats.get("trust_status", "") or "")
                    _trust_score = int(_stats.get("confidence_score", 0) or 0)
                    _status = "Undone" if _undo_applied else ("Active" if _is_active else "Inactive")

                    _hdr = f"{_u.get('filename', 'Upload')} ({(_u.get('created_at') or '')[:16].replace('T', ' ')})"
                    with st.expander(_hdr, expanded=False):
                        st.caption(
                            f"Status: {_status} · Candidate rows: {_cand} · Inserted: {_ins} · "
                            f"Duplicates: {_dup}{' · Exact duplicate import' if _exact_dup else ''}"
                        )
                        if _trust_status:
                            st.caption(
                                "Data quality: "
                                f"{_TRUST_STATUS_LABELS.get(_trust_status, _trust_status.title())} "
                                f"({_trust_score}/100)"
                            )

                        if _is_active and _ins > 0:
                            if st.button("Remove upload and rollback data", key=f"remove_upload_{_uid}"):
                                try:
                                    _undo = _meta.get("undo", {}) if isinstance(_meta, dict) else {}
                                    _tenant_id = st.session_state.get("tenant_id", "")
                                    _restored = 0
                                    _attempted = 0
                                    _verified = 0
                                    _new_ids = _undo.get("new_row_ids", []) if isinstance(_undo, dict) else []
                                    _previous = _undo.get("previous_rows", []) if isinstance(_undo, dict) else []
                                    _touched = _undo.get("touched_keys", []) if isinstance(_undo, dict) else []
                                    if not _new_ids and not _previous and not _touched:
                                        st.error("This upload has no rollback snapshot — data cannot be removed safely.")
                                        continue
                                    if _tenant_id:
                                        _restored, _attempted, _verified = _restore_uph_snapshot(
                                            _tenant_id,
                                            _new_ids,
                                            _previous,
                                            _touched,
                                        )
                                    else:
                                        st.error("Missing tenant context. Please refresh and try again.")
                                        continue

                                    if not isinstance(_meta, dict):
                                        _meta = {}
                                    _meta["undo_applied_at"] = get_user_timezone_now(tenant_id).isoformat(timespec="seconds")
                                    _meta["undo_result"] = {
                                        "restored_rows": int(_restored),
                                        "attempted_deletes": int(_attempted),
                                        "verified_deleted": int(_verified),
                                    }
                                    _deactivate_upload(st.session_state.get("tenant_id", ""), _uid, _meta)

                                    _bust_cache()
                                    _build_archived_productivity(st.session_state, force=True)
                                    if _verified == _attempted:
                                        st.success(
                                            f"✅ Rollback confirmed. Deleted {_verified}/{_attempted} row(s) from history. "
                                            f"Restored {_restored} previous row(s)."
                                        )
                                    else:
                                        st.warning(
                                            f"Rollback partial: deleted {_verified}/{_attempted} row(s) "
                                            f"({_attempted - _verified} already missing). Restored {_restored} previous row(s)."
                                        )
                                    st.rerun()
                                except Exception as _rm_err:
                                    _show_user_error(
                                        "Could not remove this upload right now.",
                                        next_steps="Please retry in a few seconds. If it keeps failing, contact support.",
                                        technical_detail=traceback.format_exc(),
                                        category="import",
                                    )
                                    _log_app_error("import", f"Remove upload failed: {_rm_err}", detail=traceback.format_exc(), severity="error")
                        elif _is_active and _ins == 0:
                            st.caption("No rollback needed: this upload inserted 0 new rows (all duplicates).")

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
                "timestamp": get_user_timezone_now(tenant_id).strftime("%Y-%m-%d %H:%M"),
            }]
            st.session_state.submission_plan = None
            st.session_state.split_overrides = {}
            st.session_state.import_step = 3
            st.rerun()
        st.divider()
        _render_recent_uploads_panel()
        return

    _uploader_key = f"import_uploader_{int(st.session_state.get('import_uploader_nonce', 0) or 0)}"
    files = st.file_uploader(
        "Drop your export here or click Browse",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
        key=_uploader_key,
    )

    if not files:
        st.info("Upload anything you have. Even partial data is enough to start.")
        with st.expander("Don't have a file ready? Download a sample template", expanded=False):
            st.caption(
                "The template has six columns: **Date**, **EmployeeID**, **EmployeeName**, "
                "**Department**, **Units**, and **HoursWorked**. Fill in your team's numbers "
                "and upload the file to get your first interpreted summary."
            )
            st.markdown(
                "| Date | EmployeeID | EmployeeName | Department | Units | HoursWorked |\n"
                "|---|---|---|---|---|---|\n"
                "| 2026-04-07 | 1001 | Alex Chen | Picking | 420 | 8.0 |\n"
                "| 2026-04-07 | 1002 | Jamie Park | Picking | 385 | 7.5 |\n"
                "| ... | ... | ... | ... | ... | ... |"
            )
            st.download_button(
                label="Download sample_template.csv",
                data=_SAMPLE_TEMPLATE_CSV.encode("utf-8"),
                file_name="sample_template.csv",
                mime="text/csv",
                use_container_width=True,
                key="download_sample_template",
            )
        st.divider()
        _render_recent_uploads_panel()
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
            _show_user_error(
                f"Could not read {f.name}.",
                next_steps="Confirm the file is not open elsewhere and try uploading again.",
                technical_detail=str(_read_err),
                category="import",
            )
            _log_app_error("import", f"File read error ({f.name}): {_read_err}")
            _log_operational_event(
                "import_failure",
                status="error",
                tenant_id=tenant_id,
                detail="File read error",
                context={"filename": str(getattr(f, "name", "")), "error": str(_read_err)},
            )
            continue

        if f.name.lower().endswith((".xlsx", ".xls")):
            try:
                _df = pd.read_excel(io.BytesIO(raw_bytes))
                _df.columns = [str(c).strip() for c in _df.columns]
                _df = _df.dropna(how="all")
                rows = _df.fillna("").to_dict("records")
                headers = list(_df.columns)
            except Exception as _xlsx_err:
                _show_user_error(
                    f"Could not parse {f.name} as an Excel file.",
                    next_steps="Re-save the file as .xlsx or export as CSV, then upload again.",
                    technical_detail=str(_xlsx_err),
                    category="import",
                )
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
                {**p, "mapping": {}, "timestamp": get_user_timezone_now(tenant_id).strftime("%Y-%m-%d %H:%M")}
                for p in pending
            ]
            # Auto-detect columns for each file
            all_auto = True
            for s in sessions:
                headers = s.get("headers", list(s.get("rows",[{}])[0].keys()) if s.get("rows") else [])
                auto = _auto_detect(headers)
                profile = _get_recent_mapping_profile(
                    tenant_id=tenant_id,
                    headers=headers,
                )

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
                elif profile and profile.get("EmployeeID") and profile.get("EmployeeName") and (
                    profile.get("UPH") or (profile.get("Units") and profile.get("HoursWorked"))
                ):
                    s["mapping"] = {
                        "Date":        profile.get("Date", ""),
                        "EmployeeID":  profile.get("EmployeeID", ""),
                        "EmployeeName":profile.get("EmployeeName", ""),
                        "Department":  profile.get("Department", ""),
                        "Shift":       profile.get("Shift", ""),
                        "UPH":         profile.get("UPH", ""),
                        "Units":       profile.get("Units", ""),
                        "HoursWorked": profile.get("HoursWorked", ""),
                    }
                else:
                    all_auto = False

            # Early employee-limit check right after file selection.
            try:
                from database import get_employee_count
                _existing = get_employee_count()
                _new_ids, _name_map = _estimate_new_employees_for_sessions(sessions)
                _limit_check = evaluate_import_limit(
                    st.session_state.get("tenant_id", ""),
                    current_count=_existing,
                    new_unique_count=len(_new_ids),
                )
                _limit = int(_limit_check.get("employee_limit", 0) or 0)
                if not _limit_check.get("allowed", True) and _limit not in (-1, 0):
                    _slots_left = max(0, int(_limit_check.get("slots_left", 0) or 0))
                    _overflow_ids = _new_ids[_slots_left:]
                    _overflow_names = [
                        f"{_name_map.get(_eid, _eid)} ({_eid})"
                        for _eid in _overflow_ids[:25]
                    ]
                    st.error(
                        f"Employee limit reached before import. Plan limit: {_limit}, "
                        f"current employees: {_existing}, new employees in file: {len(_new_ids)}."
                    )
                    if _overflow_names:
                        st.caption("Employees over your limit:")
                        st.code("\n".join(_overflow_names))
                    st.info("Upgrade your plan in Settings → Billing or reduce the file employee list.")
                    return
            except Exception:
                pass

            st.session_state.uploaded_sessions = sessions
            st.session_state.submission_plan  = None
            st.session_state.split_overrides  = {}
            if all_auto:
                # Skip mapping — go straight to pipeline
                st.session_state.import_step = 3
            else:
                st.session_state.import_step = 2
            st.rerun()

    st.divider()
    _render_recent_uploads_panel()


def _import_step2(tenant_id: str):
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
            
            st.markdown("**UPH source** — How to calculate units per hour")
            st.caption("Most warehouses track units picked/packed and hours worked. DPD will divide them for performance metrics.")
            uph_src = st.radio(
                "",
                ["Calculate: Units ÷ Hours", "Already have UPH column"],
                index=1 if "Already" in saved_src else 0,
                key=uph_src_key,
                horizontal=True,
                label_visibility="collapsed",
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


def _import_step3(tenant_id: str):
    """Step 3 — run the pipeline. Registers employees, calculates UPH, stores history."""
    def _undo_last_import() -> bool:
        _undo = st.session_state.get("_last_import_undo") or {}
        if not _undo:
            st.warning("No import snapshot available to undo.")
            return False

        try:
            _upload_id = _undo.get("upload_id")
            _tenant_id = str(_undo.get("tenant_id", "") or st.session_state.get("tenant_id", "") or "")
            _payload = {}

            if _upload_id:
                _upload_row = _get_upload_by_id(_tenant_id, _upload_id)
                _payload = _decode_jsonish((_upload_row or {}).get("header_mapping")) if _upload_row else {}

            _undo_data = _payload.get("undo", {}) if isinstance(_payload, dict) else {}
            _new_ids = _undo_data.get("new_row_ids", []) or []
            _previous = _undo_data.get("previous_rows", []) or []
            _touched = _undo_data.get("touched_keys", []) or []
            if not _new_ids and not _previous and not _touched:
                st.error("No rollback snapshot found for this import — nothing was changed.")
                return False
            _restored, _attempted, _verified = _restore_uph_snapshot(
                _tenant_id,
                _new_ids,
                _previous,
                _touched,
            )

            if _upload_id:
                if not isinstance(_payload, dict):
                    _payload = {}
                _payload["undo_applied_at"] = get_user_timezone_now(tenant_id).isoformat(timespec="seconds")
                _payload["undo_result"] = {
                    "source": "last_import_button",
                    "restored_rows": int(_restored),
                    "attempted_deletes": int(_attempted),
                    "verified_deleted": int(_verified),
                }
                _deactivate_upload(_tenant_id, _upload_id, _payload)

            _bust_cache()
            st.session_state["_archived_loaded"] = False
            st.session_state["pipeline_done"] = False
            st.session_state.import_step = 1
            st.session_state.uploaded_sessions = []
            st.session_state.pop("_last_import_undo", None)
            st.session_state.pop("_import_complete_summary", None)
            if _verified == _attempted:
                st.success(
                    f"✅ Rollback confirmed. Deleted {_verified}/{_attempted} row(s) from history. "
                    f"Restored {_restored} previous row(s)."
                )
            else:
                st.warning(
                    f"Rollback partial: deleted {_verified}/{_attempted} row(s) "
                    f"({_attempted - _verified} already missing). Restored {_restored} previous row(s)."
                )
            return True
        except Exception as _undo_err:
            st.error(f"Undo failed: {_undo_err}")
            _log_app_error("pipeline", f"Undo import failed: {_undo_err}", detail=traceback.format_exc(), severity="error")
            return False

    # ── Post-import confidence summary (shown once after pipeline completes) ──
    if st.session_state.get("_import_complete_summary"):
        _sm = st.session_state["_import_complete_summary"]
        _ic_below = _sm.get("below", 0)
        _ic_risks = _sm.get("risks", 0)
        _ic_trust = _sm.get("trust") or {}
        _render_import_ready_message(_sm)

        # ── First interpreted insight ─────────────────────────────────────────
        try:
            _goal_status_for_insight = list(st.session_state.get("goal_status") or [])
            _first_insight = build_first_import_insight(
                import_summary=_sm,
                goal_status=_goal_status_for_insight,
            )
            _render_first_import_insight(_first_insight)
        except Exception:
            pass

        if _ic_trust:
            _render_import_trust_summary(_ic_trust, heading="Import trust indicators")
            _render_latest_import_summary(
                build_latest_import_summary(
                    rows_processed=int(_sm.get("rows_processed", 0) or 0),
                    valid_rows=int(_sm.get("valid_rows", 0) or 0),
                    warning_rows=int(_sm.get("warning_rows", 0) or 0),
                    rejected_rows=int(_sm.get("rejected_rows", 0) or 0),
                    ignored_or_excluded_rows=int(_sm.get("ignored_or_excluded_rows", 0) or 0),
                ),
                heading="Latest import summary",
            )
            _render_data_confidence_panel(_ic_trust)

            _complete_row_issues = list(_sm.get("row_issues") or [])
            _complete_excluded_rows = list(_sm.get("excluded_rows") or [])
            _render_issue_group_handling(
                trust=_ic_trust,
                row_issues=_complete_row_issues,
                preview_rows=list(_sm.get("preview_rows") or []),
                excluded_rows=_complete_excluded_rows,
                state_key="import_issue_handling_complete",
            )

            with st.expander("View problematic rows", expanded=False):
                if _complete_row_issues:
                    _render_row_error_summary(_complete_row_issues)
                else:
                    st.caption("No row-level problematic rows were captured for this import.")

            with st.expander("View excluded data", expanded=False):
                if _complete_excluded_rows:
                    st.dataframe(pd.DataFrame(_complete_excluded_rows), use_container_width=True, hide_index=True)
                else:
                    st.caption("No excluded rows were captured for this import.")

            # Plain-language confidence note — replaces the old no-op radio.
            _conf_score = int((_ic_trust or {}).get("confidence_score", 0) or 0)
            if _conf_score >= 75:
                st.success(
                    "Data confidence is **High**. Comparisons and trend signals are reliable. "
                    "Navigate to Today or Team to see interpreted results."
                )
            elif _conf_score >= 50:
                st.warning(
                    "Data confidence is **Medium**. Some rows have quality issues — comparisons "
                    "will work but are noted with caveats where data is incomplete. "
                    "You can continue now or address issues later."
                )
            else:
                st.warning(
                    "Data confidence is **Low**. Several quality issues were found. "
                    "You can still continue — insights will note where confidence is limited "
                    "and comparisons may shift after cleanup."
                )
        _ic_c1, _ic_c2 = st.columns(2)
        _ic_btn_label = f"View team ({_ic_below} need attention)" if _ic_below > 0 else "View your team"
        if _ic_c1.button(f"👥 {_ic_btn_label}", type="primary", use_container_width=True, key="ic_start_day"):
            del st.session_state["_import_complete_summary"]
            st.session_state["_first_import_just_completed"] = True
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

    _candidate_preview_rows = _build_candidate_uph_rows(sessions, work_date)
    _preview_fingerprint = _build_import_fingerprint(_candidate_preview_rows)
    _matching_upload = _find_matching_upload_by_fingerprint(st.session_state.get("tenant_id", ""), _preview_fingerprint)
    _preview_dup_count = 0
    _preview_exact_duplicate_import = False
    _preview_mismatch_rows = []
    try:
        _tenant_id = st.session_state.get("tenant_id", "")
        if _candidate_preview_rows:
            if _matching_upload:
                _preview_dup_count = len(_candidate_preview_rows)
                _preview_exact_duplicate_import = True
            else:
                from database import get_client as _db_get_client, _tq as _db_tq
                _code_to_primary, _code_to_all, _rowid_to_code = _build_emp_code_maps()

                def _emp_code(_eid):
                    return str(_eid or "").strip()

                def _candidate_rowids(_code):
                    _s = _emp_code(_code)
                    _all = _code_to_all.get(_s)
                    if _all:
                        return set(_all)
                    _p = _code_to_primary.get(_s, _s)
                    return {_p} if _p else set()

                _dates = sorted({r.get("work_date") for r in _candidate_preview_rows if r.get("work_date")})
                _emp_ids = sorted({
                    _rid
                    for _r in _candidate_preview_rows
                    for _rid in _candidate_rowids(_r.get("emp_id"))
                    if _rid
                })
                _dmin = _dates[0] if _dates else ""
                _dmax = _dates[-1] if _dates else ""
                # Use integer emp_ids only — strings silently fail against bigint column
                _emp_ids_int = sorted({
                    int(_rid)
                    for _rid in _emp_ids
                    if str(_rid).lstrip("-").isdigit()
                })
                # Import history is stored as one row per employee per day for this
                # pipeline, so duplicate detection should follow the same shape.
                _existing_2key = set()
                _history_emp_ids = set()
                _history_dates_by_emp = {}
                def _norm_date(_v):
                    return str(_v or "").strip()[:10]
                if _dmin and _dmax and _emp_ids_int:
                    _sb = _db_get_client()
                    _q = _sb.table("uph_history").select("emp_id, work_date")
                    if _tenant_id:
                        _q = _q.eq("tenant_id", _tenant_id)
                    _q = _q.gte("work_date", _dmin).lte("work_date", _dmax).in_("emp_id", _emp_ids_int)
                    _res = _db_tq(_q).execute()
                    for _er in (_res.data or []):
                        _er_emp = str(_er.get("emp_id", "") or "").strip()
                        if _er_emp:
                            _history_emp_ids.add(_er_emp)
                            _history_dates_by_emp.setdefault(_er_emp, set()).add(_norm_date(_er.get("work_date", "")))
                            _existing_2key.add((
                                _er_emp,
                                _norm_date(_er.get("work_date", "")),
                            ))

                for _r in _candidate_preview_rows:
                    _k_date = _norm_date(_r.get("work_date", ""))
                    _rowids = _candidate_rowids(_r.get("emp_id", ""))
                    _is_dup = any((str(_rid), _k_date) in _existing_2key for _rid in _rowids)
                    if _is_dup:
                        _preview_dup_count += 1
                    else:
                        _resolved_rowids = [str(_rid) for _rid in sorted(_rowids)]
                        _known_dates_str = ""
                        _matching_emp_ids = [
                            _rid for _rid in _resolved_rowids if _rid in _history_emp_ids
                        ]
                        if not _resolved_rowids:
                            _reason = "Employee ID not found in employees table"
                        elif not _matching_emp_ids:
                            _reason = "No history rows found for this employee"
                        elif not any(_k_date in _history_dates_by_emp.get(_rid, set()) for _rid in _matching_emp_ids):
                            _known_dates = sorted({
                                _d
                                for _rid in _matching_emp_ids
                                for _d in _history_dates_by_emp.get(_rid, set())
                            })
                            _known_dates_str = ", ".join(_known_dates[:5])
                            if len(_known_dates) > 5:
                                _known_dates_str += ", ..."
                            _reason = "Employee exists in history, but not on this work date"
                        else:
                            _reason = "Key mismatch after duplicate comparison"
                        _preview_mismatch_rows.append({
                            "Source File(s)": _r.get("source_files", ""),
                            "Employee ID": str(_r.get("emp_id", "") or ""),
                            "Resolved Row ID(s)": ", ".join(_resolved_rowids),
                            "Work Date": _k_date,
                            "Department": str(_r.get("department", "") or ""),
                            "Reason": _reason,
                            "Known History Dates": _known_dates_str,
                        })

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

    _preview_overlap_count = _preview_dup_count
    _preview_new_count = 0 if _preview_exact_duplicate_import else len(_candidate_preview_rows)
    _preview_result_obj = None
    _preview_trust_summary = {}
    _preview_row_issues = []
    _user_role = str(st.session_state.get("user_role", "") or "")
    try:
        _preview_result_obj = run_import_preview_job(
            sessions=sessions,
            fallback_date=work_date,
            tenant_id=tenant_id,
            user_role=_user_role,
        )
        if _preview_result_obj and _preview_result_obj.success:
            _preview_trust_summary = {
                "status": _preview_result_obj.trust_summary.status,
                "confidence_score": _preview_result_obj.trust_summary.confidence_score,
                "accepted_rows": _preview_result_obj.trust_summary.accepted_rows,
                "rejected_rows": _preview_result_obj.trust_summary.rejected_rows,
                "warnings": _preview_result_obj.trust_summary.warnings,
                "duplicates": _preview_result_obj.trust_summary.duplicates,
                "missing_required_fields": _preview_result_obj.trust_summary.missing_required_fields,
                "inconsistent_names": _preview_result_obj.trust_summary.inconsistent_names,
                "suspicious_values": _preview_result_obj.trust_summary.suspicious_values,
            }
            _preview_row_issues = [
                {
                    "code": issue.code,
                    "message": issue.message,
                    "severity": issue.severity,
                    "row_index": issue.row_index,
                    "field": issue.field,
                    "value": issue.value,
                }
                for issue in (_preview_result_obj.invalid_issues or [])
            ]
    except Exception:
        _preview_trust_summary = {}
        _preview_row_issues = []

    with st.expander("👀 Preview parsed data before import", expanded=True):
        _preview_days = len(_preview_dates) if _preview_dates else 1
        st.caption(
            f"Sample preview of parsed rows. About {_preview_days} day(s) and "
            f"{len(_preview_emp_ids)} unique employee ID(s) detected."
        )
        if _preview_trust_summary:
            _render_import_trust_summary(_preview_trust_summary, heading="Projected data quality and trust")
            _render_latest_import_summary(
                build_latest_import_summary(
                    rows_processed=int(len(_candidate_preview_rows)),
                    valid_rows=int(_preview_trust_summary.get("accepted_rows", 0) or 0),
                    warning_rows=int(sum(1 for i in (_preview_row_issues or []) if str(i.get("severity", "error")) == "warning")),
                    rejected_rows=int(_preview_trust_summary.get("rejected_rows", 0) or 0),
                    ignored_or_excluded_rows=int((_preview_trust_summary.get("duplicates", 0) or 0) + len(_preview_mismatch_rows or [])),
                ),
                heading="Latest import summary",
            )
            _render_data_confidence_panel(_preview_trust_summary)
            _render_issue_group_handling(
                trust=_preview_trust_summary,
                row_issues=_preview_row_issues,
                preview_rows=_preview_rows,
                excluded_rows=_preview_mismatch_rows,
                state_key="import_issue_handling_preview",
            )
            st.caption("How data issues affect interpretation: unresolved quality issues can reduce confidence in today’s trend comparisons.")
        if _preview_row_issues:
            with st.expander("Show row-level validation issues", expanded=False):
                _render_row_error_summary(_preview_row_issues)
        if _preview_mismatch_rows:
            with st.expander("Show excluded/ignored rows", expanded=False):
                st.dataframe(pd.DataFrame(_preview_mismatch_rows[:120]), use_container_width=True, hide_index=True)
        if _candidate_preview_rows:
            if _preview_exact_duplicate_import:
                st.markdown(
                    f"**Duplicate summary**\n"
                    f"File rows selected: **{total_rows:,}**  \n"
                    f"History rows derived from file: **{len(_candidate_preview_rows):,}**  \n"
                    f"Exact duplicates already in system: **{len(_candidate_preview_rows):,}**  \n"
                    f"Rows that will be uploaded: **0**"
                )
                st.caption(
                    "This upload matches a previously imported dataset fingerprint exactly."
                )
            else:
                st.markdown(
                    f"**Import summary**\n"
                    f"File rows selected: **{total_rows:,}**  \n"
                    f"History rows derived from file: **{len(_candidate_preview_rows):,}**  \n"
                    f"Existing employee/day keys already in system: **{_preview_overlap_count:,}**  \n"
                    f"Rows that will be uploaded after overlap replacement: **{_preview_new_count:,}**"
                )
                if _preview_overlap_count:
                    st.caption(
                        f"Overlap detected for {_preview_overlap_count}/{len(_candidate_preview_rows)} row(s). "
                        "Existing history for those employee/day keys will be replaced before insert."
                    )
            if _preview_exact_duplicate_import:
                st.warning("All derived rows are duplicates. Nothing new will be uploaded.")
                if _matching_upload:
                    st.caption(
                        "Matched a previously uploaded dataset fingerprint "
                        f"(upload id: {_matching_upload.get('id')}, "
                        f"created: {str(_matching_upload.get('created_at', ''))[:19].replace('T', ' ')})."
                    )
        if _preview_rows:
            with st.expander("Show parsed sample rows", expanded=False):
                st.dataframe(pd.DataFrame(_preview_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No preview rows available from mapped data.")

        st.markdown("**Continue path**")
        st.radio(
            "Choose how to continue",
            ["continue_with_warnings", "review_later", "proceed_using_available_data"],
            format_func=lambda value: {
                "continue_with_warnings": "Continue with warnings",
                "review_later": "Review later",
                "proceed_using_available_data": "Proceed using available data",
            }.get(value, value),
            key="import_preview_continue_path",
            horizontal=True,
            label_visibility="collapsed",
        )

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

        _upload_names = [s.get("filename", "") for s in sessions if s.get("filename")]
        _upload_name = ", ".join(_upload_names).strip() or "Import"
        _import_job = _create_import_job(
            tenant_id=tenant_id,
            upload_name=_upload_name,
            total_rows=len(all_rows),
        )
        _mark_import_stage_completed(
            _import_job,
            "map",
            meta={"mapped_fields": int(sum(1 for v in (all_mapping or {}).values() if str(v or "").strip()))},
        )
        _mark_import_stage_in_progress(_import_job, "validate")
        _validate_meta = {
            "row_errors": int(sum(1 for i in (_preview_row_issues or []) if str(i.get("severity", "error")) == "error")),
            "row_warnings": int(sum(1 for i in (_preview_row_issues or []) if str(i.get("severity", "error")) == "warning")),
            "accepted_rows": int(_preview_trust_summary.get("accepted_rows", 0) or 0),
            "rejected_rows": int(_preview_trust_summary.get("rejected_rows", 0) or 0),
        }
        _mark_import_stage_completed(_import_job, "validate", meta=_validate_meta)

        _progress_container = st.container()
        with _progress_container:
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
                from database import get_employee_count
                _existing = get_employee_count()
                _existing_ids = {
                    str(e.get("emp_id", "")).strip()
                    for e in (_cached_employees() or [])
                    if str(e.get("emp_id", "")).strip()
                }
                _new_ids = [eid for eid in seen_emps.keys() if eid not in _existing_ids]
                _new_unique = len(_new_ids)
                _limit_check = evaluate_import_limit(
                    st.session_state.get("tenant_id", ""),
                    current_count=_existing,
                    new_unique_count=_new_unique,
                )
                _el = int(_limit_check.get("employee_limit", 0) or 0)
                if not _limit_check.get("allowed", True) and _el > 0:
                    _plan = str(_limit_check.get("plan") or "starter").lower()
                    _slots_left = max(0, int(_limit_check.get("slots_left", 0) or 0))
                    _sorted_new_ids = sorted(_new_ids)
                    _overflow_ids = _sorted_new_ids[_slots_left:]
                    _overflow_names = [
                        f"{seen_emps.get(_eid, {}).get('name', _eid)} ({_eid})"
                        for _eid in _overflow_ids[:25]
                    ]
                    st.error(
                        f"Employee limit reached. Your **{_plan.capitalize()}** plan allows "
                        f"**{_el}** employees and you have **{_existing}**. "
                        f"This import adds **{_new_unique}** new employee(s). "
                        f"Upgrade your plan in Settings → Subscription."
                    )
                    if _overflow_names:
                        st.caption("Employees over your plan limit:")
                        st.code("\n".join(_overflow_names))
                    return
            except Exception:
                pass  # don't block import if limit check fails
            try:
                from database import batch_upsert_employees as _batch_upsert_employees
                _batch_upsert_employees(list(seen_emps.values()))
            except Exception as _e:
                st.error(
                    "Employee sync failed, so the import cannot continue safely. "
                    "Please sign out/in and try again.\n\n"
                    f"Technical details: {_e}"
                )
                _log_app_error("pipeline", f"Employee sync error: {_e}", detail=traceback.format_exc(), severity="warning")
                return
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
            log = ErrorLog(tempfile.gettempdir(), tenant_id=tenant_id)

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
            # Import policy:
            # - exact repeat dataset => skip entirely
            # - overlapping employee/date keys => replace existing rows for those keys
            _dup_skipped = 0
            _replaced_existing_rows = 0
            _candidate_count = len(uph_batch)
            _exact_duplicate_import = False
            _undo_previous_rows = []
            _undo_touched_keys = []
            _batch_fingerprint = _build_import_fingerprint(uph_batch)
            _matching_upload = _find_matching_upload_by_fingerprint(st.session_state.get("tenant_id", ""), _batch_fingerprint)
            if _candidate_count > 0 and _matching_upload:
                _dup_skipped = _candidate_count
                _exact_duplicate_import = True
                uph_batch = []
                st.warning(
                    "This dataset matches a previously uploaded file exactly. "
                    "No new rows were uploaded."
                )
            try:
                _tenant_id = st.session_state.get("tenant_id", "")
                _dates = sorted({r.get("work_date") for r in uph_batch if r.get("work_date")})
                _date_min = _dates[0] if _dates else ""
                _date_max = _dates[-1] if _dates else ""
                _code_to_primary, _code_to_all, _rowid_to_code = _build_emp_code_maps()

                def _db_emp_key(_eid):
                    _s = str(_eid or "").strip()
                    return _code_to_primary.get(_s, _s)

                def _cmp_emp_code(_eid):
                    return str(_eid or "").strip()

                def _candidate_rowids(_code):
                    _s = _cmp_emp_code(_code)
                    _all = _code_to_all.get(_s)
                    if _all:
                        return set(_all)
                    _p = _code_to_primary.get(_s, _s)
                    return {_p} if _p else set()

                _emp_ids = sorted({
                    _rid
                    for _r in uph_batch
                    for _rid in _candidate_rowids(_r.get("emp_id"))
                    if _rid
                })
                _candidate_keys = {
                    (
                        _cmp_emp_code(_r.get("emp_id")),
                        str(_r.get("work_date", ""))[:10],
                    )
                    for _r in uph_batch
                }
                # Use integer emp_ids — strings silently fail against bigint column
                _emp_ids_int = sorted({
                    int(_rid)
                    for _rid in _emp_ids
                    if str(_rid).lstrip("-").isdigit()
                })
                # Duplicate detection follows the import pipeline shape: one row
                # per employee per day. For overlapping uploads we replace old
                # rows for the same employee/date keys before inserting fresh rows.
                _existing_2key = set()
                _rows_to_replace = []
                def _norm_date(_v):
                    return str(_v or "").strip()[:10]
                if _date_min and _date_max and _emp_ids_int:
                    from database import get_client as _db_get_client, _tq as _db_tq
                    _sb = _db_get_client()
                    _q = _sb.table("uph_history").select("id, emp_id, work_date, uph, units, hours_worked, department")
                    if _tenant_id:
                        _q = _q.eq("tenant_id", _tenant_id)
                    _q = _q.gte("work_date", _date_min).lte("work_date", _date_max).in_("emp_id", _emp_ids_int)
                    _res = _db_tq(_q).execute()
                    for _er in (_res.data or []):
                        _er_emp = str(_er.get("emp_id", "") or "").strip()
                        if _er_emp:
                            _er_code = _rowid_to_code.get(_er_emp, "")
                            _key2 = (_er_code, _norm_date(_er.get("work_date", "")))
                            if _er_code:
                                _existing_2key.add(_key2)
                                if _key2 in _candidate_keys:
                                    _rows_to_replace.append({
                                        "id": _er.get("id"),
                                        "emp_id": _er.get("emp_id"),
                                        "work_date": _er.get("work_date"),
                                        "uph": _er.get("uph"),
                                        "units": _er.get("units"),
                                        "hours_worked": _er.get("hours_worked"),
                                        "department": _er.get("department", ""),
                                    })

                _undo_previous_rows = list(_rows_to_replace)
                _rows_to_delete = [int(_r["id"]) for _r in _rows_to_replace if _r.get("id") is not None]
                if _rows_to_delete and _tenant_id:
                    from database import get_client as _db_get_client, _tq as _db_tq
                    _sb_del = _db_get_client()
                    _db_tq(
                        _sb_del.table("uph_history")
                        .delete()
                        .eq("tenant_id", _tenant_id)
                        .in_("id", _rows_to_delete)
                    ).execute()
                    _replaced_existing_rows = len(_rows_to_delete)

                _inserted_key3 = set()
                for _r in uph_batch:
                    _key_emp = str(_db_emp_key(_r.get("emp_id", "")))
                    _key_date = _norm_date(_r.get("work_date", ""))
                    _key_dept = str(_r.get("department", "") or "")
                    _inserted_key3.add((_key_emp, _key_date, _key_dept))
                _undo_touched_keys = [list(_k) for _k in sorted(_inserted_key3)]
            except Exception:
                pass

            # Store UPH history synchronously so data is in DB before pipeline completes
            try:
                _mark_import_stage_in_progress(_import_job, "persist")
                _bg_tid = st.session_state.get("tenant_id", "")
                _final_trust_summary = {}
                if _bg_tid:
                    uph_batch = [{**r, "tenant_id": _bg_tid} for r in uph_batch]
                from database import batch_store_uph_history as _batch_store_uph_history
                _batch_store_uph_history(uph_batch)

                # -----------------------------------------------------------
                # After the upsert, fetch the actual PK (id) for every row
                # that was brand-new (not an overwrite).  Storing PKs instead
                # of (emp_id, date, dept) triples means rollback is a simple
                # DELETE WHERE id IN (...) with no type-coercion footguns.
                # -----------------------------------------------------------
                _new_row_ids = []
                if _bg_tid and _undo_touched_keys:
                    try:
                        from database import get_client as _db_get_client, _tq as _db_tq
                        _sb_pk = _db_get_client()
                        # All touched keys are new inserts (skipped rows are never upserted)
                        _new_keys_set = {
                            (str(_k[0]), str(_k[1]), str(_k[2]))
                            for _k in _undo_touched_keys
                        }
                        if _new_keys_set:
                            _pk_emp_ids = []
                            for _nk in _new_keys_set:
                                try:
                                    _pk_emp_ids.append(int(_nk[0]))
                                except (TypeError, ValueError):
                                    pass
                            _pk_dates = sorted({_nk[1] for _nk in _new_keys_set})
                            if _pk_emp_ids and _pk_dates:
                                _pk_res = _db_tq(
                                    _sb_pk.table("uph_history")
                                    .select("id, emp_id, work_date, department")
                                    .eq("tenant_id", _bg_tid)
                                    .in_("emp_id", _pk_emp_ids)
                                    .gte("work_date", _pk_dates[0])
                                    .lte("work_date", _pk_dates[-1])
                                ).execute()
                                for _pk_row in (_pk_res.data or []):
                                    _pk_k = (
                                        str(_pk_row.get("emp_id", "")),
                                        str(_pk_row.get("work_date", "")),
                                        str(_pk_row.get("department", "") or ""),
                                    )
                                    if _pk_k in _new_keys_set and _pk_row.get("id") is not None:
                                        _new_row_ids.append(_pk_row["id"])
                    except Exception:
                        pass

                if _bg_tid:
                    _preview_missing_required = int(_preview_trust_summary.get("missing_required_fields", 0) or 0)
                    _preview_warning_count = int(_preview_trust_summary.get("warnings", 0) or 0)
                    _quality_warning_count = _preview_warning_count
                    if name_fixed_count > 0:
                        _quality_warning_count += 1
                    if (uph_rejected_count + neg_value_fixed_count) > 0:
                        _quality_warning_count += 1

                    _final_trust = build_import_trust_summary(
                        total_rows=int(_candidate_count),
                        accepted_rows=int(len(uph_batch)),
                        duplicates=int(_dup_skipped),
                        missing_required_fields=int(_preview_missing_required),
                        inconsistent_names=int(name_fixed_count),
                        suspicious_values=int(uph_rejected_count + neg_value_fixed_count),
                        warnings=int(_quality_warning_count),
                    )
                    _final_trust_summary = {
                        "status": str(_final_trust.status),
                        "confidence_score": int(_final_trust.confidence_score),
                        "accepted_rows": int(_final_trust.accepted_rows),
                        "rejected_rows": int(_final_trust.rejected_rows),
                        "warnings": int(_final_trust.warnings),
                        "duplicates": int(_final_trust.duplicates),
                        "missing_required_fields": int(_final_trust.missing_required_fields),
                        "inconsistent_names": int(_final_trust.inconsistent_names),
                        "suspicious_values": int(_final_trust.suspicious_values),
                    }
                    _profile_headers = []
                    for _sess in sessions:
                        _profile_headers = list(_sess.get("headers") or [])
                        if _profile_headers:
                            break
                    _upload_payload = {
                        "files": [s.get("filename", "") for s in sessions],
                        "data_fingerprint": _batch_fingerprint,
                        "mapping_profile": _build_mapping_profile_payload(
                            headers=_profile_headers,
                            mapping=all_mapping,
                        ),
                        "stats": {
                            "candidate_rows": int(_candidate_count),
                            "inserted_rows": int(len(uph_batch)),
                            "duplicate_rows": int(_dup_skipped),
                            "replaced_rows": int(_replaced_existing_rows),
                            "exact_duplicate_import": bool(_exact_duplicate_import),
                            "accepted_rows": int(_final_trust.accepted_rows),
                            "rejected_rows": int(_final_trust.rejected_rows),
                            "warnings": int(_final_trust.warnings),
                            "missing_required_fields": int(_final_trust.missing_required_fields),
                            "inconsistent_names": int(_final_trust.inconsistent_names),
                            "suspicious_values": int(_final_trust.suspicious_values),
                            "trust_status": str(_final_trust.status),
                            "confidence_score": int(_final_trust.confidence_score),
                        },
                        "import_job": _serialize_import_job(_import_job),
                        "undo": {
                            "tenant_id": _bg_tid,
                            "new_row_ids": _new_row_ids,
                            "touched_keys": _undo_touched_keys,
                            "previous_rows": _undo_previous_rows,
                        },
                        "created_at": get_user_timezone_now(tenant_id).isoformat(timespec="seconds"),
                    }
                    _upload_filename = ", ".join([s.get("filename", "") for s in sessions if s.get("filename")]).strip() or "Import"
                    _upload_log_id = _record_upload_event(_bg_tid, _upload_filename, _candidate_count, _upload_payload)

                    # Keep legacy UPH history for compatibility, and ingest normalized records for future analytics.
                    _valid_dates = sorted(
                        {
                            str(row.get("work_date") or "")[:10]
                            for row in uph_batch
                            if str(row.get("work_date") or "").strip()
                        }
                    )
                    run_import_postprocess_job(
                        uph_rows=uph_batch,
                        tenant_id=tenant_id,
                        source_import_job_id=str(_import_job.job_id),
                        source_import_file=_upload_filename,
                        source_upload_id=str(_upload_log_id or ""),
                        data_quality_status=str(_final_trust.status),
                        exclusion_note=(
                            f"duplicates_skipped={int(_dup_skipped)}; replaced_rows={int(_replaced_existing_rows)}"
                            if (_dup_skipped or _replaced_existing_rows)
                            else ""
                        ),
                        handling_choice=str(st.session_state.get("import_preview_continue_path") or ""),
                        handling_note="Imported through legacy-compatible UPH pipeline",
                        from_date=_valid_dates[0] if _valid_dates else "",
                        to_date=_valid_dates[-1] if _valid_dates else "",
                    )

                    if len(uph_batch) > 0 and (_new_row_ids or _undo_previous_rows):
                        st.session_state["_last_import_undo"] = {
                            "tenant_id": _bg_tid,
                            "row_count": len(uph_batch),
                            "created_at": time.time(),
                            "upload_id": _upload_log_id,
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
                elif _replaced_existing_rows:
                    st.info(
                        f"Overlap handled: replaced {_replaced_existing_rows} existing history row(s) "
                        f"and uploaded {len(uph_batch)} fresh row(s)."
                    )
                if not _final_trust_summary:
                    _final_trust_summary = {
                        "status": "invalid",
                        "confidence_score": 0,
                        "accepted_rows": int(len(uph_batch)),
                        "rejected_rows": int(max(0, _candidate_count - len(uph_batch))),
                        "warnings": 0,
                        "duplicates": int(_dup_skipped),
                        "missing_required_fields": 0,
                        "inconsistent_names": int(name_fixed_count),
                        "suspicious_values": int(uph_rejected_count + neg_value_fixed_count),
                    }
                _mark_import_stage_completed(
                    _import_job,
                    "persist",
                    meta={
                        "inserted_rows": int(len(uph_batch)),
                        "duplicate_rows": int(_dup_skipped),
                        "replaced_rows": int(_replaced_existing_rows),
                    },
                )
            except Exception as _uph_err:
                _mark_import_stage_failed(_import_job, "persist", error=str(_uph_err))
                _complete_import_job(_import_job, success=False)
                _show_user_error(
                    "Could not save imported history right now.",
                    next_steps=(
                        "Fix unresolved employee IDs (or missing employee records) and try the import again."
                    ),
                    technical_detail=traceback.format_exc(),
                    category="pipeline",
                )
                st.info(
                    "Import stopped. Fix unresolved employee IDs (or missing employee records) "
                    "and run the import again so all history rows are written."
                )
                _log_app_error("pipeline", f"UPH history storage failed: {_uph_err}",
                               detail=traceback.format_exc(), severity="error")
                _log_operational_event(
                    "import_failure",
                    status="error",
                    tenant_id=tenant_id,
                    detail="UPH history storage failed",
                    context={"error": str(_uph_err)},
                )
                return

            _bust_cache()
            # Keep pipeline completion fast; rebuild full analytics lazily on first destination page.
            bar.progress(90, text="Finalizing import…")
            st.session_state["_archived_loaded"] = False
            st.session_state["pipeline_done"] = False
            st.session_state["_archived_last_refresh_ts"] = 0.0

            # Quick summary from this import batch only (full trends/risks are computed lazily later).
            _ranked_count = len({str(r.get("emp_id", "")) for r in uph_batch if str(r.get("emp_id", "")).strip()})
            _dept_targets = _cached_targets()
            _emp_totals = {}
            for _r in uph_batch:
                _eid = str(_r.get("emp_id", "") or "").strip()
                if not _eid:
                    continue
                _dept = str(_r.get("department", "") or "")
                _hours = float(_r.get("hours_worked", 0) or 0)
                _units = float(_r.get("units", 0) or 0)
                _cur = _emp_totals.get(_eid, {"units": 0.0, "hours": 0.0, "dept": _dept})
                _cur["units"] += _units
                _cur["hours"] += _hours
                if _dept:
                    _cur["dept"] = _dept
                _emp_totals[_eid] = _cur

            _below_final = 0
            for _v in _emp_totals.values():
                _tgt = float(_dept_targets.get(_v.get("dept", ""), 0) or 0)
                _uph = (_v["units"] / _v["hours"]) if _v["hours"] > 0 else 0
                if _tgt > 0 and _uph < _tgt:
                    _below_final += 1
            _risks_final = 0

            st.session_state.update({
                "mapping":           all_mapping,
                "alloc_rows":        alloc_rows,
                "alloc_date":        canon_date,
                "alloc_has_date":    has_date_col,
                "pipeline_done":     True,
                "pipeline_error":    "",
            })

            # Post-import refresh can be expensive on larger files. Defer heavy
            # work so "Run pipeline" completes quickly instead of appearing stuck.
            try:
                _batch_size = int(len(uph_batch or []))
                _should_defer_refresh = _batch_size >= 300
                bar.progress(95, text="Finalizing import…")

                if _should_defer_refresh:
                    st.session_state["_post_import_refresh_pending"] = True
                    st.session_state["_last_action_engine_refresh"] = {
                        "status": "deferred",
                        "reason": "large_import",
                        "batch_size": _batch_size,
                        "queued_at": get_user_timezone_now(tenant_id).isoformat(timespec="seconds"),
                    }
                    _log_operational_event(
                        "post_import_refresh_deferred",
                        status="queued",
                        tenant_id=tenant_id,
                        context={"batch_size": _batch_size},
                    )
                else:
                    bar.progress(95, text="Refreshing signals and actions…")

                    # Refresh performance signals from archived pipeline output.
                    from pages.common import load_goal_status_history as _load_goal_status_history
                    _gs_after, _history_after = _load_goal_status_history("Refreshing performance signals…")

                    # Generate actions from latest signals and normalize open statuses.
                    from services.action_lifecycle_service import run_all_triggers as _run_all_triggers, refresh_action_statuses as _refresh_action_statuses

                    _trigger_summary = _run_all_triggers(
                        history=_history_after or [],
                        tenant_id=tenant_id,
                    )
                    _status_updates = _refresh_action_statuses(tenant_id=tenant_id)

                    # Precompute daily signals so Today stays read-only and fast.
                    from services.daily_signals_service import compute_daily_signals

                    compute_daily_signals(
                        signal_date=date.today(),
                        tenant_id=tenant_id,
                    )

                    st.session_state["_post_import_refresh_pending"] = False
                    st.session_state["_last_action_engine_refresh"] = {
                        "status": "completed",
                        "trigger_summary": _trigger_summary,
                        "status_updates": int(_status_updates or 0),
                        "refreshed_at": get_user_timezone_now(tenant_id).isoformat(timespec="seconds"),
                    }
            except Exception as _action_refresh_err:
                _log_app_error(
                    "pipeline",
                    f"Post-import action refresh failed: {_action_refresh_err}",
                    detail=traceback.format_exc(),
                    severity="warning",
                )

            bar.progress(100, text="Done!")
            _unique_emp_count = len({r["emp_id"] for r in alloc_rows})
            st.session_state["_import_complete_summary"] = {
                "emp_count": _unique_emp_count,
                "ranked":    _ranked_count,
                "below":     _below_final,
                "risks":     _risks_final,
                "days":      _estimated_days,
                "trust":     _final_trust_summary,
                "rows_processed": int(_candidate_count),
                "valid_rows": int((_final_trust_summary or {}).get("accepted_rows", 0) or len(uph_batch)),
                "warning_rows": int((_final_trust_summary or {}).get("warnings", 0) or 0),
                "rejected_rows": int((_final_trust_summary or {}).get("rejected_rows", 0) or max(0, _candidate_count - len(uph_batch))),
                "ignored_or_excluded_rows": int((_dup_skipped or 0) + len(_preview_mismatch_rows or [])),
                "row_issues": list(_preview_row_issues or []),
                "excluded_rows": list((_preview_mismatch_rows or [])[:120]),
                "preview_rows": list((_preview_rows or [])[:120]),
                "import_job": _serialize_import_job(_import_job),
                "import_file": _upload_name,
            }
            _mark_import_stage_in_progress(_import_job, "summarize")
            _mark_import_stage_completed(
                _import_job,
                "summarize",
                meta={
                    "employees": int(_unique_emp_count),
                    "below_goal": int(_below_final),
                    "risks": int(_risks_final),
                },
            )
            _complete_import_job(_import_job, success=True)
            
            # Clear the progress bar before rerun
            _progress_container.empty()
            st.rerun()

        except Exception as _pipe_err:
            _mark_import_stage_failed(_import_job, _import_job.current_stage or "persist", error=str(_pipe_err))
            _complete_import_job(_import_job, success=False)
            _tb = traceback.format_exc()
            st.error("Pipeline error:")
            st.code(_tb)
            _log_app_error("pipeline", str(_pipe_err), detail=_tb)
            _log_operational_event(
                "import_failure",
                status="error",
                tenant_id=tenant_id,
                detail="Pipeline processing failed",
                context={"error": str(_pipe_err)},
            )

    st.divider()
    col1, col2 = st.columns(2)

    if col1.button("← Back to mapping", use_container_width=True):
        st.session_state.import_step = 2
        st.rerun()

    if st.session_state.get("pipeline_done") and st.session_state.get("alloc_rows"):
        _uc = len({r["emp_id"] for r in st.session_state.alloc_rows})
        col2.success(
            f"✓ Your data is ready — {_uc} employee{'s' if _uc != 1 else ''} available for review now."
        )

    if st.button("↺ Start fresh import", use_container_width=True):
        st.session_state.uploaded_sessions = []
        st.session_state.import_step       = 1
        st.session_state.alloc_rows        = []
        st.rerun()


