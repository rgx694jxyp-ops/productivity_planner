"""
pages/coaching_intel.py
-----------------------
Coaching Intelligence Layer.

Surfaces:
  1. Smart auto-tagging of coaching notes (issue type, action, tone)
  2. Team-wide trend dashboard ("What's Actually Happening on Your Floor")
  3. "What's Working" — coaching actions correlated with UPH improvement
  4. Per-note tag editor for manual corrections
"""

from datetime import date, timedelta

import streamlit as st

from core.dependencies import require_db
from core.runtime import _html_mod, init_runtime

init_runtime()

# ── Tag taxonomy ──────────────────────────────────────────────────────────────
ISSUE_TYPES    = ["", "speed", "accuracy", "process", "attendance", "training"]
ACTION_TYPES   = ["", "coaching", "retraining", "reassignment", "reminder"]
TONE_TYPES     = ["", "warning", "neutral", "positive"]

ISSUE_KEYWORDS: dict[str, list[str]] = {
    "speed":       ["slow", "uph", "pace", "behind", "rate", "fast", "picking speed", "output"],
    "accuracy":    ["error", "mistake", "wrong", "incorrect", "accuracy", "mispick", "quality"],
    "process":     ["process", "workflow", "procedure", "steps", "method", "technique", "steps"],
    "attendance":  ["absent", "late", "tardy", "no show", "attendance", "missed", "call-out"],
    "training":    ["new hire", "training", "on-board", "ramp", "learn", "orientation", "unfamiliar"],
}
ACTION_KEYWORDS: dict[str, list[str]] = {
    "coaching":      ["coach", "discussed", "talked", "one-on-one", "feedback", "guided"],
    "retraining":    ["retrain", "re-train", "walkthrough", "shadow", "showed", "demonstrated"],
    "reassignment":  ["move", "moved", "reassign", "transfer", "changed station", "new lane"],
    "reminder":      ["remind", "reminded", "mentioned", "noted", "asked to"],
}
TONE_KEYWORDS: dict[str, list[str]] = {
    "warning":  ["warning", "final", "written up", "disciplinary", "urgent", "must improve", "last"],
    "positive": ["great", "excellent", "improved", "star", "well done", "good job", "above"],
}


# ── Auto-tagger ───────────────────────────────────────────────────────────────

def _auto_tag(note_text: str) -> dict:
    """Return best-guess tags from note text by keyword matching."""
    text = note_text.lower()
    result: dict = {"issue_type": "", "action_taken": "", "tone": "neutral"}

    for issue, kws in ISSUE_KEYWORDS.items():
        if any(kw in text for kw in kws):
            result["issue_type"] = issue
            break
    for action, kws in ACTION_KEYWORDS.items():
        if any(kw in text for kw in kws):
            result["action_taken"] = action
            break
    for tone, kws in TONE_KEYWORDS.items():
        if any(kw in text for kw in kws):
            result["tone"] = tone
            break

    return result


# ── Trend aggregation ─────────────────────────────────────────────────────────

def _aggregate_tags(notes: list[dict]) -> dict:
    """
    Returns:
    {
      "issue_counts":  {issue: count},
      "action_counts": {action: count},
      "tone_counts":   {tone: count},
      "employees_by_issue": {issue: {emp_id: count}},
    }
    """
    issue_c: dict  = {}
    action_c: dict = {}
    tone_c: dict   = {}
    emp_by_issue: dict = {}

    for n in notes:
        issue  = n.get("issue_type")  or ""
        action = n.get("action_taken") or ""
        tone   = n.get("tone")         or "neutral"
        emp_id = str(n.get("emp_id", ""))

        if issue:
            issue_c[issue] = issue_c.get(issue, 0) + 1
            if issue not in emp_by_issue:
                emp_by_issue[issue] = {}
            emp_by_issue[issue][emp_id] = emp_by_issue[issue].get(emp_id, 0) + 1
        if action:
            action_c[action] = action_c.get(action, 0) + 1
        if tone:
            tone_c[tone] = tone_c.get(tone, 0) + 1

    return {
        "issue_counts":     dict(sorted(issue_c.items(),  key=lambda x: -x[1])),
        "action_counts":    dict(sorted(action_c.items(), key=lambda x: -x[1])),
        "tone_counts":      dict(sorted(tone_c.items(),   key=lambda x: -x[1])),
        "employees_by_issue": emp_by_issue,
    }


