import time

import streamlit as st


LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 900
SESSION_TIMEOUT_SECONDS = 28800
MAX_SESSION_LIFETIME_SECONDS = 43200


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
        "</script>",
        height=0,
    )


def clear_auth_cookies():
    st.components.v1.html(
        "<script>"
        "document.cookie = 'dpd_at=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax';"
        "document.cookie = 'dpd_rt=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax';"
        "document.cookie = 'dpd_auth_ts=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax';"
        "</script>",
        height=0,
    )


def restore_session_from_cookies() -> bool:
    if st.session_state.get("supabase_session"):
        return True

    try:
        from urllib.parse import unquote as _unquote

        _cookies = st.context.cookies
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
    except Exception:
        return False


def full_sign_out(bust_cache_cb):
    bust_cache_cb()
    try:
        st.query_params["logout"] = "1"
    except Exception:
        pass
    clear_auth_cookies()
    for k in list(st.session_state.keys()):
        del st.session_state[k]


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
                  margin-bottom:24px;">📦 Productivity Planner</div>
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


def login_page(bust_cache_cb, log_app_error_cb):
    st.markdown(
        """
    <div style="max-width:400px;margin:80px auto 0;text-align:center;">
      <div style="background:#0F2D52;border-radius:12px;padding:32px 36px;">
        <div style="font-size:28px;margin-bottom:4px;">📦</div>
        <div style="font-size:20px;font-weight:700;color:#fff;letter-spacing:-.02em;">
          Productivity Planner
        </div>
      </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    if st.session_state.get("_show_reset_pw"):
        st.markdown("<div style='max-width:400px;margin:24px auto 0;'>", unsafe_allow_html=True)
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
                    _redirect = st.context.headers.get("Origin", "http://localhost:8501")
                    _sb.auth.reset_password_email(reset_email.strip(), {"redirect_to": _redirect})
                    st.success("Reset link sent! Check your inbox (and spam folder).")
                except Exception as _re:
                    st.success("If that email exists, a reset link has been sent. Check your inbox (and spam folder).")
                    log_app_error_cb("password_reset", f"Reset request for {reset_email.strip()}: {_re}")

        if rc2.button("Back to sign in", use_container_width=True):
            st.session_state["_show_reset_pw"] = False
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown("<div style='max-width:400px;margin:24px auto 0;'>", unsafe_allow_html=True)

    st.info(
        "New users: enter your email and password to sign in. "
        "If your company does not have an active subscription yet, you'll be redirected to choose and purchase a plan.\n\n"
        "Existing users: sign in as normal with your current email and password."
    )

    if check_login_lockout():
        st.markdown("</div>", unsafe_allow_html=True)
        return

    email = st.text_input("Email", placeholder="you@company.com", key="login_email")
    password = st.text_input("Password", placeholder="••••••••••••", key="login_password", type="password")

    if st.button("Sign in", type="primary", use_container_width=True):
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
                _email_confirmed = getattr(_user, "email_confirmed_at", None)
                if not _email_confirmed:
                    st.warning("Your email has not been verified. Check your inbox for a confirmation link.")
                    log_app_error_cb("login", f"Unverified email login attempt: {email.strip()}")
                    st.markdown("</div>", unsafe_allow_html=True)
                    return

                _at = resp.session.access_token
                _rt = resp.session.refresh_token
                st.session_state["supabase_session"] = {"access_token": _at, "refresh_token": _rt}
                st.session_state["_session_started_at"] = time.time()
                st.session_state["_last_activity"] = time.time()
                set_auth_cookies(_at, _rt)
                st.session_state["_sb_token_expires_at"] = (
                    resp.session.expires_at if hasattr(resp.session, "expires_at") and resp.session.expires_at else time.time() + 3600
                )

                _sb2 = _sc(SUPABASE_URL, SUPABASE_KEY)
                _sb2.auth.set_session(_at, _rt)
                _uid = resp.user.id
                prof_resp = _sb2.table("user_profiles").select("tenant_id, role, name").eq("id", _uid).execute()

                if prof_resp.data:
                    _prof = prof_resp.data[0]
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
                        log_app_error_cb("provision_tenant", f"RPC failed for {_uid}: {_rpc_err}, trying direct insert")
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
                elif any(s in _msg for s in ["invalid api key", "invalid jwt", "failed to fetch", "connection refused", "timed out"]):
                    st.error("Supabase connection failed. Check SUPABASE_URL and SUPABASE_KEY in .streamlit/secrets.toml.")
                else:
                    st.error(f"Login failed: {str(_le).strip() or 'Unknown Supabase auth error'}")
                log_app_error_cb("login", f"Failed login for {email.strip()}: {_le}")

    if st.button("Forgot password?", type="secondary", use_container_width=True, key="forgot_pw_btn"):
        st.session_state["_show_reset_pw"] = True
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def check_session_timeout() -> bool:
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
