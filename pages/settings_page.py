from core.dependencies import (
    _full_sign_out,
    _log_app_error,
    _show_user_error,
    _render_sign_out_button,
    _set_auth_cookies,
    _tenant_log_path,
)
from core.billing_cache import clear_billing_cache
from services.plan_service import can_manage_team
from core.runtime import datetime, json, re, st, time, traceback, init_runtime
from services.settings_service import (
    escape_html,
    format_error_timestamp,
    summarize_error_counts,
)
from services.upgrade_telemetry_service import log_upgrade_event

init_runtime()


def _load_billing_dashboard_cached(fetch_fn, *, tenant_id: str, app_url: str, ttl_seconds: int = 30, force_refresh: bool = False) -> dict:
    """Small session cache to avoid re-fetching billing data on every rerun."""
    cache_key = "_billing_dashboard_cache"
    now_ts = float(time.time())
    cached = st.session_state.get(cache_key)
    if (
        not force_refresh
        and isinstance(cached, dict)
        and cached.get("tenant_id") == tenant_id
        and cached.get("app_url") == app_url
        and (now_ts - float(cached.get("loaded_at", 0.0) or 0.0)) < float(ttl_seconds)
    ):
        return dict(cached.get("result") or {})

    result = fetch_fn(tenant_id, app_url)
    st.session_state[cache_key] = {
        "tenant_id": tenant_id,
        "app_url": app_url,
        "loaded_at": now_ts,
        "result": result,
    }
    return dict(result or {})

