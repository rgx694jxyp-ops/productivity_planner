"""
pages/shift_plan.py
-------------------
Shift Plan + Checkpoint System.

Manager sets:
  - Shift hours, departments, expected volume, staff
  - Baseline task times (minutes per unit) — auto-fills from history or manual
  - Auto-generated checkpoints every 2 hours

Live progress:
  - Enter actual output at each checkpoint
  - See gap vs plan per department
  - Identify top individual contributors to the gap
"""

from datetime import datetime, date, timedelta

import streamlit as st

from core.dependencies import _cached_employees, require_db
from core.runtime import _html_mod

# ── Constant ──────────────────────────────────────────────────────────────────
_CHECKPOINT_INTERVAL_HRS = 2   # generate a checkpoint every N hours
_AUTO_BASELINES_DAYS = 30      # lookback for historical average


# ── Helpers ───────────────────────────────────────────────────────────────────

def _time_to_float(t: str) -> float:
    """'14:30' → 14.5"""
    try:
        h, m = t.split(":")
        return int(h) + int(m) / 60
    except Exception:
        return 8.0


def _float_to_time(f: float) -> str:
    """14.5 → '14:30'"""
    h = int(f)
    m = int(round((f - h) * 60))
    return f"{h:02d}:{m:02d}"


def _generate_checkpoints(start: str, end: str) -> list[str]:
    """Build a list of checkpoint strings between shift start and end."""
    s = _time_to_float(start)
    e = _time_to_float(end)
    pts = []
    cur = s + _CHECKPOINT_INTERVAL_HRS
    while cur < e - 0.01:
        pts.append(_float_to_time(cur))
        cur += _CHECKPOINT_INTERVAL_HRS
    pts.append(end)
    return pts


def _expected_at_checkpoint(volume: float, start: str, end: str, checkpoint: str) -> float:
    """Linear interpolation: expected cumulative output at a given checkpoint."""
    total_hrs = max(_time_to_float(end) - _time_to_float(start), 0.001)
    elapsed   = max(_time_to_float(checkpoint) - _time_to_float(start), 0.0)
    pct       = min(elapsed / total_hrs, 1.0)
    return round(volume * pct)


def _get_auto_baseline(department: str) -> float:
    """Return average minutes-per-unit from recent UPH history for this dept."""
    try:
        from database import get_all_uph_history
        rows = get_all_uph_history(days=_AUTO_BASELINES_DAYS)
        dept_rows = [
            r for r in rows
            if str(r.get("department", "")).lower() == department.lower()
            and float(r.get("uph", 0) or 0) > 0
        ]
        if not dept_rows:
            return 0.0
        avg_uph = sum(float(r["uph"]) for r in dept_rows) / len(dept_rows)
        return round(60.0 / avg_uph, 2)   # UPH → minutes-per-unit
    except Exception:
        return 0.0


def _dept_contributors(department: str, gs: list[dict]) -> list[dict]:
    """Return employees in this dept sorted by gap (biggest laggards first)."""
    contribs = []
    for r in gs:
        if str(r.get("Department", "")).lower() != department.lower():
            continue
        try:
            uph    = float(r.get("Average UPH") or 0)
            target = float(r.get("Target UPH") or 0)
            gap    = target - uph if target > 0 else 0.0
        except (TypeError, ValueError):
            gap = 0.0
        contribs.append({
            "name": r.get("Employee Name") or r.get("EmployeeName") or "",
            "uph":  round(float(r.get("Average UPH") or 0), 1),
            "target": round(float(r.get("Target UPH") or 0), 1),
            "gap": round(gap, 1),
        })
    return sorted(contribs, key=lambda x: x["gap"], reverse=True)


# ── Main page ─────────────────────────────────────────────────────────────────

