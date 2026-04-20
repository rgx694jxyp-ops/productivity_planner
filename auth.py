import os
import time

import streamlit as st

from core.onboarding_intent import attach_post_auth_intent
from services.app_logging import log_error, log_warn, sanitize_text


LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 900
SESSION_TIMEOUT_SECONDS = 28800
MAX_SESSION_LIFETIME_SECONDS = 43200


def _show_safe_error(message: str, *, next_steps: str = "", technical_detail: str = "") -> None:
    """Show a clean auth error while keeping raw details behind an expander."""
    st.error(message)
    if next_steps:
        st.info(next_steps)
    if technical_detail:
        with st.expander("Technical details", expanded=False):
            st.code(sanitize_text(technical_detail))


def _auth_redirect_url() -> str:
    """Return a stable, browser-reachable redirect URL for auth emails.

    Priority:
    1) AUTH_REDIRECT_URL / APP_BASE_URL / PUBLIC_APP_URL env or secrets
    2) Request Origin header
    3) localhost fallback
    """
    for key in ("AUTH_REDIRECT_URL", "APP_BASE_URL", "PUBLIC_APP_URL", "RENDER_EXTERNAL_URL"):
        v = str(os.environ.get(key, "") or "").strip()
        if not v:
            try:
                v = str(st.secrets.get(key, "") or "").strip()
            except Exception:
                v = ""
        if v.startswith("http://") or v.startswith("https://"):
            return attach_post_auth_intent(v.rstrip("/"))

    try:
        origin = str(st.context.headers.get("Origin", "") or "").strip()
        if origin.startswith("http://") or origin.startswith("https://"):
            return attach_post_auth_intent(origin.rstrip("/"))
    except Exception:
        pass

    return attach_post_auth_intent("http://localhost:8501")


def render_sign_out_button(key_prefix: str, *, type: str = "secondary", use_container_width: bool = False) -> bool:
    confirm_key = f"{key_prefix}_confirm_signout"
    if not st.session_state.get(confirm_key, False):
        if st.button("Sign out", key=f"{key_prefix}_signout", type=type, use_container_width=use_container_width):
            st.session_state[confirm_key] = True
            st.rerun()
        return False

    st.warning("Confirm sign out?")
    c1, c2 = st.columns(2)
    if c1.button("Yes, sign out", key=f"{key_prefix}_signout_yes", type="primary", use_container_width=True):
        st.session_state.pop(confirm_key, None)
        return True
    if c2.button("Cancel", key=f"{key_prefix}_signout_no", use_container_width=True):
        st.session_state.pop(confirm_key, None)
        st.rerun()
    return False


def set_auth_cookies(access_token: str, refresh_token: str, max_age: int = MAX_SESSION_LIFETIME_SECONDS):
    from urllib.parse import quote as _quote

    _at = _quote(access_token or "", safe="")
    _rt = _quote(refresh_token or "", safe="")
    _ts = str(int(time.time()))
    st.components.v1.html(
        "<script>"
        f"document.cookie = 'dpd_at={_at}; path=/; max-age={int(max_age)}; SameSite=Lax';"
        f"document.cookie = 'dpd_rt={_rt}; path=/; max-age={int(max_age)}; SameSite=Lax';"
        f"document.cookie = 'dpd_auth_ts={_ts}; path=/; max-age={int(max_age)}; SameSite=Lax';"
        "document.cookie = 'dpd_logged_out=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax';"
        "</script>",
        height=0,
    )


def clear_auth_cookies():
    st.components.v1.html(
        "<script>"
        "document.cookie = 'dpd_at=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax';"
        "document.cookie = 'dpd_rt=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax';"
        "document.cookie = 'dpd_auth_ts=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax';"
        "document.cookie = 'dpd_logged_out=1; path=/; max-age=300; SameSite=Lax';"
        "</script>",
        height=0,
    )


