import streamlit as st
from datetime import datetime
from core.dependencies import require_db
from services.trend_classification_service import normalize_trend_state


def get_below_goal_employees(goal_status_rows: list[dict]) -> list[dict]:
    """Return rows currently below goal."""
    return [row for row in (goal_status_rows or []) if row.get("goal_status") == "below_goal"]


def get_departments_from_goal_status(goal_status_rows: list[dict]) -> list[str]:
    """Return sorted unique non-empty departments from goal status rows."""
    return sorted(
        {
            str(row.get("Department", "") or "").strip()
            for row in (goal_status_rows or [])
            if str(row.get("Department", "") or "").strip()
        }
    )


def load_risk_levels(goal_status_rows: list[dict], history_rows: list[dict]) -> dict:
    """Session-memoized risk levels reused across pages during the same data snapshot."""
    tenant_id = str(st.session_state.get("tenant_id", "") or "")
    snapshot_date = str(st.session_state.get("_latest_snapshot_date", "") or "")
    loaded_at = float(st.session_state.get("_goal_history_loaded_at", 0.0) or 0.0)
    key = (
        tenant_id,
        snapshot_date,
        loaded_at,
        len(goal_status_rows or []),
        len(history_rows or []),
    )

    if st.session_state.get("_risk_cache_key") == key and isinstance(st.session_state.get("_risk_cache_all"), dict):
        return st.session_state.get("_risk_cache_all") or {}

    from domain.risk import _get_all_risk_levels

    cache = _get_all_risk_levels(goal_status_rows or [], history_rows or [])
    st.session_state["_risk_cache_key"] = key
    st.session_state["_risk_cache_all"] = cache
    return cache


def get_user_timezone_now(tenant_id: str = ""):
    """Get current datetime in user's configured timezone.
    
    If timezone is configured in settings, returns timezone-aware datetime.
    Otherwise, returns server local time (naive datetime).
    """
    try:
        from services.settings_service import get_tenant_local_now

        resolved_tenant_id = str(tenant_id or st.session_state.get("tenant_id", "") or "")
        return get_tenant_local_now(resolved_tenant_id)
    except Exception:
        # Fallback on any import or other errors
        return datetime.now()


def load_goal_status_history(spinner_text: str = "Loading data…"):
    """Shared bootstrap for pages that depend on goal_status/history in session."""
    if not require_db():
        return None, None

    tenant_id = str(st.session_state.get("tenant_id", "") or "")
    now_ts = datetime.now().timestamp()
    cached_tenant = str(st.session_state.get("_goal_history_tenant", "") or "")
    cached_ts = float(st.session_state.get("_goal_history_loaded_at", 0.0) or 0.0)
    cached_goal_status = st.session_state.get("goal_status", [])
    cached_history = st.session_state.get("history", [])
    # Avoid repeated snapshot reads on rapid reruns when session data is already fresh.
    if (
        cached_tenant == tenant_id
        and (now_ts - cached_ts) < 20
        and cached_goal_status
        and cached_history
    ):
        return cached_goal_status, cached_history

    try:
        from services.daily_snapshot_service import get_latest_snapshot_goal_status

        snapshot_goal_status, snapshot_history, snapshot_date = get_latest_snapshot_goal_status(tenant_id=tenant_id, days=30)
        if snapshot_goal_status:
            st.session_state["goal_status"] = snapshot_goal_status
            st.session_state["history"] = snapshot_history
            st.session_state["_latest_snapshot_date"] = snapshot_date
            st.session_state["_goal_history_tenant"] = tenant_id
            st.session_state["_goal_history_loaded_at"] = now_ts
            return snapshot_goal_status, snapshot_history
    except Exception:
        pass

    if not st.session_state.pipeline_done and not st.session_state.get("_archived_loaded"):
        with st.spinner(spinner_text):
            try:
                from pages.employees import _build_archived_productivity

                _build_archived_productivity(st.session_state)
                st.session_state["_goal_history_tenant"] = tenant_id
                st.session_state["_goal_history_loaded_at"] = datetime.now().timestamp()
            except Exception:
                pass

    return st.session_state.get("goal_status", []), st.session_state.get("history", [])


