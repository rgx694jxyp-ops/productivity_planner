def plan_gate(min_plan: str, feature_name: str) -> bool:
    tid = st.session_state.get("tenant_id", "")
    plan = _get_current_plan(tid)
    plan_ranks = {"starter": 1, "pro": 2, "business": 3, "admin": 99}
    if plan_ranks.get(plan, 1) >= plan_ranks.get(min_plan, 1):
        return True
    st.info(f"{feature_name} is available on **{min_plan.capitalize()}** and above.")
    st.caption("Upgrade in Settings → Subscription to unlock this feature.")
    return False

# For legacy compatibility in productivity.py
_plan_gate = plan_gate
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


def render_app_navigation() -> str:
    render_subscription_banner()
    return render_sidebar()

def render_sidebar() -> str:

    # --- Restore sidebar using Streamlit's built-in sidebar and previous layout ---
    tid = st.session_state.get("tenant_id", "")
    plan = _get_current_plan(tid)
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

        st.divider()
        nav_items = [
            ("supervisor", "👔  Supervisor"),
            ("dashboard", "📊  Dashboard"),
            ("import", "📁  Import Data"),
            ("employees", "👥  Employees"),
            ("productivity", "📈  Productivity"),
            ("shift_plan", "📋  Shift Plan"),
            ("coaching_intel", "🧠  Coaching Intel"),
            ("cost_impact", "💰  Cost Impact"),
            ("email", "📧  Email Setup"),
            ("settings", "⚙️  Settings"),
        ]
        nav_keys = [key for key, _ in nav_items]
        nav_labels = {key: label for key, label in nav_items}

        goto = str(st.session_state.pop("goto_page", "") or "").lower()
        if goto:
            if goto in nav_keys:
                st.session_state["_current_page_key"] = goto
            elif "supervisor" in goto:
                st.session_state["_current_page_key"] = "supervisor"
            elif "dashboard" in goto:
                st.session_state["_current_page_key"] = "dashboard"
            elif "import" in goto:
                st.session_state["_current_page_key"] = "import"
            elif "employee" in goto:
                st.session_state["_current_page_key"] = "employees"
            elif "productivity" in goto:
                st.session_state["_current_page_key"] = "productivity"
            elif "shift" in goto:
                st.session_state["_current_page_key"] = "shift_plan"
            elif "coach" in goto or "intel" in goto:
                st.session_state["_current_page_key"] = "coaching_intel"
            elif "cost" in goto or "impact" in goto:
                st.session_state["_current_page_key"] = "cost_impact"
            elif "email" in goto:
                st.session_state["_current_page_key"] = "email"
            elif "setting" in goto:
                st.session_state["_current_page_key"] = "settings"

        if st.session_state.get("_current_page_key") not in nav_keys:
            st.session_state["_current_page_key"] = nav_keys[0]

        page = st.radio(
            "Navigation",
            nav_keys,
            format_func=lambda key: nav_labels.get(key, key.title()),
            label_visibility="collapsed",
            key="_current_page_key",
        )

        st.divider()
        if st.button("↺ Refresh data", use_container_width=True, key="sb_refresh"):
            bust_cache()
            st.rerun()

        from ui.components import toggle_simple_mode

        toggle_simple_mode()
        if st.session_state.get("simple_mode"):
            st.caption("Simple Mode keeps the app focused on who needs attention right now.")

        plan_display = plan.capitalize() if plan != "admin" else "Admin"
        plan_color = {"starter": "#888", "pro": "#1E90FF", "business": "#FFD700", "admin": "#FF6347"}.get(plan, "#888")
        st.markdown(
            f'<div style="font-size:10px;color:{plan_color};font-weight:700;margin-bottom:4px;">Plan: {plan_display}</div>',
            unsafe_allow_html=True,
        )
        try:
            from database import get_employee_count, get_employee_limit

            emp_count_ts = float(st.session_state.get("_emp_count_ts", 0) or 0)
            if (time.time() - emp_count_ts) > 300 or "_emp_count_cache" not in st.session_state:
                st.session_state["_emp_count_cache"] = get_employee_count()
                st.session_state["_emp_limit_cache"] = get_employee_limit()
                st.session_state["_emp_count_ts"] = time.time()
            emp_count = st.session_state["_emp_count_cache"]
            emp_limit = st.session_state["_emp_limit_cache"]
            limit_str = "unlimited" if emp_limit == -1 else str(emp_limit)
            st.markdown(
                f'<div style="font-size:10px;color:#7FA8CC;margin-bottom:8px;">Employees: {emp_count}/{limit_str}</div>',
                unsafe_allow_html=True,
            )
        except Exception:
            pass

        user_name = st.session_state.get("user_name", "")
        if user_name:
            safe_name = _html_mod.escape(user_name)
            st.markdown(
                f'<div style="font-size:11px;color:#7FA8CC;margin-bottom:4px;">Signed in as<br><b style="color:#CBD8E8;">{safe_name}</b></div>',
                unsafe_allow_html=True,
            )
        if render_sign_out_button("sidebar", type="secondary", use_container_width=True):
            full_sign_out()
            st.rerun()

        st.markdown(
            '<div style="font-size:10px;color:#3D5A7A;line-height:1.7;">Productivity Planner · v3.0</div>',
            unsafe_allow_html=True,
        )
    return page