def restore_session_from_cookies() -> bool:
    if st.session_state.get("supabase_session"):
        return True

    try:
        from urllib.parse import unquote as _unquote

        _cookies = st.context.cookies
        if (_cookies.get("dpd_logged_out", "") or "") == "1":
            return False
        _at = _unquote(_cookies.get("dpd_at", "") or "")
        _rt = _unquote(_cookies.get("dpd_rt", "") or "")
        _auth_ts_raw = _cookies.get("dpd_auth_ts", "") or ""
        try:
            _auth_ts = float(_auth_ts_raw)
        except (TypeError, ValueError):
            _auth_ts = 0.0
        if not _at or not _rt:
            return False
        if not _auth_ts or (time.time() - _auth_ts) > MAX_SESSION_LIFETIME_SECONDS:
            clear_auth_cookies()
            return False

        from database import get_supabase_credentials
        from supabase import create_client as _sc

        SUPABASE_URL, SUPABASE_KEY = get_supabase_credentials()
        _sb = _sc(SUPABASE_URL, SUPABASE_KEY)
        _session_resp = _sb.auth.set_session(_at, _rt)
        _user_resp = _sb.auth.get_user()
        _user = getattr(_user_resp, "user", None)
        if not _user:
            return False

        _new_at = getattr(getattr(_session_resp, "session", None), "access_token", None) or _at
        _new_rt = getattr(getattr(_session_resp, "session", None), "refresh_token", None) or _rt
        _expires_at = getattr(getattr(_session_resp, "session", None), "expires_at", None) or (time.time() + 3600)

        _profile_resp = _sb.table("user_profiles").select("tenant_id, role, name").eq("id", _user.id).execute()
        if not _profile_resp.data:
            return False
        _prof = _profile_resp.data[0]

        st.session_state["supabase_session"] = {
            "access_token": _new_at,
            "refresh_token": _new_rt,
        }
        st.session_state["_session_started_at"] = _auth_ts
        st.session_state["_last_activity"] = time.time()
        st.session_state["_sb_token_expires_at"] = _expires_at
        st.session_state["tenant_id"] = _prof.get("tenant_id", "")
        st.session_state["user_role"] = _prof.get("role", "member")
        st.session_state["user_name"] = _prof.get("name") or getattr(_user, "email", "")
        st.session_state["user_email"] = getattr(_user, "email", "") or st.session_state.get("user_email", "")
        st.session_state["user_id"] = _user.id
        set_auth_cookies(_new_at, _new_rt)
        return True
    except Exception as error:
        log_warn(
            "auth_restore_session_failed",
            "Restoring auth session from cookies failed.",
            context={"has_session_cookie": bool(st.context.cookies.get("dpd_at", ""))},
            error=error,
        )
        return False


def full_sign_out(bust_cache_cb):
    # Revoke the Supabase JWT server-side so it cannot be replayed even if captured.
    try:
        _sess = st.session_state.get("supabase_session", {})
        _at = _sess.get("access_token", "")
        _rt = _sess.get("refresh_token", "")
        if _at and _rt:
            from database import get_supabase_credentials
            from supabase import create_client as _sc
            _SURL, _SKEY = get_supabase_credentials()
            _sb = _sc(_SURL, _SKEY)
            _sb.auth.set_session(_at, _rt)
            _sb.auth.sign_out()
    except Exception as error:
        log_warn(
            "auth_sign_out_revoke_failed",
            "Supabase sign-out revoke failed; continuing with local sign-out.",
            context={"has_access_token": bool(_at), "has_refresh_token": bool(_rt)},
            error=error,
        )
        pass  # best-effort; cookie and state clearing below always runs
    bust_cache_cb()
    st.session_state["_logout_requested"] = True
    try:
        st.query_params["logout"] = "1"
    except Exception as error:
        log_warn(
            "auth_logout_query_param_cleanup_failed",
            "Failed to set logout query parameter during sign-out.",
            error=error,
        )
        pass
    clear_auth_cookies()


def check_access() -> bool:
    pw = st.session_state.get("app_password_set", "")
    if not pw:
        return True
    if st.session_state.get("authenticated"):
        return True

    st.markdown(
        """
    <div style="max-width:400px;margin:80px auto;background:#fff;
                border:1px solid #E2EBF4;border-radius:12px;padding:36px;">
      <div style="font-size:22px;font-weight:700;color:#0F2D52;
                  margin-bottom:24px;">📦 Pulse Ops</div>
    </div>""",
        unsafe_allow_html=True,
    )

    entered = st.text_input("Password", type="password", placeholder="Enter your access password", key="login_input")
    if st.button("Sign in", type="primary"):
        if entered == pw:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


