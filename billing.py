import time
from datetime import datetime

import streamlit as st
from core.billing_cache import clear_billing_cache
from services.upgrade_telemetry_service import log_upgrade_event


def verify_checkout_and_activate(tenant_id: str, user_id: str = ""):
    """After Stripe checkout, verify payment and create subscription in DB."""
    import requests as _req
    import database as _db
    from core.dependencies import log_operational_event

    _debug = []
    get_subscription = _db.get_subscription
    get_tenant = _db.get_tenant
    _get_config = _db._get_config
    PLAN_LIMITS = _db.PLAN_LIMITS
    set_tenant_stripe_customer_id = getattr(_db, "set_tenant_stripe_customer_id", lambda *_args, **_kwargs: False)

    stripe_key = _get_config("STRIPE_SECRET_KEY")
    tid = str(tenant_id or "").strip()
    uid = str(user_id or "").strip()
    log_operational_event(
        "checkout_verification_attempt",
        status="start",
        tenant_id=tid,
        detail="verify_checkout_and_activate invoked",
        context={"has_user_id": bool(uid)},
    )
    if not stripe_key:
        _debug.append("no STRIPE_SECRET_KEY")
        log_operational_event(
            "checkout_verification_result",
            status="error",
            tenant_id=tid,
            detail="Missing Stripe secret key",
        )
        st.session_state["_verify_debug"] = _debug
        return False
    if not tid:
        _debug.append("no tenant_id")
        log_operational_event(
            "checkout_verification_result",
            status="error",
            detail="Missing tenant id",
        )
        st.session_state["_verify_debug"] = _debug
        return False
    if not uid:
        _debug.append("no user_id in session; continuing tenant-level sync")

    _debug.append(f"tenant_id={tid[:8]}...")

    try:
        tenant = get_tenant(tid, columns="stripe_customer_id") or {}
        cust_id = tenant.get("stripe_customer_id")
    except Exception as e:
        _debug.append(f"tenant lookup err: {e}")
        st.session_state["_verify_debug"] = _debug
        return False

    # Fallback: recover customer from Stripe if tenant row is missing/stale.
    # This can happen when checkout succeeds but local tenant mirror update lags.
    if not cust_id:
        _debug.append("no stripe_customer_id on tenant; trying Stripe fallbacks")
        try:
            c_resp = _req.get(
                "https://api.stripe.com/v1/customers",
                auth=(stripe_key, ""),
                params={"limit": 100},
                timeout=10,
            )
            if c_resp.status_code == 200:
                for _c in c_resp.json().get("data", []):
                    _meta_tid = ((_c.get("metadata") or {}).get("tenant_id") or "").strip()
                    if _meta_tid == tid:
                        cust_id = _c.get("id")
                        break
            if cust_id:
                _debug.append(f"recovered stripe_customer_id={cust_id}")
                try:
                    set_tenant_stripe_customer_id(cust_id, tid)
                except Exception:
                    pass
        except Exception as _ce:
            _debug.append(f"customer fallback err: {_ce}")

    if not cust_id:
        _debug.append("no stripe_customer_id after fallback")
        log_operational_event(
            "checkout_verification_result",
            status="failed",
            tenant_id=tid,
            detail="No Stripe customer id found",
        )
        st.session_state["_verify_debug"] = _debug
        return False

    _debug.append(f"stripe_customer={cust_id[:12]}...")

    try:
        sub_resp = _req.get(
            "https://api.stripe.com/v1/subscriptions",
            auth=(stripe_key, ""),
            params={"customer": cust_id, "status": "all", "limit": 10},
            timeout=10,
        )
        if sub_resp.status_code != 200:
            _debug.append(f"stripe list subs: {sub_resp.status_code} {sub_resp.text[:100]}")
            st.session_state["_verify_debug"] = _debug
            return False
        subs = sub_resp.json().get("data", [])

        # Fallback: if no subs found by customer, inspect recent completed
        # checkout sessions and recover subscription id from tenant metadata.
        if not subs:
            _debug.append("no subscriptions by customer; checking recent checkout sessions")
            cs_resp = _req.get(
                "https://api.stripe.com/v1/checkout/sessions",
                auth=(stripe_key, ""),
                params={"limit": 25},
                timeout=10,
            )
            if cs_resp.status_code == 200:
                _sessions = cs_resp.json().get("data", [])
                _match_sub = ""
                _match_cust = ""
                for _s in _sessions:
                    _meta = _s.get("metadata") or {}
                    _tid = (_meta.get("tenant_id") or "").strip()
                    _mode = (_s.get("mode") or "").strip()
                    _status = (_s.get("status") or "").strip()
                    _sub = (_s.get("subscription") or "").strip()
                    if _tid == tid and _mode == "subscription" and _status == "complete" and _sub:
                        _match_sub = _sub
                        _match_cust = (_s.get("customer") or "").strip()
                        break
                if _match_sub:
                    _debug.append(f"recovered subscription from checkout session: {_match_sub[:18]}...")
                    _single = _req.get(
                        f"https://api.stripe.com/v1/subscriptions/{_match_sub}",
                        auth=(stripe_key, ""),
                        timeout=10,
                    )
                    if _single.status_code == 200:
                        subs = [_single.json()]
                        if _match_cust and not cust_id:
                            cust_id = _match_cust
                    else:
                        _debug.append(f"single subscription fetch failed: {_single.status_code}")

        if not subs:
            _debug.append("no subscriptions found in Stripe")
            log_operational_event(
                "checkout_verification_result",
                status="failed",
                tenant_id=tid,
                detail="No Stripe subscriptions found",
                context={"customer_id": cust_id},
            )
            st.session_state["_verify_debug"] = _debug
            return False

        _preferred = ["active", "trialing", "past_due", "unpaid", "incomplete"]
        subs_sorted = sorted(
            subs,
            key=lambda s: (
                _preferred.index(s.get("status")) if s.get("status") in _preferred else 999,
                -(s.get("created") or 0),
            ),
        )
        stripe_sub = subs_sorted[0]
        _debug.append(f"stripe status picked: {stripe_sub.get('status')}")

        # Only grant access when Stripe shows an active/trialing subscription.
        # Prevents stale canceled/incomplete subscriptions from unlocking the app.
        stripe_status = str(stripe_sub.get("status") or "").lower().strip()
        if stripe_status not in ("active", "trialing"):
            _debug.append(f"subscription not active/trialing: status={stripe_status or 'unknown'}")
            log_operational_event(
                "checkout_verification_result",
                status="denied",
                tenant_id=tid,
                detail="Stripe subscription not active/trialing",
                context={"stripe_status": stripe_status or "unknown"},
            )
            st.session_state["_sub_check_result"] = False
            st.session_state["_sub_check_ts"] = time.time()
            st.session_state["_verify_debug"] = _debug
            return False
        stripe_sub_id = str(stripe_sub.get("id") or "").strip()
        if not stripe_sub_id:
            _debug.append("stripe subscription id missing")
            st.session_state["_sub_check_result"] = False
            st.session_state["_sub_check_ts"] = time.time()
            st.session_state["_verify_debug"] = _debug
            return False
    except Exception as e:
        _debug.append(f"stripe API err: {e}")
        log_operational_event(
            "checkout_verification_result",
            status="error",
            tenant_id=tid,
            detail=f"Stripe API error: {e}",
        )
        st.session_state["_verify_debug"] = _debug
        return False

    _debug.append(f"found stripe sub {stripe_sub['id'][:16]}...")

    plan = ""
    try:
        price_obj = stripe_sub["items"]["data"][0]["price"]
        price_meta = price_obj.get("metadata", {})
        plan = price_meta.get("plan", "").lower().strip()
        _debug.append(f"plan from metadata: '{plan}'")
    except Exception as _pe:
        _debug.append(f"price metadata err: {_pe}")

    if not plan or plan not in PLAN_LIMITS:
        try:
            _price_id = stripe_sub["items"]["data"][0]["price"]["id"]
            _sec_starter = _get_config("STRIPE_PRICE_STARTER") or ""
            _sec_pro = _get_config("STRIPE_PRICE_PRO") or ""
            _sec_business = _get_config("STRIPE_PRICE_BUSINESS") or ""
            if _price_id and _sec_business and _price_id == _sec_business:
                plan = "business"
            elif _price_id and _sec_pro and _price_id == _sec_pro:
                plan = "pro"
            elif _price_id and _sec_starter and _price_id == _sec_starter:
                plan = "starter"
            else:
                plan = plan or "starter"
            _debug.append(f"plan from price ID match: '{plan}'")
        except Exception as _pie:
            _debug.append(f"price ID fallback err: {_pie}")
            plan = plan or "starter"

    if not plan:
        plan = "starter"
    limit = PLAN_LIMITS.get(plan, 25)
    _debug.append(f"plan={plan} limit={limit}")

    # The Supabase edge function webhook handles writing to the DB (service role, bypasses RLS).
    # Attempting an upsert here via the user's anon client would fail silently due to RLS
    # (there is no INSERT/UPDATE policy for regular users on the subscriptions table).
    # Instead, poll for the row the webhook wrote.
    import time as _time
    _poll_deadline = _time.time() + 8  # wait up to 8 seconds for webhook to land
    _sub_row = None
    while _time.time() < _poll_deadline:
        try:
            _row = get_subscription(
                tid,
                columns="plan, status, stripe_subscription_id, current_period_end",
                allow_live_fallback=False,
            )
            if _row:
                _db_status = str(_row.get("status") or "").lower().strip()
                _db_sub_id = str(_row.get("stripe_subscription_id") or "").strip()
                _db_plan = str(_row.get("plan") or "").lower().strip()
                if _db_status not in ("active", "trialing"):
                    _debug.append(f"db status not active yet: {_db_status or 'none'}")
                elif not _db_sub_id or _db_sub_id != stripe_sub_id:
                    _debug.append("db subscription id not synced yet")
                elif _db_plan and _db_plan != plan:
                    _debug.append(f"db plan not synced yet: db={_db_plan} stripe={plan}")
                else:
                    _sub_row = _row
                    break
        except Exception:
            pass
        _time.sleep(1)

    if _sub_row:
        _debug.append(
            "DB confirmed webhook sync: "
            f"sub_id={_sub_row.get('stripe_subscription_id')} "
            f"plan={_sub_row.get('plan')} status={_sub_row.get('status')}"
        )
        st.session_state["_current_plan"] = _sub_row.get("plan")
        st.session_state["_sub_check_result"] = True
        st.session_state["_sub_check_ts"] = _time.time()
        st.session_state["_verify_debug"] = _debug
        log_operational_event(
            "checkout_verification_result",
            status="success",
            tenant_id=tid,
            detail="Webhook-confirmed subscription activation",
            context={
                "plan": _sub_row.get("plan"),
                "status": _sub_row.get("status"),
                "stripe_subscription_id": _sub_row.get("stripe_subscription_id"),
            },
        )
        return True

    _debug.append("DB row not yet active after polling — waiting for webhook-confirmed activation")
    st.session_state["_sub_check_result"] = False
    st.session_state["_sub_check_ts"] = _time.time()
    st.session_state["_verify_debug"] = _debug
    log_operational_event(
        "checkout_verification_result",
        status="pending",
        tenant_id=tid,
        detail="Stripe looked valid but DB sync not yet confirmed",
        context={"stripe_subscription_id": stripe_sub_id},
    )
    return False