def _normalize_label_text(value, max_len: int = 64) -> str:
    """Normalize labels to keep dropdown and chip text readable/safe."""
    s = str(value or "").replace("\x00", " ").strip()
    s = " ".join(s.split())
    s = s.replace("|", " ").replace("<", " ").replace(">", " ")
    s = s.strip(" '\"")
    if len(s) > max_len:
        s = s[: max_len - 3].rstrip() + "..."
    return s or "Unknown"


def _build_coaching_recommendations():
    """Generate coaching recommendations from current goal status rows."""
    gs = st.session_state.get("goal_status", [])
    if not gs:
        return []

    recommendations = []
    for r in gs:
        name = r.get("Employee Name") or r.get("Employee") or ""
        dept = r.get("Department", "")
        uph = r.get("Average UPH")
        target = r.get("Target UPH")
        trend_dir = normalize_trend_state(r.get("trend", ""))

        if not name:
            continue

        try:
            uph = float(uph) if uph not in ("—", None, "") else None
        except (ValueError, TypeError):
            uph = None
        try:
            target = float(target) if target not in ("—", None, "", 0) else None
        except (ValueError, TypeError):
            target = None

        if uph is None:
            continue

        rec = {
            "name": name,
            "dept": dept,
            "uph": uph,
            "target": target,
            "priority": "low",
            "actions": [],
            "status": "",
        }

        gap_pct = 0
        if target and target > 0:
            gap_pct = round(((uph - target) / target) * 100, 1)

        if target and gap_pct < -20:
            rec["priority"] = "high"
            rec["status"] = f"{gap_pct}% below target"
            rec["actions"].append(
                f"Schedule one-on-one coaching session — {name} is significantly below the {dept} target of {target} UPH."
            )
            rec["actions"].append("Review workstation setup and process efficiency for immediate improvements.")
            rec["actions"].append("Pair with a high performer for side-by-side work to share techniques.")
            if trend_dir == "declining":
                rec["actions"].append("URGENT: Performance is declining. Investigate equipment, training, or workload blockers.")
        elif target and gap_pct < -10:
            rec["priority"] = "medium"
            rec["status"] = f"{gap_pct}% below target"
            rec["actions"].append(f"Monitor closely — {name} is moderately below the {target} UPH target.")
            rec["actions"].append("Provide targeted training on efficiency techniques.")
            if trend_dir == "improving":
                rec["actions"].append("Positive sign: trend is improving. Continue current support.")
            else:
                rec["actions"].append("Set a 2-week improvement checkpoint to track progress.")
        elif target and gap_pct < 0:
            rec["priority"] = "low"
            rec["status"] = f"{gap_pct}% below target"
            rec["actions"].append(f"Slightly below target. Encourage {name} and recognize effort.")
            rec["actions"].append("Small workflow adjustments may close the gap.")
        elif target and gap_pct >= 20:
            rec["priority"] = "star"
            rec["status"] = f"+{gap_pct}% above target"
            rec["actions"].append(f"⭐ {name} is a top performer — consistent strong results.")
            rec["actions"].append("Recognize achievement publicly to reinforce best practices.")
        elif target and gap_pct >= 0:
            rec["priority"] = "low"
            rec["status"] = f"+{gap_pct}% above target"
            rec["actions"].append("Meeting or exceeding target. Keep up the good work.")
        else:
            rec["status"] = "No target set"
            rec["actions"].append(f"Set a department target for {dept} to enable performance tracking.")

        if trend_dir == "declining" and rec["priority"] == "low":
            rec["priority"] = "medium"
            rec["actions"].append("Note: Trend is declining — schedule a check-in.")

        recommendations.append(rec)

    priority_order = {"high": 0, "medium": 1, "low": 2, "star": 3}
    recommendations.sort(key=lambda x: priority_order.get(x["priority"], 99))
    return recommendations