def page_shift_plan():
    st.title("📋 Shift Plan")
    st.caption("Set today's plan, auto-generate checkpoints, and track live progress against expectation.")

    if not require_db():
        return

    try:
        from database import (
            get_shift_plan, save_shift_plan,
            get_shift_checkpoints, save_shift_checkpoint,
        )
    except Exception as _e:
        st.error(f"Database functions not available: {_e}")
        st.info("Run the migration `migrations/005_operations_features.sql` in Supabase to enable this page.")
        return

    today_str = date.today().isoformat()
    gs = st.session_state.get("goal_status", [])

    # ── Load existing plan ──────────────────────────────────────────────────
    _plan_cache_key = f"_shift_plan_{today_str}"
    if _plan_cache_key not in st.session_state:
        try:
            st.session_state[_plan_cache_key] = get_shift_plan(today_str)
        except Exception:
            st.session_state[_plan_cache_key] = None
    existing = st.session_state[_plan_cache_key] or {}

    # ── Tab layout ──────────────────────────────────────────────────────────
    tab_setup, tab_live, tab_history = st.tabs(["⚙️ Plan Setup", "📡 Live Progress", "📅 History"])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — Plan Setup
    # ══════════════════════════════════════════════════════════════════════════
    with tab_setup:
        st.subheader(f"Shift Plan · {today_str}")

        c1, c2 = st.columns(2)
        shift_start = c1.text_input(
            "Shift start (HH:MM)", value=existing.get("shift_start", "08:00"), key="sp_start"
        )
        shift_end = c2.text_input(
            "Shift end (HH:MM)", value=existing.get("shift_end", "16:00"), key="sp_end"
        )

        # ── Department rows ─────────────────────────────────────────────
        st.markdown("#### Departments active today")
        st.caption(
            "Add each department, set expected volume, and staff count. "
            "Baseline minutes-per-unit auto-fills from your history (edit to override)."
        )

        _existing_depts = existing.get("departments") or []
        _existing_baselines = existing.get("task_baselines") or {}

        # Detect departments from current goal_status if no plan yet
        _detected_depts = list({
            str(r.get("Department", "")).strip()
            for r in gs
            if str(r.get("Department", "")).strip()
        })
        if not _existing_depts and _detected_depts:
            _existing_depts = [
                {"name": d, "staff": 1, "volume": 0}
                for d in _detected_depts
            ]

        # Number of dept rows
        _n_depts = st.number_input(
            "Number of departments",
            min_value=1, max_value=20,
            value=max(len(_existing_depts), 1),
            step=1, key="sp_n_depts",
        )

        dept_rows = []
        baseline_rows = {}
        for i in range(int(_n_depts)):
            _def = _existing_depts[i] if i < len(_existing_depts) else {}
            _dname = _def.get("name", f"Dept {i+1}")
            _auto_bl = _get_auto_baseline(_dname)
            _saved_bl = _existing_baselines.get(_dname, {}).get("picking", _auto_bl) if _existing_baselines else _auto_bl

            with st.expander(f"Department {i+1}: {_dname}", expanded=(i == 0)):
                dc1, dc2, dc3 = st.columns(3)
                _name  = dc1.text_input("Name", value=_dname, key=f"sp_dept_name_{i}")
                _staff = dc2.number_input("Staff", min_value=1, max_value=500, value=int(_def.get("staff", 1)), key=f"sp_dept_staff_{i}")
                _vol   = dc3.number_input("Expected units/orders", min_value=0, value=int(_def.get("volume", 0)), step=10, key=f"sp_dept_vol_{i}")
                _bl    = st.number_input(
                    f"Baseline: minutes per unit (auto: {_auto_bl:.1f})",
                    min_value=0.0, max_value=120.0, value=float(_saved_bl or _auto_bl or 1.0),
                    step=0.5, format="%.1f", key=f"sp_dept_bl_{i}",
                )
                dept_rows.append({"name": _name, "staff": _staff, "volume": _vol})
                baseline_rows[_name] = {"picking": _bl}

        notes = st.text_area("Notes / special instructions", value=existing.get("notes", ""), key="sp_notes")

        if st.button("💾 Save shift plan", type="primary", use_container_width=True, key="sp_save"):
            try:
                saved = save_shift_plan(
                    plan_date=today_str,
                    shift_start=shift_start,
                    shift_end=shift_end,
                    departments=dept_rows,
                    task_baselines=baseline_rows,
                    notes=notes,
                )
                st.session_state[_plan_cache_key] = saved
                st.success("Plan saved! Switch to Live Progress to track checkpoints.")
                st.rerun()
            except Exception as _err:
                st.error(f"Could not save plan: {_err}")

        # Preview generated checkpoints
        if dept_rows:
            st.markdown("---")
            st.markdown("##### Generated checkpoints")
            _cps = _generate_checkpoints(shift_start, shift_end)
            _rows = []
            for d in dept_rows:
                for cp in _cps:
                    _exp = _expected_at_checkpoint(d["volume"], shift_start, shift_end, cp)
                    _rows.append({"Department": d["name"], "Checkpoint": cp, "Expected cumulative": _exp})
            import pandas as pd
            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — Live Progress
    # ══════════════════════════════════════════════════════════════════════════
    with tab_live:
        if not existing:
            st.info("No plan set for today yet. Go to **Plan Setup** to create one.")
            st.stop()

        _depts   = existing.get("departments") or []
        _start   = existing.get("shift_start", "08:00")
        _end     = existing.get("shift_end", "16:00")
        _cps     = _generate_checkpoints(_start, _end)

        # Load saved checkpoints
        _cp_cache_key = f"_shift_cps_{today_str}"
        if _cp_cache_key not in st.session_state:
            try:
                _saved_cps = get_shift_checkpoints(today_str)
                st.session_state[_cp_cache_key] = _saved_cps
            except Exception:
                st.session_state[_cp_cache_key] = []
        _saved_cps = st.session_state[_cp_cache_key]

        # Build lookup: (dept, checkpoint) → actual
        _cp_map: dict = {}
        for _sc in _saved_cps:
            _cp_map[(str(_sc.get("department", "")), str(_sc.get("checkpoint", "")))] = float(_sc.get("actual", 0) or 0)

        # ── Shift Status header ─────────────────────────────────────────
        st.subheader("Shift Status")
        st.caption(f"Today · {_start} – {_end}")

        _now_str = datetime.now().strftime("%H:%M")
        _current_cp = _cps[0]
        for cp in _cps:
            if _time_to_float(cp) <= _time_to_float(_now_str):
                _current_cp = cp

        _status_cols = st.columns(len(_depts) or 1)
        for _di, _dept in enumerate(_depts):
            _dname  = _dept["name"]
            _vol    = float(_dept.get("volume", 0) or 0)
            _exp    = _expected_at_checkpoint(_vol, _start, _end, _current_cp)
            _actual = _cp_map.get((_dname, _current_cp), 0.0)
            _gap    = _actual - _exp
            _gap_pct = (_gap / _exp * 100) if _exp > 0 else 0.0

            if _gap_pct >= -5:
                _icon  = "🟢"
                _label = "On Track"
                _color = "#1B5E20"
                _bg    = "#E8F5E9"
            elif _gap_pct >= -15:
                _icon  = "🟡"
                _label = "Slightly Behind"
                _color = "#F57F17"
                _bg    = "#FFFDE7"
            else:
                _icon  = "🔴"
                _label = "Behind"
                _color = "#B71C1C"
                _bg    = "#FFEBEE"

            _status_cols[_di].markdown(
                f'<div style="background:{_bg};border:2px solid {_color}20;border-radius:10px;'
                f'padding:12px 16px;text-align:center;">'
                f'<div style="font-size:22px">{_icon}</div>'
                f'<div style="font-weight:700;font-size:14px;color:{_color};">{_html_mod.escape(_dname)}</div>'
                f'<div style="font-size:12px;color:#555;">{_label}</div>'
                f'<div style="font-size:11px;margin-top:4px;color:#333;">'
                f'Expected: <b>{int(_exp)}</b>&nbsp;&nbsp;'
                f'Actual: <b>{int(_actual)}</b>&nbsp;&nbsp;'
                f'Gap: <b>{"+" if _gap >= 0 else ""}{int(_gap)}</b>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown("---")

        # ── Checkpoint entry ────────────────────────────────────────────
        st.markdown("#### Enter checkpoint actuals")
        _sel_cp = st.selectbox("Checkpoint time", _cps, key="sp_cp_select")
        _cp_dept_cols = st.columns(len(_depts) or 1)
        _new_actuals: dict = {}
        for _di, _dept in enumerate(_depts):
            _dname = _dept["name"]
            _vol   = float(_dept.get("volume", 0) or 0)
            _exp   = _expected_at_checkpoint(_vol, _start, _end, _sel_cp)
            _prev  = _cp_map.get((_dname, _sel_cp), 0.0)
            _new_actuals[_dname] = _cp_dept_cols[_di].number_input(
                f"{_dname} — expected {int(_exp)}",
                min_value=0, value=int(_prev), step=5, key=f"sp_actual_{_di}_{_sel_cp}",
            )

        if st.button("📥 Record checkpoint", type="primary", use_container_width=True, key="sp_record_cp"):
            try:
                for _dept in _depts:
                    _dname = _dept["name"]
                    _vol   = float(_dept.get("volume", 0) or 0)
                    _exp   = _expected_at_checkpoint(_vol, _start, _end, _sel_cp)
                    save_shift_checkpoint(
                        plan_date=today_str,
                        department=_dname,
                        checkpoint=_sel_cp,
                        expected=_exp,
                        actual=float(_new_actuals.get(_dname, 0)),
                    )
                st.session_state.pop(_cp_cache_key, None)  # bust cache
                st.success("Checkpoint recorded!")
                st.rerun()
            except Exception as _ce:
                st.error(f"Could not record checkpoint: {_ce}")

        # ── Gap contributors ────────────────────────────────────────────
        if gs:
            st.markdown("---")
            st.markdown("#### Gap Attribution")
            st.caption("Who/where the gap is coming from — sorted by largest individual gap first.")
            for _dept in _depts:
                _dname = _dept["name"]
                _vol   = float(_dept.get("volume", 0) or 0)
                _exp   = _expected_at_checkpoint(_vol, _start, _end, _current_cp)
                _actual = _cp_map.get((_dname, _current_cp), 0.0)
                _gap    = _actual - _exp

                contribs = _dept_contributors(_dname, gs)
                if not contribs:
                    continue

                behind = [c for c in contribs if c["gap"] > 0]
                if not behind:
                    continue

                with st.expander(
                    f"{'🔴' if _gap < 0 else '🟢'} {_dname} · gap: {'+' if _gap >= 0 else ''}{int(_gap)} units",
                    expanded=(_gap < 0),
                ):
                    st.caption("Employees contributing most to gap (below their own target):")
                    for c in behind[:5]:
                        _gb = round(c["gap"], 1)
                        st.markdown(
                            f"**{_html_mod.escape(c['name'])}** — "
                            f"UPH: {c['uph']} / Target: {c['target']} · gap: -{_gb} UPH"
                        )
                    st.markdown("**Suggested actions:**")
                    top2 = [c["name"] for c in behind[:2]]
                    if top2:
                        st.info(
                            f"{'🔴 ' if _gap < -10 else ''}Top contributors to gap: "
                            f"{', '.join(top2)}. "
                            "Consider rebalancing workload or immediate coaching."
                        )

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 3 — History
    # ══════════════════════════════════════════════════════════════════════════
    with tab_history:
        st.subheader("Recent Shift Plans")
        try:
            import pandas as pd
            from database import get_shift_checkpoints, get_shift_plan
            _rows = []
            for _offset in range(7):
                _d = (date.today() - timedelta(days=_offset)).isoformat()
                _p = get_shift_plan(_d)
                if not _p:
                    continue
                _cps_hist = get_shift_checkpoints(_d)
                _depts_h = _p.get("departments") or []
                for _dept in _depts_h:
                    _dname = _dept["name"]
                    _vol   = float(_dept.get("volume", 0) or 0)
                    _last_cp = None
                    _last_exp = 0.0
                    _last_act = 0.0
                    for _cp_r in reversed(_cps_hist):
                        if str(_cp_r.get("department", "")) == _dname:
                            _last_cp  = _cp_r.get("checkpoint")
                            _last_exp = float(_cp_r.get("expected", 0) or 0)
                            _last_act = float(_cp_r.get("actual", 0) or 0)
                            break
                    _rows.append({
                        "Date": _d,
                        "Department": _dname,
                        "Volume goal": int(_vol),
                        "Last checkpoint": _last_cp or "—",
                        "Expected": int(_last_exp),
                        "Actual": int(_last_act),
                        "Gap": int(_last_act - _last_exp),
                    })
            if _rows:
                _df = pd.DataFrame(_rows)
                st.dataframe(_df, use_container_width=True, hide_index=True)
            else:
                st.info("No shift plans recorded yet. Create one in Plan Setup.")
        except Exception as _he:
            st.error(f"Could not load history: {_he}")
