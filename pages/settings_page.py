from app import (
    _bust_cache,
    _dl_auto_detect,
    _dl_parse_csv,
    _full_sign_out,
    _get_current_plan,
    _log_app_error,
    _render_sign_out_button,
    _set_auth_cookies,
    _tenant_log_path,
    datetime,
    json,
    re,
    st,
    time,
    traceback,
)

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
            from database import (
                get_subscription, get_employee_count, get_employee_limit,
                create_billing_portal_url, get_live_stripe_subscription_status,
                modify_subscription,
                _get_config,
            )
            _tid_local = st.session_state.get("tenant_id", "")
            sub = get_subscription(_tid_local)
            if sub:
                _plan_raw   = sub.get("plan", "unknown").lower()
                _plan_label = _plan_raw.capitalize()
                _status     = sub.get("status", "unknown")
                _limit      = sub.get("employee_limit", 0)
                _limit_str  = "Unlimited" if _limit == -1 else str(_limit)
                _emp_count  = get_employee_count(_tid_local)
                _period_end = sub.get("current_period_end", "")

                # ── Current plan banner ───────────────────────────────
                _pc = {"starter": "#6b7280", "pro": "#2563eb", "business": "#7c3aed"}.get(_plan_raw, "#6b7280")
                _renew_str = ""
                if _period_end:
                    try:
                        _pe = datetime.fromisoformat(_period_end.replace("Z", "+00:00"))
                        _renew_str = _pe.strftime("%b %d, %Y")
                    except Exception:
                        pass
                st.markdown(f"""
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
                    <div style="font-size:12px;color:#444;">{_status.replace("_"," ").title()}</div>
                    {"<div style='font-size:12px;color:#888;'>Renews " + _renew_str + "</div>" if _renew_str else ""}
                  </div>
                </div>
                """, unsafe_allow_html=True)

                if sub.get("cancel_at_period_end"):
                    st.warning("Your subscription will cancel at the end of the current period.")

                _app_url    = st.context.headers.get("Origin", "http://localhost:8501")
                _return_url = _app_url + "/?portal=return"
                _portal_url = create_billing_portal_url(return_url=_return_url)
                _manage_plan_url = create_billing_portal_url(
                    return_url=_return_url,
                    flow="subscription_update",
                ) or _portal_url

                # Plan-targeted deep links so Stripe opens the intended update flow.
                _price_map = {
                    "starter": _get_config("STRIPE_PRICE_STARTER") or "",
                    "pro": _get_config("STRIPE_PRICE_PRO") or "",
                    "business": _get_config("STRIPE_PRICE_BUSINESS") or "",
                }

                if _manage_plan_url:
                    st.link_button("Manage Subscription (change plan tier)",
                                   _manage_plan_url, use_container_width=True, type="primary")
                else:
                    st.info("Billing portal not available. Contact support.")

                if _portal_url:
                    st.link_button("Open Billing Portal (card, invoices, cancel)",
                                   _portal_url, use_container_width=True)

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
                        st.write(f"Effective access now: {_live.get('db_plan', _plan_raw).capitalize()} ({_live.get('db_status', _status)})")
                        st.write(f"Stripe live plan: {_live.get('current_plan', '').capitalize()} | Stripe status: {_live.get('status', '')}")
                        if _stripe_period:
                            st.write(f"Current billing period ends: {_stripe_period}")
                        if _live.get("has_pending_update") and _live.get("pending_plan"):
                            st.success(
                                f"Pending change detected: the app should keep {_live.get('db_plan', _plan_raw).capitalize()} access until {_stripe_period or 'period end'}, then switch to {_live.get('pending_plan', '').capitalize()}."
                            )
                        else:
                            st.info("No pending Stripe plan change detected right now.")

                # ── Plan comparison ───────────────────────────────────
                st.markdown("---")
                st.markdown("##### Change Plan")
                st.caption("Upgrade options are shown below. Downgrades/cancel are handled in Billing Portal.")

                _PORD  = ["starter", "pro", "business"]
                _PINFO = {
                    "starter":  {"label": "Starter",  "price": "$30/mo", "emp": "Up to 25",  "clr": "#6b7280"},
                    "pro":      {"label": "Pro",      "price": "$59/mo", "emp": "Up to 100", "clr": "#2563eb"},
                    "business": {"label": "Business", "price": "$99/mo", "emp": "Unlimited", "clr": "#7c3aed"},
                }
                _FEATS = {
                    "starter":  ["CSV upload & auto-detection", "Dashboard & rankings",
                                 "Dept-level UPH tracking", "Weekly email reports", "Excel & PDF exports"],
                    "pro":      ["Everything in Starter", "Goal setting & UPH targets",
                                 "Employee trend analysis", "Underperformer flagging & alerts",
                                 "Custom date range reports",
                                 "Coaching notes per employee"],
                    "business": ["Everything in Pro", "Unlimited employees"],
                }
                # What you GAIN when moving from key[0] → key[1]
                _GAINS = {
                    ("starter", "pro"):      ["75 more employee slots (25 → 100)", "Goal setting & UPH targets",
                                              "Employee trend analysis", "Underperformer alerts",
                                              "Custom date ranges",
                                              "Coaching notes per employee"],
                    ("pro", "business"):     ["Unlimited employees (100 → ∞)"],
                    ("starter", "business"): ["Unlimited employees", "Goal setting & UPH targets",
                                              "Employee trend analysis", "Underperformer alerts",
                                              "Custom date ranges", "Coaching notes per employee"],
                    ("pro", "starter"):      ["75 employee slots (100 → 25)", "Goal setting & UPH targets",
                                              "Employee trend analysis", "Underperformer alerts",
                                              "Custom date ranges",
                                              "Coaching notes per employee"],
                    ("business", "pro"):     ["Unlimited employees (capped at 100)"],
                    ("business", "starter"): ["Unlimited employees", "Goal setting & UPH targets",
                                              "Employee trend analysis", "Underperformer alerts",
                                              "Custom date ranges", "Coaching notes per employee"],
                }

                _rank = {"starter": 1, "pro": 2, "business": 3}
                _cur_rank = _rank.get(_plan_raw, 1)
                _alternatives = [p for p in _PORD if _rank.get(p, 1) > _cur_rank]
                if not _alternatives:
                    st.info("You are already on the highest tier. Use Billing Portal for billing, invoices, or cancellation.")
                _pcols = st.columns(len(_alternatives)) if _alternatives else []
                for _ci, _pk in enumerate(_alternatives):
                    _pi    = _PINFO[_pk]
                    with _pcols[_ci]:
                        _is_up = True
                        _badge_html = "<div style='color:#16a34a;font-size:11px;font-weight:700;text-transform:uppercase;'>↑ Upgrade</div>"
                        st.markdown(_badge_html, unsafe_allow_html=True)
                        st.markdown(f"**{_pi['label']}** &nbsp; {_pi['price']}")
                        st.caption(_pi['emp'] + " employees")

                        _delta = _GAINS.get((_plan_raw, _pk), [])
                        if _delta:
                            _label = "You'd gain:"
                            _clr = "#16a34a"
                            st.markdown(
                                f"<div style='font-size:12px;font-weight:600;margin-top:4px;'>{_label}</div>",
                                unsafe_allow_html=True,
                            )
                            for _x in _delta:
                                _prefix = "+"
                                st.markdown(
                                    f"<div style='font-size:12px;color:{_clr};line-height:1.8;'>{_prefix} {_x}</div>",
                                    unsafe_allow_html=True,
                                )

                        st.markdown("")
                        _target_price = _price_map.get(_pk, "")
                        _btn_label = f"Upgrade to {_pi['label']}"
                        if st.button(_btn_label, key=f"switch_plan_{_pk}", use_container_width=True, type="primary"):
                            if not _target_price:
                                st.error(f"Price for {_pi['label']} is not configured.")
                            else:
                                with st.spinner("Requesting plan change in Stripe…"):
                                    _ok, _msg = modify_subscription(_target_price, _tid_local)
                                if _ok:
                                    st.success("Plan change submitted. Status will refresh shortly.")
                                    st.session_state.pop("_sub_check_result", None)
                                    st.session_state.pop("_sub_check_ts", None)
                                    st.session_state.pop("_current_plan", None)
                                    st.session_state.pop("_current_plan_ts", None)
                                    _bust_cache()
                                    st.rerun()
                                else:
                                    st.error(_msg or "Could not change plan.")
            else:
                st.info("No active subscription found.")
                _app_url = st.context.headers.get("Origin", "http://localhost:8501")
                try:
                    _portal_url = create_billing_portal_url(return_url=_app_url + "/?portal=return")
                    if _portal_url:
                        st.link_button("Manage Subscription", _portal_url,
                                       use_container_width=True, type="primary")
                except Exception:
                    pass
        except Exception as _sub_err:
            st.error(f"Could not load subscription info: {_sub_err}")

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
            _is_admin = (_my_role == "admin" or _get_current_plan() == "admin")

            # ── Invite link ────────────────────────────────────────────────────
            _inv_code = get_invite_code(_tid_team)
            if _inv_code:
                _app_origin = st.context.headers.get("Origin", "")
                _inv_link = f"{_app_origin}/?invite={_inv_code}" if _app_origin else f"Invite code: {_inv_code}"
                st.markdown("**Invite link — share this with anyone you want to add to your team:**")
                _safe_link = _inv_link.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
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
                st.error(f"Could not read audit log: {_ae}")

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
                        try:    st.error(f"Cleanup error: {repr(_ce)[:200]}")
                        except Exception: st.error("Cleanup failed.")
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
                        st.error(f"Failed: {_cpe}")
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
                    st.error(f"Export failed: {_gdpr_e}")
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
                            st.error(f"Deletion failed: {_del_e}")
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
        st.info("Email delivery is configured in the Email Setup page.")
        st.caption("Stripe billing integration is managed in the Billing tab.")

    # ── Advanced tab ─────────────────────────────────────────────────────
    with tab_advanced:
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
                _err_count = sum(1 for e in errors if e.get("severity") == "error")
                _warn_count = sum(1 for e in errors if e.get("severity") == "warning")
                _info_count = sum(1 for e in errors if e.get("severity") == "info")
                bc1, bc2, bc3 = st.columns(3)
                bc1.metric("Errors", _err_count)
                bc2.metric("Warnings", _warn_count)
                bc3.metric("Info", _info_count)

                st.divider()

                _SEV_ICON = {"error": "🔴", "warning": "🟡", "info": "🔵"}

                def _fmt_ts(raw_ts: str) -> str:
                    """Convert UTC ISO timestamp to browser-local time via JS offset stored in session."""
                    try:
                        from datetime import timezone as _tz, timedelta as _td
                        import datetime as _dt_mod
                        raw = str(raw_ts or "").replace("Z", "+00:00")
                        if not raw:
                            return ""
                        _utc_dt = _dt_mod.datetime.fromisoformat(raw)
                        if _utc_dt.tzinfo is None:
                            _utc_dt = _utc_dt.replace(tzinfo=_tz.utc)
                        # Use tz offset (minutes) stored from JS component, if available
                        _tz_offset_min = int(st.session_state.get("_tz_offset_min", 0))
                        _local_dt = _utc_dt.astimezone(_tz(offset=_td(minutes=-_tz_offset_min)))
                        return _local_dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        return str(raw_ts or "")[:19].replace("T", " ")

                # Capture browser UTC offset once via query params (survives rerun)
                _tz_qp = st.query_params.get("_tz", None)
                if _tz_qp is not None:
                    try:
                        st.session_state["_tz_offset_min"] = int(_tz_qp)
                    except Exception:
                        pass
                if "_tz_offset_min" not in st.session_state:
                    st.session_state["_tz_offset_min"] = 0

                for err in errors:
                    sev = err.get("severity", "error")
                    icon = _SEV_ICON.get(sev, "⚪")
                    cat = err.get("category", "unknown")
                    msg = err.get("message", "")
                    ts = _fmt_ts(err.get("created_at", ""))
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