def subscription_page(render_sign_out_button_cb, full_sign_out_cb):
    from database import (
        _get_config,
        create_billing_portal_url,
        create_stripe_checkout_url,
        get_subscription,
    )
    from services.billing_service import get_subscription_entitlement

    _PORD = ["starter", "pro", "business"]
    _PINFO = {
        "starter": {"label": "Starter", "price": "$30/mo", "emp": "Up to 25", "clr": "#6b7280", "desc": "For small teams getting started."},
        "pro": {"label": "Pro", "price": "$59/mo", "emp": "Up to 100", "clr": "#2563eb", "desc": "For growing operations that need deeper insights."},
        "business": {"label": "Business", "price": "$99/mo", "emp": "Unlimited", "clr": "#7c3aed", "desc": "For large warehouses and multi-site operations."},
    }
    _FEATS = {
        "starter": ["CSV upload & auto-detection", "Dashboard & rankings", "Dept-level UPH tracking", "Weekly email reports", "Excel & PDF exports"],
        "pro": ["Everything in Starter", "Goal setting & UPH targets", "Employee trend analysis", "Underperformer flagging & alerts", "Custom date range reports", "Coaching notes per employee"],
        "business": ["Everything in Pro", "Order & client tracking", "Submission plans & progress", "Client trend recording", "Multi-department management", "Priority email support"],
    }
    _tenant_id = str(st.session_state.get("tenant_id", "") or "")
    _user_id = str(st.session_state.get("user_id", "") or "")
    _user_email = str(st.session_state.get("user_email", "") or "")
    _entitlement = get_subscription_entitlement(_tenant_id, _user_email)
    _current_plan = str(_entitlement.get("plan") or "starter")
    _employee_count = int(_entitlement.get("employee_count") or 0)
    _employee_limit = int(_entitlement.get("employee_limit") or 0)

    def _queue_billing_portal_continue(*, label: str, launch_key: str, url: str, feature_context: str, button_type: str = "primary") -> None:
        if not url:
            return
        if st.button(label, key=launch_key, use_container_width=True, type=button_type):
            log_upgrade_event(
                "billing_portal_opened",
                prompt_location="",
                prompt_type="",
                current_plan=_current_plan,
                employee_count=_employee_count,
                employee_limit=_employee_limit,
                feature_context=feature_context,
                tenant_id=_tenant_id,
                user_id=_user_id,
                user_email=_user_email,
            )
            st.session_state[f"_{launch_key}_url"] = url
        if st.session_state.get(f"_{launch_key}_url") == url:
            st.link_button("Continue to Billing Portal →", url, use_container_width=True, type="secondary")

    _qp = st.query_params
    if _qp.get("checkout") == "success":
        clear_billing_cache(clear_checkout_state=True)
        with st.spinner("Activating your subscription..."):
            activated = verify_checkout_and_activate(_tenant_id, _user_id)
        if activated:
            st.balloons()
            st.success("Welcome! Your subscription is now active.")
            st.query_params.clear()
            clear_billing_cache(clear_checkout_state=True)
            time.sleep(2)
            st.rerun()
        else:
            st.warning("Payment received! It may take a moment to activate. Please refresh in a few seconds.")
            st.query_params.clear()
    if _qp.get("checkout") == "canceled":
        st.info("Checkout canceled — no charge was made. Choose a plan below.")
        st.query_params.clear()

    if st.button("Refresh subscription status", key="refresh_subscription_status"):
        clear_billing_cache()
        with st.spinner("Checking latest billing status..."):
            _synced = False
            try:
                _synced = verify_checkout_and_activate(_tenant_id, _user_id)
            except Exception:
                _synced = False
        if _synced:
            st.success("Subscription status refreshed.")
            clear_billing_cache()
            st.rerun()
        st.info("No subscription update found yet. Please wait a few seconds and try again.")

    _dbg = st.session_state.get("_verify_debug") or []
    if _dbg:
        with st.expander("Subscription activation diagnostics", expanded=False):
            for _line in _dbg[-20:]:
                st.caption(str(_line))

    try:
        existing_sub = get_subscription(_tenant_id)
    except Exception:
        existing_sub = None

    _app_url = st.context.headers.get("Origin", "http://localhost:8501")
    _portal_url = None
    _price_map = {}
    try:
        _portal_url = create_billing_portal_url(return_url=_app_url + "/?portal=return", tenant_id=_tenant_id)
        _price_map = {
            "starter": _get_config("STRIPE_PRICE_STARTER") or "",
            "pro": _get_config("STRIPE_PRICE_PRO") or "",
            "business": _get_config("STRIPE_PRICE_BUSINESS") or "",
        }
    except Exception:
        pass

    _sub_status = (existing_sub or {}).get("status", "")
    _sub_plan = (existing_sub or {}).get("plan", "").lower()
    _period_end = (existing_sub or {}).get("current_period_end", "")
    _renew_str = ""
    if _period_end:
        try:
            _pe = datetime.fromisoformat(_period_end.replace("Z", "+00:00"))
            _renew_str = _pe.strftime("%b %d, %Y")
        except Exception:
            pass

    st.markdown(
        """
    <div style="max-width:860px;margin:32px auto 0;text-align:center;">
      <div style="background:#0F2D52;border-radius:12px;padding:28px 36px;margin-bottom:8px;">
        <div style="font-size:26px;margin-bottom:4px;">📦</div>
        <div style="font-size:20px;font-weight:700;color:#fff;letter-spacing:-.02em;">
          Productivity Planner
        </div>
      </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    if _sub_status == "past_due":
        _pi = _PINFO.get(_sub_plan, {})
        st.markdown(
            f"""
        <div style="background:#fef2f2;border:2px solid #dc2626;border-radius:10px;
                    padding:16px 20px;margin:16px 0 8px;">
          <div style="font-weight:700;color:#dc2626;font-size:15px;">⚠ Payment Past Due</div>
          <div style="color:#555;margin-top:4px;font-size:13px;">
            Your <strong>{_pi.get('label', _sub_plan.capitalize()) if _pi else _sub_plan.capitalize()}</strong> plan
            is on hold because your last payment failed.
            Update your card to restore access immediately.
          </div>
        </div>
        """,
            unsafe_allow_html=True,
        )
        if _portal_url:
            _queue_billing_portal_continue(
                label="Update Payment Method",
                launch_key="billing_update_payment_method",
                url=_portal_url,
                feature_context="billing_past_due_update_payment",
            )
        else:
            st.info("Contact support to update your payment method.")
        st.markdown("---")
        if render_sign_out_button_cb("sub_past_due", type="secondary"):
            full_sign_out_cb()
            st.rerun()
        st.stop()

    if _sub_status in ("canceled", "incomplete_expired") and _sub_plan:
        _pi = _PINFO.get(_sub_plan, {})
        _ended = f"  Ended {_renew_str}." if _renew_str else ""
        st.markdown(
            f"""
        <div style="background:#fffbeb;border:2px solid #d97706;border-radius:10px;
                    padding:16px 20px;margin:16px 0 8px;">
          <div style="font-weight:700;color:#d97706;font-size:15px;">Your plan has ended</div>
          <div style="color:#555;margin-top:4px;font-size:13px;">
            You previously had the <strong>{_pi.get('label', _sub_plan.capitalize()) if _pi else _sub_plan.capitalize()}</strong> plan.{_ended}
            Re-subscribe below to restore access.
          </div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    if not existing_sub or _sub_status not in ("past_due", "canceled", "incomplete_expired"):
        st.markdown("<h2 style='text-align:center;margin:16px 0 4px;'>Choose Your Plan</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center;color:#555;margin-bottom:20px;'>Pick the plan that fits your team. Cancel any time.</p>", unsafe_allow_html=True)

    _success = _app_url + "/?checkout=success"
    _cancel = _app_url + "/?checkout=canceled"

    if st.session_state.get("_checkout_url"):
        _plan_name = st.session_state.get("_checkout_plan", "your plan")
        st.subheader(f"Ready to checkout: {_plan_name}")
        st.link_button("Complete checkout on Stripe →", st.session_state["_checkout_url"], use_container_width=True, type="primary")
        if st.button("← Choose a different plan"):
            st.session_state.pop("_checkout_url", None)
            st.session_state.pop("_checkout_plan", None)
            st.rerun()
        st.markdown("---")
        if render_sign_out_button_cb("sub_checkout", type="secondary"):
            full_sign_out_cb()
            st.rerun()
        st.stop()

    try:
        _price_starter = _get_config("STRIPE_PRICE_STARTER") or ""
        _price_pro = _get_config("STRIPE_PRICE_PRO") or ""
        _price_business = _get_config("STRIPE_PRICE_BUSINESS") or ""
    except Exception:
        _price_starter = _price_pro = _price_business = ""
    _prices = {"starter": _price_starter, "pro": _price_pro, "business": _price_business}

    _cols = st.columns(3)
    for _ci, _pk in enumerate(_PORD):
        _pi = _PINFO[_pk]
        _is_prev = _pk == _sub_plan and _sub_status in ("canceled", "incomplete_expired")
        _is_pop = _pk == "pro"
        with _cols[_ci]:
            if _is_prev:
                st.markdown(
                    "<div style='color:#d97706;font-size:11px;font-weight:700;text-transform:uppercase;'>↺ Your Previous Plan</div>",
                    unsafe_allow_html=True,
                )
            elif _is_pop:
                st.markdown(
                    "<div style='color:#2563eb;font-size:11px;font-weight:700;text-transform:uppercase;'>★ Most Popular</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown("<div style='font-size:11px;'>&nbsp;</div>", unsafe_allow_html=True)

            st.markdown(f"**{_pi['label']}**")
            st.markdown(f"### {_pi['price']}")
            st.caption(f"{_pi['emp']} employees · {_pi['desc']}")
            st.markdown("---")
            for _f in _FEATS[_pk]:
                st.markdown(f"<div style='font-size:12px;color:#444;line-height:1.9;'>✓ {_f}</div>", unsafe_allow_html=True)
            st.markdown("")

            _price_id = _prices.get(_pk, "")
            if _is_prev and _portal_url:
                _reactivate_url = create_billing_portal_url(
                    return_url=_app_url + "/?portal=return",
                    tenant_id=_tenant_id,
                    target_price_id=_price_map.get(_pk, ""),
                    flow="subscription_update",
                ) or _portal_url
                _queue_billing_portal_continue(
                    label=f"Reactivate {_pi['label']}",
                    launch_key=f"billing_reactivate_{_pk}",
                    url=_reactivate_url,
                    feature_context=f"billing_reactivate:{_pk}",
                )
            elif _price_id:
                _btn_label = f"Get {_pi['label']}"
                _btn_type = "primary" if _is_pop else "secondary"
                if st.button(_btn_label, use_container_width=True, type=_btn_type, key=f"btn_{_pk}"):
                    with st.spinner("Connecting to Stripe..."):
                        url, err = create_stripe_checkout_url(
                            _price_id,
                            _success,
                            _cancel,
                            tenant_id=_tenant_id,
                            user_id=_user_id,
                            user_email=_user_email,
                        )
                    if url:
                        log_upgrade_event(
                            "billing_checkout_started",
                            prompt_location="",
                            prompt_type="",
                            current_plan=_current_plan,
                            employee_count=_employee_count,
                            employee_limit=_employee_limit,
                            feature_context=f"subscription_page_checkout:{_pk}",
                            tenant_id=_tenant_id,
                            user_id=_user_id,
                            user_email=_user_email,
                        )
                        st.session_state["_checkout_url"] = url
                        st.session_state["_checkout_plan"] = _pi["label"]
                        st.rerun()
                    elif err == "active_subscription":
                        # Already subscribed — route to portal for plan management
                        if _portal_url:
                            _manage_url = create_billing_portal_url(
                                return_url=_app_url + "/?portal=return",
                                tenant_id=_tenant_id,
                                flow="subscription_update",
                            ) or _portal_url
                            st.info("You already have an active subscription. Use the billing portal to change plans.")
                            _queue_billing_portal_continue(
                                label="Manage Subscription",
                                launch_key=f"billing_manage_subscription_{_pk}",
                                url=_manage_url,
                                feature_context="billing_active_subscription_manage",
                            )
                        else:
                            st.info("You already have an active subscription. Go to Settings → Billing to manage it.")
                    else:
                        from core.dependencies import show_user_error

                        show_user_error(
                            "Could not start checkout right now.",
                            next_steps="Please try again in a moment. If this keeps happening, use Manage Subscription or contact support.",
                            technical_detail=str(err or "unknown checkout error"),
                            category="billing",
                        )

    if not (_price_starter or _price_pro or _price_business):
        st.info("Payment system is being configured. Check back soon.")

    st.markdown("---")
    if render_sign_out_button_cb("sub_footer", type="secondary"):
        full_sign_out_cb()
        st.rerun()
