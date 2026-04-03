from app import (
    _cached_targets,
    _success_then_rerun,
    date,
    st,
)
from pages.employees import _build_archived_productivity

def page_email():
    st.title("📧 Email Setup")
    st.caption("Configure who receives reports and send manual reports.")
    try:
        from email_engine import (save_smtp_config, get_smtp_config, add_recipient,
                                   remove_recipient, get_recipients, send_report_email,
                                   save_email_delivery_config, get_email_delivery_config,
                                   build_dept_email_body, import_recipients_from_csv)
    except ImportError:
        st.error("Email module not found."); return

    tab_smtp, tab_recip, tab_send = st.tabs([
        "1️⃣ Email Delivery (Easy Setup)", "2️⃣ Recipients", "📤 Send Now"
    ])

    # ── SMTP ─────────────────────────────────────────────────────────────────
    with tab_smtp:
        st.subheader("Email delivery settings")
        st.caption("Use your own work or personal email with SMTP, or choose Resend API.")

        cfg = get_smtp_config()
        delivery_cfg = get_email_delivery_config()
        mode_label = "Use Resend API (optional)" if delivery_cfg.get("mode") == "resend" else "Use my own email (work/personal)"
        mode = st.radio(
            "Delivery method",
            ["Use my own email (work/personal)", "Use Resend API (optional)"],
            index=1 if "Resend" in mode_label else 0,
            horizontal=True,
            key="email_delivery_mode",
        )

        if "Resend" in mode:
            st.info("Resend is optional. Choose this if you prefer API-key delivery over your own inbox credentials.")
            lr1, lr2 = st.columns(2)
            lr1.link_button("Create Resend Account", "https://resend.com", use_container_width=True)
            lr2.link_button("Verify Domain Guide", "https://resend.com/docs/dashboard/domains/introduction", use_container_width=True)
            _from_default = delivery_cfg.get("from") or cfg.get("from") or cfg.get("username", "")
            with st.form("resend_form"):
                resend_from = st.text_input(
                    "From email (must be verified in Resend)",
                    value=_from_default,
                    placeholder="reports@yourcompany.com",
                )
                resend_key = st.text_input(
                    "Resend API key",
                    type="password",
                    placeholder="re_...",
                )
                if st.form_submit_button("Save Resend settings", type="primary", use_container_width=True):
                    save_email_delivery_config(
                        mode="resend",
                        provider="resend",
                        api_key=resend_key,
                        from_addr=resend_from,
                    )
                    st.success("✓ Resend settings saved.")
                    st.rerun()

            if st.button("Send test email via Resend", key="resend_test", use_container_width=True):
                _to = (cfg.get("username") or "").strip()
                if not _to:
                    _all_r = get_recipients() or []
                    if _all_r:
                        _to = (_all_r[0].get("email") or "").strip()
                if not _to:
                    st.warning("Set a sender email in SMTP or add a recipient first so we know where to send the test.")
                else:
                    with st.spinner("Sending test email…"):
                        ok, err = send_report_email(
                            [_to],
                            "Productivity Planner — Resend Test",
                            "<p>Your Resend configuration is working correctly.</p>",
                        )
                    if ok:
                        st.success(f"✓ Test email sent to {_to}")
                    else:
                        st.error(f"Send failed: {err}")
            st.divider()
            st.markdown("##### Resend Quick Setup")
            st.caption("1) Create Resend account. 2) Verify sender domain. 3) Create API key. 4) Paste key. 5) Send test.")
            st.success("Once saved, all emails sent from this app use this method.")

        if "own email" in mode:
            st.caption("Recommended for most users: enter your own inbox email + app password. We auto-fill most server settings.")

            # Provider quick-select
            providers = {
                "Gmail":            ("smtp.gmail.com",      587),
                "Outlook / Office 365": ("smtp.office365.com", 587),
                "Yahoo":            ("smtp.mail.yahoo.com", 587),
                "Custom":           ("", 587),
            }
            # Detect current provider from saved server
            cur_server = cfg.get("server","")
            detected = next((k for k,v in providers.items() if v[0] == cur_server), "Custom")
            pcols = st.columns(len(providers))
            for i,(pname,pvals) in enumerate(providers.items()):
                active = (detected == pname)
                if pcols[i].button(pname, key=f"prov_{i}",
                                   type="primary" if active else "secondary",
                                   use_container_width=True):
                    st.session_state["smtp_server_override"] = pvals[0]
                    st.session_state["smtp_port_override"]   = pvals[1]
                    st.rerun()

            # App password help
            with st.expander("❓ How to get an App Password"):
                st.markdown("""
#### Gmail

**Before you start:** You must have 2-Step Verification turned on — App Passwords won't appear without it.

1. Go to **myaccount.google.com**
2. Click **Security** in the left sidebar
3. Under *"How you sign in to Google"*, click **2-Step Verification** and turn it on if it's off
4. Go back to the Security page and type **"App passwords"** in the search bar at the top — it won't appear in the menu, search is the only way to find it
5. Click **App passwords** in the results
6. Type a name like **Productivity Planner** and click **Create**
7. Google shows you a **16-character password** — copy it immediately, you won't see it again
8. Paste it into the **App password** field below

> ⚠️ If App Passwords doesn't appear even after enabling 2-Step Verification, your account may be managed by a Google Workspace admin who needs to enable it.

---

#### Outlook / Office 365

**Before you start:** You must have 2-Step Verification turned on for your Microsoft account.

1. Go to **account.microsoft.com** and sign in
2. Click **Security** at the top of the page
3. Click **Advanced security options** (under "Security basics")
4. Scroll down to the *"App passwords"* section
5. Click **Create a new app password**
6. Microsoft shows you a password — copy it immediately, you won't see it again
7. Paste it into the **App password** field below

> ⚠️ If you don't see the App passwords section, your organization's admin may need to enable it. Work and school accounts managed by an IT department may require admin approval first.

---

#### Yahoo

**Before you start:** You must have 2-Step Verification turned on for your Yahoo account.

1. Go to **login.yahoo.com** and sign in
2. Click your **profile icon** (top-right) and select **Account Info**
3. Click **Account Security** in the left sidebar
4. Make sure **Two-step verification** is turned on — if it's off, click it and follow the prompts to enable it
5. Scroll down and click **Generate app password** (or "Manage app passwords")
6. Select **Other app** from the dropdown and type **Productivity Planner**
7. Click **Generate**
8. Yahoo shows you a **16-character password** — copy it immediately, you won't see it again
9. Paste it into the **App password** field below

> ⚠️ If Generate app password doesn't appear, make sure Two-step verification is fully enabled and you've refreshed the page.

---

#### Custom SMTP Server

If your email provider isn't listed above, select **Custom** and fill in the Advanced server settings:

1. Ask your email provider or IT team for the **SMTP server address** (e.g. `mail.yourcompany.com`)
2. Ask for the **SMTP port** — usually **587** (TLS) or **465** (SSL)
3. Enter your **full email address** in the "Your email address" field
4. Enter your **email password** or app-specific password in the "App password" field
5. Open **Advanced server settings**, enter the server address and port, and make sure **Use TLS encryption** is checked (recommended)
6. Click **Save settings** and then **Send test email to myself** to verify

> ⚠️ Some corporate servers require a VPN connection or only allow sending from within the company network.

---

You **cannot** use your regular login password for Gmail, Outlook, or Yahoo — they block it for third-party apps.
App passwords are typically 16 characters and look like: **abcd efgh ijkl mnop**
                """)

            def _infer_smtp_from_email(addr: str) -> tuple[str, int, bool]:
                """Best-effort SMTP defaults by common email domains."""
                dom = (addr or "").split("@")[-1].lower().strip() if "@" in (addr or "") else ""
                if dom in {"gmail.com", "googlemail.com"}:
                    return "smtp.gmail.com", 587, True
                if dom in {"outlook.com", "hotmail.com", "live.com", "msn.com", "office365.com"}:
                    return "smtp.office365.com", 587, True
                if dom.startswith("yahoo.") or dom == "yahoo.com":
                    return "smtp.mail.yahoo.com", 587, True
                if dom in {"icloud.com", "me.com", "mac.com"}:
                    return "smtp.mail.me.com", 587, True
                if dom and "." in dom:
                    return f"smtp.{dom}", 587, True
                return "", 587, True

            _saved_user = cfg.get("username", "")
            _infer_server, _infer_port, _infer_tls = _infer_smtp_from_email(_saved_user)

            # Use override if provider button was just pressed; else use saved config; else infer.
            server_val = st.session_state.get("smtp_server_override", cfg.get("server", "") or _infer_server)
            port_val   = st.session_state.get("smtp_port_override", int(cfg.get("port", _infer_port)))
            tls_val    = bool(cfg.get("use_tls", _infer_tls))

            with st.form("smtp_form"):
                username = st.text_input("Your email address", value=cfg.get("username",""),
                                          placeholder="you@gmail.com")
                _det_server, _det_port, _det_tls = _infer_smtp_from_email(username)
                if not cfg.get("server") and _det_server:
                    st.caption(f"Auto-detected SMTP: {_det_server}:{_det_port} (TLS {'on' if _det_tls else 'off'})")
                st.caption("If your company uses Microsoft 365 or Google Workspace, this usually works as-is.")
                password = st.text_input("App password", value=cfg.get("password",""),
                                          type="password", placeholder="16-character app password")
                # Advanced — collapsed by default
                with st.expander("Advanced server settings"):
                    c1, c2 = st.columns(2)
                    server  = c1.text_input("SMTP server", value=server_val, placeholder="smtp.gmail.com")
                    port    = c2.number_input("Port", value=port_val, min_value=1, max_value=65535)
                    use_tls = st.checkbox("Use TLS encryption (recommended)", value=tls_val)

                if st.form_submit_button("Save settings", type="primary", use_container_width=True):
                    _svr = (server or "").strip()
                    _prt = int(port)
                    _tls = bool(use_tls)
                    if not _svr and username:
                        _auto_svr, _auto_prt, _auto_tls = _infer_smtp_from_email(username)
                        if _auto_svr:
                            _svr = _auto_svr
                            _prt = _auto_prt
                            _tls = _auto_tls
                    save_smtp_config(_svr, _prt, username, password, username, _tls)
                    save_email_delivery_config(mode="smtp", provider="resend", from_addr=username)
                    # Clear overrides now that they are saved
                    st.session_state.pop("smtp_server_override", None)
                    st.session_state.pop("smtp_port_override", None)
                    st.success("✓ Settings saved.")
                    st.rerun()

            if st.button("Send test email to myself", use_container_width=True):
                cfg2 = get_smtp_config()
                if not cfg2.get("username"):
                    st.warning("Save your email address first.")
                else:
                    with st.spinner("Sending test email to yourself…"):
                        ok, err = send_report_email(
                            [cfg2["username"]],
                            "Productivity Planner — Test Email",
                            "<p>Your email configuration is working correctly! 🎉</p>",
                        )
                    if ok:
                        st.success(f"✓ Test email sent to {cfg2['username']}")
                        st.caption("💡 If you don't see it in 1-2 minutes, check your spam folder.")
                    else:
                        st.error(f"❌ Send failed")
                        # Parse error to provide actionable help
                        err_lower = str(err).lower()
                        if "authentication" in err_lower or "535" in err_lower:
                            st.warning("**Incorrect email or app password.** Review SMTP credentials, or switch to **Resend API (recommended)** to avoid app-password setup.")
                        elif "timeout" in err_lower or "connection" in err_lower or "refused" in err_lower:
                            st.warning("**Connection failed.** Check that the server and port are correct. Try port 465 (SSL) in Advanced settings instead.")
                        elif "certificate" in err_lower or "tls" in err_lower:
                            st.warning("**Encryption error.** Try unchecking 'Use TLS encryption' in Advanced settings, or switch to port 465 (SSL).")
                        else:
                            st.caption(f"Technical details: {err}")
        else:
            st.info("Switch delivery method to 'Use my own email (work/personal)' if you want to send from your own inbox instead.")

    # ── Recipients ────────────────────────────────────────────────────────────
    with tab_recip:
        st.subheader("Who receives reports")

        recipients = get_recipients()
        if recipients:
            # Show each recipient with an inline remove button
            for r in recipients:
                rc1, rc2, rc3 = st.columns([3, 4, 1])
                rc1.markdown(f"**{r['name']}**")
                rc2.caption(r["email"])
                if rc3.button("✕", key=f"rm_recip_{r['email']}", help="Remove"):
                    remove_recipient(r["email"])
                    _success_then_rerun(f"✓ {r['email']} removed.")
            st.divider()
        else:
            st.info("No recipients yet.")

        st.subheader("Add recipients")
        st.caption("Add one or more at a time. Press **+ Add row** then **Save all** when done.")

        # Dynamic multi-row add form
        if "new_recips" not in st.session_state:
            st.session_state.new_recips = [{"name": "", "email": ""}]

        for ni, nr in enumerate(st.session_state.new_recips):
            nr1, nr2, nr3 = st.columns([3, 4, 1])
            nr["name"]  = nr1.text_input("Name",  value=nr["name"],  key=f"nrn_{ni}",
                                          placeholder="Jane Smith",    label_visibility="visible" if ni == 0 else "collapsed")
            nr["email"] = nr2.text_input("Email", value=nr["email"], key=f"nre_{ni}",
                                          placeholder="jane@acme.com", label_visibility="visible" if ni == 0 else "collapsed")
            if nr3.button("✕", key=f"nrr_{ni}") and len(st.session_state.new_recips) > 1:
                st.session_state.new_recips.pop(ni); st.rerun()

        ba1, ba2 = st.columns(2)
        if ba1.button("+ Add row"):
            st.session_state.new_recips.append({"name": "", "email": ""}); st.rerun()

        if ba2.button("💾 Save all", type="primary", use_container_width=True):
            saved = 0
            for nr in st.session_state.new_recips:
                if nr["name"].strip() and nr["email"].strip():
                    add_recipient(nr["name"].strip(), nr["email"].strip(), [])
                    saved += 1
            if saved:
                st.session_state.new_recips = [{"name": "", "email": ""}]
                _success_then_rerun(f"✓ {saved} recipient(s) added.")
            else:
                st.warning("Enter at least one name and email before saving.")

    # ── Send Now ──────────────────────────────────────────────────────────────
    with tab_send:
        st.subheader("Send Daily Report")
        st.caption("Send an outcome-focused daily report to your recipients.")

        # Load archived data if pipeline hasn't run this session
        if not st.session_state.pipeline_done and not st.session_state.get("_archived_loaded"):
            _build_archived_productivity()

        if not st.session_state.pipeline_done and not st.session_state.get("_archived_loaded"):
            st.info("No productivity data available yet.")
        else:
            gs         = st.session_state.goal_status
            depts      = sorted({r.get("Department","") for r in gs if r.get("Department")})
            recipients = get_recipients()

            if not recipients:
                st.warning("No recipients set up yet. Add them in the Recipients tab.")
            else:
                recip_labels = [f"{r['name']} <{r['email']}>" for r in recipients]
                chosen = st.multiselect("Send to", recip_labels,
                                        default=recip_labels[:1] if recip_labels else [])

                from datetime import timedelta as _sn_td
                _sn_today = date.today()
                dc1, dc2 = st.columns(2)
                _sn_start = dc1.date_input("Start date", value=_sn_today - _sn_td(days=1),
                                            key="send_now_start")
                # Reset end date when start changes so they stay in sync
                _prev_start = st.session_state.get("_sn_prev_start")
                if _prev_start and _sn_start != _prev_start:
                    st.session_state.pop("send_now_end", None)
                st.session_state["_sn_prev_start"] = _sn_start
                _sn_end   = dc2.date_input("End date (same as start for a single day)",
                                            value=_sn_start, key="send_now_end")
                if _sn_end < _sn_start:
                    st.warning("End date cannot be before start date.")

                dept_choice = st.selectbox("Department", ["All departments"] + depts)

                _risk_count = len([r for r in gs if r.get("goal_status") == "below_goal"])
                st.info(f"This report currently includes {_risk_count} below-goal employee(s).")

                if st.button("Send Daily Report Now", type="primary", use_container_width=True):
                    if not chosen:
                        st.warning("Select at least one recipient.")
                    elif _sn_end < _sn_start:
                        st.warning("Fix the date range first.")
                    else:
                        to_addrs = [r.split("<")[1].rstrip(">") for r in chosen]
                        with st.spinner("Building report…"):
                            xl_data, subj, body = _build_period_report(
                                _sn_start, _sn_end, dept_choice, depts, gs, _cached_targets())
                        with st.spinner("Sending…"):
                            ok, err = send_report_email(to_addrs, subj, body, xl_data)
                        if ok:
                            if xl_data is None:
                                st.info(f"ℹ️ No data for period — notification sent to {len(to_addrs)} recipient(s).")
                            else:
                                st.success(f"✓ Report sent to {len(to_addrs)} recipient(s).")
                        else:
                            st.error(f"Send failed: {err}")






# ══════════════════════════════════════════════════════════════════════════════
# PAGE: SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

