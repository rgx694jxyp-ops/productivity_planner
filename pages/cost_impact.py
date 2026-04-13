"""
pages/cost_impact.py
--------------------
Cost Impact of Improvement — the "money feature".

Shows:
  1. Per-employee cost of the UPH gap ($ lost productivity / week)
  2. Team-wide "top cost opportunities" table
  3. If target were met — recovered value per employee
  4. Coaching ROI: before/after improvement value recovered
"""

from datetime import datetime, date, timedelta

import streamlit as st

from core.dependencies import require_db
from core.runtime import _html_mod, init_runtime
from services.cost_service import (
    weekly_cost_impact as _weekly_cost_impact,
    get_wage as _get_wage,
    get_coaching_gains_for_employee as _get_coaching_gains,
)

init_runtime()

_WEEKS_IN_YEAR = 52


# ── Main page ─────────────────────────────────────────────────────────────────

def page_cost_impact():
    st.title("💰 Cost Impact")
    st.caption(
        "See exactly what the UPH gap costs each week — and what recovering it is worth."
    )

    if not require_db():
        return

    gs      = st.session_state.get("goal_status", [])
    history = st.session_state.get("history", [])

    if not gs:
        st.info("No productivity data loaded. Run **Import Data** first.")
        return

    # ── Settings ────────────────────────────────────────────────────────────
    try:
        from settings import Settings
        _tid = st.session_state.get("tenant_id", "")
        _stg = Settings(_tid)
        _wage = _get_wage(_stg)
    except Exception:
        _wage = _DEFAULT_WAGE

    # Allow inline override
    with st.expander("⚙️ Calculation settings", expanded=False):
        _wage = st.number_input(
            "Average hourly wage ($/hr)",
            min_value=1.0, max_value=200.0,
            value=float(_wage), step=0.50, format="%.2f",
            key="ci_wage",
        )
        _hrs_pw = st.number_input(
            "Hours worked per week per employee",
            min_value=1.0, max_value=80.0,
            value=40.0, step=1.0, key="ci_hrs_pw",
        )

    # ── Build table ─────────────────────────────────────────────────────────
    rows = []
    for r in gs:
        _name    = r.get("Employee Name") or r.get("EmployeeName") or ""
        _dept    = r.get("Department", "")
        _status  = r.get("goal_status", "")
        try:
            _uph    = float(r.get("Average UPH") or 0)
            _target = float(r.get("Target UPH") or 0)
        except (TypeError, ValueError):
            _uph, _target = 0.0, 0.0

        if not _name or _uph <= 0:
            continue

        _impact = _weekly_cost_impact(_uph, _target, _hrs_pw, _wage)

        _coaching_gain, _coaching_action = _get_coaching_gains(
            str(r.get("EmployeeID", r.get("Employee Name", ""))),
            _target, _hrs_pw, _wage,
        )

        rows.append({
            "Name":                 _name,
            "Dept":                 _dept,
            "UPH":                  round(_uph, 1),
            "Target":               round(_target, 1),
            "GAP (UPH)":            round(_target - _uph, 1) if _target > 0 else 0.0,
            "Lost units/week":      int(_impact["lost_units_per_week"]),
            "$/week lost":          _impact["lost_labor_cost_per_week"],
            "Value if at target":   _impact["recovery_per_week"],
            "Coaching gain $/wk":   _coaching_gain,
            "Coaching action":      _coaching_action,
            "_status": _status,
        })

    if not rows:
        st.info("No employees with UPH data found.")
        return

    # Sort by highest $ loss first
    rows_behind = [r for r in rows if r["$/week lost"] > 0]
    rows_ontgt  = [r for r in rows if r["$/week lost"] <= 0]
    rows_behind.sort(key=lambda x: -x["$/week lost"])

    # ── TOP COST OPPORTUNITIES ──────────────────────────────────────────────
    if rows_behind:
        st.subheader("🔴 Top Cost Opportunities")
        _top3_total = sum(r["$/week lost"] for r in rows_behind[:3])

        _top_cols = st.columns(min(len(rows_behind[:3]), 3))
        for _i, _r in enumerate(rows_behind[:3]):
            _tc = _top_cols[_i]
            _pct_of_gap = (_r["$/week lost"] / _top3_total * 100) if _top3_total > 0 else 0
            _tc.markdown(
                f'<div style="border:2px solid #B71C1C33;border-radius:10px;'
                f'padding:14px 16px;background:#FFF8F8;">'
                f'<div style="font-weight:800;font-size:14px;">{_html_mod.escape(_r["Name"])}</div>'
                f'<div style="font-size:11px;color:#555;margin-bottom:6px;">{_html_mod.escape(_r["Dept"])}</div>'
                f'<div style="font-size:22px;font-weight:800;color:#B71C1C;">'
                f'${_r["$/week lost"]:,.0f}/wk</div>'
                f'<div style="font-size:11px;color:#777;">Gap: {_r["GAP (UPH)"]:.1f} UPH · '
                f'{_r["Lost units/week"]:,} units lost/wk</div>'
                f'<div style="font-size:11px;color:#1B5E20;margin-top:4px;">'
                f'✔ At target = +${_r["Value if at target"]:,.0f}/wk potential</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            f'<div style="background:#FFF3E0;border:1px solid #E65100;border-radius:8px;'
            f'padding:12px 16px;margin:12px 0;">'
            f'<b>Top {min(len(rows_behind), 3)} at-target potential = '
            f'${_top3_total:,.0f}/week recovered</b> · '
            f'${_top3_total * 52:,.0f}/year</div>',
            unsafe_allow_html=True,
        )

    # ── Full table ──────────────────────────────────────────────────────────
    st.subheader("All Employees — Cost Impact")

    import pandas as pd
    _display_rows = []
    for _r in rows_behind + rows_ontgt:
        _display_rows.append({
            "Name":            _r["Name"],
            "Dept":            _r["Dept"],
            "UPH":             _r["UPH"],
            "Target":          _r["Target"],
            "Gap":             _r["GAP (UPH)"],
            "Lost units/wk":   _r["Lost units/week"] if _r["Lost units/week"] > 0 else "—",
            "Cost wasted/wk":  f'${_r["$/week lost"]:,.0f}' if _r["$/week lost"] > 0 else "On target",
            "Value if fixed":  f'${_r["Value if at target"]:,.0f}' if _r["Value if at target"] > 0 else "—",
            "Coaching gain":   f'${_r["Coaching gain $/wk"]:,.0f}' if _r["Coaching gain $/wk"] > 0 else "—",
        })

    _df = pd.DataFrame(_display_rows)
    st.dataframe(_df, use_container_width=True, hide_index=True)

    # ── Total summary ───────────────────────────────────────────────────────
    _total_weekly = sum(r["$/week lost"] for r in rows_behind)
    _total_annual = _total_weekly * 52
    if _total_weekly > 0:
        st.markdown("---")
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Total lost productivity / week",  f"${_total_weekly:,.0f}")
        mc2.metric("Projected annual impact",          f"${_total_annual:,.0f}")
        mc3.metric("Employees below target",           str(len(rows_behind)))

    # ── Coaching ROI section ────────────────────────────────────────────────
    _coached_wins = [r for r in rows if r.get("Coaching gain $/wk", 0) > 0]
    if _coached_wins:
        st.markdown("---")
        st.subheader("🏆 Coaching ROI")
        st.caption("Value already recovered through coaching sessions with before/after UPH recorded.")
        for _w in sorted(_coached_wins, key=lambda x: -x["Coaching gain $/wk"])[:10]:
            st.markdown(
                f"**{_html_mod.escape(_w['Name'])}** · {_html_mod.escape(_w['Coaching action'])} → "
                f"+${_w['Coaching gain $/wk']:,.0f}/week improvement value recovered"
            )
        _total_roi = sum(r["Coaching gain $/wk"] for r in _coached_wins)
        st.success(f"Total coaching ROI so far: +${_total_roi:,.0f}/week")

    # ── Team total output opportunity ────────────────────────────────────────
    st.markdown("---")
    st.subheader("📈 Output Opportunity")
    _total_extra_units = sum(r.get("Lost units/week", 0) for r in rows_behind if isinstance(r.get("Lost units/week"), int))
    if _total_extra_units > 0:
        st.markdown(
            f'<div style="background:#E8F5E9;border:1px solid #43A047;border-radius:8px;'
            f'padding:14px 18px;">'
            f'<div style="font-size:15px;font-weight:700;color:#1B5E20;">If all below-target employees hit their goals:</div>'
            f'<div style="font-size:24px;font-weight:800;color:#1B5E20;margin-top:4px;">'
            f'+{_total_extra_units:,} additional units/week</div>'
            f'<div style="font-size:12px;color:#555;margin-top:4px;">'
            f'≈ {_total_extra_units * 52:,} units/year · without adding staff</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