def _coaching_effectiveness(notes: list[dict]) -> list[dict]:
    """
    For notes that have both uph_before and uph_after, calculate
    average improvement grouped by action_taken.
    Returns list of {action, count, avg_improvement_pct} sorted by improvement desc.
    """
    buckets: dict = {}
    for n in notes:
        act    = n.get("action_taken") or "untagged"
        before = n.get("uph_before")
        after  = n.get("uph_after")
        if before is None or after is None:
            continue
        try:
            b = float(before)
            a = float(after)
            if b <= 0:
                continue
            pct = round((a - b) / b * 100, 1)
            if act not in buckets:
                buckets[act] = []
            buckets[act].append(pct)
        except (TypeError, ValueError):
            pass
    out = []
    for act, improvements in buckets.items():
        out.append({
            "action": act,
            "count":  len(improvements),
            "avg_improvement_pct": round(sum(improvements) / len(improvements), 1),
        })
    return sorted(out, key=lambda x: -x["avg_improvement_pct"])


# ── Main page ─────────────────────────────────────────────────────────────────

def page_coaching_intel():
    st.title("🧠 Coaching Intelligence")
    st.caption(
        "Turn coaching notes into patterns. "
        "See what's actually happening across your floor and what's working."
    )

    if not require_db():
        return

    try:
        from database import get_all_coaching_notes, update_coaching_note_tags, get_employees
    except Exception as _e:
        st.error(f"Database functions not available: {_e}")
        st.info("Run the migration `migrations/005_operations_features.sql` in Supabase.")
        return

    _days = st.slider("Look-back window (days)", 7, 90, 14, key="ci_days")

    # Load notes
    with st.spinner("Loading coaching notes…"):
        try:
            notes = get_all_coaching_notes(days=_days)
        except Exception as _ne:
            st.error(f"Could not load notes: {_ne}")
            return

    if not notes:
        st.info(f"No coaching notes in the last {_days} days. Notes appear here after being saved on the Employees page.")
        return

    # Auto-tag notes that have no tags yet (client-side, saved to DB)
    _untagged = [n for n in notes if not (n.get("issue_type") or n.get("action_taken"))]
    if _untagged:
        with st.spinner(f"Auto-tagging {len(_untagged)} untagged notes…"):
            for n in _untagged:
                _tags = _auto_tag(n.get("note", ""))
                try:
                    update_coaching_note_tags(
                        n["id"],
                        issue_type=_tags["issue_type"],
                        action_taken=_tags["action_taken"],
                        tone=_tags["tone"],
                    )
                    n.update(_tags)   # update in-memory too
                except Exception:
                    pass

    stats  = _aggregate_tags(notes)
    effect = _coaching_effectiveness(notes)

    # ── Build emp_id → name map ──────────────────────────────────────────
    try:
        _emps = get_employees() or []
        _eid_to_name = {str(e.get("emp_id", "")): e.get("name", str(e.get("emp_id", ""))) for e in _emps}
    except Exception:
        _eid_to_name = {}

    tab_trends, tab_working, tab_notes = st.tabs(
        ["📊 Trends", "✅ What's Working", "🏷️ Tag Notes"]
    )

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — Trends
    # ══════════════════════════════════════════════════════════════════════════
    with tab_trends:
        st.subheader(f"What's Actually Happening on Your Floor · last {_days} days")

        # ── Top issues ───────────────────────────────────────────────────
        st.markdown("#### Top Issues")
        _ic = stats["issue_counts"]
        if _ic:
            _total_notes = len(notes)
            for _rank, (_issue, _cnt) in enumerate(list(_ic.items())[:6], 1):
                emp_ids = list((stats["employees_by_issue"].get(_issue) or {}).keys())
                _emp_names = [_eid_to_name.get(eid, eid) for eid in emp_ids[:5]]
                _issue_label = _issue.replace("_", " ").capitalize()
                _pct = round(_cnt / _total_notes * 100)
                _affected = len(emp_ids)
                _bar_w = int(_pct * 2)
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">'
                    f'<span style="font-size:13px;font-weight:700;min-width:90px;">'
                    f'{_rank}. {_html_mod.escape(_issue_label)}</span>'
                    f'<div style="background:#EEF2FF;border-radius:4px;height:12px;flex:1;max-width:160px;">'
                    f'<div style="background:#3730A3;height:12px;border-radius:4px;width:{min(_bar_w, 100)}%;"></div>'
                    f'</div>'
                    f'<span style="font-size:12px;color:#555;">{_cnt} notes · {_affected} employee{"s" if _affected != 1 else ""}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if _emp_names:
                    st.caption(f"  → {', '.join(_html_mod.escape(n) for n in _emp_names)}")
        else:
            st.info("No tagged issues yet — auto-tagging is being applied.")

        st.markdown("---")

        # ── Most common actions ──────────────────────────────────────────
        st.markdown("#### Most Common Coaching Actions")
        _ac = stats["action_counts"]
        if _ac:
            for _action, _cnt in list(_ac.items())[:5]:
                _al = _action.replace("_", " ").capitalize()
                st.markdown(f"- **{_html_mod.escape(_al)}** — used {_cnt} times")
        else:
            st.info("No action tags yet.")

        st.markdown("---")

        # ── Tone distribution ────────────────────────────────────────────
        st.markdown("#### Note Tone")
        _tc = stats["tone_counts"]
        _tone_colors = {"warning": "#B71C1C", "neutral": "#37474F", "positive": "#1B5E20"}
        _cols = st.columns(len(_tc) or 1)
        for _i, (_tone, _cnt) in enumerate((_tc or {}).items()):
            _color = _tone_colors.get(_tone, "#555")
            _cols[_i].markdown(
                f'<div style="text-align:center;padding:12px;">'
                f'<div style="font-size:22px">{"⚠️" if _tone == "warning" else "✅" if _tone == "positive" else "📝"}</div>'
                f'<div style="font-weight:700;color:{_color};">{_tone.capitalize()}</div>'
                f'<div style="font-size:18px;font-weight:800;">{_cnt}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown("---")

        # ── Pattern insight ──────────────────────────────────────────────
        top_issue = next(iter(_ic), None)
        if top_issue:
            _aff = len(list((stats["employees_by_issue"].get(top_issue) or {}).keys()))
            if _aff >= 3:
                st.warning(
                    f"🔍 **Pattern detected:** '{top_issue.capitalize()}' is flagged across "
                    f"{_aff} employees. This may be a **floor-wide process issue**, not just individual performance."
                )

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — What's Working
    # ══════════════════════════════════════════════════════════════════════════
    with tab_working:
        st.subheader("Coaching ROI — What's Working")
        st.caption(
            "Coaching actions with recorded before/after UPH show improvement. "
            "Add UPH before/after in the Tag Notes tab to populate this."
        )

        if effect:
            for _e in effect:
                _imp = _e["avg_improvement_pct"]
                _arrow = "↑" if _imp > 0 else "↓"
                _color = "#1B5E20" if _imp > 0 else "#B71C1C"
                st.markdown(
                    f'<div style="border:1px solid #E0E0E0;border-radius:8px;'
                    f'padding:12px 16px;margin-bottom:8px;">'
                    f'<span style="font-weight:700;">{_html_mod.escape(_e["action"].capitalize())}</span>'
                    f' — {_e["count"]} coaching session{"s" if _e["count"] != 1 else ""} · '
                    f'<span style="color:{_color};font-weight:700;">'
                    f'{_arrow} {abs(_imp)}% avg UPH change</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info(
                "No before/after UPH data recorded yet.\n\n"
                "In the **Tag Notes** tab, enter UPH before and after coaching to start tracking ROI."
            )

        # ── Coaching impact from UPH history (existing logic) ────────────
        st.markdown("---")
        st.markdown("#### Recent Individual Wins")
        st.caption("Employees who improved UPH after receiving a coaching note.")
        try:
            _gs = st.session_state.get("goal_status", [])
            _history = st.session_state.get("history", [])
            if _gs and _history:
                from services.coaching_service import find_coaching_impact
                _wins = []
                for row in _gs:
                    _eid = str(row.get("EmployeeID", row.get("Employee Name", "")))
                    _impact = find_coaching_impact(_eid, _history)
                    if _impact and _impact.get("improvement_pct", 0) > 0:
                        _wins.append({
                            "name": row.get("Employee Name") or _eid,
                            "improvement_pct": _impact.get("improvement_pct", 0),
                            "before": _impact.get("before_uph", 0),
                            "after":  _impact.get("after_uph", 0),
                        })
                _wins.sort(key=lambda x: -x["improvement_pct"])
                for _w in _wins[:5]:
                    st.markdown(
                        f"**{_html_mod.escape(_w['name'])}** — "
                        f"UPH: {_w['before']:.1f} → {_w['after']:.1f} "
                        f"(+{_w['improvement_pct']:.0f}%)"
                    )
                if not _wins:
                    st.caption("No improvements detected yet in recent history.")
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 3 — Tag Notes
    # ══════════════════════════════════════════════════════════════════════════
    with tab_notes:
        st.subheader("Review & Edit Note Tags")
        st.caption(
            "Auto-tags are applied on load. Edit any note to correct the category, "
            "or add before/after UPH to enable coaching ROI tracking."
        )

        # Filter controls
        fc1, fc2, fc3 = st.columns(3)
        _f_issue  = fc1.selectbox("Filter: Issue",  ["All"] + ISSUE_TYPES[1:], key="ci_f_issue")
        _f_action = fc2.selectbox("Filter: Action", ["All"] + ACTION_TYPES[1:], key="ci_f_action")
        _f_tone   = fc3.selectbox("Filter: Tone",   ["All"] + TONE_TYPES[1:],  key="ci_f_tone")

        _filtered = notes
        if _f_issue  != "All": _filtered = [n for n in _filtered if n.get("issue_type")   == _f_issue]
        if _f_action != "All": _filtered = [n for n in _filtered if n.get("action_taken") == _f_action]
        if _f_tone   != "All": _filtered = [n for n in _filtered if n.get("tone")         == _f_tone]

        st.caption(f"Showing {len(_filtered)} of {len(notes)} notes")

        for _note in _filtered[:50]:
            _nid   = _note.get("id", "")
            _eid   = str(_note.get("emp_id", ""))
            _ename = _eid_to_name.get(_eid, _eid)
            _text  = _note.get("note", "")
            _date  = str(_note.get("created_at", ""))[:10]
            _cur_issue  = _note.get("issue_type",   "") or ""
            _cur_action = _note.get("action_taken", "") or ""
            _cur_tone   = _note.get("tone",         "") or "neutral"
            _cur_before = _note.get("uph_before")
            _cur_after  = _note.get("uph_after")

            with st.expander(
                f"{_date} · {_html_mod.escape(_ename)} · {_cur_issue or 'untagged'}",
                expanded=False,
            ):
                st.markdown(f"> {_html_mod.escape(_text)}")
                ec1, ec2, ec3 = st.columns(3)
                _new_issue  = ec1.selectbox("Issue",   ISSUE_TYPES,  index=ISSUE_TYPES.index(_cur_issue)  if _cur_issue  in ISSUE_TYPES  else 0, key=f"ci_issue_{_nid}")
                _new_action = ec2.selectbox("Action",  ACTION_TYPES, index=ACTION_TYPES.index(_cur_action) if _cur_action in ACTION_TYPES else 0, key=f"ci_action_{_nid}")
                _new_tone   = ec3.selectbox("Tone",    TONE_TYPES,   index=TONE_TYPES.index(_cur_tone)    if _cur_tone   in TONE_TYPES   else 0, key=f"ci_tone_{_nid}")
                bc1, bc2 = st.columns(2)
                _new_before = bc1.number_input("UPH before coaching",  min_value=0.0, value=float(_cur_before or 0), step=0.1, format="%.1f", key=f"ci_before_{_nid}")
                _new_after  = bc2.number_input("UPH after coaching",   min_value=0.0, value=float(_cur_after  or 0), step=0.1, format="%.1f", key=f"ci_after_{_nid}")

                if st.button("Save tags", key=f"ci_save_{_nid}", use_container_width=True):
                    try:
                        update_coaching_note_tags(
                            _nid,
                            issue_type=_new_issue,
                            action_taken=_new_action,
                            tone=_new_tone,
                            uph_before=_new_before if _new_before > 0 else None,
                            uph_after=_new_after   if _new_after > 0  else None,
                        )
                        st.success("Tags saved!")
                    except Exception as _te:
                        st.error(f"Could not save: {_te}")
