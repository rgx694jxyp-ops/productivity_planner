from core.dependencies import bust_cache, full_sign_out, render_sign_out_button
from core.runtime import _html_mod, datetime, st, time
from services.plan_service import get_current_plan as _get_current_plan, can_access_feature, enforce_plan_or_raise

def plan_rank(plan: str) -> int:
    return {"starter": 1, "pro": 2, "business": 3, "admin": 99}.get((plan or "").lower(), 1)

def render_subscription_banner() -> None:
    cached_sub = st.session_state.get("_banner_sub")
    cached_ts = float(st.session_state.get("_banner_sub_ts", 0) or 0)
    if cached_sub is None or (time.time() - cached_ts) > 300:
        try:
            from database import get_employee_count, get_employee_limit, get_subscription
            tid = st.session_state.get("tenant_id", "")
            cached_sub = get_subscription(tid) or {}
            st.session_state["_banner_sub"] = cached_sub
            st.session_state["_banner_sub_ts"] = time.time()
            st.session_state["_banner_emp_count"] = get_employee_count(tid)
            st.session_state["_banner_emp_limit"] = get_employee_limit(tid)
        except Exception:
            return

    if not cached_sub:
        return

    plan = cached_sub.get("plan", "").lower()
    status = cached_sub.get("status", "")
    period_end = cached_sub.get("current_period_end", "")
    cancel_at = cached_sub.get("cancel_at_period_end", False)
    emp_count = st.session_state.get("_banner_emp_count", 0)
    emp_limit = st.session_state.get("_banner_emp_limit", 0)

    if not plan or status not in ("active", "trialing", "past_due"):
        return

    date_str = ""
    if period_end:
        try:
            period_end_dt = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
            date_str = period_end_dt.strftime("%b %-d")
        except Exception:
            pass

    plan_colors = {"starter": "#6b7280", "pro": "#2563eb", "business": "#7c3aed"}
    color = plan_colors.get(plan, "#6b7280")
    emp_str = f"{emp_count} / Unlimited" if emp_limit == -1 else f"{emp_count} / {emp_limit}"

    if status == "past_due":
        bg = "#fef2f2"
        border = "#dc2626"
        date_label = "Payment past due — update card in Settings"
        date_style = "color:#dc2626;font-weight:700;"
    elif cancel_at and date_str:
        bg = "#fffbeb"
        border = "#d97706"
        date_label = f"⚠ Cancels {date_str}"
        date_style = "color:#d97706;font-weight:600;"
    elif date_str:
        bg = "#f8fafc"
        border = "#e2e8f0"
        date_label = f"Renews {date_str}"
        date_style = "color:#6b7280;"
    else:
        bg = "#f8fafc"
        border = "#e2e8f0"
        date_label = ""
        date_style = ""

    plan_part = f'<span style="font-weight:700;color:{color};font-size:13px;">Plan: {plan.capitalize()}</span>'
    date_part = f'<span style="{date_style};font-size:13px;">{date_label}</span>' if date_label else ""
    emp_part = f'<span style="color:#374151;font-size:13px;">{emp_str} employees</span>'
    parts = [part for part in [plan_part, date_part, emp_part] if part]
    separator = '<span style="color:#d1d5db;">  ·  </span>'

    st.markdown(
        f'<div style="background:{bg};border:1px solid {border};border-radius:6px;padding:7px 16px;margin-bottom:14px;display:flex;align-items:center;flex-wrap:wrap;gap:4px;">'
        + separator.join(parts)
        + "</div>",
        unsafe_allow_html=True,
    )

def render_sidebar() -> str:
        plan = _get_current_plan(st.session_state.get("tenant_id"))
        with st.sidebar:
                st.markdown(
                        """
<div style="padding:8px 0 20px;">
    <div style="font-size:19px;font-weight:700;color:#fff;letter-spacing:-.02em;line-height:1.15;">
        📦 Productivity<br>Planner
    </div>
</div>""",
                        unsafe_allow_html=True,
                )
                # Robust navigation menu with page keys for routing
                nav_options = [
                    ("🏠 Dashboard", "dashboard"),
                    ("📈 Productivity", "productivity"),
                    ("👥 Employees", "employees"),
                    ("📂 Import Data", "import"),
                    ("⚙️ Settings", "settings"),
                    ("👔 Supervisor View", "supervisor"),
                    ("🧠 Coaching Intelligence", "coaching_intel"),
                    ("📋 Shift Plan", "shift_plan"),
                    ("💰 Cost Impact", "cost_impact"),
                    ("✉️ Email", "email"),
                ]
                page_choice = st.radio(
                    "Navigation",
                    nav_options,
                    format_func=lambda x: x[0],
                    key="sidebar_nav"
                )
                st.session_state["goto_page"] = page_choice[1]
                return page_choice[1]

# --- Sidebar footer: user info and sign out ---
        st.markdown("<hr style='margin:18px 0 10px 0;border:0;border-top:1px solid #e5e7eb;' />", unsafe_allow_html=True)
        user_email = st.session_state.get("user_email")
        if user_email:
            st.markdown(f"<div style='color:#374151;font-size:13px;margin-bottom:6px;'>Signed in as<br><b>{_html_mod.escape(user_email)}</b></div>", unsafe_allow_html=True)

        from auth import render_sign_out_button
        from core.dependencies import full_sign_out
        if render_sign_out_button("sidebar", use_container_width=True):
            full_sign_out()
            st.rerun()