def page_settings():
    st.title("⚙️ Settings")

    tab_account, tab_team, tab_billing, tab_integrations, tab_advanced = st.tabs([
        "Account", "Team", "Billing", "Integrations", "Advanced"
    ])

    # ── Subscription tab ──────────────────────────────────────────────────
    with tab_billing:
        st.subheader("Your Subscription")
        st.caption("Manage subscription, invoices, and plan limits.")
        try:
            from services.billing_service import get_billing_dashboard, request_plan_change
            from database import create_billing_portal_url, get_live_stripe_subscription_status

            _tid_local = st.session_state.get("tenant_id", "")
            _app_url = st.context.headers.get("Origin", "http://localhost:8501")
            _refresh_billing = st.button("Refresh billing data", key="settings_refresh_billing", type="secondary")
            _bill_result = _load_billing_dashboard_cached(
                get_billing_dashboard,
                tenant_id=_tid_local,
                app_url=_app_url,
                force_refresh=_refresh_billing,
            )
            if not _bill_result.get("success"):
                raise RuntimeError(_bill_result.get("error") or "Could not load billing dashboard")

            _bill_data = _bill_result.get("data") or {}
            sub = _bill_data.get("sub") if _bill_data.get("has_subscription") else None
            _user_id = str(st.session_state.get("user_id", "") or "")
            _user_email = str(st.session_state.get("user_email", "") or "")

            def _queue_billing_portal_continue(*, label: str, launch_key: str, url: str, feature_context: str, current_plan: str, employee_count: int, employee_limit: int) -> None:
                if not url:
                    return
                if st.button(label, key=f"{launch_key}_button", use_container_width=True, type="primary"):
                    log_upgrade_event(
                        "billing_portal_opened",
                        prompt_location="",
                        prompt_type="",
                        current_plan=current_plan,
                        employee_count=employee_count,
                        employee_limit=employee_limit,
                        feature_context=feature_context,
                        tenant_id=_tid_local,
                        user_id=_user_id,
                        user_email=_user_email,
                    )
                    st.session_state[f"_{launch_key}_url"] = url
                if st.session_state.get(f"_{launch_key}_url") == url:
                    st.link_button("Continue to Billing Portal →", url, use_container_width=True, type="secondary")

            if sub:
                _plan_raw = _bill_data.get("plan_raw", "unknown")
                _plan_label = _bill_data.get("plan_label", _plan_raw.capitalize())
                _status = _bill_data.get("status", "unknown")
                _limit_str = _bill_data.get("limit_str", "0")
                _emp_count = _bill_data.get("emp_count", 0)
                try:
                    _employee_limit = int(sub.get("employee_limit", 0) or 0)
                except Exception:
                    _employee_limit = 0
                _renew_str = _bill_data.get("renew_str", "")
                _pending_plan = _bill_data.get("pending_plan", "")
                _pending_date = _bill_data.get("pending_date", "period end")
                _pending_cancel = bool(_bill_data.get("pending_cancel", False))

                _pc = {"starter": "#6b7280", "pro": "#2563eb", "business": "#7c3aed"}.get(_plan_raw, "#6b7280")
                st.markdown(
                    f"""
                    <div style="background:{_pc}12;border:2px solid {_pc};border-radius:10px;
                                padding:14px 20px;margin-bottom:4px;display:flex;
                                align-items:center;gap:16px;">
                      <div>
                        <div style="font-size:11px;font-weight:700;text-transform:uppercase;
                                    letter-spacing:.07em;color:{_pc};">Your Current Plan</div>
                        <div style="font-size:24px;font-weight:800;color:#111;
                                    line-height:1.15;">{_plan_label}</div>
                      </div>
                      <div style="margin-left:auto;text-align:right;line-height:1.6;">
                        <div style="font-size:12px;color:#444;">{_emp_count} / {_limit_str} employees used</div>
                        <div style="font-size:12px;color:#444;">{_status.replace('_', ' ').title()}</div>
                        {"<div style='font-size:12px;color:#888;'>Renews " + _renew_str + "</div>" if _renew_str else ""}
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if _pending_plan:
                    st.markdown(
                        f"<div style='background:#FFF7ED;border:1px solid #FDBA74;border-radius:8px;padding:10px 12px;margin:8px 0 12px;'>"
                        f"<strong style='color:#9A3412;'>Pending billing change:</strong> "
                        f"<span style='color:#7C2D12;'>Plan changes to <strong>{_pending_plan.capitalize()}</strong> on <strong>{_pending_date}</strong>."
                        f" You keep current access until then.</span></div>",
                        unsafe_allow_html=True,
                    )
                elif _pending_cancel:
                    st.markdown(
                        f"<div style='background:#FFF7ED;border:1px solid #FDBA74;border-radius:8px;padding:10px 12px;margin:8px 0 12px;'>"
                        f"<strong style='color:#9A3412;'>Pending billing change:</strong> "
                        f"<span style='color:#7C2D12;'>Cancellation is scheduled for <strong>{_pending_date}</strong>."
                        f" Your current plan stays active until then.</span></div>",
                        unsafe_allow_html=True,
                    )

                if sub.get("cancel_at_period_end"):
                    st.warning("Your subscription will cancel at the end of the current period.")

                _portal_url = _bill_data.get("portal_url")
                _manage_plan_url = _bill_data.get("manage_plan_url")
                _price_map = _bill_data.get("price_map", {})

                if _manage_plan_url:
                    _queue_billing_portal_continue(
                        label="Manage Subscription (billing portal)",
                        launch_key="settings_manage_subscription",
                        url=_manage_plan_url,
                        feature_context="settings_manage_subscription",
                        current_plan=_plan_raw,
                        employee_count=int(_emp_count or 0),
                        employee_limit=_employee_limit,
                    )
                else:
                    st.info("Billing portal not available. Contact support.")

                if _portal_url:
                    _queue_billing_portal_continue(
                        label="Open Billing Portal (card, invoices, cancel)",
                        launch_key="settings_open_billing_portal",
                        url=_portal_url,
                        feature_context="settings_billing_portal",
                        current_plan=_plan_raw,
                        employee_count=int(_emp_count or 0),
                        employee_limit=_employee_limit,
                    )
                    st.caption("Use the in-app Change Plan cards below for plan upgrades.")

                with st.expander("Live Stripe verification", expanded=False):
                    _live_cache_key = f"_live_stripe_status_{_tid_local}"
                    _load_live = st.button("Load live Stripe status", key="load_live_stripe", use_container_width=True)
                    _refresh_live = st.button("Refresh live Stripe status", key="refresh_live_stripe", use_container_width=True)

                    if _load_live or _refresh_live:
                        with st.spinner("Checking Stripe…"):
                            st.session_state[_live_cache_key] = get_live_stripe_subscription_status(_tid_local)

                    _live = st.session_state.get(_live_cache_key)
                    if _live is None:
                        st.caption("Loads live data from Stripe on demand to keep Settings navigation fast.")
                    elif not _live:
                        st.info("No live Stripe subscription found yet.")
                    elif _live.get("error"):
                        st.error(_live.get("error"))
                    else:
                        _stripe_period = ""
                        try:
                            if _live.get("current_period_end"):
                                _stripe_period = datetime.fromtimestamp(int(_live.get("current_period_end"))).strftime("%b %d, %Y")
                        except Exception:
                            _stripe_period = ""

                        _db_plan = (_live.get("db_plan", _plan_raw) or _plan_raw).capitalize()
                        _stripe_plan = (_live.get("current_plan", "") or "unknown").capitalize()
                        st.write(f"Effective access now: {_db_plan} ({_live.get('db_status', _status)})")
                        st.write(f"Stripe live plan: {_stripe_plan} | Stripe status: {_live.get('status', '')}")
                        if _stripe_period:
                            st.write(f"Current billing period ends: {_stripe_period}")

                        st.caption(
                            "Live pending debug: "
                            f"source={_live.get('pending_change_source','') or 'none'} · "
                            f"has_pending={bool(_live.get('has_pending_update'))} · "
                            f"pending_plan={_live.get('pending_plan','') or 'none'} · "
                            f"cancel_at_period_end={bool(_live.get('cancel_at_period_end'))}"
                        )
                        st.caption(
                            "Live price debug: "
                            f"current_price={_live.get('current_price_id','') or 'none'} · "
                            f"pending_price={_live.get('pending_price_id','') or 'none'} · "
                            f"schedule_pending_plan={_live.get('schedule_pending_plan','') or 'none'}"
                        )
                        _sched_rows = _live.get("debug_schedule_rows") or []
                        if _sched_rows:
                            st.caption("Stripe schedules (id/status/subscription/phase_count):")
                            st.code(
                                "\n".join(
                                    f"{r.get('id','')} | {r.get('status','')} | sub={r.get('subscription','')} | phases={r.get('phase_count')}"
                                    for r in _sched_rows
                                ),
                                language=None,
                            )
                        else:
                            st.caption("Stripe schedules: none returned for this customer/subscription query.")
                        st.caption(
                            "Live sub debug: "
                            f"chosen={_live.get('stripe_subscription_id','') or 'none'} · "
                            f"db={_live.get('stripe_subscription_id_db','') or 'none'}"
                        )
                        _cand = _live.get("debug_subscription_candidates") or []
                        if _cand:
                            st.caption("Stripe candidate subscriptions (id/status/cancel_at_period_end/has_pending_update):")
                            st.code(
                                "\n".join(
                                    f"{c.get('id','')} | {c.get('status','')} | cancel_at_period_end={c.get('cancel_at_period_end')} | has_pending_update={c.get('has_pending_update')}"
                                    for c in _cand
                                ),
                                language=None,
                            )

                        if _pending_plan:
                            st.success(
                                f"Pending downgrade is recorded in app state. Access should remain on {_plan_label} until {_pending_date}."
                            )
                        elif _live.get("has_pending_update") and _live.get("pending_plan"):
                            st.success(
                                f"Pending change detected: app should keep {_db_plan} access until {_stripe_period or 'period end'}, then switch to {_live.get('pending_plan', '').capitalize()}."
                            )
                        else:
                            st.info("No pending Stripe plan change detected right now.")

                st.markdown("---")
                st.markdown("##### Change Plan")
                st.caption("Upgrade your plan here. In-app downgrades are disabled.")

                _PINFO = _bill_data.get("plan_info", {})
                _GAINS = _bill_data.get("gains", {})
                _rank = _bill_data.get("rank", {})
                _cur_rank = _rank.get(_plan_raw, 1)
                _alternatives = _bill_data.get("alternatives", [])

                if not _alternatives:
                    st.info("No upgrade options are available right now.")

                _pcols = st.columns(len(_alternatives)) if _alternatives else []
                for _ci, _pk in enumerate(_alternatives):
                    _pi = _PINFO[_pk]
                    with _pcols[_ci]:
                        st.markdown(
                            "<div style='color:#16a34a;font-size:11px;font-weight:700;text-transform:uppercase;'>↑ Upgrade (Immediate)</div>",
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"**{_pi['label']}** &nbsp; {_pi['price']}")
                        st.caption(_pi['emp'] + " employees")

                        _delta = _GAINS.get((_plan_raw, _pk), [])
                        if _delta:
                            st.markdown(
                                "<div style='font-size:12px;font-weight:600;margin-top:4px;'>You'd gain:</div>",
                                unsafe_allow_html=True,
                            )
                            for _x in _delta:
                                st.markdown(
                                    f"<div style='font-size:12px;color:#16a34a;line-height:1.8;'>+ {_x}</div>",
                                    unsafe_allow_html=True,
                                )

                        st.markdown("")
                        _target_price = _price_map.get(_pk, "")
                        if st.button(
                            f"Upgrade to {_pi['label']}",
                            key=f"switch_plan_{_pk}",
                            use_container_width=True,
                            type="primary",
                            disabled=bool(_pending_plan),
                        ):
                            if not _target_price:
                                st.error(f"Price for {_pi['label']} is not configured.")
                            else:
                                with st.spinner("Requesting plan change in Stripe…"):
                                    _chg = request_plan_change(_target_price, _tid_local)
                                if _chg.get("success"):
                                    st.success("Upgrade submitted. Access and billing should refresh shortly.")
                                    clear_billing_cache()
                                    st.rerun()
                                else:
                                    st.error(_chg.get("error") or "Could not change plan.")
            else:
                st.info("No active subscription found.")
                _app_url = _bill_data.get("app_url", st.context.headers.get("Origin", "http://localhost:8501"))
                try:
                    _portal_url = create_billing_portal_url(return_url=_app_url + "/?portal=return")
                    if _portal_url:
                        _queue_billing_portal_continue(
                            label="Manage Subscription",
                            launch_key="settings_manage_subscription_no_sub",
                            url=_portal_url,
                            feature_context="settings_manage_subscription_no_subscription",
                            current_plan="starter",
                            employee_count=0,
                            employee_limit=0,
                        )
                except Exception:
                    pass
        except Exception as _sub_err:
            _show_user_error(
                "Could not load billing information.",
                next_steps="Refresh the page. If this continues, use Settings later or contact support.",
                technical_detail=traceback.format_exc(),
                category="billing",
            )
            _log_app_error("billing", f"Billing tab load failed: {_sub_err}", detail=traceback.format_exc())

    st.caption("Productivity Planner · Powered by Supply Chain Automation Co")

    with tab_team:
        # ── Team Members & Invite ──────────────────────────────────────────────
        st.subheader("👥 Team Members")
        st.caption("Invite supervisors or managers to your workspace. Everyone on the same team shares the same data.")
        try:
            from database import (
                get_invite_code, regenerate_invite_code as _regen_invite,
                get_team_members, remove_team_member, set_member_role, get_my_role,
            )
            _tid_team = st.session_state.get("tenant_id", "")
            _my_role = get_my_role(_tid_team)
            _is_admin = can_manage_team(_tid_team, _my_role)

            # ── Invite link ────────────────────────────────────────────────────
            _inv_code = get_invite_code(_tid_team)
            if _inv_code:
                _app_origin = st.context.headers.get("Origin", "")
                _inv_link = f"{_app_origin}/?invite={_inv_code}" if _app_origin else f"Invite code: {_inv_code}"
                st.markdown("**Invite link — share this with anyone you want to add to your team:**")
                _safe_link = escape_html(_inv_link)
                st.markdown(
                    f'<div style="background:#1e1e2e;border-radius:6px;padding:10px 14px;'
                    f'font-family:monospace;font-size:13px;color:#ffffff;word-break:break-all;">'
                    f'{_safe_link}</div>',
                    unsafe_allow_html=True,
                )
                st.caption("Anyone who signs up with this link (or enters the code manually) joins your team automatically.")
                if _is_admin:
                    if st.button("🔄 Rotate invite code", key="rotate_invite", type="secondary"):
                        _new_code = _regen_invite(_tid_team)
                        if _new_code:
                            st.success("✓ Invite code rotated — old links no longer work.")
                            st.rerun()
            else:
                st.info("Invite code not available. Run migration 003_team_invites.sql in Supabase SQL Editor.")

            st.divider()

            # ── Member list ────────────────────────────────────────────────────
            _members = get_team_members(_tid_team)
            _current_uid = st.session_state.get("user_id", "")
            if _members:
                st.caption(f"**{len(_members)} member(s) on this team**")
                for _m in _members:
                    _m_id   = _m.get("id", "")
                    _m_name = _m.get("name") or "Unnamed"
                    _m_role = _m.get("role", "member")
                    _m_since = str(_m.get("created_at", ""))[:10]
                    _is_me = (_m_id == _current_uid)
                    mc1, mc2, mc3, mc4 = st.columns([3, 1.5, 1.2, 1])
                    mc1.markdown(f"**{_m_name}**{'&nbsp;&nbsp;*(you)*' if _is_me else ''}", unsafe_allow_html=True)
                    mc2.caption(_m_role.capitalize())
                    mc3.caption(f"Since {_m_since}")
                    if _is_admin and not _is_me:
                        with mc4:
                            _remove_key = f"rm_member_{_m_id}"
                            if st.button("Remove", key=_remove_key, type="secondary"):
                                if remove_team_member(_m_id, _tid_team):
                                    st.success(f"✓ {_m_name} removed from team.")
                                    st.rerun()
                    if _is_admin and not _is_me:
                        _role_key = f"role_{_m_id}"
                        _new_role = st.selectbox(
                            f"Role for {_m_name}",
                            ["member", "admin"],
                            index=0 if _m_role == "member" else 1,
                            key=_role_key,
                            label_visibility="collapsed",
                        )
                        if _new_role != _m_role:
                            if set_member_role(_m_id, _new_role, _tid_team):
                                st.toast(f"✓ {_m_name} is now {_new_role}", icon="✅")
                                st.rerun()
            else:
                st.info("No team members yet — share the invite link above.")

        except Exception as _team_err:
            st.info(f"Team management not available: {_team_err}")
            st.caption("Make sure migrations/003_team_invites.sql has been run in Supabase.")

        st.divider()

        # ── Preserved: chart/labor/audit/cleanup settings ─────────────────────
        st.subheader("🎯 Department Targets")
        st.caption("Set optional UPH targets by department/process. These are used as comparison baselines when available.")
        try:
            from goals import clear_process_target, get_all_targets, set_process_target

            _target_rows = []
            _targets = dict(get_all_targets(_tid_team) or {})
            for _dept_name in sorted(_targets.keys()):
                _target_rows.append(
                    {
                        "Department": str(_dept_name),
                        "Target UPH": float(_targets.get(_dept_name) or 0),
                    }
                )

            if _target_rows:
                st.dataframe(_target_rows, use_container_width=True, hide_index=True)
            else:
                st.caption("No department targets configured yet.")

            _dept_col1, _dept_col2 = st.columns([2, 1])
            _dept_name_input = _dept_col1.text_input(
                "Department/process",
                key="settings_target_department_name",
                placeholder="e.g. Picking",
            )
            _target_input = _dept_col2.number_input(
                "Target UPH",
                min_value=0.0,
                step=0.5,
                key="settings_target_uph_value",
            )

            _t1, _t2 = st.columns(2)
            if _t1.button("Save department target", key="settings_save_department_target", use_container_width=True):
                _name = str(_dept_name_input or "").strip()
                if not _name:
                    st.warning("Enter a department/process name before saving.")
                else:
                    set_process_target(_name, float(_target_input or 0), tenant_id=_tid_team)
                    st.success(f"✓ Saved target for {_name}.")
                    st.rerun()

            _existing_target_names = sorted([str(name) for name in _targets.keys() if str(name).strip()])
            _clear_choice = _t2.selectbox(
                "Remove configured target",
                ["—"] + _existing_target_names,
                key="settings_clear_department_target_choice",
            )
            if _t2.button("Remove target", key="settings_clear_department_target", use_container_width=True):
                if _clear_choice == "—":
                    st.warning("Select a configured department target to remove.")
                else:
                    clear_process_target(_clear_choice, tenant_id=_tid_team)
                    st.success(f"✓ Removed target for {_clear_choice}.")
                    st.rerun()
        except Exception as _targets_err:
            _log_app_error("settings", f"Department targets controls unavailable: {_targets_err}", detail=traceback.format_exc(), severity="warning")

        st.divider()
        # ── Preserved: chart/labor/audit/cleanup settings ─────────────────────
        st.subheader("⚙️ App Settings")
        st.caption("Configure team-level behavior, labor assumptions, and cleanup tools.")
        _chart_months_default = int(st.session_state.get("chart_months", 12) or 12)
        st.session_state["chart_months"] = st.slider(
            "History window used across charts (months)",
            0,
            60,
            _chart_months_default,
        )
        st.caption("This limits how many months of historical data are included in dashboard/productivity trend charts.")
        st.session_state["smart_merge"] = True   # always on
        from settings import Settings as _AppSettings
        _tzs = _AppSettings()

        st.divider()
        st.subheader(" Labor Cost Settings")
        st.caption("Used to calculate the financial impact of performance gaps.")
        _cur_wage = _tzs.get("avg_hourly_wage", 18.0)
        _wage_input = st.number_input(
            "Average hourly wage ($)",
            min_value=0.0,
            value=_cur_wage,
            step=1.0,
            key="settings_hourly_wage",
            help="Used to calculate labor cost impact across all reports and dashboards"
        )
        if st.button("Save wage settings", key="save_wage"):
            _tzs.set("avg_hourly_wage", float(_wage_input))
            st.success(f"✓ Average hourly wage set to ${_wage_input:.2f}")

        st.divider()
        st.subheader("📋 Audit log")
        st.caption("Recent changes to goals, flags, and journal entries.")
        if st.button("View recent activity", key="view_audit"):
            try:
                import os as _os
                log_path = _tenant_log_path("dpd_audit")
                if _os.path.exists(log_path):
                    lines = open(log_path, encoding="utf-8").readlines()
                    recent = lines[-50:] if len(lines) > 50 else lines
                    st.code("".join(reversed(recent)), language=None)
                else:
                    st.info("No audit log yet — changes will appear here after goals or flags are modified.")
            except Exception as _ae:
                _show_user_error(
                    "Could not read the audit log right now.",
                    next_steps="Try again in a moment. If this continues, contact support.",
                    technical_detail=traceback.format_exc(),
                    category="settings",
                )

        st.divider()
        st.subheader("🧹 Data cleanup")
        st.caption("Remove duplicate UPH history rows created by running the pipeline multiple times on the same data.")
        if "confirm_cleanup" not in st.session_state:
            st.session_state.confirm_cleanup = False
        if not st.session_state.confirm_cleanup:
            if st.button("Remove duplicate UPH history rows", type="secondary"):
                st.session_state.confirm_cleanup = True
                st.rerun()
        else:
            st.warning("⚠️ This will permanently delete duplicate rows. Are you sure?")
            cc1, cc2 = st.columns(2)
            if cc1.button("Yes, delete duplicates", type="primary", use_container_width=True):
                with st.spinner("Scanning and removing duplicates…"):
                    try:
                        from database import delete_duplicate_uph_history
                        deleted = delete_duplicate_uph_history()
                        _raw_cached_uph_history.clear()
                        st.session_state.confirm_cleanup = False
                        if deleted:
                            st.success(f"✓ Removed {deleted:,} duplicate row(s).")
                        else:
                            st.success("✓ No duplicates found — data is clean.")
                    except BaseException as _ce:
                        st.session_state.confirm_cleanup = False
                        _show_user_error(
                            "Cleanup failed.",
                            next_steps="Please retry. If this continues, contact support before re-running cleanup.",
                            technical_detail=traceback.format_exc(),
                            category="cleanup",
                        )
                        _log_app_error("cleanup", f"Duplicate cleanup failed: {repr(_ce)[:500]}", detail=traceback.format_exc())
            if cc2.button("Cancel", use_container_width=True):
                st.session_state.confirm_cleanup = False
                st.rerun()

    with tab_account:
        st.subheader("Account")
        st.caption("Manage your sign-in credentials and personal data controls.")
        _uname = st.session_state.get("user_name", "")
        _urole = st.session_state.get("user_role", "member")
        if _uname:
            st.caption(f"Signed in as **{_uname}** · {_urole}")

        # ── Change password ──────────────────────────────────────────────
        st.markdown("**Change password**")
        with st.form("change_pw_form", clear_on_submit=True):
            cur_pw   = st.text_input("Current password", type="password")
            new_pw   = st.text_input("New password", type="password",
                                      placeholder="Min 6 characters")
            conf_pw  = st.text_input("Confirm new password", type="password")
            if st.form_submit_button("Update password", type="primary"):
                if not cur_pw:
                    st.warning("Enter your current password.")
                elif len(new_pw) < 6:
                    st.warning("New password must be at least 6 characters.")
                elif new_pw != conf_pw:
                    st.warning("Passwords don't match.")
                else:
                    try:
                        from database import get_supabase_credentials
                        from supabase import create_client as _sc
                        SUPABASE_URL, SUPABASE_KEY = get_supabase_credentials()
                        _sb = _sc(SUPABASE_URL, SUPABASE_KEY)
                        sess = st.session_state.get("supabase_session", {})
                        # Re-authenticate with current password to verify identity
                        _sb.auth.sign_in_with_password({
                            "email": st.session_state.get("user_email", _uname),
                            "password": cur_pw,
                        })
                        # Set session and update password
                        _sb.auth.set_session(sess["access_token"], sess["refresh_token"])
                        _sb.auth.update_user({"password": new_pw})
                        st.success("✓ Password updated.")
                    except Exception as _cpe:
                        _show_user_error(
                            "Could not change password right now.",
                            next_steps="Verify your current password and try again.",
                            technical_detail=traceback.format_exc(),
                            category="auth",
                        )
                        _log_app_error("auth", f"Password change failed: {_cpe}")

        # ── Data export (GDPR) ────────────────────────────────────────────
        st.divider()
        st.markdown("**Your data**")
        st.caption("Download a copy of all your data, or permanently delete your account.")

        if st.button("📥 Export all my data", key="gdpr_export"):
            with st.spinner("Collecting your data…"):
                try:
                    from database import export_all_tenant_data
                    _export = export_all_tenant_data()
                    if _export:
                        _json_bytes = json.dumps(_export, indent=2, default=str).encode("utf-8")
                        st.download_button(
                            "⬇️ Download JSON",
                            data=_json_bytes,
                            file_name="my_data_export.json",
                            mime="application/json",
                            key="gdpr_download",
                        )
                    else:
                        st.info("No data found for your account.")
                except Exception as _gdpr_e:
                    _show_user_error(
                        "Could not export your data right now.",
                        next_steps="Please retry in a moment. If this continues, contact support.",
                        technical_detail=traceback.format_exc(),
                        category="gdpr",
                    )
                    _log_app_error("gdpr", f"Data export failed: {_gdpr_e}", detail=traceback.format_exc())

        # ── Account deletion ─────────────────────────────────────────────
        if "confirm_delete_account" not in st.session_state:
            st.session_state.confirm_delete_account = False

        if not st.session_state.confirm_delete_account:
            if st.button("🗑️ Delete my account and all data", type="secondary", key="gdpr_delete_start"):
                st.session_state.confirm_delete_account = True
                st.rerun()
        else:
            st.error("⚠️ This will **permanently delete** your account, all employees, UPH history, goals, settings, and email config. This cannot be undone.")
            _del_confirm = st.text_input(
                "Type DELETE to confirm", key="gdpr_delete_confirm",
                placeholder="DELETE",
            )
            dc1, dc2 = st.columns(2)
            if dc1.button("Permanently delete everything", type="primary", use_container_width=True, key="gdpr_delete_go"):
                if _del_confirm == "DELETE":
                    with st.spinner("Deleting all data…"):
                        try:
                            from database import delete_all_tenant_data
                            delete_all_tenant_data()
                            _full_sign_out()
                            st.rerun()
                        except Exception as _del_e:
                            _show_user_error(
                                "Could not delete account data right now.",
                                next_steps="Please retry. If this continues, contact support immediately.",
                                technical_detail=traceback.format_exc(),
                                category="gdpr",
                            )
                            _log_app_error("gdpr", f"Account deletion failed: {_del_e}", detail=traceback.format_exc())
                else:
                    st.warning("Type DELETE exactly to confirm.")
            if dc2.button("Cancel", use_container_width=True, key="gdpr_delete_cancel"):
                st.session_state.confirm_delete_account = False
                st.rerun()

        # ── Sign out ─────────────────────────────────────────────────────
        st.divider()
        if _render_sign_out_button("settings_account", type="secondary"):
            _full_sign_out()
            st.rerun()

    with tab_integrations:
        st.subheader("Integrations")
        st.caption("Connected tools and external services.")
        st.caption("Stripe billing integration is managed in the Billing tab.")

    # ── Advanced tab ─────────────────────────────────────────────────────
    with tab_advanced:
        # ── Admin: operational reset (keep account/team) ─────────────────
        st.subheader("🧨 Reset tenant data (keep account/team)")
        st.caption(
            "Admin-only reset for demo/testing. This clears operational records, "
            "including imports, actions, derived snapshots/signals, and error logs, "
            "while keeping your tenant/account/team/auth records intact."
        )
        try:
            from database import get_my_role, reset_tenant_operational_data

            _reset_tid = st.session_state.get("tenant_id", "")
            _reset_role = get_my_role(_reset_tid)
            _can_reset_tenant_data = can_manage_team(_reset_tid, _reset_role)

            if _can_reset_tenant_data:
                if "confirm_reset_tenant_operational" not in st.session_state:
                    st.session_state.confirm_reset_tenant_operational = False

                if not st.session_state.confirm_reset_tenant_operational:
                    if st.button(
                        "Reset tenant data but keep account/team",
                        key="tenant_operational_reset_start",
                        type="secondary",
                    ):
                        st.session_state.confirm_reset_tenant_operational = True
                        st.rerun()
                else:
                    st.error(
                        "⚠️ This permanently deletes operational tenant data (imports, actions, "
                        "derived signals/snapshots, and diagnostics). Account/team/auth is preserved."
                    )
                    _reset_phrase = st.text_input(
                        "Type RESET TENANT DATA to confirm",
                        key="tenant_operational_reset_phrase",
                        placeholder="RESET TENANT DATA",
                    )
                    rc1, rc2 = st.columns(2)
                    if rc1.button(
                        "Permanently reset operational data",
                        key="tenant_operational_reset_go",
                        type="primary",
                        use_container_width=True,
                    ):
                        if _reset_phrase == "RESET TENANT DATA":
                            with st.spinner("Resetting tenant operational data…"):
                                try:
                                    _result = reset_tenant_operational_data(_reset_tid)
                                    from cache import bust_cache as _bust_cache

                                    _bust_cache()
                                    for _key in [
                                        "_import_step3_preview_cache",
                                        "_import_complete_summary",
                                        "_last_import_undo",
                                        "_today_precomputed_payload",
                                        "_post_import_refresh_pending",
                                        "data_sessions",
                                        "submission_plan",
                                        "split_overrides",
                                    ]:
                                        st.session_state.pop(_key, None)
                                    st.session_state.confirm_reset_tenant_operational = False
                                    if _result.get("errors"):
                                        st.warning(
                                            "Reset completed with some table errors. "
                                            "Review error log details below."
                                        )
                                    else:
                                        st.success(
                                            "✓ Tenant operational data reset complete. "
                                            "Account/team/auth records were preserved."
                                        )
                                    st.rerun()
                                except Exception as _reset_err:
                                    st.session_state.confirm_reset_tenant_operational = False
                                    _show_user_error(
                                        "Could not reset tenant operational data right now.",
                                        next_steps="Please retry. If this continues, contact support.",
                                        technical_detail=traceback.format_exc(),
                                        category="cleanup",
                                    )
                                    _log_app_error(
                                        "cleanup",
                                        f"Tenant operational reset failed: {_reset_err}",
                                        detail=traceback.format_exc(),
                                    )
                        else:
                            st.warning("Type RESET TENANT DATA exactly to confirm.")

                    if rc2.button(
                        "Cancel",
                        key="tenant_operational_reset_cancel",
                        use_container_width=True,
                    ):
                        st.session_state.confirm_reset_tenant_operational = False
                        st.rerun()
            else:
                st.info("Admin role required for tenant reset.")
        except Exception as _reset_ui_err:
            _log_app_error(
                "cleanup",
                f"Tenant reset controls unavailable: {_reset_ui_err}",
                detail=traceback.format_exc(),
                severity="warning",
            )

        # ── Error log ─────────────────────────────────────────────────────
        st.subheader("Error Log")
        st.caption("Diagnostics and troubleshooting tools for admins.")
        st.caption("Recent errors and warnings logged by the application. Use this to diagnose issues.")

        # Filters
        fc1, fc2, fc3 = st.columns(3)
        _err_cat = fc1.selectbox("Category", ["All", "login", "pipeline", "email", "employees",
                                               "clients", "productivity", "gdpr", "auth",
                                               "cleanup", "import", "database", "password_reset"],
                                 key="err_cat_filter")
        _err_sev = fc2.selectbox("Severity", ["All", "error", "warning", "info"], key="err_sev_filter")
        _err_limit = fc3.number_input("Show last N", min_value=10, max_value=500, value=50, step=10, key="err_limit")

        try:
            from database import get_error_reports, clear_error_reports
            _cat_arg = "" if _err_cat == "All" else _err_cat
            _sev_arg = "" if _err_sev == "All" else _err_sev
            errors = get_error_reports(limit=_err_limit, category=_cat_arg, severity=_sev_arg)

            if errors:
                st.markdown(f"**{len(errors)}** error(s) found")

                # Summary badges
                _err_count, _warn_count, _info_count = summarize_error_counts(errors)
                bc1, bc2, bc3 = st.columns(3)
                bc1.metric("Errors", _err_count)
                bc2.metric("Warnings", _warn_count)
                bc3.metric("Info", _info_count)

                st.divider()

                _SEV_ICON = {"error": "🔴", "warning": "🟡", "info": "🔵"}

                # Capture browser UTC offset once via query params (survives rerun)
                _tz_qp = st.query_params.get("_tz", None)
                if _tz_qp is not None:
                    try:
                        st.session_state["_tz_offset_min"] = int(_tz_qp)
                    except Exception:
                        pass

                for err in errors:
                    sev = err.get("severity", "error")
                    icon = _SEV_ICON.get(sev, "⚪")
                    cat = err.get("category", "unknown")
                    msg = err.get("message", "")
                    ts = format_error_timestamp(err.get("created_at", ""), st.session_state.get("_tz_offset_min"))
                    user = err.get("user_email", "")

                    with st.expander(f"{icon} **[{cat}]** {msg[:120]}{'…' if len(msg) > 120 else ''} — {ts}"):
                        st.markdown(f"**Category:** {cat}")
                        st.markdown(f"**Severity:** {sev}")
                        st.markdown(f"**Time:** {ts}")
                        if user:
                            st.markdown(f"**User:** {user}")
                        st.markdown(f"**Message:** {msg}")
                        detail = err.get("detail", "")
                        if detail:
                            st.markdown("**Detail / Stack trace:**")
                            st.code(detail, language=None)

                st.divider()
                if st.button("🗑️ Clear all error logs", type="secondary", key="clear_errors"):
                    clear_error_reports()
                    st.success("✓ Error log cleared.")
                    st.rerun()
            else:
                st.success("No errors logged. Everything is running smoothly.")
        except Exception as _err_ui_err:
            st.warning(f"Could not load error reports: {_err_ui_err}")
            st.caption("The error_reports table may not exist yet. Run the migration in migrations/001_setup.sql.")


