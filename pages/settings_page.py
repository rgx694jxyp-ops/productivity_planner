from core.dependencies import (
    _bust_cache,
    _full_sign_out,
    _log_app_error,
    _render_sign_out_button,
    _set_auth_cookies,
    _tenant_log_path,
)
from core.navigation import _get_current_plan
from core.runtime import datetime, json, re, st, time, traceback, init_runtime

init_runtime()

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
                st.caption("Upgrade or downgrade your plan. Upgrades apply immediately; downgrades apply at the end of your billing period.")

                _pending_plan = (sub.get("pending_plan") or "").strip().lower()
                _pending_change_at = sub.get("pending_change_at") or ""
                _pending_date = "period end"
                if _pending_change_at:
                    try:
                        _pending_dt = datetime.fromisoformat(_pending_change_at.replace("Z", "+00:00"))
                        _pending_date = _pending_dt.strftime("%b %d, %Y")
                    except Exception:
                        _pending_date = _renew_str or "period end"
                elif _renew_str:
                    _pending_date = _renew_str
                if _pending_plan:
                    st.info(f"Your plan will change to {_pending_plan.capitalize()} on {_pending_date}.")
                    st.warning(
                        f"A pending downgrade to {_pending_plan.capitalize()} is already scheduled for {_pending_date}. "
                        "You keep current access until then, and additional changes are temporarily locked."
                    )

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
                _alternatives = [] if _pending_plan else [p for p in _PORD if p != _plan_raw]
                if not _alternatives:
                    if not _pending_plan:
                        st.info("No plan alternatives are available right now.")
                _pcols = st.columns(len(_alternatives)) if _alternatives else []
                for _ci, _pk in enumerate(_alternatives):
                    _pi    = _PINFO[_pk]
                    with _pcols[_ci]:
                        _is_up = _rank.get(_pk, 1) > _cur_rank
                        _badge_html = (
                            "<div style='color:#16a34a;font-size:11px;font-weight:700;text-transform:uppercase;'>↑ Upgrade (Immediate)</div>"
                            if _is_up
                            else "<div style='color:#b45309;font-size:11px;font-weight:700;text-transform:uppercase;'>↓ Downgrade (End of Period)</div>"
                        )
                        st.markdown(_badge_html, unsafe_allow_html=True)
                        st.markdown(f"**{_pi['label']}** &nbsp; {_pi['price']}")
                        st.caption(_pi['emp'] + " employees")

                        _delta = _GAINS.get((_plan_raw, _pk), [])
                        if _delta:
                            _label = "You'd gain:" if _is_up else "You'd lose at period end:"
                            _clr = "#16a34a" if _is_up else "#b45309"
                            st.markdown(
                                f"<div style='font-size:12px;font-weight:600;margin-top:4px;'>{_label}</div>",
                                unsafe_allow_html=True,
                            )
                            for _x in _delta:
                                _prefix = "+" if _is_up else "-"
                                st.markdown(
                                    f"<div style='font-size:12px;color:{_clr};line-height:1.8;'>{_prefix} {_x}</div>",
                                    unsafe_allow_html=True,
                                )

                        st.markdown("")
                        _target_price = _price_map.get(_pk, "")
                        _btn_label = (
                            f"Upgrade to {_pi['label']}"
                            if _is_up
                            else f"Schedule downgrade to {_pi['label']}"
                        )
                        _btn_disabled = bool(_pending_plan)
                        _btn_type = "primary" if _is_up else "secondary"
                        if st.button(
                            _btn_label,
                            key=f"switch_plan_{_pk}",
                            use_container_width=True,
                            type=_btn_type,
                            disabled=_btn_disabled,
                        ):
                            if not _target_price:
                                st.error(f"Price for {_pi['label']} is not configured.")
                            else:
                                with st.spinner("Requesting plan change in Stripe…"):
                                    _ok, _msg = modify_subscription(_target_price, _tid_local)
                                if _ok:
                                    if _is_up:
                                        st.success("Upgrade submitted. Access and billing should refresh shortly.")
                                    else:
                                        _when = _renew_str or "the end of your current period"
                                        st.success(f"Downgrade scheduled. Your plan will switch on {_when}.")
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