# ══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

_SUSPICIOUS_NAME_RE = re.compile(r"(<\s*/?\s*script\b|drop\s+table|;--|javascript:)", re.IGNORECASE)


def _normalize_label_text(value, max_len: int = 64) -> str:
    """Normalize UI labels so imported text stays readable and safe-looking."""
    s = str(value or "")
    s = s.replace("\x00", " ")
    s = re.sub(r"[\r\n\t]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("|", " ").replace("<", " ").replace(">", " ")
    s = s.strip(" '\"")
    if len(s) > max_len:
        s = s[: max_len - 3].rstrip() + "..."
    return s or "Unknown"


def _sanitize_employee_name(raw_name, emp_id: str = "") -> tuple[str, bool]:
    """Return a cleaned display name and a flag indicating suspicious input."""
    raw = str(raw_name or "")
    suspicious = bool(_SUSPICIOUS_NAME_RE.search(raw))
    cleaned = _normalize_label_text(raw, max_len=64)
    if suspicious:
        fallback = f"Employee {emp_id}".strip() if emp_id else "Employee"
        return _normalize_label_text(fallback, max_len=64), True
    return cleaned, False

def _parse_csv(raw: bytes) -> tuple[list[dict], list[str]]:
    """Parse CSV bytes → (rows, headers). Delegates to data_loader."""
    hdrs, rows = _dl_parse_csv(raw)
    return rows, hdrs


def _auto_detect(headers: list) -> dict:
    """Auto-detect CSV column mapping. Delegates to data_loader."""
    return _dl_auto_detect(headers)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

# ── Access control ────────────────────────────────────────────────────────────
# Set APP_PASSWORD in Settings page. Leave blank to disable the gate.

def _check_access() -> bool:
    """Return True if the user is authenticated (or no password is set)."""
    pw = st.session_state.get("app_password_set", "")
    if not pw:
        return True   # no password configured — open access
    if st.session_state.get("authenticated"):
        return True   # already logged in this session

    st.markdown("""
    <div style="max-width:400px;margin:80px auto;background:#fff;
                border:1px solid #E2EBF4;border-radius:12px;padding:36px;">
      <div style="font-size:22px;font-weight:700;color:#0F2D52;
                  margin-bottom:24px;">📦 Productivity Planner</div>
    </div>""", unsafe_allow_html=True)

    entered = st.text_input("Password", type="password",
                             placeholder="Enter your access password",
                             key="login_input")
    if st.button("Sign in", type="primary"):
        if entered == pw:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_LOCKOUT_SECONDS = 900  # 15 minutes


def _check_login_lockout() -> bool:
    """Return True if the user is locked out from too many failed login attempts."""
    attempts = st.session_state.get("_login_attempts", 0)
    lockout_until = st.session_state.get("_login_lockout_until", 0)
    if lockout_until and time.time() < lockout_until:
        remaining = int(lockout_until - time.time())
        mins = remaining // 60
        secs = remaining % 60
        st.error(f"Too many failed attempts. Try again in {mins}m {secs}s.")
        return True
    # Reset lockout if time has passed
    if lockout_until and time.time() >= lockout_until:
        st.session_state["_login_attempts"] = 0
        st.session_state["_login_lockout_until"] = 0
    return False


def _record_failed_login():
    """Increment failed login counter and lock out if threshold reached."""
    attempts = st.session_state.get("_login_attempts", 0) + 1
    st.session_state["_login_attempts"] = attempts
    if attempts >= _LOGIN_MAX_ATTEMPTS:
        st.session_state["_login_lockout_until"] = time.time() + _LOGIN_LOCKOUT_SECONDS
        st.error(f"Account locked for 15 minutes after {_LOGIN_MAX_ATTEMPTS} failed attempts.")
    else:
        remaining = _LOGIN_MAX_ATTEMPTS - attempts
        st.error(f"Invalid email or password. {remaining} attempt(s) remaining.")


def _login_page():
    """Supabase Auth login screen — shown when no valid session exists."""

    st.markdown("""
    <div style="max-width:400px;margin:80px auto 0;text-align:center;">
      <div style="background:#0F2D52;border-radius:12px;padding:32px 36px;">
        <div style="font-size:28px;margin-bottom:4px;">📦</div>
        <div style="font-size:20px;font-weight:700;color:#fff;letter-spacing:-.02em;">
          Productivity Planner
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Password reset mode ───────────────────────────────────────────
    if st.session_state.get("_show_reset_pw"):
        st.markdown("<div style='max-width:400px;margin:24px auto 0;'>", unsafe_allow_html=True)

        # Sub-mode: paste reset link ────────────────────────────────────
        if st.session_state.get("_show_paste_link"):
            # If we already verified, show password form directly
            if st.session_state.get("_recovery_access_token"):
                st.subheader("Set new password")
                new_pw  = st.text_input("New password", type="password", key="paste_new_pw")
                conf_pw = st.text_input("Confirm password", type="password", key="paste_conf_pw")
                if st.button("Update password", type="primary", use_container_width=True, key="paste_update_pw"):
                    if not new_pw or len(new_pw) < 6:
                        st.warning("Password must be at least 6 characters.")
                    elif new_pw != conf_pw:
                        st.warning("Passwords do not match.")
                    else:
                        try:
                            import requests as _req
                            from database import get_supabase_credentials
                            SUPABASE_URL, SUPABASE_KEY = get_supabase_credentials()
                            _upd_resp = _req.put(
                                f"{SUPABASE_URL}/auth/v1/user",
                                json={"password": new_pw},
                                headers={
                                    "apikey": SUPABASE_KEY,
                                    "Authorization": f"Bearer {st.session_state['_recovery_access_token']}",
                                    "Content-Type": "application/json",
                                },
                                timeout=10,
                            )
                            if _upd_resp.status_code == 200:
                                st.session_state.pop("_recovery_access_token", None)
                                st.session_state.pop("_show_paste_link", None)
                                st.session_state.pop("_show_reset_pw", None)
                                st.success("Password updated! Redirecting to sign in...")
                                time.sleep(2)
                                st.rerun()
                            else:
                                st.error(f"Failed to update password: {_upd_resp.text}")
                        except Exception as _upe:
                            st.error(f"Failed to update password: {_upe}")
                st.markdown("</div>", unsafe_allow_html=True)
                st.stop()

            # Step 1: paste the link
            st.subheader("Paste your reset link")
            st.caption("Open the reset email, copy the full link, and paste it below.")
            _paste_url = st.text_input("Reset link from email", placeholder="Paste the full URL from your email", key="paste_reset_url")
            pc1, pc2 = st.columns(2)
            if pc1.button("Continue", type="primary", use_container_width=True):
                if not _paste_url.strip():
                    st.warning("Paste the link from your reset email.")
                else:
                    from urllib.parse import parse_qs, urlparse
                    _parsed = urlparse(_paste_url.strip())
                    _at, _rt = "", ""
                    _paste_err = ""

                    # Case 1: URL fragment has access_token (redirected URL)
                    if _parsed.fragment:
                        _fp = parse_qs(_parsed.fragment)
                        _at = (_fp.get("access_token") or [""])[0]
                        _rt = (_fp.get("refresh_token") or [""])[0]

                    # Case 2: Supabase verify URL with ?token=...&type=recovery
                    if not _at and _parsed.query:
                        _qp2 = parse_qs(_parsed.query)
                        _verify_token = (_qp2.get("token") or [""])[0]
                        _verify_type  = (_qp2.get("type") or [""])[0]
                        if _verify_token and _verify_type == "recovery":
                            try:
                                import requests as _req
                                from database import get_supabase_credentials
                                SUPABASE_URL, SUPABASE_KEY = get_supabase_credentials()
                                _vresp = _req.post(
                                    f"{SUPABASE_URL}/auth/v1/verify",
                                    json={"token_hash": _verify_token, "type": "recovery"},
                                    headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"},
                                    timeout=10,
                                )
                                if _vresp.status_code == 200:
                                    _vdata = _vresp.json()
                                    _at = _vdata.get("access_token", "")
                                    _rt = _vdata.get("refresh_token", "")
                                else:
                                    _paste_err = f"Supabase returned {_vresp.status_code}: {_vresp.text[:150]}"
                            except Exception as _ve:
                                _paste_err = f"Verify failed: {_ve}"
                                _log_app_error("password_reset", f"Verify API error: {_ve}")
                        elif not _verify_token:
                            _paste_err = "No token found in the URL."
                        elif _verify_type != "recovery":
                            _paste_err = f"Wrong link type: '{_verify_type}' (expected 'recovery')."

                    if _at:
                        # Store token and rerun to show password form
                        st.session_state["_recovery_access_token"] = _at
                        st.rerun()
                    else:
                        st.error(_paste_err or "Could not find a reset token in that link.")
            if pc2.button("Back", use_container_width=True):
                st.session_state["_show_paste_link"] = False
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
            return

        # Sub-mode: request reset email ─────────────────────────────────
        st.subheader("Reset your password")
        st.caption("Enter your email address and we'll send you a password reset link.")
        reset_email = st.text_input("Email", placeholder="you@company.com", key="reset_email")
        rc1, rc2 = st.columns(2)
        if rc1.button("Send reset link", type="primary", use_container_width=True):
            if not reset_email.strip():
                st.warning("Enter your email address.")
            else:
                try:
                    from database import get_supabase_credentials
                    from supabase import create_client as _sc
                    SUPABASE_URL, SUPABASE_KEY = get_supabase_credentials()
                    _sb = _sc(SUPABASE_URL, SUPABASE_KEY)
                    # Pass redirect URL so Supabase sends user back here with PKCE code
                    _redirect = st.context.headers.get("Origin", "http://localhost:8501")
                    _sb.auth.reset_password_email(reset_email.strip(), {
                        "redirect_to": _redirect,
                    })
                    st.success("Reset link sent! Check your inbox (and spam folder).")
                    st.info("After you get the email, click **\"I have a reset link\"** below and paste the link.")
                except Exception as _re:
                    # Don't reveal whether email exists
                    st.success("If that email exists, a reset link has been sent. Check your inbox (and spam folder).")
                    _log_app_error("password_reset", f"Reset request for {reset_email.strip()}: {_re}")
        st.markdown("---")
        rc3, rc4 = st.columns(2)
        if rc3.button("I have a reset link", use_container_width=True):
            st.session_state["_show_paste_link"] = True
            st.rerun()
        if rc4.button("Back to sign in", use_container_width=True):
            st.session_state["_show_reset_pw"] = False
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # ── Sign in mode ──────────────────────────────────────────────────
    st.markdown("<div style='max-width:400px;margin:24px auto 0;'>", unsafe_allow_html=True)

    if _check_login_lockout():
        st.markdown("</div>", unsafe_allow_html=True)
        return

    email    = st.text_input("Email",    placeholder="you@company.com",  key="login_email")
    password = st.text_input("Password", placeholder="••••••••••••",      key="login_password", type="password")

    if st.button("Sign in", type="primary", use_container_width=True):
        if not email.strip() or not password.strip():
            st.error("Enter your email and password.")
        else:
            try:
                from database import get_supabase_credentials
                from supabase import create_client as _sc
                SUPABASE_URL, SUPABASE_KEY = get_supabase_credentials()
                _sb   = _sc(SUPABASE_URL, SUPABASE_KEY)
                resp  = _sb.auth.sign_in_with_password({"email": email.strip(), "password": password})

                # ── Email verification check ──────────────────────────
                _user = resp.user
                _email_confirmed = getattr(_user, "email_confirmed_at", None)
                if not _email_confirmed:
                    st.warning("Your email has not been verified. Check your inbox for a confirmation link.")
                    _log_app_error("login", f"Unverified email login attempt: {email.strip()}")
                    st.markdown("</div>", unsafe_allow_html=True)
                    return

                _at = resp.session.access_token
                _rt = resp.session.refresh_token
                # Store session tokens + expiry for auto-refresh
                st.session_state["supabase_session"] = {
                    "access_token": _at, "refresh_token": _rt,
                }
                _set_auth_cookies(_at, _rt)
                st.session_state["_sb_token_expires_at"] = (
                    resp.session.expires_at
                    if hasattr(resp.session, "expires_at") and resp.session.expires_at
                    else time.time() + 3600
                )
                # Create a fresh client with the auth session baked in
                _sb2 = _sc(SUPABASE_URL, SUPABASE_KEY)
                _sb2.auth.set_session(_at, _rt)

                _uid = resp.user.id
                prof_resp = _sb2.table("user_profiles").select("tenant_id, role, name") \
                               .eq("id", _uid).execute()
                if prof_resp.data:
                    _prof = prof_resp.data[0]
                else:
                    # First login — check for pending invite code first
                    _pending_invite = st.session_state.get("_pending_invite", "")
                    if _pending_invite:
                        # Join existing tenant via invite code
                        try:
                            from database import join_tenant_by_invite as _join_invite
                            _display = email.strip().split("@")[0]
                            _joined_tid = _join_invite(_uid, _pending_invite, _display)
                            if _joined_tid:
                                st.session_state.pop("_pending_invite", None)
                                _prof = {"tenant_id": _joined_tid, "role": "member", "name": _display}
                            else:
                                st.error("That invite code is not valid. Contact your supervisor for a new link.")
                                st.markdown("</div>", unsafe_allow_html=True)
                                return
                        except Exception as _inv_err:
                            st.error(f"Could not join team: {_inv_err}")
                            st.markdown("</div>", unsafe_allow_html=True)
                            return
                    else:
                        # No invite — provision a new tenant for this user
                        import uuid as _uuid
                        _new_tid = str(_uuid.uuid4())
                        _display = email.strip().split("@")[0]
                        # Use RPC to bypass RLS — falls back to direct insert
                        try:
                            _rpc_result = _sb2.rpc("provision_tenant", {
                                "p_user_id":     _uid,
                                "p_tenant_name": _display,
                                "p_user_name":   _display,
                            }).execute()
                            # RPC returns the generated tenant_id
                            if _rpc_result.data:
                                _new_tid = _rpc_result.data
                        except Exception as _rpc_err:
                            # RPC doesn't exist yet — try direct insert
                            _log_app_error("provision_tenant", f"RPC failed for {_uid}: {_rpc_err}, trying direct insert")
                            _sb2.table("tenants").insert({
                                "id": _new_tid, "name": _display,
                            }).execute()
                            _sb2.table("user_profiles").insert({
                                "id": _uid, "tenant_id": _new_tid,
                                "role": "admin", "name": _display,
                            }).execute()
                        _prof = {"tenant_id": _new_tid, "role": "admin",
                                 "name": _display}
                st.session_state["tenant_id"] = _prof["tenant_id"]
                st.session_state["user_role"] = _prof.get("role", "member")
                st.session_state["user_name"]  = _prof.get("name") or email.strip()
                st.session_state["user_email"] = email.strip()
                st.session_state["user_id"] = _uid
                # Clear login attempt counter on success
                st.session_state["_login_attempts"] = 0
                st.session_state["_login_lockout_until"] = 0
                _bust_cache()
                st.rerun()
            except Exception as _le:
                _msg = str(_le).strip()
                _msg_l = _msg.lower()
                if "email not confirmed" in _msg_l:
                    st.warning("This user exists, but the email is not confirmed yet. In Supabase Auth, open the user and confirm them, or disable email confirmation while setting up.")
                elif any(s in _msg_l for s in [
                    "invalid login credentials",
                    "invalid password",
                    "email or password",
                ]):
                    _record_failed_login()
                elif any(s in _msg_l for s in [
                    "invalid api key",
                    "invalid jwt",
                    "failed to fetch",
                    "name or service not known",
                    "connection refused",
                    "timed out",
                ]):
                    st.error("Supabase connection failed. Check SUPABASE_URL and SUPABASE_KEY in .streamlit/secrets.toml.")
                elif "user not found" in _msg_l or "signup disabled" in _msg_l:
                    st.error("This email does not exist in Supabase Auth yet. Create the user first in Supabase: Authentication -> Users -> Add user.")
                else:
                    st.error(f"Login failed: {_msg or 'Unknown Supabase auth error'}")
                _log_app_error("login", f"Failed login for {email.strip()}: {_le}")

    # Forgot password link
    if st.button("Forgot password?", type="secondary", use_container_width=True, key="forgot_pw_btn"):
        st.session_state["_show_reset_pw"] = True
        st.rerun()

    # ── Join existing team via invite code ──────────────────────────────────
    _pending_inv = st.session_state.get("_pending_invite", "")
    if _pending_inv:
        st.info(f"You have a team invite: **{_pending_inv}** — sign in above to join the team.")
        if st.button("✕ Cancel invite", key="cancel_invite", type="secondary", use_container_width=True):
            st.session_state.pop("_pending_invite", None)
            st.rerun()
    else:
        with st.expander("Have an invite code? Join an existing team"):
            _inv_input = st.text_input(
                "Enter invite code",
                placeholder="e.g. a1b2c3d4",
                key="manual_invite_input",
                help="Your admin can find this in Settings → Team.",
            )
            if st.button("Use this invite code", key="use_invite_btn", use_container_width=True):
                if _inv_input.strip():
                    st.session_state["_pending_invite"] = _inv_input.strip().lower()
                    st.info("Invite saved — now sign in above to join the team.")
                    st.rerun()
                else:
                    st.warning("Enter an invite code first.")

    st.markdown("</div>", unsafe_allow_html=True)


_SESSION_TIMEOUT_SECONDS = 28800  # 8 hour idle timeout


def _check_session_timeout():
    """Auto-logout if user has been idle for more than 1 hour."""
    now = time.time()
    last_activity = st.session_state.get("_last_activity", now)
    if now - last_activity > _SESSION_TIMEOUT_SECONDS:
        # Clear session
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        return True  # timed out
    st.session_state["_last_activity"] = now
    return False