def check_login_lockout() -> bool:
    lockout_until = st.session_state.get("_login_lockout_until", 0)
    if lockout_until and time.time() < lockout_until:
        remaining = int(lockout_until - time.time())
        mins = remaining // 60
        secs = remaining % 60
        st.error(f"Too many failed attempts. Try again in {mins}m {secs}s.")
        return True

    if lockout_until and time.time() >= lockout_until:
        st.session_state["_login_attempts"] = 0
        st.session_state["_login_lockout_until"] = 0
    return False


def record_failed_login():
    attempts = st.session_state.get("_login_attempts", 0) + 1
    st.session_state["_login_attempts"] = attempts
    if attempts >= LOGIN_MAX_ATTEMPTS:
        st.session_state["_login_lockout_until"] = time.time() + LOGIN_LOCKOUT_SECONDS
        st.error(f"Account locked for 15 minutes after {LOGIN_MAX_ATTEMPTS} failed attempts.")
    else:
        remaining = LOGIN_MAX_ATTEMPTS - attempts
        st.error(f"Invalid email or password. {remaining} attempt(s) remaining.")


def login_page(bust_cache_cb, log_app_error_cb):  # noqa: C901
    st.markdown(
        """
    <div style="max-width:400px;margin:80px auto 0;text-align:center;">
      <div style="background:#0F2D52;border-radius:12px;padding:32px 36px;">
        <div style="font-size:28px;margin-bottom:4px;">📦</div>
        <div style="font-size:20px;font-weight:700;color:#fff;letter-spacing:-.02em;">
                    Pulse Ops
        </div>
                <div style="font-size:12px;color:#BDD7EE;margin-top:6px;">
                    Supervisor signal and action workflow
                </div>
      </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    # ── Password reset mode ───────────────────────────────────────────────
    if st.session_state.get("_show_reset_pw"):
        st.markdown("<div style='max-width:400px;margin:24px auto 0;'>", unsafe_allow_html=True)

        # Sub-mode: user has a reset link and wants to paste it ──────────
        if st.session_state.get("_show_paste_link"):
            # If we already verified the link, show the new-password form.
            if st.session_state.get("_recovery_access_token"):
                st.subheader("Set new password")
                new_pw  = st.text_input("New password",      type="password", key="paste_new_pw")
                conf_pw = st.text_input("Confirm password",  type="password", key="paste_conf_pw")
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
                                st.success("Password updated! Sign in with your new password.")
                                st.rerun()
                            else:
                                _show_safe_error(
                                    "Could not update your password right now.",
                                    next_steps="Please try again. If this continues, request a new reset link.",
                                    technical_detail=_upd_resp.text,
                                )
                        except Exception as _upe:
                            _show_safe_error(
                                "Could not update your password right now.",
                                next_steps="Please try again. If this continues, request a new reset link.",
                                technical_detail=str(_upe),
                            )
                st.markdown("</div>", unsafe_allow_html=True)
                return

            # Step 1: paste the reset URL from email ─────────────────────
            st.subheader("Paste your reset link")
            st.caption("Open the reset email, copy the full link, and paste it below.")
            _paste_url = st.text_input(
                "Reset link from email",
                placeholder="Paste the full URL from your email",
                key="paste_reset_url",
            )
            pc1, pc2 = st.columns(2)
            if pc1.button("Continue", type="primary", use_container_width=True):
                if not _paste_url.strip():
                    st.warning("Paste the link from your reset email.")
                else:
                    from urllib.parse import parse_qs, urlparse
                    _parsed = urlparse(_paste_url.strip())
                    _at = ""
                    # Case 1: URL fragment contains access_token (post-redirect URL)
                    if _parsed.fragment:
                        _fp = parse_qs(_parsed.fragment)
                        _at = (_fp.get("access_token") or [""])[0]
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
                                    headers={
                                        "apikey": SUPABASE_KEY,
                                        "Content-Type": "application/json",
                                    },
                                    timeout=10,
                                )
                                if _vresp.status_code == 200:
                                    _at = _vresp.json().get("access_token", "")
                            except Exception:
                                pass
                    if _at:
                        st.session_state["_recovery_access_token"] = _at
                        st.rerun()
                    else:
                        st.error(
                            "Could not extract a recovery token from that URL. "
                            "Make sure you copied the full link."
                        )
            if pc2.button("Back", use_container_width=True, key="paste_back_btn"):
                st.session_state.pop("_show_paste_link", None)
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
            return

        # Simple sub-mode: request a reset email ─────────────────────────
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
                    _redirect = _auth_redirect_url()
                    _sb.auth.reset_password_email(reset_email.strip(), {"redirect_to": _redirect})
                except Exception as _re:
                    log_app_error_cb("password_reset", f"Reset request for {reset_email.strip()}: {_re}")
                # Always show success — never reveal whether an email exists.
                st.success(
                    "If that email exists, a reset link has been sent. "
                    "Check your inbox (and spam folder)."
                )
        if rc2.button("Back to sign in", use_container_width=True):
            st.session_state["_show_reset_pw"] = False
            st.rerun()
        st.markdown("---")
        rc3, _ = st.columns(2)
        if rc3.button("I have a reset link", use_container_width=True):
            st.session_state["_show_paste_link"] = True
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # ── Sign in / Create account tabs ─────────────────────────────────────
    st.markdown("<div style='max-width:400px;margin:24px auto 0;'>", unsafe_allow_html=True)
    _tab_signin, _tab_signup = st.tabs(["Sign in", "Create account"])

    with _tab_signin:
        # Lockout only disables the button — Create account tab remains accessible.
        _is_locked = check_login_lockout()
        email    = st.text_input("Email",    placeholder="you@company.com", key="login_email")
        password = st.text_input("Password", placeholder="••••••••••••",    key="login_password", type="password")

        if st.button("Sign in", type="primary", use_container_width=True, disabled=_is_locked):
            if not email.strip() or not password.strip():
                st.error("Enter your email and password.")
            else:
                try:
                    from database import get_supabase_credentials
                    from supabase import create_client as _sc
                    SUPABASE_URL, SUPABASE_KEY = get_supabase_credentials()
                    _sb = _sc(SUPABASE_URL, SUPABASE_KEY)
                    resp = _sb.auth.sign_in_with_password({"email": email.strip(), "password": password})

                    _user = resp.user
                    if not getattr(_user, "email_confirmed_at", None):
                        st.warning(
                            "Your email has not been verified. "
                            "Check your inbox for a confirmation link before signing in."
                        )
                        log_app_error_cb("login", f"Unverified email login attempt: {email.strip()}")
                        st.markdown("</div>", unsafe_allow_html=True)
                        return

                    _at = resp.session.access_token
                    _rt = resp.session.refresh_token
                    _exp = float(
                        resp.session.expires_at
                        if hasattr(resp.session, "expires_at") and resp.session.expires_at
                        else time.time() + 3600
                    )
                    st.session_state["supabase_session"] = {"access_token": _at, "refresh_token": _rt}
                    st.session_state["_session_started_at"] = time.time()
                    st.session_state["_last_activity"] = time.time()
                    st.session_state["_sb_token_expires_at"] = _exp
                    set_auth_cookies(_at, _rt)

                    _sb2 = _sc(SUPABASE_URL, SUPABASE_KEY)
                    _sb2.auth.set_session(_at, _rt)
                    _uid = resp.user.id
                    prof_resp = _sb2.table("user_profiles").select("tenant_id, role, name").eq("id", _uid).execute()

                    if prof_resp.data:
                        _prof = prof_resp.data[0]
                    else:
                        # New user: check for a pending invite first, else provision solo tenant.
                        _pending_invite = st.session_state.get("_pending_invite", "")
                        if _pending_invite:
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
                                _msg = str(_inv_err or "").strip()
                                if "team seats" in _msg.lower() or "plan '" in _msg.lower():
                                    st.error(_msg)
                                else:
                                    _show_safe_error(
                                        "Could not join that team right now.",
                                        next_steps="Check with your admin that the invite is valid and has available seats, then try again.",
                                        technical_detail=str(_inv_err),
                                    )
                                st.markdown("</div>", unsafe_allow_html=True)
                                return
                        else:
                            import uuid as _uuid
                            _new_tid = str(_uuid.uuid4())
                            _display = email.strip().split("@")[0]
                            try:
                                _rpc_result = _sb2.rpc(
                                    "provision_tenant",
                                    {"p_user_id": _uid, "p_tenant_name": _display, "p_user_name": _display},
                                ).execute()
                                if _rpc_result.data:
                                    _new_tid = _rpc_result.data
                            except Exception as _rpc_err:
                                log_app_error_cb(
                                    "provision_tenant",
                                    f"RPC failed for {_uid}: {_rpc_err}, trying direct insert",
                                )
                                _sb2.table("tenants").insert({"id": _new_tid, "name": _display}).execute()
                                _sb2.table("user_profiles").insert(
                                    {"id": _uid, "tenant_id": _new_tid, "role": "admin", "name": _display}
                                ).execute()
                            _prof = {"tenant_id": _new_tid, "role": "admin", "name": _display}

                    st.session_state["tenant_id"] = _prof["tenant_id"]
                    st.session_state["user_role"] = _prof.get("role", "member")
                    st.session_state["user_name"] = _prof.get("name") or email.strip()
                    st.session_state["user_email"] = email.strip()
                    st.session_state["user_id"] = _uid
                    st.session_state["_login_attempts"] = 0
                    st.session_state["_login_lockout_until"] = 0
                    bust_cache_cb()
                    st.rerun()
                except Exception as _le:
                    _msg = str(_le).strip().lower()
                    if any(s in _msg for s in ["invalid login credentials", "invalid password", "email or password"]):
                        record_failed_login()
                        st.info("New here? Use the **Create account** tab above instead.")
                    elif "email not confirmed" in _msg:
                        st.warning(
                            "This account exists but the email is not confirmed yet. "
                            "Check your inbox for a verification link."
                        )
                    elif any(s in _msg for s in ["user not found", "signup disabled"]):
                        st.error("No account found for that email. Use the Create account tab.")
                    elif any(s in _msg for s in [
                        "invalid api key", "invalid jwt", "failed to fetch",
                        "connection refused", "timed out", "name or service not known",
                    ]):
                        st.error(
                            "Supabase connection failed. "
                            "Check SUPABASE_URL and SUPABASE_KEY in .streamlit/secrets.toml."
                        )
                    else:
                        _show_safe_error(
                            "Sign-in failed.",
                            next_steps="Please retry. If this continues, use Forgot password or contact support.",
                            technical_detail=str(_le).strip() or "Unknown Supabase auth error",
                        )
                    log_app_error_cb("login", f"Failed login for {email.strip()}: {_le}")

        if st.button("Forgot password?", type="secondary", use_container_width=True, key="forgot_pw_btn"):
            st.session_state["_show_reset_pw"] = True
            st.rerun()

    with _tab_signup:
        st.caption("Create your account — no admin setup needed.")
        st.info(
            "After you confirm your email, sign in with the same email and password. "
            "If your account needs billing activation, the app will take you to the purchase page automatically."
        )
        _signup_email = st.text_input(
            "Email", placeholder="you@company.com", key="signup_email"
        )
        _signup_pw = st.text_input(
            "Password", placeholder="At least 6 characters", type="password", key="signup_password"
        )
        _signup_pw2 = st.text_input(
            "Confirm password", placeholder="Re-enter password", type="password", key="signup_password_confirm"
        )
        if st.button("Create account", key="create_account_btn", use_container_width=True, type="primary"):
            if not _signup_email.strip() or not _signup_pw.strip() or not _signup_pw2.strip():
                st.warning("Enter email, password, and confirmation.")
            elif _signup_pw != _signup_pw2:
                st.warning("Passwords do not match.")
            elif len(_signup_pw) < 6:
                st.warning("Password must be at least 6 characters.")
            else:
                try:
                    from database import get_supabase_credentials
                    from supabase import create_client as _sc
                    SUPABASE_URL, SUPABASE_KEY = get_supabase_credentials()
                    _sb = _sc(SUPABASE_URL, SUPABASE_KEY)
                    _redirect = _auth_redirect_url()
                    _signup_resp = _sb.auth.sign_up({
                        "email": _signup_email.strip(),
                        "password": _signup_pw,
                        "options": {"email_redirect_to": _redirect},
                    })
                    _signup_user    = getattr(_signup_resp, "user", None)
                    _signup_session = getattr(_signup_resp, "session", None)
                    if _signup_user and _signup_session:
                        st.success("Account created! You can now sign in.")
                        st.info(
                            "Sign in with the same email and password. "
                            "If billing is required, you will be taken to the purchase page automatically."
                        )
                        st.session_state["_login_attempts"] = 0
                        st.session_state["_login_lockout_until"] = 0
                        st.session_state["login_email"] = _signup_email.strip()
                    elif _signup_user:
                        st.success("Account created! Check your email to verify, then sign in.")
                        st.info(
                            "After you verify your email, return here and sign in with the same email and password. "
                            "If billing is required, the app will take you to the purchase page automatically."
                        )
                        st.caption("No email? Check your spam folder.")
                    else:
                        st.warning("Sign-up sent. Check your email for next steps.")
                        st.caption(
                            "After email verification, sign in here with the same credentials. "
                            "If needed, you will be redirected to the purchase page."
                        )
                except Exception as _se:
                    _se_msg = str(_se).strip().lower()
                    if any(s in _se_msg for s in ["already registered", "already exists", "user already"]):
                        st.warning(
                            "That email already has an account. "
                            "Try signing in or resetting your password."
                        )
                    elif "error sending confirmation email" in _se_msg:
                        st.error(
                            "Account creation could not send the confirmation email."
                        )
                        st.info(
                            "Supabase email delivery is not configured yet. "
                            "In Supabase Auth settings, either configure SMTP "
                            "or temporarily disable email confirmation, then try again."
                        )
                    elif "signup is disabled" in _se_msg:
                        st.error(
                            "Sign-up is currently disabled. "
                            "Enable Email sign-up in the Supabase Auth settings."
                        )
                    else:
                        _show_safe_error(
                            "Could not create your account right now.",
                            next_steps="Please try again in a moment. If this continues, contact support.",
                            technical_detail=str(_se).strip() or "Unknown sign-up error",
                        )
                    log_app_error_cb("signup", f"Failed signup for {_signup_email.strip()}: {_se}")

    # ── Team invite code ──────────────────────────────────────────────────
    _pending_inv = st.session_state.get("_pending_invite", "")
    if _pending_inv:
        st.info(f"Team invite active: **{_pending_inv}** — sign in above to join the team.")
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
                    st.info("Invite saved — sign in above to join the team.")
                    st.rerun()
                else:
                    st.warning("Enter an invite code first.")

    st.markdown("</div>", unsafe_allow_html=True)


def refresh_session_if_needed() -> bool:
    """Proactively refresh the Supabase JWT when it is within 5 minutes of expiry.

    Returns True if a refresh was performed successfully.
    This prevents mid-session 401 errors on long-lived tabs.
    """
    expires_at = float(st.session_state.get("_sb_token_expires_at", 0) or 0)
    # Nothing to do if we don't know the expiry or there is still plenty of time left.
    if not expires_at or time.time() < expires_at - 300:
        return False
    _sess = st.session_state.get("supabase_session", {})
    _rt = _sess.get("refresh_token", "")
    if not _rt:
        return False
    try:
        from database import get_supabase_credentials
        from supabase import create_client as _sc
        _SURL, _SKEY = get_supabase_credentials()
        _sb = _sc(_SURL, _SKEY)
        _resp = _sb.auth.refresh_session(_rt)
        _new_at = _resp.session.access_token
        _new_rt = _resp.session.refresh_token
        _new_exp = float(getattr(_resp.session, "expires_at", None) or (time.time() + 3600))
        st.session_state["supabase_session"] = {"access_token": _new_at, "refresh_token": _new_rt}
        st.session_state["_sb_token_expires_at"] = _new_exp
        set_auth_cookies(_new_at, _new_rt)
        return True
    except Exception:
        return False


def check_session_timeout() -> bool:
    # Silently refresh the JWT before checking timeouts so an active user is
    # never bounced simply because their token rolled over.
    refresh_session_if_needed()
    now = time.time()
    session_started_at = float(st.session_state.get("_session_started_at", now) or now)
    last_activity = st.session_state.get("_last_activity", now)
    if now - session_started_at > MAX_SESSION_LIFETIME_SECONDS:
        clear_auth_cookies()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        return True
    if now - last_activity > SESSION_TIMEOUT_SECONDS:
        clear_auth_cookies()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        return True
    st.session_state["_last_activity"] = now
    return False
